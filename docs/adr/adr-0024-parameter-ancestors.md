# ADR-0024 — Naming a field inside a required parameter names that parameter

**Status:** Accepted
**Date:** 2026-07-26
**Extends:** ADR-0004 (`key_parameters` required-subset containment).

## Context

`key_parameters` asks whether an answer named every parameter ground truth marks required. It
compared names by exact string match.

Ground truth names a request-body field at whatever depth the vendor's own documentation describes
it. For a payments flagship whose documented examples show top-level containers, that is `amount`,
`source`, `merchantDetails`. Four of five archived runs on that vendor's headline operation answered:

```
amount.total, amount.currency, source.sourceType, source.card.cardData,
merchantDetails.merchantId, merchantDetails.terminalId
```

Every required container is there, each with the field inside it the caller must fill — strictly
more useful to a developer than the answer key. **Exact match scored all four runs 0.0.** The
dimension read **7.3%** on that pack while crediting nothing more accurate than the answers it
rejected.

This is the ADR-0013 shape again: a dimension reporting a vendor as unknown when the model was
right, with the whole difference being notation. It was caught the same way — by the
suspect-instrument rule and by reading the transcripts of a task whose *endpoint* scored 100% while
its *parameters* scored 0, a combination that should never look plausible.

## Decision

An answer item satisfies a required parameter `g` when it equals `g`, **or** when it is a dotted path
whose parent is `g`:

```python
a == g or a.startswith(g + ".")
```

### The rule is asymmetric, and the asymmetry is the design

| | |
|---|---|
| `amount.total` satisfies a requirement for `amount` | **yes** — you cannot send `amount.total` without sending `amount`. Naming the child proves the parent. |
| `amount` satisfies a requirement for `amount.total` | **no** — naming a container proves nothing about which field inside it the caller supplied. |

Only the second direction can manufacture a score, by letting a vague answer pass a specific
requirement. It is refused, and pinned by a **must-not** test that fails the moment the asymmetry is
removed.

**The separator must be a literal `.`** So `source_type`, `sourceDetails` and `paymentSource.card` do
not satisfy `source`; a prefix is not a parent. Also pinned.

## Consequences

- **Three published cards move, all upward, and none of them is the pack that found the fault.**
  Measured by re-scoring every archived run in the cohort:

  | pack | `key_parameters` no-context | public-docs |
  |---|---|---|
  | one insurance platform | 32.0% → **38.0%** | 54.0% → **60.0%** |
  | one cloud IdP | 64.0% → **72.0%** | 58.0% → **64.0%** |
  | the payments pack that found it | 7.3% → **18.2%** | — |
  | the other six packs (12 rows) | unchanged | unchanged |

  The frozen 73/68/93 regression gate is unmoved: that pack's answers name parameters flatly.
- **Two published claims are weakened by their own correction.** Both moved cards name required
  parameters as their weakest dimension. That remains true after the fix — but part of the weakness
  was ours, and a vendor reading either card was being told its API is less well known than the
  transcripts show. Restated in the packs repo.
- **The correction is upward, which is the direction that deserves more suspicion, not less.** It is
  accepted because the asymmetry blocks the inflating direction outright and because every moved run
  was inspected: in each, the answer names the required container explicitly as the root of a dotted
  path. Nothing is credited for a parameter it did not name.
- **What this still does not do.** It compares *names*, not values or types. An answer naming
  `amount.total` scores identically whether or not it understands that `total` is a decimal in major
  units. And an answer may still name a required container while omitting a *different* required
  field entirely — the dimension is all-or-nothing per task, unchanged by this ADR.
- Both rules **verified by breaking them on purpose** and confirming the named test fails.
