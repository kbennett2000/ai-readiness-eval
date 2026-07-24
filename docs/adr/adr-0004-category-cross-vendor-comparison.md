# ADR-0004: Category-level rollup and the cross-vendor comparison renderer

## Status
Accepted

## Context
ADR-0003 established the job-category taxonomy as the only axis on which vendors may be compared: tasks
are product-native and do not compare directly, but their `job_category` does. That ADR made
`job_category` a validated, *inert* field — nothing yet consumes it. To actually produce a cross-vendor
statement (the method's headline: how much good context is worth, side by side across vendors) we need
code that (a) rolls a single condition's per-task scores up to per-category numbers, and (b) renders
several such rollups — from different packs — into one labeled table.

Two constraints shape where this lives:
- **It is vendor-agnostic scoring/aggregation**, so per the core/pack architecture it belongs in `core/`,
  not in any pack or private script. The private repo only *invokes* it with real vendor data.
- **The public repo may name no prospect.** The renderer therefore takes labels and a
  `task_id -> job_category` map as arguments; it hard-codes no vendor and is unit-tested against the
  public reference pack only.

## Decision

### `core/category.py` — two pure functions
- `rollup_by_category(aggregate, task_to_category, na_categories=None)` takes the `aggregate` block of a
  `scores.json` (one condition) plus a task→category map and returns, for every canonical category,
  its per-dimension numbers, an overall accuracy, the contributing task ids, and an N/A flag+reason.
- `render_cross_vendor_category_md(sources, note=None, dimension=None)` takes an ordered list of
  `(label, rollup)` and renders a `category × source` markdown table (overall accuracy, or one
  dimension). It names no vendor — the caller supplies the labels.

### Within-category rollup rule (coarse by design)
When a vendor maps several tasks onto one category, that category's dimension is the **mean of those
tasks' per-dimension means** — the raw runs are not re-pooled. Category comparison is deliberately
coarse (ADR-0003 compares *only* at this level), and the committed, consumable artifact is each pack's
`scores.json` aggregate, not its raw runs. A dimension that is N/A for every contributing task, and an
N/A category, both render `n/a`.

### Per-condition, not blended
The renderer compares one labeled rollup per source. A fair cross-vendor table therefore holds one
*condition* fixed (e.g. a no-context three-way, a public-docs three-way) so the numbers are
like-for-like; the caller decides which condition each source represents and labels it accordingly. This
keeps `core/` free of any assumption about how many conditions a given pack ran.

### Known-good check
Because the reference pack's task↔category map is 1:1 (ADR-0003), rolling its per-task aggregate up to
categories must reproduce each task's numbers under its category label. `core/tests/test_category.py`
asserts exactly this against the committed reference fixture, plus multi-task averaging, None-dimension
exclusion, and N/A handling.

## Consequences
- A cross-vendor, category-level comparison is now a two-call operation over any set of packs' committed
  `scores.json` files, with no vendor names in the public engine.
- The reference pack's numbers are unmoved: `job_category` remains inert to scoring, and the regression
  gate still reproduces the reference tables (this ADR adds a renderer, not a score path).
- The renderer is intentionally minimal (overall or single-dimension, category × source). Richer
  cross-vendor views (per-dimension matrices, gap columns) can be composed by the caller from the same
  rollups, or added here by a later ADR if they become load-bearing.
