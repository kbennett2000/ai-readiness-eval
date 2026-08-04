# ADR-0056 — A manifest entry cannot be both retrieved and refused

**Status:** Accepted
**Date:** 2026-08-04
**Related:** [ADR-0051](adr-0051-a-filter-on-the-user-agent-is-a-finding.md) (the two-agent
measurement that fetches one URL twice, and so made a latent bug certain),
[ADR-0034](adr-0034-an-anchor-is-not-an-injection.md) (an anchor is fetched because its hash and
byte size are the evidence a ground-truth citation rests on),
[ADR-0009](adr-0009-throttled-docs-fetch.md) and
[ADR-0052](adr-0052-a-refusal-is-not-an-absence.md) (a refusal is recorded, never worked around),
[ADR-0036](adr-0036-robots-txt-is-a-fetch-permission.md),
[ADR-0015](adr-0015-hazard-registry.md).

## Context

A `docs-manifest.yaml` entry carries two independent records. Whether content arrived:
`content_hash`, `byte_size`, `cache_file`, `fetched_with_user_agent`. And whether the attempt
failed: `fetch_error`. Nothing made the two agree, and they disagreed in production.

On the one pack measured under ADR-0051, **all ten `anchors` entries** record a `content_hash`, a
non-zero `byte_size`, a `cache_file` and the agent that fetched them — and, beside all of that,
`fetch_error: HTTP Error 403: Forbidden`.

The cause is in the fetcher, not the pack. `fetch_all` overwrites every success field on each pass,
but `fetch_error` was written **only** by the failure paths, so an entry that failed once and then
succeeded kept the first attempt's error underneath the second attempt's proof. ADR-0051's
measurement points the same URL at both `pages` and `gated_pages` and fetches it under two agents by
design — the plain agent is refused, the conventional one is served — so a bug that needed a
re-fetch to appear was guaranteed to appear the moment that ADR shipped.

### `fetch_error` is not an inert field, and the first draft of this ADR said it was

Worth stating plainly, because getting it wrong is what would have made this a tidy-up instead of a
gate. `_InjectedTextCondition._load_text` tests `fetch_error` **first**, before it touches the disk:
a page carrying one injects nothing at all (ADR-0054). So a stale error is not cosmetic — it
suppresses a page that now fetches, and it does so in the condition whose whole job is to model what
a real reader retrieves.

**No published number moves here, and that was measured rather than argued.** The ten stale errors
sat on `anchors`, which no condition reads (ADR-0034). Rebuilding the injected context for every
condition and every task on the affected pack, before and after the correction: **30 slots, 49,594
injected bytes, 0 changed.** The reproduction gate passes 41 of 41 results directories either way.

The fetcher change *is* a live behaviour change, and it is the one intended: a page that failed once
and now succeeds will inject, where before the superseded error kept it out. That is the bug, not a
side effect of fixing it.

What was wrong is what a reviewer sees. An anchor is the artifact a ground-truth citation rests on,
and ADR-0034's whole argument for fetching anchors is that a reviewer can check the claim against a
recorded hash. Ten of them declared the document unreadable in the same breath as the evidence that
it had been read. A reviewer opening the manifest to verify an answer key finds a contradiction and
has no way to tell which half is stale.

That is worth an ADR rather than a quiet patch, because it is the second time this cycle that a
correct measurement was published beside evidence a reader could not check — the first being an
`evidence:` URL on a page recorded at `byte_size: 0` (ADR-0055, issue #97). The pattern is the same:
the number is right, the artifact backing it says otherwise, and nothing was comparing the two.

## Decision 1 — a success clears the failure it replaces

On the success path, `fetch_all` now drops `fetch_error`. Every other field on a successful entry is
already overwritten unconditionally; this makes the failure record behave like the rest of them
instead of accumulating.

The two failure paths get the mirror: they drop `cache_file`. An entry that sets `content_hash:
null` and `byte_size: 0` is stating that it attests no content, and it may not simultaneously point
at a file. On the robots-disallowed branch the snapshot is deleted anyway (ADR-0036), so keeping the
key named a file that is not there. On the error branch the snapshot is **not** deleted — a network
flake is not a withdrawal of permission, and discarding a good capture over a transient error is the
more expensive mistake — but the manifest stops vouching for it.

## Decision 2 — the `validate` gate refuses the state, however it arrived

`validate.validate_docs_manifest` walks every entry in every list `docs_fetch.ENTRY_KEYS` names and
blocks on:

- a `fetch_error` alongside a `content_hash`, a non-zero `byte_size` **and** a `cache_file`;
- a `cache_file` with no `content_hash`.

Reported under the pseudo-file key `(docs-manifest)`, alongside the existing `(suite)`, so the
`validate` gate — which already runs before `roundtrip` and before any grid burns — fails the pack.

**Both halves are needed and neither is redundant.** The fetcher fix stops the state being produced;
it cannot reach a manifest already on disk, and it cannot reach a hand edit at all. The validator
refuses the state wherever it sits and says nothing about how it got there. A test asserts the two
agree with each other rather than each agreeing with a hand-built fixture — a fetcher and a
validator written from the same misunderstanding would both be green and still disagree about what a
manifest means.

The rule is parametrized over `ENTRY_KEYS` itself, so a fifth page list cannot be added past it.

## Consequences

- One pack's ten anchors are backfilled in the packs repository; a cohort-wide sweep of **409
  manifest entries across every pack on disk** found those ten and nothing else, and found zero
  instances of the mirror shape. The sweep ran against the **unbackfilled** tree — the baseline on
  which a violation is visible — which is the control ADR-0055 recorded getting wrong.
- **The backfill must merge before this gate does.** The packs repository's CI clones this
  repository's default branch and runs `validate_pack` over every pack, so a blocking rule landing
  first turns that suite red on a defect the other repository has already fixed. Same ordering
  constraint as ADR-0055, and stated in both pull requests rather than rediscovered.
- `core/tests/test_manifest_entry_consistency.py` breaks each rule on purpose in both directions:
  every contradictory shape must block, every legitimate shape — a clean success, an honest refusal
  with no content fields, a pack with no manifest at all — must not.

## What this does not do

- **It does not check that a recorded hash still matches the cached bytes.** The manifest can be
  internally consistent and describe a snapshot that has since changed. That join is the same
  unbuilt one issue #97 needs, and it is not smuggled in here.
- **It does not make `fetch_error` mean one thing.** The field carries a robots refusal, an HTTP
  status, an empty render and a decode failure, which are different findings sharing a string.
  `_load_text` treats all four identically — inject nothing — which is right for every one of them
  today, and is the reason nobody had cause to separate them. Doing so is a schema change and is not
  this ADR's subject.
- **It cannot detect the inverse omission** — an entry whose fetch failed and which was hand-edited
  to drop the error entirely. Nothing distinguishes that from a page never attempted.
