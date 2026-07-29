# ADR-0031 — a prompt must name its target, and the pack must declare what naming it means

**Status:** Accepted
**Date:** 2026-07-29
**Follows:** ADR-0006 (the gate pipeline), ADR-0010 (the round-trip control and its stated limit),
ADR-0016 (fix what affects a published number; file the rest).

## Context

Every gate this project has reads the **answer key**.

| gate | what it reads |
|---|---|
| `recon` | the spec finding and the licence |
| `validate` | the task file's schema — including that `prompt` is a non-empty string |
| `roundtrip` | the answer key, scored against itself (ADR-0010) |
| `anchoring` | the answer key's endpoints, resolved against a spec or a manifest |
| docs truncation audit | that the injected documentation still contains the answer key's path |

**Not one of them reads the question.**

That gap cost a whole grid. Twelve prompts described their target as *"this vendor's consumer digital
banking API"* and named nobody. 45 of 60 cold runs were format failures — the measured model
correctly refusing to guess:

> "Your question refers to 'this vendor's' API, but no vendor name, documentation link, or API spec
> was included in your message. I don't have enough context to answer accurately."

**Every gate passed.** The task files validated, the answer keys round-tripped, the anchors resolved,
the docs were not truncated. The grid was discarded at a cost of **$9.16**, and what caught it was a
human reading one transcript after the money was gone.

A prompt that is answerable but under-specified is structurally invisible to a gate that reads the
answer key, because the defect is not in the answer key.

## Decision

`pack.yaml`'s `vendor:` block gains two lists, and **every task prompt must name at least one from
each**, matched whole-word and case-insensitively:

```yaml
vendor:
  vendor_names:  [...]   # who sells it
  product_names: [...]   # what the API is
```

The rule lives in one place, `core/prompt_gate.py`, with three callers and no second copy: a new
`prompts` stage in `factory.GATES` (after `validate`, before `roundtrip`), a pre-flight check in
`cmd_run` before the transport is even constructed, and a `prompts` subcommand for authors.

### Both lists, not one — and why the "and" is the whole ruling

Requiring only "some identifying name" would have passed the cases this gate most needs to catch.
Two published packs name a corporate parent that sells **more than one identity API**, so the prompt
does not say which surface is being asked about. That is not a lesser version of the failure above;
it is the same failure with a smaller radius, and a one-list rule cannot see it.

### Declared, not derived

`display_name` was the obvious source and is the wrong one: it is a card heading. It is vendor-only
in some packs and a whole `Vendor Product (Surface API)` string in others, so a gate built on
splitting it would pass or fail on punctuation. Declaring the lists also puts the claim where a
reviewer reads it — which is most of the value, because the author has to decide what counts.

### Fail-closed, with no waiver mechanism at all

A pack that declares neither list **blocks**. There is no default, no skip flag, no exemption list
and no grandfather clause. This is deliberate: an exemption list is the thing that decays, and the
absence of one is what makes the reference pack's disposition below honest rather than a loophole.

### Whole-word matching, not substring

Several real product marks are short abbreviations. Under a plain `in` test, `ISC` matches
*discovery*, *basic* and *miscellaneous* — so a pack whose prompts never name the target would be
reported as fully compliant. A gate that can pass by accident is worse than no gate, because it
reports coverage it does not have. Pinned by a must-not test.

### Dual-listing: permitted for a product mark, never for a bare parent

A distinctive product name identifies its vendor exactly as well as the vendor's own name does. A
prompt naming a trademarked product that exactly one company ships — the fixture pack's `Widget
Cloud` stands in for the real ones, which live in the private packs repo — leaves no reader in doubt
about whose API is meant. So a name may appear in **both** lists, and this is the argument that
permits it, as this ADR is required to carry.

The converse is the rule that matters: **a bare corporate parent never qualifies.** Listing the
parent as its own product name would turn every under-specified prompt green while changing nothing
true about it — the flattering move this project exists to refuse.

**Core cannot tell those apart**, and this ADR does not pretend otherwise. Core *reports* every
dual-listing by name (in `validate`, in `prompts`, and in the factory's gate detail) so the claim is
visible in ordinary output; the judgement is made in review, and the reviewed list is asserted in the
packs repo's own suite. Recorded as an **ungated** hazard, not dressed up as a guard.

## The backfill — what would have failed, measured before any code was written

All 13 packs on disk, every prompt, both halves of the rule:

| pack | prompts failing | what they say instead |
|---|---|---|
| the **frozen reference pack** | **10 of 11** | `ISC` alone — never the vendor |
| a published pack, largest gap in its cohort at the time | **12 of 12** | its two product marks, never the corporate name |
| a published pack | **10 of 11** | the corporate parent alone, never the surface |
| a published pack | **9 of 11** | the corporate parent alone, never the platform |
| two published packs | **1 each** | one describes the surface without naming it; one names a parent that sells several APIs |
| the remaining 7 packs | **0** | — |

**41 prompts across 6 of 13 packs.** The vendor half and the product half fail in different packs,
which is the evidence for requiring both.

Twelve of those (one pack, in full) are repaired **declaration-side**: its prompts do name
distinctive product marks, so declaring them is a true statement, not a widened matcher. **No prompt
text is edited and no published number moves.**

The remaining **31, across 5 packs, are genuine defects and are left in place.**

## The reference pack fails this gate, and is not fixed

10 of its 11 prompts identify the target only as `ISC`. That abbreviation belongs to several
unrelated real organizations, so the ambiguity is real, not pedantic.

It is **pinned, not fixed, and not exempted**:

- **Not fixed** — these are the questions that produced the frozen 73/68/93 regression anchor.
  Rewriting them would silently re-baseline the one table this repo checks itself against, which is
  an unwalkbackable change made inside the review that would authorize it.
- **Not exempted** — no exemption mechanism exists. The gate blocks the pack, and a test asserts it
  blocks the pack, naming **exactly which 10 task ids fail and with which single problem**. Editing
  any of them breaks the pin on purpose. Filed as #51.
- **`ISC` is deliberately absent from `vendor_names`.** Listing it would assert that an ambiguous
  abbreviation names this vendor. A test pins that it stays absent.

**What the ambiguity does and does not bound.** Every condition was run with **identical prompts**,
so the gap between conditions — which is what this method measures and reports — is unaffected. The
ambiguity bounds the pack's absolute numbers, not its finding. The same is true of every other
pinned pack, and each card that carries one says so.

## What this cannot do

- **It cannot tell a good question from a bad one.** A prompt can name both and still be leading,
  ambiguous, or wrong about what it asks for. This closes exactly one failure mode.
- **It cannot judge a name.** It matches strings a human chose. A pack that declares a misleading
  name gets a green check on a false claim, and only review catches that.
- **It cannot see the answer-block contract suffix.** That text is shared, vendor-free and appended
  by `core/prompt.py`; only the task's own prompt is read.

## Consequences

- A new `prompts` stage sits in `STAGES` and `GATES` between `validate` and `roundtrip`. The order
  is part of the ruling and is pinned: the schema says a prompt exists, this says it identifies its
  subject, and only then is proving the answer key worth doing.
- `cmd_run` blocks before constructing the transport, so the check costs nothing and needs no
  credentials. `--mock` is exempt: it spends nothing and exists to prove plumbing.
- Six packs now fail a gate they previously passed. **31 of those prompts are recorded rather than
  repaired**, with the fix filed, because rewriting a question after its grid ran changes what was
  measured and re-running is real model spend this cycle was not authorized to make.
- **No scorer, parser, answer-block contract, task file or prompt text is touched. No published
  number moves. The frozen 73/68/93 is unmoved.**
