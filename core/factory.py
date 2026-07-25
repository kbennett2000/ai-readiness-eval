"""The factory: an unattended dispatcher that works a ranked target queue through a fixed pipeline
and stocks the drawer with DRAFT report cards (ADR-0006).

Vendor-agnostic, like the rest of `core`. It carries no vendor name: the ranked `queue.yaml` (which
names targets) and the packs it drives both live outside this repo and reach the dispatcher only as a
queue path + a packs dir. The pipeline is a chain of **hard gates** — recon, validate, roundtrip,
anchoring, mock, canary — each of which, on failure, marks the target `blocked` with a written reason
and stops. The
factory never guesses past a gate, never scores a guess, and never reduces N to fit a window. Producing
is unattended; shipping is gated: every card it writes carries a DRAFT/UNREVIEWED banner and nothing
leaves the drawer toward a prospect without human review.

Authoring a pack's tasks + anchored ground truth is deliberately NOT the factory's job (that would be
fabricating the very ground truth the method scores against). Authoring is an external, human/agent step
whose output must pass the validate + roundtrip + anchoring gates here before any grid burns. See
ADR-0006 and ADR-0010.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .pack import Pack
from .report import _DIM_LABELS
from .scorer import DIMENSIONS

# Pipeline stages, in order. A target advances through these; its `status` records how far it got.
STAGES = ["recon", "validate", "roundtrip", "anchoring", "mock", "canary", "grid", "compare", "card"]
# A target is "done" (skipped by next_target) when it is either finished or parked.
DONE_STATUSES = {"carded", "blocked"}
_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


# --------------------------------------------------------------------------- #
# Queue model
# --------------------------------------------------------------------------- #

@dataclass
class QueueEntry:
    """One target in the queue. Unknown YAML keys round-trip via `extra` so hand-authored notes and
    future fields survive a save."""
    id: str
    display_name: str = ""
    tier: int | None = None
    status: str = "queued"
    spec_state: str = "unknown"          # verified | partial | unknown
    notes: str = ""
    blocked_reason: str = ""
    spend_usd: float = 0.0
    wall_seconds: float = 0.0
    last_run: str = ""
    extra: dict = field(default_factory=dict)

    _KNOWN = ("id", "display_name", "tier", "status", "spec_state", "notes",
              "blocked_reason", "spend_usd", "wall_seconds", "last_run")

    @classmethod
    def from_dict(cls, d: dict) -> "QueueEntry":
        known = {k: d[k] for k in cls._KNOWN if k in d}
        extra = {k: v for k, v in d.items() if k not in cls._KNOWN}
        return cls(**known, extra=extra)

    def to_dict(self) -> dict:
        out: dict = {"id": self.id, "display_name": self.display_name}
        if self.tier is not None:
            out["tier"] = self.tier
        out.update({"status": self.status, "spec_state": self.spec_state})
        if self.notes:
            out["notes"] = self.notes
        if self.blocked_reason:
            out["blocked_reason"] = self.blocked_reason
        if self.spend_usd:
            out["spend_usd"] = round(self.spend_usd, 4)
        if self.wall_seconds:
            out["wall_seconds"] = round(self.wall_seconds, 1)
        if self.last_run:
            out["last_run"] = self.last_run
        out.update(self.extra)
        return out


def load_queue(path: str | Path) -> list[QueueEntry]:
    """Load the ranked queue. Accepts either a top-level `targets:` list or a bare list."""
    data = yaml.safe_load(Path(path).read_text()) or []
    rows = data.get("targets", []) if isinstance(data, dict) else data
    return [QueueEntry.from_dict(r) for r in rows]


def save_queue(path: str | Path, entries: list[QueueEntry], *, header: str | None = None) -> None:
    """Write the queue back, preserving order. `header` is an optional leading comment block."""
    body = yaml.safe_dump({"targets": [e.to_dict() for e in entries]},
                          sort_keys=False, default_flow_style=False, allow_unicode=True)
    text = (header.rstrip() + "\n\n" if header else "") + body
    Path(path).write_text(text)


def next_target(entries: list[QueueEntry]) -> QueueEntry | None:
    """The first target not yet finished or parked (skip-done, like a per-item worklist loop)."""
    for e in entries:
        if e.status not in DONE_STATUSES:
            return e
    return None


# --------------------------------------------------------------------------- #
# Gates (deterministic, model-free) — each returns (ok, detail)
# --------------------------------------------------------------------------- #

def _load_spec_file(path: Path) -> dict:
    text = path.read_text()
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


def _spec_prefix_segments(spec: dict) -> list[str]:
    """The path segments a spec declares to be in front of every one of its paths.

    OpenAPI 3 puts them in `servers[0].url`, Swagger 2 in `basePath`. A spec is free to split the
    address between the two — `servers[0].url: /Vendor/api` with paths `/v1/things` describes exactly
    the same URL as `servers[0].url: /Vendor` with paths `/api/v1/things`. That split is the spec
    author's convenience and says nothing about the API.
    """
    raw = ""
    servers = spec.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        raw = str(servers[0].get("url") or "")
    if not raw:
        raw = str(spec.get("basePath") or "")
    if "://" in raw:  # an absolute server URL: keep only its path component
        rest = raw.split("://", 1)[1]
        raw = rest[rest.find("/"):] if "/" in rest else ""
    return [s for s in raw.split("/") if s]


def _anchor_paths(spec_path: str, prefix_segments: list[str]) -> list[str]:
    """Every path a pack may legitimately write for one spec path.

    The bare spec path, plus that path prefixed by any SUFFIX of the spec's declared server prefix.
    For a prefix of `/Vendor/api` and a spec path of `/v1/things`, a pack may write `/v1/things`,
    `/api/v1/things`, or `/Vendor/api/v1/things` — all three name the same endpoint, and which one is
    right depends on where the VENDOR'S OWN documentation says the base URL ends. Ground truth has to
    be free to follow the documentation, because that is what the model being measured has read.
    """
    base = spec_path.strip().rstrip("/") or "/"
    out = [base]
    for i in range(len(prefix_segments) - 1, -1, -1):
        out.append("/" + "/".join(prefix_segments[i:]) + base)
    return out


def _index_operations(spec: dict) -> dict[str, tuple[str, list[str]]]:
    """operationId -> (METHOD, [acceptable paths]) for every operation in an OpenAPI spec."""
    prefix = _spec_prefix_segments(spec)
    idx: dict[str, tuple[str, list[str]]] = {}
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() in _METHODS and isinstance(op, dict) and op.get("operationId"):
                idx[op["operationId"]] = (method.upper(), _anchor_paths(path, prefix))
    return idx


def check_recon(pack: Pack) -> tuple[bool, str]:
    """Recon gate (step zero): can the method anchor this vendor at all?

    A pack whose spec is available (yes/partial) must carry a vendored spec + license so ground truth
    can be anchored offline forever. A pack with no machine-readable spec is not blocked — it runs in
    doc-anchored mode, and the spec-availability finding leads its card (ADR-0005). The one hard failure
    is an *incoherent* pack: it claims a spec but did not vendor one.
    """
    try:
        specs = yaml.safe_load(pack.specs_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        return False, f"specs.yaml unreadable: {exc}"
    finding = specs.get("spec_finding") or {}
    avail = finding.get("machine_readable_spec_available")
    if avail is None:
        return False, "specs.yaml has no spec_finding.machine_readable_spec_available (recon incomplete)"
    # YAML unquotes `yes`/`no` to booleans — normalize so a pack can write either form.
    avail = {True: "yes", False: "no"}.get(avail, str(avail)).lower()
    if not finding.get("license"):
        return False, "spec_finding names no license (license is a scored dimension)"
    vendored = pack.root / "vendored-spec"
    spec_files = [p for p in sorted(vendored.glob("*")) if p.suffix in (".json", ".yaml", ".yml")] \
        if vendored.is_dir() else []
    if avail in ("yes", "partial"):
        if not spec_files:
            return False, f"spec_finding says spec is '{avail}' but vendored-spec/ has no spec file"
        if not (vendored / "LICENSE").exists():
            return False, "vendored spec present but no vendored-spec/LICENSE"
        return True, f"spec available ({avail}); vendored + licensed ({finding['license']})"
    return True, f"no machine-readable spec ({avail!r}) — doc-anchored mode; availability leads the card"


def check_validate(pack: Pack) -> tuple[bool, str]:
    """Validate gate: every task file matches the schema, and the suite is coherent.

    Thin adapter over `validate.validate_pack` so the schema check is an ordinary entry in `GATES`
    rather than a special case spliced into the loop. The import stays deferred so `jsonschema` is
    only imported when a pack is actually being gated.
    """
    from .validate import format_report, validate_pack

    _text, total = format_report(validate_pack(pack))
    if total:
        return False, f"{total} schema problem(s); run `validate` for detail"
    return True, "task files match the schema"


def check_roundtrip(pack: Pack) -> tuple[bool, str]:
    """Round-trip control: every task scores its own ground truth 1.0 (ADR-0010).

    A task whose documented answer key cannot score a perfect mark against itself is an unscoreable
    instrument — a grid run against it would produce a number about our harness, not about the
    vendor. This gate settles that before any spend. It does NOT check whether the ground truth is
    *right*: an answer key always matches itself. See `core/roundtrip.py` for the full limit.
    """
    from .roundtrip import check_pack, summarize_failures

    controls = check_pack(pack)
    failures = summarize_failures(controls)
    if failures:
        return False, failures
    n_na = sum(len(c.na_dimensions) for c in controls)
    return True, f"{len(controls)} task(s) score their own ground truth 1.0 ({n_na} n/a dimension(s))"


def check_anchoring(pack: Pack) -> tuple[bool, str]:
    """Anchoring gate: every spec_ref resolves to a real operation in the vendored spec (operationId,
    with method+path agreeing), and every doc_ref URL appears in the docs-manifest. This is the
    "never score a guess" enforcement — ground truth that isn't anchored to something durable is a
    hard stop, not a warning.
    """
    vendored = pack.root / "vendored-spec"
    ops: dict[str, tuple[str, str]] = {}
    if vendored.is_dir():
        for f in sorted(vendored.glob("*")):
            if f.suffix in (".json", ".yaml", ".yml"):
                ops.update(_index_operations(_load_spec_file(f)))
    try:
        manifest = pack.docs_manifest()
    except (OSError, yaml.YAMLError):
        manifest = {}
    manifest_urls = {
        page["url"]
        for entry in (manifest.get("tasks") or {}).values()
        for page in entry.get("pages", [])
    }

    problems: list[str] = []
    n_spec, n_doc = 0, 0
    for task in pack.load_tasks():
        for ep in task["ground_truth"]["endpoints"]:
            ref = ep.get("spec_ref")
            doc = ep.get("doc_ref")
            if ref:
                n_spec += 1
                oid = ref["operation_id"]
                if oid not in ops:
                    problems.append(f"{task['id']}: operationId '{oid}' not in vendored spec")
                    continue
                method, accepted = ops[oid]
                if method != ep["method"].upper():
                    problems.append(f"{task['id']}/{oid}: method {ep['method']} != spec {method}")
                want = ep["path"].strip().rstrip("/").lower()
                if want not in {p.strip().rstrip("/").lower() for p in accepted}:
                    problems.append(
                        f"{task['id']}/{oid}: path {ep['path']} != spec {accepted[0]}"
                        + (f" (nor with the spec's server prefix: {', '.join(accepted[1:])})"
                           if len(accepted) > 1 else "")
                    )
            elif doc:
                n_doc += 1
                if doc["url"] not in manifest_urls:
                    problems.append(f"{task['id']}: doc_ref {doc['url']} not in docs-manifest")
    if problems:
        return False, "; ".join(problems)
    if pack.spec_ref_file_prefix and n_spec == 0:
        return False, "pack declares spec anchoring (spec_ref_file_prefix) but no endpoint is spec-anchored"
    return True, f"{n_spec} spec-anchored + {n_doc} doc-anchored endpoint(s) resolve"


# The deterministic gates, in the order the dispatcher runs them. Declaring them as data (rather than
# inlining the order in `run_pipeline`) is what keeps STAGES and the dispatcher from drifting apart —
# a test asserts these names are the leading prefix of STAGES.
GATES: tuple[tuple[str, Callable[[Pack], tuple[bool, str]]], ...] = (
    ("recon", check_recon),
    ("validate", check_validate),
    ("roundtrip", check_roundtrip),
    ("anchoring", check_anchoring),
)


# --------------------------------------------------------------------------- #
# Draft report card scaffold (name-free renderer; the vendor label is pack data, not core source)
# --------------------------------------------------------------------------- #

def render_card_scaffold(pack: Pack, results: list[tuple[str, dict, dict]], invented: dict) -> str:
    """Render the DRAFT report-card scaffold from the graded conditions. `results` is a list of
    (condition, aggregate, metadata); `invented` is {task_id: Counter((method, path): count)}. The
    executor fills the Findings prose; the numbers, the headline table, and the invented-endpoints
    exhibit are computed here so the card is never hand-transcribed."""
    dims = list(DIMENSIONS)
    meta = results[0][2] if results else {}
    lines = [
        f"# {pack.display_name} — AI API-readiness report card",
        "",
        "> **DRAFT — UNREVIEWED, NOT FOR OUTREACH.**",
        "",
        f"**Method:** {len(pack.load_tasks())} tasks, {len(results)} condition(s), "
        f"model `{meta.get('model', '?')}`, transport `{meta.get('provider', '?')}`, N="
        f"{meta.get('n', '?')}, sterile per-run, tool-discipline asserted every run. "
        "Scored deterministically on six dimensions.",
        "",
        "## Headline",
        "",
        "| condition | overall | " + " | ".join(_DIM_LABELS[d] for d in dims) + " |",
        "|" + "---|" * (len(dims) + 2),
    ]

    def _pct(v):
        return "n/a" if v is None else f"{round(v * 100)}"

    for cond, agg, _m in results:
        row = [cond, _pct(agg.get("overall_accuracy"))]
        row += [_pct(agg["overall_dimensions"].get(d)) for d in dims]
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "## Findings",
        "",
        "1. _(scaffold — replace with 3–5 plain-English findings, each with an `*Evidence:*` link "
        "to a task file, results dir, ADR, or manifest entry.)_",
        "",
        "## Spec availability (scored)",
        "",
        f"_See `specs.yaml` `spec_finding`._ Recon: {_recon_line(pack)}",
        "",
        "## Invented endpoints (verbatim)",
        "",
    ]
    exhibit = _format_invented(invented)
    lines += exhibit if exhibit else ["_(none — no endpoint outside ground truth was proposed)_"]
    lines += [
        "",
        "## Coverage, exclusions & disclosures",
        "",
        "- _(scaffold — list any excluded dimensions/tasks and why.)_",
        "",
        "## Bottom line (draft)",
        "",
        "_(scaffold)_",
        "",
    ]
    return "\n".join(lines)


def _recon_line(pack: Pack) -> str:
    ok, detail = check_recon(pack)
    return detail


def _format_invented(invented: dict) -> list[str]:
    lines: list[str] = []
    for task_id in sorted(invented):
        entries = invented[task_id]
        if not entries:
            continue
        lines.append(f"- **{task_id}**")
        for (method, path), count in entries.most_common():
            lines.append(f"  - `{method} {path}` (×{count})")
    return lines


# --------------------------------------------------------------------------- #
# Status rendering
# --------------------------------------------------------------------------- #

def render_status(entries: list[QueueEntry]) -> str:
    """The at-a-glance queue table an operator reads without touching dispatcher code."""
    if not entries:
        return "(queue is empty)"
    header = f"{'#':>2}  {'tier':>4}  {'status':<9}  {'spec':<8}  {'spend':>7}  {'wall':>6}  target"
    lines = [header, "-" * len(header)]
    for i, e in enumerate(entries, 1):
        spend = f"${e.spend_usd:.2f}" if e.spend_usd else "-"
        wall = f"{e.wall_seconds/60:.0f}m" if e.wall_seconds else "-"
        tier = str(e.tier) if e.tier is not None else "-"
        label = e.display_name or e.id
        lines.append(f"{i:>2}  {tier:>4}  {e.status:<9}  {e.spec_state:<8}  {spend:>7}  {wall:>6}  {label}")
        if e.status == "blocked" and e.blocked_reason:
            lines.append(f"                                              ↳ blocked: {e.blocked_reason}")
    done = sum(1 for e in entries if e.status == "carded")
    blocked = sum(1 for e in entries if e.status == "blocked")
    lines += ["", f"{done} carded · {blocked} blocked · {len(entries) - done - blocked} open"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #

def _run_namespace(pack_root: Path, *, condition: str, n: int, model: str | None,
                   provider: str, mock: bool, out: Path | None, packs_dir: str | None,
                   skip_preflight: bool) -> argparse.Namespace:
    """Build the argparse.Namespace `cmd_run` expects, so the dispatcher reuses the exact per-condition
    engine (resumability, discipline retries, report writing) instead of re-implementing it."""
    return argparse.Namespace(
        pack=str(pack_root), packs_dir=packs_dir, condition=condition, n=n, tasks=None,
        model=model, out=str(out) if out else None, overwrite=False,
        provider=provider, mock=mock, skip_preflight=skip_preflight, allow_unpinned_model=False,
    )


def _read_scores(out_dir: Path) -> dict:
    return json.loads((out_dir / "scores.json").read_text())


def run_pipeline(entry: QueueEntry, pack: Pack, *, today: str, model: str | None = None, n: int = 5,
                 provider: str = "cli", packs_dir: str | None = None,
                 log=print) -> dict:
    """Drive a target through recon → validate → roundtrip → anchoring → mock → canary → grid →
    compare → card.

    Each stage is a hard gate: on failure the target is marked `blocked` with a written reason and the
    function returns. On success `status` advances to `carded`. `provider="mock"` runs the whole spine
    offline (no model burn) for tests and dry-runs — it skips the canary and grids with the mock model.
    Returns a report dict {vendor, outcome, stage, reason, conditions, spend_usd, wall_seconds, card}.
    """
    from . import conditions as conditions_mod
    from .__main__ import EXIT_OK, cmd_run

    report: dict = {"vendor": pack.vendor_id, "outcome": None, "stage": None, "reason": "",
                    "conditions": [], "spend_usd": 0.0, "wall_seconds": 0.0, "card": None}

    def _block(stage: str, reason: str) -> dict:
        entry.status = "blocked"
        entry.blocked_reason = f"[{stage}] {reason}"
        entry.last_run = today
        report.update(outcome="blocked", stage=stage, reason=reason)
        log(f"  BLOCKED at {stage}: {reason}")
        return report

    # --- deterministic gates (model-free) --- #
    for stage, fn in GATES:
        entry.status = stage
        ok, detail = fn(pack)
        log(f"  {stage}: {'ok' if ok else 'FAIL'} — {detail}")
        if not ok:
            return _block(stage, detail)

    # --- mock plumbing proof (always, even before a real grid) --- #
    entry.status = "mock"
    mock_out = pack.root / "results" / f"{today}-mock-preflight"
    rc = cmd_run(_run_namespace(pack.root, condition="no-context", n=1, model=None,
                                provider="mock", mock=True, out=mock_out, packs_dir=packs_dir,
                                skip_preflight=True))
    log(f"  mock: {'ok' if rc == EXIT_OK else 'FAIL'}")
    if rc != EXIT_OK:
        return _block("mock", "mock run did not produce a report (plumbing broken)")

    # --- the grid: every condition the pack exposes (mcp only if it declares a context layer) --- #
    grid_conditions = [c for c in conditions_mod.build_registry(pack).keys()]
    entry.status = "grid"
    result_dirs: list[Path] = []
    is_mock = provider == "mock"
    canaried = False
    for cond in grid_conditions:
        out_dir = pack.root / "results" / f"{today}-{cond}"
        # Canary once (the first real cli condition); resumes/later conditions skip the re-run.
        skip_pre = is_mock or canaried
        try:
            rc = cmd_run(_run_namespace(pack.root, condition=cond, n=(1 if is_mock else n),
                                        model=(None if is_mock else model),
                                        provider=("mock" if is_mock else "cli"), mock=is_mock,
                                        out=out_dir, packs_dir=packs_dir, skip_preflight=skip_pre))
        except Exception as exc:  # a malformed pack/condition must block, not crash the dispatcher
            return _block("grid", f"condition '{cond}' raised {type(exc).__name__}: {str(exc)[:160]}")
        if rc != EXIT_OK:
            # EXIT_BLOCKED (3) = a gate (canary/transport/pin) refused; record and stop, don't guess.
            return _block("grid", f"condition '{cond}' returned exit {rc} "
                                  "(canary/transport/model-pin gate or run error)")
        if not is_mock:
            canaried = True
        result_dirs.append(out_dir)
        scores = _read_scores(out_dir)
        meta = scores.get("metadata", {})
        report["spend_usd"] += meta.get("total_cost_usd", 0.0)
        report["wall_seconds"] += meta.get("total_duration_ms", 0) / 1000.0
        report["conditions"].append(cond)
        log(f"  grid[{cond}]: ok  (${meta.get('total_cost_usd', 0.0):.4f})")

    # --- compare + card scaffold --- #
    entry.status = "compare"
    graded: list[tuple[str, dict, dict]] = []
    from .report import aggregate
    for d in result_dirs:
        scores = _read_scores(d)
        graded.append((scores["metadata"].get("condition", d.name),
                       aggregate(scores["runs"]), scores["metadata"]))

    entry.status = "card"
    invented = unmatched_for_dirs(result_dirs, pack)
    card = render_card_scaffold(pack, graded, invented)
    card_path = pack.root / "REPORT.scaffold.md"
    card_path.write_text(card)
    report["card"] = str(card_path)
    log(f"  card: wrote scaffold → {card_path.name}")

    # --- advance --- #
    entry.status = "carded"
    entry.spend_usd += report["spend_usd"]
    entry.wall_seconds += report["wall_seconds"]
    entry.last_run = today
    report.update(outcome="carded", stage="card")
    return report


def unmatched_for_dirs(result_dirs: list[Path], pack: Pack) -> dict:
    """Union the invented (non-ground-truth) endpoints across every graded condition dir."""
    from collections import Counter

    from .analyze import unmatched_endpoints
    tasks_by_id = pack.tasks_by_id()
    merged: dict[str, Counter] = {}
    for d in result_dirs:
        for tid, counter in unmatched_endpoints(d, tasks_by_id).items():
            merged.setdefault(tid, Counter()).update(counter)
    return merged
