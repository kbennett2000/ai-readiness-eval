# ADR-0028 — a prospect is named by what it sells, not only by what it is called

**Status:** Accepted
**Date:** 2026-07-27
**Extends:** ADR-0018 (the leak guard loads its names from the private queue).
**Amends:** ADR-0020 — for the privacy rule only, replacing leaked literals; no decision changes.
**Closes:** core issue #40.

## Context

The leak guard enforces the project's hard privacy rule: no tracked file in this public repository
may name a measured prospect. Since ADR-0018 it holds no names of its own — it loads them at runtime
from the private packs repo, derived from each queue entry's `id`, `display_name`, `guard_tokens` and
`guard_tokens_cased`.

Every one of those fields answers the same question: **what is this vendor called?**

While drafting an ADR in the previous cycle, a public file described a measured target's surface split
by naming four of that vendor's distinctive **product** names. Capitalised, unambiguous, and enough
that any reader in the space would know exactly which vendor was being measured. The guard was green
the entire time, and stayed green, because no field in the queue records a product name and no token
derived from an id can ever match one.

It was caught by a human reading the file — the same thing that caught all three cycle-19 faults, and
not a control that scales.

## Decision

A queue entry may declare what the target **sells**, in two lists, and the guard scans for those as
well as for the name:

```yaml
guard_product_tokens:        [widgetron, acmefs, orchardctl]   # matched case-insensitively
guard_product_tokens_cased:  [Data Fabric, Batch Serving]      # matched exactly as written
```

(Those values are invented. The first draft of this ADR illustrated the field with a real target's
actual products, and the guard failed on its own decision record — see below.)

Three properties, each load-bearing:

**They extend; they never replace.** `guard_tokens` replaces its default — that is how an id which is
also an ordinary English word opts out of case-insensitive matching. That narrowing must not reach
across and disarm the products, which are a separate declaration about a separate disclosure route.
An entry that narrowed its name and silently lost its products would still *look* like it declared
them. Pinned by `test_narrowing_the_name_does_not_disarm_the_products`.

**They are returned by their own accessor.** `leak_guard_product_tokens()` sits beside
`leak_guard_tokens()` rather than merging into it, because the guard compares the two kinds
differently and a caller that merged them would apply one kind's boundary rule to the other.

**They are matched whole-word, where vendor names are matched as substrings.** This asymmetry is the
part that was not obvious in advance, and it was forced by evidence rather than reasoned out — see
below.

## The boundary rule, and how it was found

The first run of the widened guard reported **nine** offending lines. One was a true positive. Eight
were a product token sitting inside a longer, entirely innocent word — a token matching an ordinary
English word in six ADR headers, and another matching a substring of an unrelated camelCase
identifier in a test fixture.

Substring matching is right for a vendor name: the name is distinctive, so over-matching costs
nothing and usefully catches `<name>-api` or `<name>'s`. It is wrong for a product name, because a
product is very often named with ordinary technical English. Unbounded, this guard was not merely
noisy; at eight false positives to one true positive it was **unusable**, and an unusable guard is
one somebody switches off — which would have been a worse outcome than the gap it was built to close.

Product tokens are therefore `\b`-bounded, and the author chooses per token which list a name belongs
in: coined names that are never ordinary prose go in the case-insensitive list; names made of
ordinary technical English go in the cased list, where they must fire on the proper noun and stay
silent on the lowercase words. Both halves of that bargain are asserted per token.

## What the scan found

Nineteen queue entries were annotated: **143 product tokens, 88 case-insensitive and 55 cased.** The
guard was then run over every tracked file in this repository.

| | |
|---|---|
| offending lines, first (unbounded) run | 9 |
| of those, false positives from substring matching | 8 |
| **genuine pre-existing product-name leaks** | **1**, across 4 tracked files |
| new leaks this cycle wrote *while building the guard*, caught by it | **2** |

**The genuine pre-existing leak.** The ADR-0020 cycle illustrated a scoring problem using the measured
vendor's real per-service version notation and the real name of its query language, in the ADR, in the
ADR index, in a `core/scorer.py` comment and across a test file. Those literals were only ever
synthetic fixture inputs — nothing asserted or measured depended on their spelling — so they are
replaced with neutral stand-ins and ADR-0020 carries an amendment note recording the substitution.
No assertion, decision or published number moves. The amendment is written into the ADR rather than
applied quietly, because silently editing a merged decision record is precisely the move this
project's conventions forbid.

**The two leaks this cycle wrote are the more useful finding**, because they say something about the
failure mode that the pre-existing one does not.

1. The first draft of the code comment explaining the boundary rule **quoted the two offending
   product tokens**, and named a real vendor as an example of substring matching. The guard scans its
   own source — as ADR-0018 requires, exactly so this cannot be excused — and failed on all three.
   *The comment explaining the leak fix was itself a leak.*
2. The first draft of **this ADR** illustrated the new YAML field with a real target's actual product
   names: three offending lines in the decision record that exists to stop exactly that.

Neither was noticed while writing. Both were caught in the second the guard ran. Together they are
the argument for the whole design: this is not a mistake made once by an inattentive author, it is
the *default* behaviour when documenting a rule — the natural way to explain a token list is to show
real tokens. A guard that scans everything, with no exemption for the files that discuss it, is the
only thing that catches a habit. Prose about the guard is where the leak wants to live.

## What this still cannot do

**A target with no queue entry contributes zero tokens.** The guard is not weak about an unqueued
target; it is silent. And cycles naturally draft an ADR or a plan *before* the queue entry exists —
which is exactly how the near-miss that produced issue #40 happened. No list-based guard can close
this: the guard cannot know a name it has never been told.

Only ordering closes it, so the ordering rule is now written where review can see it: **add the queue
entry, with its name and product tokens, before writing any public prose about a target.** It is
recorded in the guard's own module docstring and in the private queue's header, because it previously
lived only in a gitignored handoff note — invisible in every PR diff, which is where this class of
mistake is actually caught.

**Nor is the token list complete by construction.** A product missing from the queue is a product the
guard does not know. The lists are an author's judgement, reviewable in the private repo, and their
incompleteness is a live ungated hazard rather than a solved problem.

**And it does not reach history.** Names already pushed remain in the git history of both
repositories; that is unchanged here and remains issue #24.

## Consequences

- The guard covers both disclosure routes, and a file naming four of a target's products while naming
  no vendor at all now fails — verified by planting exactly that file and watching it fail.
- 143 product tokens are declared in the private queue; annotating a new target is now part of adding
  it, and non-vacuity is asserted so an unannotated queue fails loudly instead of passing green.
- One pre-existing leak is closed and disclosed; ADR-0020's decision is untouched.
- No scorer, parser, prompt, pack or fixture is touched. **The frozen 73/68/93 is unmoved**, and no
  published number changes.
