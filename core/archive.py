"""Make an archived run record agree with the report built from it (ADR-0033).

`rebuild_report` re-scores every archived run and writes the corrected records into `scores.json` —
and stops one file short of `runs/*.json`, which keeps whatever the scorer said the day the grid ran.
That is not a cosmetic inconsistency. `cmd_run` resumes a grid by reading the run record and appending
it **verbatim**, so a stale `dimensions` block flows straight into a newly published `scores.json`, and
the ADR-0032 breaker reads the same stale `format_failure` flags.

This module closes the gap in the only direction that cannot move a published number: it copies the
**scorer-derived** fields OUT of the committed `scores.json` and INTO the run records. `scores.json` is
opened read-only and never written here. Re-scoring instead — running `rebuild-report` over an old
archive — would score it with TODAY's scorer, which is exactly how a published number would move.

The safety argument rests on one property, so it is checked rather than assumed: the raw evidence is
never rewritten. Every transport-derived field must already be byte-identical on both sides before a
single byte is written, and a directory that fails that check is left completely untouched.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# What the scorer and the parser decide. These are the fields a rebuild recomputes, and the only
# fields this module ever writes.
DERIVED_FIELDS: tuple[str, ...] = (
    "format_failure",
    "failure_reason",
    "dimensions",
    "endpoint_matches",
    "format_repaired",       # ADR-0014; conditional — absent means the repair did not fire
    "repaired_block_text",   # ADR-0014; conditional
    # ADR-0044; conditional — the per-run values a contract records but does not score. Derived,
    # because a rebuild recomputes it from the same archived response the dimensions come from, and
    # conditional for the same reason `format_repaired` is: absent means the contract produced none,
    # which is what it means for every API record ever written.
    "exhibit",
)

# What the model and the transport produced. This is the evidence a published number rests on. It is
# never written by this module, and a mismatch in any of it aborts the directory.
TRANSPORT_FIELDS: tuple[str, ...] = (
    "raw_response",
    "transcript",
    "tool_uses",
    "tool_discipline",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "duration_ms",
    "mock",
)

_ABSENT = object()


def _key(rec: dict) -> tuple:
    return (rec.get("task_id"), rec.get("run_index"))


def _label(key: tuple) -> str:
    return f"{key[0]}-run{key[1]}"


@dataclass
class Reconciliation:
    """What one result directory needed, and what (if anything) stopped it."""

    results_dir: Path
    checked: int = 0
    changed: dict[str, list[str]] = field(default_factory=dict)   # run label -> field names
    problems: list[str] = field(default_factory=list)
    written: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def total_fields(self) -> int:
        return sum(len(v) for v in self.changed.values())


def _load(path: Path):
    try:
        return json.loads(path.read_text()), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name} unreadable: {exc}"


def reconcile_runs(results_dir: str | Path, *, write: bool = True) -> Reconciliation:
    """Sync scorer-derived fields from `scores.json` into `runs/*.json`. Never raises.

    `write=False` reports exactly what would change without touching the filesystem — the mode the
    standing consistency sweep uses, so the test and the fix cannot disagree about what "agrees" means.
    """
    d = Path(results_dir)
    res = Reconciliation(results_dir=d)

    scores_path = d / "scores.json"
    runs_dir = d / "runs"
    if not scores_path.exists():
        res.problems.append(f"{d}: no scores.json")
        return res
    if not runs_dir.is_dir():
        res.problems.append(f"{d}: no runs/ directory")
        return res

    scores, err = _load(scores_path)
    if err:
        res.problems.append(f"{d}: {err}")
        return res
    published = scores.get("runs")
    if not isinstance(published, list):
        res.problems.append(f"{d}: scores.json has no `runs` array to reconcile against")
        return res

    by_key: dict[tuple, dict] = {}
    for rec in published:
        k = _key(rec)
        if k in by_key:
            res.problems.append(f"{d}: scores.json carries two entries for {_label(k)}")
            return res
        by_key[k] = rec

    files = sorted(runs_dir.glob("*.json"))
    if not files:
        res.problems.append(f"{d}: runs/ holds no run files")
        return res
    if len(files) != len(by_key):
        res.problems.append(
            f"{d}: {len(files)} run file(s) but {len(by_key)} entry(ies) in scores.json — a missing "
            "pairing is a defect, not something to reconcile around")
        return res

    # --- verify everything before writing anything ----------------------------------------------- #
    # A partial write would leave the archive in a state neither the run files nor the report
    # describe, which is worse than the drift being fixed.
    plan: list[tuple[Path, dict, list[str]]] = []
    for path in files:
        run, err = _load(path)
        if err:
            res.problems.append(f"{d}: {err}")
            continue
        k = _key(run)
        pub = by_key.get(k)
        if pub is None:
            res.problems.append(f"{d}: {path.name} has no matching entry in scores.json")
            continue
        res.checked += 1

        drift = [f for f in TRANSPORT_FIELDS
                 if run.get(f, _ABSENT) != pub.get(f, _ABSENT)]
        if drift:
            res.problems.append(
                f"{d}: {_label(k)} disagrees on transport-derived field(s) {', '.join(drift)} — this "
                "is raw evidence, not a score, so the directory is left untouched")
            continue

        updated = dict(run)
        touched: list[str] = []
        for f in DERIVED_FIELDS:
            want = pub.get(f, _ABSENT)
            have = updated.get(f, _ABSENT)
            if want is have or want == have:
                continue
            touched.append(f)
            if want is _ABSENT:
                updated.pop(f, None)
            else:
                updated[f] = want
        if touched:
            plan.append((path, updated, touched))
            res.changed[_label(k)] = touched

    if not res.ok:
        return res

    if write:
        for path, updated, _touched in plan:
            path.write_text(json.dumps(updated, indent=2))
        res.written = bool(plan)
    return res


def format_report(results: list[Reconciliation]) -> tuple[str, int]:
    """Render one line per directory. Returns (text, problem_count) — the `(text, total)` contract
    `validate.py`, `roundtrip.py` and `prompt_gate.py` already use, so callers stay uniform."""
    lines: list[str] = []
    problems = 0
    for r in results:
        if not r.ok:
            problems += len(r.problems)
            lines.append(f"BLOCKED {r.results_dir}")
            lines += [f"    {p}" for p in r.problems]
            continue
        if not r.changed:
            lines.append(f"ok      {r.results_dir}  ({r.checked} run(s) already agree)")
            continue
        verb = "synced" if r.written else "stale"
        lines.append(f"{verb:<7} {r.results_dir}  "
                     f"({len(r.changed)} of {r.checked} run(s), {r.total_fields} field(s))")
        for label, fields in sorted(r.changed.items()):
            lines.append(f"    {label}: {', '.join(fields)}")
    return "\n".join(lines), problems
