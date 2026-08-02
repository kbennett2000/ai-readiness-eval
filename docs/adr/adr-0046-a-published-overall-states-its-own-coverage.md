# ADR-0046 — A published overall states what it is a mean of, including when the answer is "all of them"

**Status:** Accepted
**Date:** 2026-08-02
**Follows:** ADR-0045 (a dimension with no task — this is the display half it deliberately left
filed), ADR-0004 (the report renderer and its judgment calls), ADR-0044 (the second answer contract,
and the separate baseline it created).
**Refs:** issue #73.

## Context

ADR-0045 built the gate that blocks a docs pack whose contract declares a dimension no task
exercises, and measured the condition for the first time: **13 of 18 packs publish an
`overall_accuracy` that is a mean over fewer dimensions than their contract declares.** It fixed
what a pack *file* says. It changed nothing about what a *reader* sees, and said so:

> **#73** — print the scored-dimension count beside every published overall — is the display half,
> and stays filed rather than folded in here.

What a reader sees today is a bolded overall above a six-column table in which one column reads
`n/a`. `n/a` is a word this method uses legitimately and often — a task with no required scopes, a
dimension a pack refused to score because it could not corroborate the key (ADR-0041) — so it
carries no alarm and is not meant to. Nothing beside the number says the number is a mean of five.

The failure is not arithmetic. Every published figure is correct. The failure is that **two
different quantities render identically**: a mean of six and a mean of five are both "81%", in the
same font, in the same column, under the same header. ADR-0041 already wrote down the obligation
this ADR discharges — *"any card with an n/a column must state which dimensions are scored and that
its overall is the mean of those"* — and then, being prose, it was honoured on two cards and
forgotten on fifteen. That is the ADR-0015 decay mode with a two-cycle delay.

## Decision 1 — the sentence is generated, not typed

`core/report.py` gains two pure functions beside the renderers that already live there:

```python
covered_dimensions(agg, contract)    -> (covered, unexercised)
coverage_line(agg, contract, unexercised=None, adr_ref=...)  -> one markdown line
coverage_cohort_note(entries, contract, adr_ref=...)         -> one markdown line
```

A dimension is **covered** iff `aggregate.overall_dimensions[d]` is not `None` — which is exactly
the set `overall_accuracy` was averaged over. The count is therefore a fact about the number printed
beside it rather than a second opinion about it, and `coverage_line` **raises** if the two ever
disagree (a non-empty covered set with a `None` overall, or the reverse) instead of rendering a
sentence about a different number than the one on the page.

It is generated for the reason `render_group_comparison_md` already records in its own docstring —
*"hand-maintained derived numbers go stale silently while the gated ones stay right"* — and the
reason the packs repo's cohort tables became a gate: two cards independently claimed a cohort
superlative from a stale copy of a table. A coverage sentence typed once per card is that same
artefact, seventeen times over, updated by whoever remembers.

The ADR citation is a **parameter**, not a constant, because the two repos cite this repo's ADRs
differently (`ADR-0045` here, `public ADR-0045` there). One generator, two spellings, both checked.

## Decision 2 — the clean case is stated too

The reference pack's README now carries the line reading **all 6 of 6**, and the packs repo's
complete packs carry theirs.

This is the decision most likely to be undone by a later cycle as redundant, so the argument is
recorded rather than left implicit. A disclosure that appears **only where something is wrong** has
two costs, and the second is worse than the first:

1. its presence becomes the signal, so a reader learns to scan for the line rather than read it —
   and a reader who does not know the convention cannot tell "all six" from "nobody checked";
2. it teaches the next author that the line is **optional when the news is good**, which is exactly
   the discretion that produced fifteen silent cards from ADR-0041's obligation.

A standard that is only followed where it hurts is not a standard. Stating the clean case costs one
line and makes the absence of the line a fault the gate can see.

## Decision 3 — every card is checked against its own committed scores, with no exemption list

The packs repo gains `tests/test_cards_state_their_coverage.py`, which enumerates packs **from
disk** and, for each one with a committed `scores.json`, recomputes the line and requires the card to
carry it **verbatim** and **before the card's first table row** — so it cannot be read past on the
way to the number.

No exemption list, and no roster of which cards are covered: the exclusions are structural. A recon
record that publishes no number has no `pack.yaml` and no `scores.json`, so it is never enumerated;
it is not on a list of things to skip. Hand-maintained lists have decayed repeatedly in this project
— `docs/adr/README.md` went four ADRs stale, the hazard registry exists because 47 hazards were
stated once and never re-read — and a list of cards exempt from a disclosure rule is the same object
with a worse failure mode.

The gate also asserts a pack's coverage is **identical across its conditions**. It is today, for
every pack. If it ever stops being, a single line cannot honestly describe both arms, and the gate
says so rather than silently picking one.

## Decision 4 — `render_summary_md` is not touched, and that is filed rather than dropped

The line belongs in each run's `summary.md` as much as on a card. Emitting it there now would
regenerate **~60 committed derived reports inside the one diff whose entire job is to prove that no
published number moved** — and a reviewer would have to take the byte-identity of the numbers on
faith while reading sixty changed files.

So it is filed with that reasoning (issue **#85**), for a cycle where a moved byte is legible on its
own. Every `scores.json` and every `summary.md` in both repos is byte-identical after this change;
`git diff --name-only` touches no path under `results/`, which is the whole proof and one command.

## Consequences

- Sixteen measured cards, both cohort-table header notes, and the reference pack's README state
  which dimensions their overall covers.
- The docs cohort's header note said the cohort is *"scored on **three** dimensions"* — true of the
  contract, false of the one measured pack's overall, which is a mean of two. That is the exact
  misreading this closes.
- Twelve api cards now say, in their own voice, that a dimension is exercised by no task **and that
  no written reason is declared for it** — the honest display of the state ADR-0045 warned and filed
  (#82), not a repair of it. A pack that later declares a reason gets a different sentence for free.
- **No number is recomputed, re-scored or re-run.** $0, no model call, 73/68/93 unmoved.

## What this does not do

**It does not make a five-dimension overall comparable to a six-dimension one.** It makes the
difference visible at the point of reading. Whether such a comparison is ever legitimate is a
question for the cohort tables, and rule 4 of the packs repo's cohort gate already forbids the
cross-cohort version of it outright.

**It does not check that a covered dimension was worth covering.** It counts columns. An answer key
always matches itself (ADR-0010), and a dimension carried by one weak task is counted exactly like
one carried by twelve — the residual ADR-0045 named, restated here because a card now prints a
number that reads like a quality signal and is not one.

**It does not add a scored-dimension column to the cohort tables.** The tables are gated on their
parsed cells; adding a column is a change to a gated structure and belongs in its own diff, not in a
disclosure change. The header note carries the same fact in prose that the gate recomputes.

**It cannot reach a card in another repository, or a number quoted in a slide.** Nothing gates prose
outside the two trees, which is the standing limit recorded as
`two-cohort-numbers-look-alike-on-a-page` in the hazard registry and unchanged by this.
