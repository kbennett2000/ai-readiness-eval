# ADR-0025 — A dotted numeric version is the same version with or without the `v`

**Status:** Accepted
**Date:** 2026-07-27
**Extends:** ADR-0004 (`api_version` normalization), ADR-0008 (unversioned spellings), ADR-0020
(service-qualified versions).

## Context

`api_version` asks whether the model knows which version of an API an operation lives at. It compares
normalized strings. The normalizer recognized exactly three shapes: a `vN` segment, a small set of
sentinels meaning "there isn't one" (ADR-0008), and a `<service>/vN` pair (ADR-0020).

The next queued target versions its paths with **bare dotted numerics** — `/api/2.0/…`, `/api/2.1/…`,
`/api/2.2/…`. There is no `v` anywhere in the vendor's addresses. Against that, the normalizer did
this:

```
normalize_version('2.0')     -> '2.0'
normalize_version('v2.0')    -> 'v2.0'    # compares unequal to a ground truth of 2.0
normalize_version('api/2.0') -> 'api/2.0' # ADR-0020's pair rule never fires: `2.0` is not `vN`
```

The prompt contract's own `api_version` example demonstrates **`v1`**. So a model that has correctly
learned this vendor's version, and then writes it in the notation *our own contract taught it*, loses
the dimension. The instrument would report a vendor as not knowing a version it does know.

This is the third time in three cycles that a dimension has been found measuring our phrasebook
rather than the vendor: ADR-0013 (a base-URL prefix, a dimension reported at 13.7% where the model
was right in 98% of runs), ADR-0020 (a service-qualified version, a dimension reported at 1% where
the model was right 95% of the time), ADR-0024 (a dotted parameter path). **Every one of them
understated a vendor.** Read that as this project's actual failure mode.

Unlike all three, this one was found **before** the grid rather than after, by asking what the
scorer would do with the notation the target actually uses. That is the whole reason it is decided
here in writing rather than argued about once a number exists.

## Decision

A dotted numeric version normalizes with an optional leading `v` removed:

```python
_DOTTED_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)+)$", re.IGNORECASE)
```

applied **symmetrically** to ground truth and answer alike, after the ADR-0008 sentinel strip and as
part of ADR-0020's pair rule (so `api/2.0` and `api/v2.2` also resolve). It can only ever collapse a
difference the prompt contract already said was not one.

### It cannot merge two different versions

`2.0` and `2.1` still compare unequal, as do `2.0` and `""`. The rule removes one character of
notation; it does not widen what counts as a match.

### The dot is required, and that is what makes it safe

Folding a bare `v1` to `1` is a **different question with a different risk profile**. `v1` occurs
**694 times** across the archived cohort; that fold could move published numbers, and no measured
vendor needs it. Requiring the dot is what makes this rule provably inert on every archive — see the
evidence below. Narrow now; the residue is recorded as a hazard rather than taken silently.

### The rule is kept out of path comparison, deliberately

`_DOTTED_VERSION_RE` is a **second pattern**, not a widening of `_VERSION_SEG_RE`. That matters
because `_VERSION_SEG_RE` is what `normalize_path` **strips out of an address**. Widening it would
delete `2.0` from `/api/2.0/jobs/create`, and then:

```
/api/v2.0/jobs/create   ==   /api/2.0/jobs/create      # WRONG — the first address 404s
```

A notation rule would be manufacturing an **endpoint** score. That is the only direction in which
this change could ever inflate a result, so it is pinned by
`test_dotted_version_never_leaks_into_path_comparison`. Verified by breaking: widening
`_VERSION_SEG_RE` on purpose makes the 404-ing path score endpoint **1.0**, and the test fails.

The two dimensions therefore move independently, which is correct — the version dimension asks what
the model knows, the endpoint dimension asks what address it would call:

| ground truth | answer | version | endpoint |
|---|---|---|---|
| `2.0`, `/api/2.0/clusters/create` | `v2.0`, `/api/2.0/clusters/create` | **1.0** (new) | 1.0 |
| `2.0`, `/api/2.0/clusters/create` | `2.0`, `/api/v2.0/clusters/create` | 1.0 | **0.0** |

## Evidence that no published number moves

Re-normalizing every archived `api_version` pair in the cohort with the shipped implementation, and
comparing to the pre-change behaviour:

| | |
|---|---|
| packs scanned | **10** — every measured pack in the private packs repo |
| compared endpoint pairs | **666** |
| version strings whose normalization changes | **0** |
| pairs whose `version_ok` flips | **0** |

No archived version string anywhere in the cohort is a dotted numeric: all are `vN`-shaped,
service-qualified, sentinel, or empty. The full `rebuild-report` re-score over all ten packs × two
conditions was additionally run **before** any new grid burned, and the frozen 73/68/93 reference
table is unmoved.

## What this does not fix

`api_version` still requires **exactly one** spelling to be correct. Where a vendor's own live
documentation publishes **two** versions for one operation — as the next target's does, showing
`/api/2.1/jobs/create` on one current page and `/api/2.2/jobs/get` on another — ground truth must
pick one, and a model naming the other scores 0 on a dimension where it is quoting the vendor. That
is the ADR-0023 problem in a different dimension, and the answer is the same shape:
`api_version_alternates`, authored and evidenced, never inferred. It is **filed, not built** — see
the hazard registry entry for where it is queued.

## Consequences

- Scorer-only and archive-neutral, so nothing re-runs and nothing costs anything.
- A vendor whose paths carry bare numeric versions can be measured on `api_version` at all.
- One more residue on the pile behind the cohort re-baseline: the prompt contract still demonstrates
  a single `v1` example, so it still teaches one notation for a field that has several.
