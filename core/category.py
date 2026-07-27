"""Category-level rollup + cross-vendor comparison (ADR-0004).

Cross-vendor comparison happens only at the job-category level (ADR-0003): tasks are product-native and
do not compare across vendors, but their `job_category` does. This module rolls a single condition's
per-task aggregate up to per-category numbers, then renders a labeled cross-vendor table from several
such rollups.

It names no vendor. Callers pass a label and a `task_id -> job_category` map (available from a loaded
`Pack.tasks_by_id()`), so the same renderer serves any set of packs — including the public reference
pack, whose 1:1 task/category map makes its per-task table also its per-category table (a known-good
check used by the tests).
"""
from __future__ import annotations

from statistics import mean

from .scorer import DIMENSIONS
from .taxonomy import CATEGORIES


def _fmt_cell(value) -> str:
    """Percent or n/a — mirrors report._fmt_cell so the two renderers read identically."""
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def rollup_by_group(aggregate: dict, task_to_group: dict, groups,
                    na_groups: dict | None = None) -> dict:
    """Roll one condition's per-task aggregate up to per-GROUP numbers (ADR-0026).

    The grouping is a parameter, not a fixed taxonomy: `groups` is the ordered set of group keys to
    emit and `task_to_group` maps each task id into one of them. `job_category` is one such grouping
    (see `rollup_by_category`); a pack's declared `task_groups` — e.g. surface age — is another.

    Each dimension is the mean of the group's tasks' per-dimension means — a coarse rollup, the raw
    runs are not re-pooled. `na_groups` (optional `{group: reason}`) marks groups the pack declares
    not-applicable: they render `n/a` and carry the reason.

    Returns `{group: {dimensions{6}, overall, tasks:[...], na:bool, na_reason}}` in `groups` order.
    """
    na = dict(na_groups or {})
    per_task = aggregate.get("per_task", {})

    by_group: dict[str, list[str]] = {g: [] for g in groups}
    for tid, group in task_to_group.items():
        if group in by_group and tid in per_task:
            by_group[group].append(tid)

    out: dict[str, dict] = {}
    for group in groups:
        tids = by_group[group]
        if group in na:
            out[group] = {
                "dimensions": {d: None for d in DIMENSIONS},
                "overall": None,
                "tasks": tids,
                "na": True,
                "na_reason": na[group],
            }
            continue
        dims: dict[str, float | None] = {}
        for d in DIMENSIONS:
            vals = [per_task[t]["dimensions"].get(d) for t in tids]
            vals = [v for v in vals if v is not None]
            dims[d] = mean(vals) if vals else None
        applicable = [v for v in dims.values() if v is not None]
        out[group] = {
            "dimensions": dims,
            "overall": mean(applicable) if applicable else None,
            "tasks": tids,
            "na": False,
            "na_reason": None,
        }
    return out


def rollup_by_category(aggregate: dict, task_to_category: dict,
                       na_categories: dict | None = None) -> dict:
    """Roll one condition's per-task aggregate up to per-category numbers.

    `aggregate` is the `aggregate` block of a scores.json (it must carry `per_task`). `task_to_category`
    maps each task id to its `job_category`. When several tasks share a category, each dimension is the
    mean of those tasks' per-dimension means — a simple, coarse category rollup (category comparison is
    coarse by design; the raw runs are not re-pooled). `na_categories` (optional `{category: reason}`)
    marks categories the pack declares not-applicable — they render `n/a` and carry the reason.

    Returns `{category: {dimensions{6}, overall, tasks:[...], na:bool, na_reason}}` for every canonical
    category, in taxonomy order.

    A thin wrapper over `rollup_by_group` with the taxonomy as the grouping (ADR-0026) — the
    arithmetic lives in exactly one place, so a pack's own task groups and the shared job-category
    rollup can never drift into computing "the mean of a group" two different ways.
    """
    return rollup_by_group(aggregate, task_to_category, CATEGORIES, na_categories)


def render_cross_vendor_category_md(sources: list[tuple[str, dict]],
                                    note: str | None = None,
                                    dimension: str | None = None) -> str:
    """Render a category × source table. `sources` is an ordered list of `(label, rollup)` (each rollup
    from `rollup_by_category`). Cells are the per-category overall accuracy, or a single `dimension`'s
    value when `dimension` is given. A category that a source marks N/A — or has no task for — renders
    `n/a`. Comparison is category-level only, by design (ADR-0003)."""
    labels = [s[0] for s in sources]
    rollups = [s[1] for s in sources]
    what = dimension or "overall accuracy"
    lines = [f"# Cross-vendor category comparison — {what}", ""]
    if note:
        lines += [f"> **Note:** {note}", ""]
    lines += [
        "> Category level only — tasks are product-native and do not compare directly (ADR-0003). "
        "Cells are the mean of the applicable dimension scores for the tasks a vendor maps onto that "
        "category; `n/a` = the vendor declares the category not-applicable or has no task for it.",
        "",
        "| category | " + " | ".join(labels) + " |",
        "|" + "---|" * (len(labels) + 1),
    ]
    for cat in CATEGORIES:
        cells = []
        for r in rollups:
            entry = r.get(cat)
            if entry is None:
                cells.append("n/a")
            elif dimension:
                cells.append(_fmt_cell(entry["dimensions"].get(dimension)))
            else:
                cells.append(_fmt_cell(entry["overall"]))
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)
