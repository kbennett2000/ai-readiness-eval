# ADR-0029 — "a spec exists" and "we may keep a copy" are two findings

**Status:** Accepted
**Date:** 2026-07-27
**Refines:** ADR-0006 (the factory's gates). Follows ADR-0001, which scores spec availability and
licence as *separate* dimensions — this is the gate catching up with that.
**Also lands:** the docs-condition truncation audit (see "The second ruling" below).

## Context

`check_recon` is step zero of the pipeline: can the method anchor this vendor at all? It read one
finding, `machine_readable_spec_available`, and demanded a vendored spec file plus a licence file from
any pack that answered `yes` or `partial`. Its one hard failure was the **incoherent** pack — claims a
spec, ships nothing.

`spec_finding.permits_vendoring` is recorded by **every pack in the cohort** and was **never read**.

So consider a vendor that publishes a real, first-party, complete, machine-readable OpenAPI document,
served unauthenticated — and whose site terms are all rights reserved, with no licence grant. Two
facts, both true, both scored dimensions of this method. Under the old gate that combination had **no
passable honest encoding**. The only ways through were:

- write `machine_readable_spec_available: no` — **a false claim on a published report card**, which
  destroys the very finding the card exists to report; or
- commit a copyrighted document — breaking both the licence and this project's standing rule against
  committing vendor doc snapshots.

**This is not hypothetical, and it is not new.** Packs already in the cohort took the first option, and
each says so in a comment sitting directly above the flag, reading *"READ THE FINDING BEFORE THE
FLAG"* — explaining that `no` is being used as shorthand for "no *consolidated, fetchable,
redistributable* public spec", and that the whole truth is closer to the opposite of the flag.

When a gate's own inputs have to be written wrong to pass it, the gate is measuring itself.

## Decision

The two findings are asserted **separately**, in four branches:

| availability | permits_vendoring | requirement |
|---|---|---|
| yes / partial | yes | **unchanged, byte for byte** — `vendored-spec/<spec>` + `vendored-spec/LICENSE` |
| yes / partial | **no** | must **not** carry a vendored spec, and must record `where` / `where_now` |
| no | either | doc-anchored mode, passes (ADR-0005) |
| either finding unreadable | | **block**, in both directions |

Plus one availability-independent clause: **a pack that says it may not redistribute the document may
not have redistributed it.** That is a fact about a licence, not about a finding, so it is checked first.

### Why `permits_vendoring: no` is not a free escape hatch

Because **it is the long way round.**

- *Permitted:* copy one file and one LICENSE, once. Every endpoint then anchors by `operationId`,
  resolved automatically by `check_anchoring`.
- *Not permitted:* the spec file is **forbidden**, so `validate`'s either/or anchor rule and
  `check_anchoring`'s resolver together force **every** endpoint to be `doc_ref`-anchored into a
  docs-manifest that pins each page by URL, byte size and hash — per endpoint, hand-authored, and
  re-fetched whenever the docs move.

A pack author who writes `no` to avoid work has bought themselves *more* work. That inversion is what
makes the branch safe to open. It is **not** a claim that the gate can detect a false licence claim —
it cannot, and that is recorded as a hazard rather than pretended to be a guard.

**Clause 3 is deliberately not implemented.** "Every endpoint must be doc_ref-anchored" is already a
theorem of two existing gates once the spec file is forbidden. Re-stating it inside `check_recon` would
duplicate a rule enforced in two other places, and duplicated rules drift — ADR-0013 and ADR-0017 each
paid for exactly that. The property is instead **pinned by a cross-gate test**, because a property that
holds across three gates and is asserted in none is the archetype of a hazard that decays (ADR-0015).

### The ruling normalizer, and why it reads prose

`permits_vendoring` is not a boolean on disk. It is a bool in most packs, and a **folded paragraph** in
others — and one of those rules **both ways in a single field**: yes for the copy that pack vendors, no
for a second published copy carrying no licence file. `_ruling` therefore reads the **leading token**
and ignores the argument after it. That is not a shortcut; it is the convention those packs were
already written in, and forbidding prose to get a clean flag would discard the argument that makes the
finding worth reading while moving packs that are already published.

Anything it cannot read returns `''`, and **every caller treats that as a block** — in both directions.
Reading an unreadable value as `yes` would re-create the trap this ADR removes; reading it as `no`
would hand every pack the exemption for free.

### A pre-existing hole, closed on the way past

The old code compared availability literally after `.lower()`, so **anything** outside `yes`/`partial`
fell through to the doc-anchored **PASS** — including `unknown`, a hedge, a typo, or a trailing space.
The one value that most needed to block was the only one that passed silently, and the pack then ran a
full grid in a mode nobody had chosen for it. Both findings now block when unreadable.

## The second ruling: the docs condition must not measure our own truncation

`public-docs` enforces its token budget by dropping low-priority pages and then **cropping the tail of
the last page it keeps**. When the cropped page is the one carrying the operation a task asks about,
the resulting score measures *our budget*, not the vendor's documentation — and nothing downstream can
tell the difference, because a truncated-away endpoint and an undocumented endpoint produce an
identical transcript. That is the ADR-0013 fault class, which cost a cycle when a dimension read 13.7%
while the model was in fact right in 98% of runs.

`audit_docs_truncation` reports, per task and endpoint, whether a ground-truth path is present in the
**full cached** text and in the **injected** text. The defect is strictly **relative**: present in the
first, absent from the second.

It deliberately does **not** require the docs to contain the answer. A vendor whose documentation omits
an endpoint is a finding this method exists to publish, and gating on it would quietly forbid the
result the cohort most wants to report. Because the check is relative, the matcher does not need to be
clever — both sides are the same bytes from the same page — and a *normalizing* matcher would be
strictly worse, since it could differ between the two sides and manufacture a loss that sends a cycle
hunting a budget bug that does not exist.

The sweep runs over **every pack on disk**, not only the pack a cycle happens to be authoring — the
ADR-0010 lesson, and precisely the lesson whose absence produced the reference-pack finding below.

## What the change moved

**Nothing.** Verified by running the old and new gate side by side over all 13 pack directories on
disk and diffing both the boolean and the detail string:

| | |
|---|---|
| packs checked | 13 |
| results that moved | **0** |
| pass/fail strings changed | **0** — so no card's recon line moves |
| truncation losses across the cohort | **0 of 138 endpoints** |
| frozen 73/68/93 regression anchor | unmoved |

Spec availability and vendorability are gate conditions and card findings, **never inputs to a scored
dimension**, so no published number changes in either direction.

## What this cannot do

**It cannot tell whether a licence claim is true.** `permits_vendoring: no` is the assertion that opens
the lighter-*looking* branch, and no test in this repository can read a vendor's terms of use, diff them
over time, or notice a permissive licence mislabelled restrictive. The defence is entirely structural —
the branch forbids the spec file and therefore forces per-endpoint doc anchoring, so a false claim costs
work rather than saving it — and structural defences bind honest authors, not determined ones.

**It cannot read a ruling that does not lead with its verdict**, and where a pack rules two ways about
two copies of one document, only the first word is consulted.

**It does not re-encode the packs already published under the overloaded flag.** Until that is done
separately, the cohort's availability dimension is **not comparable across vendors**: one value means
"nothing exists" for some packs and "something exists that we may not keep" for others, and a
cross-vendor reading of that dimension silently mixes them. Filed against the packs repo rather than
done here, because altering published claims inside the review that authorizes the alteration is not a
check.

**It does not fix the reference pack.** `packs/sailpoint` declares an available permissive spec and
deliberately vendors nothing, because a frozen upstream repository holds the closure. That is a **third**
honest combination this gate still cannot express, and it has been **blocking recon since ADR-0006 with
nobody noticing** — because recon runs only when the factory *dispatches* a target, and the reference
pack is never dispatched. The round-trip control sweeps every pack on disk for exactly this reason;
recon does not, and that asymmetry is what hid it. Not caused by this change, so the compatibility sweep
added here covers **external packs only and says why**, and the failure is pinned by a drift test so the
day someone resolves it, the resolution has to be a decision rather than a side effect.

## Consequences

- A vendor with a real spec it may not let us keep is now measurable **without writing anything false**.
- The pipeline's one original hard failure survives byte for byte, asserted character-for-character by
  a must-not-weaken test whose docstring says why the fixture's `permits_vendoring: yes` is load-bearing.
- Two unreadable-value holes close; both directions fail closed.
- Every new rule was **verified by breaking it on purpose** — each mutation of the gate fails a
  specific named test, and the suite returns to green when restored.
- No scorer, parser, prompt, pack or fixture is touched. **The frozen 73/68/93 is unmoved.**
