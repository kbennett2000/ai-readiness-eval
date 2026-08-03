"""Report generator: turn per-run scores into summary.md + scores.json (ADR-0004).

Consumes a list of run-record dicts (produced by the runner) plus a metadata dict.
Everything here is pure computation over those records so it is trivially testable
and re-runnable from committed raw responses.
"""
from __future__ import annotations

import json
from statistics import mean

from .contract import API_CONTRACT
from .scorer import DIMENSIONS

# The API cohort's dimension labels, kept as a module constant because tools outside this repo import
# it by name. Every renderer below now takes its dimensions and labels from a CONTRACT (ADR-0044) and
# defaults to the API one, so a caller that passes nothing gets byte-identical output.
_DIM_LABELS = dict(API_CONTRACT.dim_labels)


def _dims_and_labels(contract):
    """`(dimensions, labels)` for a renderer. `None` means the API contract, exactly as before."""
    if contract is None:
        return list(DIMENSIONS), _DIM_LABELS
    return list(contract.dimensions), contract.dim_labels


def _fmt_cell(value) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def aggregate(records: list[dict], contract=None) -> dict:
    """Compute per-task and overall aggregates from run records.

    A run with format_failure contributes to the format-failure count and is
    excluded from dimension means (its dimensions are absent). A dimension that is
    n/a for a task (score None) is excluded from that dimension's mean.
    """
    dimensions, _labels = _dims_and_labels(contract)
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
        for dim in dimensions:
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
    for dim in dimensions:
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


# ---------------------------------------------------------------------------
# Coverage disclosure (ADR-0046)
#
# A published `overall_accuracy` is the mean of the dimensions that were actually scored, which is
# not always the set the contract declares — ADR-0045 measured the condition at 13 of 18 packs. The
# cell reads `n/a`, a word this project uses legitimately and often, and nothing said the overall
# beside it was a mean of five where the header said six. These two functions GENERATE that sentence
# so a card can paste it and a gate can recompute it; a hand-typed derived figure is the failure
# mode `render_group_comparison_md` already exists to avoid.
# ---------------------------------------------------------------------------

_COVERAGE_ADR = "ADR-0045"


def covered_dimensions(agg: dict, contract=None) -> tuple[list[str], list[str]]:
    """`(covered, unexercised)` for one aggregate: covered iff the dimension's overall is not None.

    That is exactly the set `overall_accuracy` was averaged over, so the count this returns is a
    fact about the published number rather than a second opinion about it.
    """
    dims, _labels = _dims_and_labels(contract)
    overall = agg.get("overall_dimensions") or {}
    covered = [d for d in dims if overall.get(d) is not None]
    return covered, [d for d in dims if d not in covered]


def _names(labels, dims) -> str:
    return ", ".join(f"**{labels[d]}**" for d in dims)


def coverage_line(agg: dict, contract=None, unexercised: dict | None = None,
                  adr_ref: str = _COVERAGE_ADR) -> str:
    """The one-line coverage disclosure for a card (ADR-0046).

    `unexercised` is the pack's `unexercised_dimensions` declaration ({dimension: written reason});
    a dimension with no task is named either way, and whether a reason was written for it is part of
    what the line says. `adr_ref` lets a downstream repo cite the ADR the way its own docs do.
    """
    dims, labels = _dims_and_labels(contract)
    covered, missing = covered_dimensions(agg, contract)
    declared = {k: v for k, v in (unexercised or {}).items() if str(v).strip()}

    # The count and the published mean must agree, or the line would describe a different number
    # than the one printed beside it. Structural, not asserted in a test only.
    if bool(covered) != (agg.get("overall_accuracy") is not None):
        raise ValueError(
            f"coverage disagrees with the published overall: {len(covered)} dimension(s) scored but "
            f"overall_accuracy={agg.get('overall_accuracy')!r}"
        )

    head = f"**Dimension coverage ({adr_ref}):** overall = mean of "
    if not covered:
        return (head.replace("overall = mean of ", "this pack publishes no overall — ")
                + f"no declared dimension ({', '.join(labels[d] for d in dims)}) is exercised by any task.")
    if not missing:
        return head + (f"**all {len(dims)}** declared dimensions — "
                       + ", ".join(labels[d] for d in dims) + ".")

    line = (head + f"**{len(covered)} of {len(dims)}** declared dimensions — "
            + ", ".join(labels[d] for d in covered) + ".")
    with_reason = [d for d in missing if d in declared]
    without = [d for d in missing if d not in declared]
    if with_reason:
        line += (f" {_names(labels, with_reason)} {'is' if len(with_reason) == 1 else 'are'} exercised"
                 f" by no task; [`pack.yaml`](pack.yaml) declares"
                 f" {'the reason' if len(with_reason) == 1 else 'the reasons'}.")
    if without:
        line += (f" {_names(labels, without)} {'is' if len(without) == 1 else 'are'} exercised by no"
                 f" task, and no written reason is declared in `pack.yaml`.")
    return line


def coverage_cohort_note(entries: list[tuple[str, dict]], contract=None,
                         adr_ref: str = _COVERAGE_ADR) -> str:
    """The one-line coverage note for a cohort's comparison table (ADR-0046).

    `entries` is `[(label, aggregate)]` for every measured pack in one cohort. The counts are
    generated for the same reason the per-card line is: a cohort table's prose goes stale one new
    pack at a time, silently, and this one is checked against the packs on disk.
    """
    dims, labels = _dims_and_labels(contract)
    n = len(entries)
    if not n:
        raise ValueError("a cohort note over no measured pack would be a sentence about nothing")

    per_pack = [covered_dimensions(agg, contract) for _label, agg in entries]
    shortfalls: dict[str, int] = {}
    for _covered, missing in per_pack:
        for d in missing:
            shortfalls[d] = shortfalls.get(d, 0) + 1

    if not shortfalls:
        return (f"> **Every overall in this column is the mean of all {len(dims)} declared "
                f"dimensions** ({', '.join(labels[d] for d in dims)}), and each card states that on "
                f"one line ({adr_ref}).")

    tail = (f" Each card states its own coverage on one line, recomputed from its committed scores "
            f"({adr_ref}).")
    if n == 1:
        covered, missing = per_pack[0]
        return (f"> **The overall in this column is not the mean of all {len(dims)} declared "
                f"dimensions.** The single measured pack scores {len(covered)} of {len(dims)}; no "
                f"task exercises {_names(labels, missing)}." + tail)

    by_count: dict[int, int] = {}
    for covered, _missing in per_pack:
        by_count[len(covered)] = by_count.get(len(covered), 0) + 1
    groups = ", ".join(
        f"{c} {'scores' if c == 1 else 'score'} "
        + (f"all {k}" if k == len(dims) else f"{k} of {len(dims)}")
        for k, c in sorted(by_count.items(), reverse=True)
    )
    misses = " and ".join(
        f"{_names(labels, [d])} in {c}"
        for d, c in sorted(shortfalls.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return (f"> **Not every overall in this column is the mean of the same number of dimensions.** "
            f"Of {n} measured packs against {len(dims)} declared dimensions: {groups}; no task "
            f"exercises {misses}." + tail)


def render_summary_md(agg: dict, metadata: dict, contract=None) -> str:
    dims, labels = _dims_and_labels(contract)
    header = "| task | " + " | ".join(labels[d] for d in dims) + " | fmt-fail |"
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
                         label_b: str, agg_b: dict, meta_b: dict, contract=None) -> str:
    """Side-by-side comparison of two conditions (e.g. no-context vs public-docs)."""
    dims, labels = _dims_and_labels(contract)
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
        lines.append(f"| {labels[d]} | {_fmt_cell(a)} | {_fmt_cell(b)} | {_delta_cell(a, b)} |")
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
              "| task | " + " | ".join(labels[d] for d in dims) + " | fmt A/B |",
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


def render_group_comparison_md(label_a: str, roll_a: dict, label_b: str, roll_b: dict,
                               groups: dict, note: str | None = None, contract=None) -> str:
    """Two conditions × a pack's declared task groups, dimension by dimension (ADR-0026).

    `roll_a`/`roll_b` are `category.rollup_by_group` outputs for the same grouping; `groups` is the
    pack's `task_groups` block, which supplies each group's label, rationale and task list.

    This renderer exists so a group split is GENERATED rather than typed. Cycle 19's whole finding
    was that hand-maintained derived numbers go stale silently while the gated ones stay right.
    """
    dims, labels = _dims_and_labels(contract)
    lines = [f"# Task-group comparison — {label_a} vs {label_b}", ""]
    if note:
        lines += [f"> {note}", ""]
    lines += [
        "## Overall accuracy by group",
        "",
        f"| group | tasks | {label_a} | {label_b} | delta |",
        "|---|---|---|---|---|",
    ]
    for key in groups:
        a, b = roll_a.get(key, {}), roll_b.get(key, {})
        label = groups[key].get("label", key)
        oa, ob = a.get("overall"), b.get("overall")
        lines.append(f"| **{label}** | {len(a.get('tasks', []))} | "
                     f"{_fmt_cell(oa)} | {_fmt_cell(ob)} | {_delta_cell(oa, ob)} |")

    for key in groups:
        a, b = roll_a.get(key, {}), roll_b.get(key, {})
        label = groups[key].get("label", key)
        lines += ["", f"### {label}", ""]
        rationale = groups[key].get("rationale")
        if rationale:
            lines += [f"{str(rationale).strip()}", ""]
        lines += [f"| dimension | {label_a} | {label_b} | delta |", "|---|---|---|---|"]
        for d in dims:
            va, vb = a.get("dimensions", {}).get(d), b.get("dimensions", {}).get(d)
            lines.append(f"| {labels[d]} | {_fmt_cell(va)} | {_fmt_cell(vb)} | "
                         f"{_delta_cell(va, vb)} |")
        oa, ob = a.get("overall"), b.get("overall")
        lines.append(f"| **overall** | {_fmt_cell(oa)} | {_fmt_cell(ob)} | {_delta_cell(oa, ob)} |")
        lines += ["", "Tasks: " + ", ".join(f"`{t}`" for t in a.get("tasks", [])) + "."]

    lines.append("")
    return "\n".join(lines)


def render_multi_comparison_md(entries: list[tuple[str, dict, dict]], note: str | None = None,
                               contract=None) -> str:
    """N-condition side-by-side (e.g. no-context vs public-docs vs mcp). `entries` is an ordered list
    of (label, aggregate, metadata); the LAST entry is treated as the 'after' and gets deltas vs each
    prior condition. Includes the per-condition tool-discipline summary when present in metadata."""
    dims, dim_labels = _dims_and_labels(contract)
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
        lines.append(_row(dim_labels[d], [a["overall_dimensions"][d] for a in aggs]))
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
              "| task | " + " | ".join(dim_labels[d] for d in dims) + " |",
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
                          base_label: str = "cycle-6", contract=None) -> str:
    """Per-condition, per-dimension delta of NEW minus BASELINE, matched by condition name.

    Quantifies what the ambient crib sheet (CLAUDE.md) was worth to each condition: a large negative
    number means that condition leaned on CLAUDE.md and the true-cold score is lower. Reuses
    `_delta_cell`'s `"+N pts"` convention (delta = new − base)."""
    dims, labels = _dims_and_labels(contract)
    base_by = {meta.get("condition", lbl): agg for lbl, agg, meta in baseline_entries}
    lines = [
        f"## Delta vs {base_label}: what the crib sheet (CLAUDE.md) was worth", "",
        f"> {new_label} − {base_label}, per condition per dimension (matched by condition name). "
        f"Positive = {new_label} scored higher; negative = the condition leaned on ambient CLAUDE.md.",
        "",
        "| condition | " + " | ".join(labels[d] for d in dims) + " | overall |",
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


def write_reports(out_dir, records: list[dict], metadata: dict, contract=None) -> dict:
    """Write summary.md + scores.json into out_dir. Returns the aggregate dict."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    agg = aggregate(records, contract)
    (out / "summary.md").write_text(render_summary_md(agg, metadata, contract))
    (out / "scores.json").write_text(
        json.dumps({"metadata": metadata, "aggregate": agg, "runs": records}, indent=2, sort_keys=True)
    )
    return agg
