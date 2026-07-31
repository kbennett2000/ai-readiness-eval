# ADR-0039 — A vendor may disagree with itself in more than one place

**Status:** Accepted
**Date:** 2026-07-31
**Amends:** [ADR-0017](adr-0017-endpoint-base-prefix.md) (the opt-in endpoint-base tolerance), which
this widens without changing what it decided.
**Follows:** [ADR-0013](adr-0013-spec-server-prefix.md) (where a spec ends its server URL is not
where the vendor's docs start the path), [ADR-0014](adr-0014-answer-format-repair.md) (the
must-not-inflate counterexample this rule is still pinned against),
[ADR-0010](adr-0010-ground-truth-round-trip-control.md) (what the round-trip control cannot catch).

**No published number moves. Every archived score is byte-identical and the frozen 73/68/93 gate is
unmoved.** Verified: the five packs that declare this field produce the same comparable segments
they produced before, and the change is inert for every pack that declares nothing.

## Context

ADR-0017 gave a pack **one** `endpoint_base_prefix`: a path prefix the scorer ignores on both sides
of an endpoint comparison, for a vendor whose documentation and whose machine-readable description
disagree about where the base URL ends. One was enough, because the vendor that forced the rule
disagreed with itself in exactly one place — a spec fragment starting its `paths` key after a
segment the prose put in the base URL.

Recon on the next queued target found a vendor that disagrees with itself in **two places at once**,
and — this is the part ADR-0013 did not anticipate — the disagreement is **between two of the
vendor's own machine-readable documents**, not between a document and a guide:

1. Two of its OpenAPI documents describe **the same domain, on the same host, in the same current
   version branch**. One writes a leading platform segment into every `paths` key; the other omits
   it entirely. Both are first-party, both are current, and neither is marked superseded.
2. A third document absorbs a **different** segment into `servers[].url`, so the address the
   vendor's own reference page **displays** to a reader carries a prefix that document's `paths`
   key does not. That is the ADR-0013 shape, and it is a different prefix from the one in (1).

One declared prefix cannot reconcile both. Declaring either leaves half the pack mis-scored in
precisely the direction this project has now corrected five times: a model writing the address the
vendor's own page shows is recorded as wrong, and a dimension reads low while the model was right.
ADR-0013 found that the expensive way — a dimension reported at 13.7% when the model was correct in
98% of runs, the whole gap one path segment.

## Decision 1 — `endpoint_base_prefix` accepts a list as well as a string

A pack may declare several prefixes. `scorer.as_prefix_list` is the single place the two shapes are
told apart, and a bare string still normalizes to exactly one prefix, so **no pack that declares one
changes in any way**. That inertness is not a nice property; it is the licence for the change.

## Decision 2 — First match wins, and stripping happens AT MOST ONCE

Both are deliberate, and the second is the whole safety argument.

**First match wins** makes declaration order the pack's own tie-break rather than a hidden rule. A
pack that declares an ambiguous pair has chosen which applies, in a committed file, in advance.

**At most once** keeps the tolerance exactly as wide as *one base URL*. Repeated stripping would let
two short declared prefixes eat a real resource segment between them: `/svc/hubprefix/users` is one
base plus a resource named `hubprefix`, and stripping twice would reduce it to `/users` and match an
unrelated endpoint. The tolerance would then be as wide as the number of prefixes declared rather
than as wide as one base. That is pinned by a test that fails if the loop is made to repeat.

## Decision 3 — The must-not-inflate properties are re-pinned, not inherited

A tolerance can only ever collapse a difference; the risk is collapsing one that is real. Every
property below was verified by breaking it on purpose, on the multi-prefix path specifically rather
than assumed to carry over from ADR-0017:

| property | test |
|---|---|
| an undeclared leading segment is still a miss (`/admin/users` ≠ `/users`) | `test_an_undeclared_leading_segment_is_still_a_miss` |
| stripping is single, not repeated | `test_stripping_happens_at_most_once` |
| a declared prefix is absorbed only at the front | `test_a_declared_prefix_is_only_stripped_at_the_front` |
| absorbing a base does not merge two genuinely different surfaces | `test_two_surfaces_sharing_a_declared_prefix_do_not_collide` |
| an empty inner prefix is dropped, not treated as matching everything | `test_empty_inner_prefixes_are_dropped_rather_than_matching_everything` |
| the single-string shape is unchanged | `test_a_single_flat_prefix_still_means_one_prefix` |
| declaring nothing is inert | `test_no_declaration_is_still_inert` |

All in `core/tests/test_scorer_base_prefixes.py`. The ADR-0017 suite is kept as it was and still
passes unmodified, which is the evidence that this amends rather than replaces.

## Decision 4 — The declaration is still a pack's claim, and it is still auditable

Nothing here infers a prefix. A pack writes the prefixes it means, in `pack.yaml`, before its grid
runs, and the citation for each belongs beside it — the vendor page or document that writes the
address that way. Widening the field does not widen who may decide: a prefix nobody can cite is a
prefix nobody should declare, and the reviewer reads the pack file to check.

## Consequences

- `core/scorer.py` gains `as_prefix_list`; `_strip_base_prefix` iterates declared prefixes.
- `core/pack.py` gains `declared_base_prefixes` (the literal strings) and `base_prefix_segments` now
  returns a list of prefixes. The only caller that needs literal strings is the truncation audit.
- `core/conditions.py::_path_spellings` contributes one spelling pair per declared prefix, and still
  accepts a bare string.
- No scorer rule is relaxed and no dimension gets easier by default. A pack that declares nothing is
  scored exactly as before.

## What this does not do

It does not decide which notation a pack's ground truth should use — that stays a pack question,
answered by citing the vendor. It does not detect a disagreement; nothing here reads a vendor's
documents looking for one, and a pack whose author does not notice the second prefix will still be
mis-scored exactly as before. **The round-trip control (ADR-0010) structurally cannot catch it
either**: an answer key written in one notation still matches itself — the same blind spot that ADR
recorded about itself. What catches it is reading the
vendor's own documents and the suspect-instrument rule, which is what caught it this time.

And it widens a tolerance, which is the direction that can only move cells **up**. That asymmetry is
why the counterexamples above are pinned as tests rather than described in prose.
