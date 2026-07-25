"""Report generator: turn per-run scores into summary.md + scores.json (ADR-0004).

Consumes a list of run-record dicts (produced by the runner) plus a metadata dict.
Everything here is pure computation over those records so it is trivially testable
and re-runnable from committed raw responses.
"""
from __future__ import annotations

import json
from statistics import mean

from .scorer import DIMENSIONS

_DIM_LABELS = {
    "endpoint": "endpoint",
    "method": "method",
    "api_version": "version",
    "auth_flow": "auth",
    "required_scopes": "scopes",
    "key_parameters": "params",
}


def _fmt_cell(value) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def aggregate(records: list[dict]) -> dict:
    """Compute per-task and overall aggregates from run records.

    A run with format_failure contributes to the format-failure count and is
    excluded from dimension means (its dimensions are absent). A dimension that is
    n/a for a task (score None) is excluded from that dimension's mean.
    """
    task_ids: list[str] = []
    for r in records:
        if r["task_id"] not in task_ids:
            task_ids.append(r["task_id"])

    per_task: dict[str, dict] = {}
    for tid in task_ids:
        runs = [r for r in records if r["task_id"] == tid]
        n_runs = len(runs)
        n_fmt = sum(1 for r in runs if r.get("format_failure"))
        scored = [r for r in runs if not r.get("format_failure")]
        dim_means: dict[str, float | None] = {}
        for dim in DIMENSIONS:
            vals = [
                r["dimensions"][dim] for r in scored
                if r.get("dimensions", {}).get(dim) is not None
            ]
            dim_means[dim] = mean(vals) if vals else None
        per_task[tid] = {
            "runs": n_runs,
            "format_failures": n_fmt,
            "format_repairs": sum(1 for r in runs if r.get("format_repaired")),
            "dimensions": dim_means,
        }

    # Overall per-dimension mean across all scored runs (all tasks pooled).
    overall: dict[str, float | None] = {}
    scored_all = [r for r in records if not r.get("format_failure")]
    for dim in DIMENSIONS:
        vals = [
            r["dimensions"][dim] for r in scored_all
            if r.get("dimensions", {}).get(dim) is not None
        ]
        overall[dim] = mean(vals) if vals else None

    applicable = [v for v in overall.values() if v is not None]
    return {
        "task_ids": task_ids,
        "per_task": per_task,
        "overall_dimensions": overall,
        "overall_accuracy": mean(applicable) if applicable else None,
        "total_runs": len(records),
        "format_failures": sum(1 for r in records if r.get("format_failure")),
        # ADR-0014. Always present, including as 0 — a reader must be able to tell
        # "no answer needed repair" from "this report predates the counter".
        "format_repairs": sum(1 for r in records if r.get("format_repaired")),
    }


def render_summary_md(agg: dict, metadata: dict) -> str:
    dims = list(DIMENSIONS)
    header = "| task | " + " | ".join(_DIM_LABELS[d] for d in dims) + " | fmt-fail |"
    sep = "|" + "---|" * (len(dims) + 2)
    lines = [
        f"# Eval results — {metadata.get('condition', '?')}",
        "",
        "## Run metadata",
        "",
        f"- **condition:** {metadata.get('condition')}",
        f"- **model:** {metadata.get('model')}",
        f"- **provider:** {metadata.get('provider')}",
        f"- **sampling:** {metadata.get('sampling')}",
        f"- **date:** {metadata.get('date')}",
        f"- **spec_sha:** {metadata.get('spec_sha')}",
        f"- **runs per task (N):** {metadata.get('n')}",
        f"- **total runs:** {agg['total_runs']}",
        f"- **format failures:** {agg['format_failures']}",
        f"- **format repairs (ADR-0014):** {agg.get('format_repairs', 0)}",]
    if metadata.get("total_cost_usd") is not None and metadata.get("provider") not in (None, "mock"):
        lines.append(f"- **subscription cost (USD, as reported by CLI):** "
                     f"{metadata.get('total_cost_usd')}")
    tds = metadata.get("tool_discipline_summary")
    if tds:
        lines.append(f"- **tool discipline:** {tds.get('violations_logged', 0)} violation(s) logged "
                     f"across {tds.get('runs_asserted', 0)} asserted runs; "
                     f"final all-ok: {tds.get('final_all_ok')}")
    if metadata.get("rebuild_note"):
        lines += ["", f"> **Disclosure:** {metadata['rebuild_note']}"]
    lines += [
        "",
        "Cells are mean accuracy across the N runs for that task; `n/a` = the "
        "dimension does not apply to that task (e.g. no required scopes). "
        "`fmt-fail` counts runs whose `answer-summary` block was unparseable "
        "(excluded from the dimension means, never scored zero).",
        "",
        "## Per-task × per-dimension",
        "",
        header,
        sep,
    ]
    for tid in agg["task_ids"]:
        pt = agg["per_task"][tid]
        cells = [_fmt_cell(pt["dimensions"][d]) for d in dims]
        lines.append(f"| {tid} | " + " | ".join(cells) + f" | {pt['format_failures']}/{pt['runs']} |")

    overall_cells = [_fmt_cell(agg["overall_dimensions"][d]) for d in dims]
    lines.append(f"| **ALL** | " + " | ".join(overall_cells) + f" | {agg['format_failures']}/{agg['total_runs']} |")

    lines += [
        "",
        "## Aggregate",
        "",
        f"- **overall accuracy (mean of applicable dimension scores):** {_fmt_cell(agg['overall_accuracy'])}",
        f"- **format failures:** {agg['format_failures']} of {agg['total_runs']} runs",
        "",
        "## Scoring notes (judgment calls — see ADR-0004)",
        "",
        "- **required_scopes** is scored as *any-of overlap*: a run passes when it "
        "names at least one scope in the ground-truth acceptable set, because task "
        "ground truth mixes alternative scopes with jointly-required ones.",
        "- **key_parameters** is scored over the *required-subset* of ground-truth "
        "parameters; optional params (paging, optional filters) are ignored.",
        "- **method** and **api_version** are credited only on endpoints whose path "
        "was matched — a right method on an unidentified endpoint earns nothing.",
        "",
    ]
    return "\n".join(lines)


def _task_accuracy(dims: dict) -> float | None:
    vals = [v for v in dims.values() if v is not None]
    return mean(vals) if vals else None


def _delta_cell(a, b) -> str:
    if a is None or b is None:
        return "n/a"
    d = (b - a) * 100
    return f"{d:+.0f} pts"


def render_comparison_md(label_a: str, agg_a: dict, meta_a: dict,
                         label_b: str, agg_b: dict, meta_b: dict) -> str:
    """Side-by-side comparison of two conditions (e.g. no-context vs public-docs)."""
    dims = list(DIMENSIONS)
    task_ids = list(dict.fromkeys(agg_a["task_ids"] + agg_b["task_ids"]))
    lines = [
        f"# Condition comparison — {label_a} vs {label_b}",
        "",
        "## Run metadata",
        "",
        f"- **A = {label_a}:** model {meta_a.get('model')}, provider {meta_a.get('provider')}, "
        f"{meta_a.get('date')}, N={meta_a.get('n')}",
        f"- **B = {label_b}:** model {meta_b.get('model')}, provider {meta_b.get('provider')}, "
        f"{meta_b.get('date')}, N={meta_b.get('n')}",
        f"- **spec_sha:** {meta_a.get('spec_sha')}",
        "",
        "## Overall accuracy by dimension",
        "",
        f"| dimension | {label_a} | {label_b} | delta |",
        "|---|---|---|---|",
    ]
    for d in dims:
        a, b = agg_a["overall_dimensions"][d], agg_b["overall_dimensions"][d]
        lines.append(f"| {_DIM_LABELS[d]} | {_fmt_cell(a)} | {_fmt_cell(b)} | {_delta_cell(a, b)} |")
    oa, ob = agg_a["overall_accuracy"], agg_b["overall_accuracy"]
    lines.append(f"| **overall** | {_fmt_cell(oa)} | {_fmt_cell(ob)} | {_delta_cell(oa, ob)} |")
    lines += [
        f"| format failures | {agg_a['format_failures']}/{agg_a['total_runs']} | "
        f"{agg_b['format_failures']}/{agg_b['total_runs']} | |",
        "",
        "## Per-task accuracy (mean of applicable dimensions)",
        "",
        f"| task | {label_a} | {label_b} | delta |",
        "|---|---|---|---|",
    ]
    for tid in task_ids:
        da = agg_a["per_task"].get(tid, {}).get("dimensions", {})
        db = agg_b["per_task"].get(tid, {}).get("dimensions", {})
        aa, ab = _task_accuracy(da), _task_accuracy(db)
        lines.append(f"| {tid} | {_fmt_cell(aa)} | {_fmt_cell(ab)} | {_delta_cell(aa, ab)} |")

    lines += ["", "## Per-task × per-dimension (A / B)", "",
              "| task | " + " | ".join(_DIM_LABELS[d] for d in dims) + " | fmt A/B |",
              "|" + "---|" * (len(dims) + 2)]
    for tid in task_ids:
        da = agg_a["per_task"].get(tid, {}).get("dimensions", {})
        db = agg_b["per_task"].get(tid, {}).get("dimensions", {})
        cells = [f"{_fmt_cell(da.get(d))} / {_fmt_cell(db.get(d))}" for d in dims]
        fa = agg_a["per_task"].get(tid, {})
        fb = agg_b["per_task"].get(tid, {})
        lines.append(f"| {tid} | " + " | ".join(cells) +
                     f" | {fa.get('format_failures', 0)}/{fb.get('format_failures', 0)} |")
    lines.append("")
    return "\n".join(lines)


def render_multi_comparison_md(entries: list[tuple[str, dict, dict]], note: str | None = None) -> str:
    """N-condition side-by-side (e.g. no-context vs public-docs vs mcp). `entries` is an ordered list
    of (label, aggregate, metadata); the LAST entry is treated as the 'after' and gets deltas vs each
    prior condition. Includes the per-condition tool-discipline summary when present in metadata."""
    dims = list(DIMENSIONS)
    labels = [e[0] for e in entries]
    aggs = [e[1] for e in entries]
    metas = [e[2] for e in entries]
    task_ids: list[str] = []
    for a in aggs:
        for tid in a["task_ids"]:
            if tid not in task_ids:
                task_ids.append(tid)

    lines = [f"# Condition comparison — {' vs '.join(labels)}", ""]
    if note:
        lines += [f"> **Note:** {note}", ""]
    lines += ["## Run metadata", ""]
    for lbl, _agg, meta in entries:
        line = (f"- **{lbl}:** model {meta.get('model')}, provider {meta.get('provider')}, "
                f"{meta.get('date')}, N={meta.get('n')}")
        tds = meta.get("tool_discipline_summary")
        if tds:
            line += (f" — tool discipline: {tds.get('violations_logged', 0)} violation(s) / "
                     f"{tds.get('runs_asserted', 0)} asserted, all-ok={tds.get('final_all_ok')}")
        lines.append(line)
    lines += [f"- **spec_sha:** {metas[0].get('spec_sha')}", ""]

    # Overall accuracy by dimension, with deltas of the last condition vs each prior one.
    delta_heads = [f"Δ({labels[-1]}−{labels[i]})" for i in range(len(labels) - 1)]
    lines += ["## Overall accuracy by dimension", "",
              "| dimension | " + " | ".join(labels) + " | " + " | ".join(delta_heads) + " |",
              "|" + "---|" * (len(labels) + len(delta_heads) + 1)]

    def _row(name, values):
        cells = [_fmt_cell(v) for v in values]
        deltas = [_delta_cell(values[i], values[-1]) for i in range(len(values) - 1)]
        return f"| {name} | " + " | ".join(cells) + " | " + " | ".join(deltas) + " |"

    for d in dims:
        lines.append(_row(_DIM_LABELS[d], [a["overall_dimensions"][d] for a in aggs]))
    lines.append(_row("**overall**", [a["overall_accuracy"] for a in aggs]))
    lines.append("| format failures | "
                 + " | ".join(f"{a['format_failures']}/{a['total_runs']}" for a in aggs)
                 + " |" + " |" * len(delta_heads))

    # Per-task overall accuracy.
    lines += ["", "## Per-task accuracy (mean of applicable dimensions)", "",
              "| task | " + " | ".join(labels) + " |", "|" + "---|" * (len(labels) + 1)]
    for tid in task_ids:
        accs = [_task_accuracy(a["per_task"].get(tid, {}).get("dimensions", {})) for a in aggs]
        lines.append(f"| {tid} | " + " | ".join(_fmt_cell(x) for x in accs) + " |")

    # Per-task × per-dimension, cells "v1 / v2 / v3".
    lines += ["", f"## Per-task × per-dimension ({' / '.join(labels)})", "",
              "| task | " + " | ".join(_DIM_LABELS[d] for d in dims) + " |",
              "|" + "---|" * (len(dims) + 1)]
    for tid in task_ids:
        cells = []
        for d in dims:
            vals = [a["per_task"].get(tid, {}).get("dimensions", {}).get(d) for a in aggs]
            cells.append(" / ".join(_fmt_cell(v) for v in vals))
        lines.append(f"| {tid} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def render_delta_table_md(new_entries: list[tuple[str, dict, dict]],
                          baseline_entries: list[tuple[str, dict, dict]],
                          new_label: str = "cycle-7 sterile",
                          base_label: str = "cycle-6") -> str:
    """Per-condition, per-dimension delta of NEW minus BASELINE, matched by condition name.

    Quantifies what the ambient crib sheet (CLAUDE.md) was worth to each condition: a large negative
    number means that condition leaned on CLAUDE.md and the true-cold score is lower. Reuses
    `_delta_cell`'s `"+N pts"` convention (delta = new − base)."""
    dims = list(DIMENSIONS)
    base_by = {meta.get("condition", lbl): agg for lbl, agg, meta in baseline_entries}
    lines = [
        f"## Delta vs {base_label}: what the crib sheet (CLAUDE.md) was worth", "",
        f"> {new_label} − {base_label}, per condition per dimension (matched by condition name). "
        f"Positive = {new_label} scored higher; negative = the condition leaned on ambient CLAUDE.md.",
        "",
        "| condition | " + " | ".join(_DIM_LABELS[d] for d in dims) + " | overall |",
        "|" + "---|" * (len(dims) + 2),
    ]
    for lbl, agg, meta in new_entries:
        cond = meta.get("condition", lbl)
        bagg = base_by.get(cond)
        if bagg is None:
            lines.append(f"| {cond} | " + " | ".join(["n/a"] * len(dims)) + " | n/a |")
            continue
        cells = [_delta_cell(bagg["overall_dimensions"][d], agg["overall_dimensions"][d]) for d in dims]
        odelta = _delta_cell(bagg["overall_accuracy"], agg["overall_accuracy"])
        lines.append(f"| {cond} | " + " | ".join(cells) + f" | {odelta} |")
    lines.append("")
    return "\n".join(lines)


def write_reports(out_dir, records: list[dict], metadata: dict) -> dict:
    """Write summary.md + scores.json into out_dir. Returns the aggregate dict."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    agg = aggregate(records)
    (out / "summary.md").write_text(render_summary_md(agg, metadata))
    (out / "scores.json").write_text(
        json.dumps({"metadata": metadata, "aggregate": agg, "runs": records}, indent=2, sort_keys=True)
    )
    return agg
