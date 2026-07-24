"""Post-run analysis: list the endpoints a model proposed that are not ground truth.

Re-parses the archived answers in a results dir and, per task, reports every
answer endpoint whose normalized path matches no ground-truth endpoint for that
task. These "unmatched" endpoints are the raw material for the invented-endpoints
exhibit (a human then curates which are genuinely non-existent vs. real-but-wrong).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import answer_block
from .scorer import normalize_path


def _gt_paths(task: dict) -> list[list[str]]:
    return [normalize_path(e["path"]) for e in task["ground_truth"]["endpoints"]]


def unmatched_endpoints(results_dir: str | Path, tasks_by_id: dict) -> dict:
    """Return {task_id: Counter({(method, verbatim_path): count})} for unmatched endpoints."""
    runs_dir = Path(results_dir) / "runs"
    out: dict[str, Counter] = {}
    for run_file in sorted(runs_dir.glob("*.json")):
        rec = json.loads(run_file.read_text())
        task_id = rec["task_id"]
        task = tasks_by_id.get(task_id)
        if not task:
            continue
        parsed = answer_block.parse(rec.get("raw_response", ""))
        if parsed.is_failure:
            continue
        gt = _gt_paths(task)
        counter = out.setdefault(task_id, Counter())
        for ep in parsed.summary.endpoints:
            npath = normalize_path(ep.path)
            if npath not in gt:
                counter[(ep.method or "?", ep.path or "?")] += 1
    return out


def format_unmatched(unmatched: dict) -> str:
    lines = []
    for task_id in sorted(unmatched):
        entries = unmatched[task_id]
        if not entries:
            continue
        lines.append(f"## {task_id}")
        for (method, path), count in entries.most_common():
            lines.append(f"  {method:6s} {path}   (x{count})")
    return "\n".join(lines) if lines else "(no unmatched endpoints)"


def consultation_rates(results_dir: str | Path, mcp_tool_prefix: str) -> dict:
    """Per-task tool-consultation stats for an mcp-condition results dir (ADR-0009 lineage).

    A run "consulted" if it invoked at least one tool under the pack's `mcp_tool_prefix` (the
    discovery meta-tool alone is only discovery, not consultation). "Availability isn't adoption":
    the context-layer server is offered on every run, but the model decides whether to use it.
    Returns {task_id: {runs, consulted, skipped, skip_rate}} plus an "_overall" key.
    """
    runs_dir = Path(results_dir) / "runs"
    per: dict[str, dict] = {}
    for run_file in sorted(runs_dir.glob("*.json")):
        rec = json.loads(run_file.read_text())
        tid = rec["task_id"]
        names = [t.get("name") for t in (rec.get("tool_uses") or [])]
        consulted = any(n and n.startswith(mcp_tool_prefix) for n in names)
        d = per.setdefault(tid, {"runs": 0, "consulted": 0, "skipped": 0})
        d["runs"] += 1
        d["consulted" if consulted else "skipped"] += 1
    total = {"runs": 0, "consulted": 0, "skipped": 0}
    for d in per.values():
        for k in total:
            total[k] += d[k]
        d["skip_rate"] = round(d["skipped"] / d["runs"], 3) if d["runs"] else None
    total["skip_rate"] = round(total["skipped"] / total["runs"], 3) if total["runs"] else None
    per["_overall"] = total
    return per


def format_consultation(rates: dict) -> str:
    lines = ["task                      runs  consulted  skipped  skip_rate"]
    overall = rates.get("_overall")
    for tid in sorted(k for k in rates if k != "_overall"):
        d = rates[tid]
        lines.append(f"{tid:24s}  {d['runs']:4d}  {d['consulted']:9d}  {d['skipped']:7d}  "
                     f"{d['skip_rate']:.0%}")
    if overall:
        lines.append(f"{'ALL':24s}  {overall['runs']:4d}  {overall['consulted']:9d}  "
                     f"{overall['skipped']:7d}  {overall['skip_rate']:.0%}")
    return "\n".join(lines)
