"""Re-score archived runs and regenerate reports — the `rebuild-report` path and the regression gate.

Pure recompute over committed transcripts: no model call, no network. Every `runs/*.json` is
re-scored from its stored `raw_response` with the CURRENT scorer and the pack's task ground truth,
then `summary.md` + `scores.json` are rewritten. Only the top-level run-provenance metadata changes on
a rebuild (it gains `rebuilt_from_runs: true` and does not reconstruct the live-run `cli_policy` /
`tool_discipline_summary`); every score-bearing figure recomputes identically (ADR-0002).

Since ADR-0033 a rebuild also writes the recomputed **scorer-derived** fields back into `runs/*.json`,
because a run record that disagrees with the report built from it is re-published verbatim by the next
resumed grid. The raw evidence — `raw_response`, `transcript`, and every transport-derived field — is
still never rewritten, and that is enforced rather than asserted (see `core/archive.py`).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import answer_block
from .archive import reconcile_runs
from .pack import Pack
from .report import write_reports
from .scorer import DIMENSIONS, format_failure_score, score_task

DEFAULT_MODEL = "claude-sonnet-4-6"


def score_response(task: dict, raw_text: str, base_prefix: list[str] | None = None):
    """Parse + score one archived raw response. A format failure is a distinct outcome, never zeroed.

    Returns (score, parse_result) so the caller can record an ADR-0014 repair.
    """
    parsed = answer_block.parse(raw_text)
    if parsed.is_failure:
        return format_failure_score(task["id"], parsed.failure.reason), parsed
    return score_task(task, parsed.summary, base_prefix), parsed


def rebuild_report(results_dir: str | Path, pack: Pack, *, note: str | None = None,
                   model: str = DEFAULT_MODEL, provider: str = "cli") -> dict:
    """Re-score every archived run in `results_dir` and rewrite summary.md + scores.json. Returns the
    aggregate dict."""
    d = Path(results_dir)
    runs_dir = d / "runs"
    files = sorted(runs_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no run files in {runs_dir}")
    raw_records = [json.loads(f.read_text()) for f in files]
    tasks_by_id = pack.tasks_by_id()
    records: list[dict] = []
    for rr in raw_records:
        task = tasks_by_id.get(rr["task_id"])
        rec = dict(rr)
        if task is not None:
            score, parsed = score_response(task, rr.get("raw_response", ""), pack.base_prefix_segments)
            rec["format_failure"] = score.format_failure
            rec["failure_reason"] = score.failure_reason
            rec["dimensions"] = {dm: (score.dim(dm).score if score.dim(dm) else None)
                                 for dm in DIMENSIONS}
            rec["endpoint_matches"] = score.endpoint_matches
            # Clear before re-deciding: `dict(rr)` carries the archived value forward, so a
            # conditionally-set key would otherwise survive a rebuild in which the repair no
            # longer fires — a stale `true` that could never be cleared (ADR-0014).
            rec.pop("format_repaired", None)
            rec.pop("repaired_block_text", None)
            if parsed.repaired:
                rec["format_repaired"] = True
                rec["repaired_block_text"] = parsed.repaired_block_text
        records.append(rec)

    # Infer <YYYY-MM-DD>-<condition> from the dir name (e.g. 2026-07-23-no-context).
    name = d.name
    parts = name.split("-", 3)
    date = "-".join(parts[:3]) if len(parts) >= 4 else name
    condition = parts[3] if len(parts) >= 4 else "unknown"
    n = max((r.get("run_index", 0) for r in records), default=0) + 1

    # Preserve the original run's metadata where present so a re-score for integrity does not silently
    # rewrite how the run was produced.
    prior: dict = {}
    scores_json = d / "scores.json"
    if scores_json.exists():
        try:
            prior = json.loads(scores_json.read_text()).get("metadata", {})
        except (OSError, json.JSONDecodeError):
            prior = {}
    metadata = {
        "condition": prior.get("condition", condition),
        "model": prior.get("model", model),
        "provider": prior.get("provider", provider),
        "sampling": prior.get("sampling",
                              "cli default (temperature not configurable via CLI)"
                              if provider == "cli" else "temperature=0"),
        "date": prior.get("date", date),
        "spec_sha": pack.spec_sha(),
        "n": prior.get("n", n),
        "mock": False,
        "model_reported": prior.get("model_reported", [model]),
        "total_cost_usd": prior.get("total_cost_usd",
                                    round(sum(r.get("cost_usd", 0.0) for r in records), 4)),
        "total_duration_ms": prior.get("total_duration_ms",
                                       sum(r.get("duration_ms", 0) for r in records)),
        "rebuilt_from_runs": True,
    }
    if note:
        metadata["rebuild_note"] = note
    agg = write_reports(d, records, metadata)

    # ADR-0033. Every value this function just recomputed is now in scores.json and nowhere else; the
    # run records still carry whatever the scorer said the day the grid ran. `cmd_run` resumes a grid
    # by appending an archived record verbatim, so leaving them stale is a live path to a wrong
    # published number, not an untidy archive. Syncing here rather than writing the records inline is
    # deliberate: it is the same code the standing consistency sweep checks with, so the fix and the
    # test cannot disagree about what "agrees" means. It re-reads what was just written and refuses to
    # touch anything if a transport-derived field does not match — the raw evidence is never rewritten.
    report = reconcile_runs(d, write=True)
    if not report.ok:
        raise RuntimeError("rebuilt reports, but the run records could not be reconciled with them: "
                           + "; ".join(report.problems))
    return agg
