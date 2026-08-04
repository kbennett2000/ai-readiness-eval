# ADR-0057 — A recorded outcome must say when

**Status:** Accepted
**Date:** 2026-08-04
**Related:** [ADR-0056](adr-0056-an-entry-cannot-be-both-retrieved-and-refused.md) (the rule this
completes, and the hazard entry that queued this check in writing),
[ADR-0052](adr-0052-a-refusal-is-not-an-absence.md) (a refusal is recorded, never worked around),
[ADR-0036](adr-0036-robots-txt-is-a-fetch-permission.md) (a robots refusal is an outcome too),
[ADR-0034](adr-0034-an-anchor-is-not-an-injection.md) (an anchor never retrieved is an unverified
claim), [ADR-0002](adr-0002-extraction-and-regression-gate.md) (the spec side is pinned to a
commit), [ADR-0015](adr-0015-hazard-registry.md),
[ADR-0016](adr-0016-deferred-work-has-a-destination.md).

## Context

This cycle was dispatched to close an "empty `fetch_date`" gap in the public reference pack's
`docs-manifest.yaml`, and to derive a defensible capture-date bound from git evidence rather than
invent one.

**The gap does not exist, and establishing that is the first thing this ADR records.** All 29 entries
in `packs/sailpoint/docs-manifest.yaml` carry `fetch_date: '2026-07-23'` — the only distinct value in
the file. `git log -S"fetch_date" -- packs/sailpoint/docs-manifest.yaml` returns exactly one commit,
`043308e` (authored 2026-07-24), so the field has never been empty in this repository's history. The
date is corroborated on disk by the imported run fixtures, `2026-07-23-sterile-{canary,mcp,no-context,public-docs}`,
which is the grid the manifest's pages were fetched for.

Swept across every manifest reachable from the machine that ran this cycle, over all four
`ENTRY_KEYS` (`pages`, `anchors`, `spec_documents`, `gated_pages`):

| | manifests | entries | without `fetch_date` | dated, but recording no outcome |
|---|---:|---:|---:|---:|
| this repository | 1 | 29 | **0** | **0** |
| the external packs cohort | 19 | 409 | **0** | **0** |
| **total** | **20** | **438** | **0** | **0** |

So there is no date to bound and none to invent. Two facts survive the correction, and one of them
was already written down as work owed.

**Nothing enforced the date.** `validate_docs_manifest` checked only ADR-0056's contradiction rules;
an entry recording a retrieval with no `fetch_date` passed. ADR-0056's own hazard entry,
`an-omitted-fetch-error-is-indistinguishable-from-a-page-never-tried`, queued exactly this and said
why it was not taken there: *"`fetch_all` writes `fetch_date` on every path it takes, so an entry
with no `fetch_date` was never attempted and one with a `fetch_date` and neither content nor error is
the suspect case. A future cycle touching the manifest schema should take that check."*

**No published number depends on the date, and that was checked rather than assumed.** `fetch_date`
has **zero readers** across the whole repository. It is written on all three paths `fetch_all` can
take — success, fetch failure, robots refusal (`core/docs_fetch.py`) — and read by no condition, no
scorer, no report and no card. Nothing about this ADR can move a cell in any table.

### Why a gate for a field nothing reads

Because a reader outside the repository reads it. The spec side of every published number is pinned
to a public commit (`specs.yaml`, `spec_sha`) that a third party can re-resolve. The
documentation-condition side is pinned by `fetch_date` + `content_hash` + `byte_size` per page, and
by nothing else — `**/docs-cache/` is gitignored, because the snapshots are the vendor's copyrighted
documentation. The date is not an input to a score; it is the only statement of *how current* the
documentation condition was, and it is load-bearing for a claim made outside this repository rather
than inside it. A field that nothing reads is also a field nothing notices the loss of.

## Decision

Two clauses in `validate_docs_manifest`, checked independently of ADR-0056's contradiction rules
because an entry can be both self-contradictory and undated, and those are two different things
wrong with it.

1. **An entry that records an outcome must carry a `fetch_date`.** The outcome keys are
   `content_hash`, `byte_size`, `cache_file`, `fetch_error`, and membership is by **key presence,
   not truthiness** — an honest failure records `content_hash: null` and `byte_size: 0`, both falsy,
   and both the fetcher's own account of an attempt. A retrieval or a refusal that does not say
   *when* is an undated claim.
2. **An entry carrying a `fetch_date` and no outcome at all is refused.** This is the silent-drop
   shape ADR-0056's hazard named and could not reach: a fetch that failed and whose `fetch_error`
   went missing reads exactly like a page nobody ever tried. It is the direction that flatters,
   because a manifest with no recorded refusals looks like a vendor that refused nothing.

### The rule keys on the claim, not on the entry, and a counterexample decided that

The stronger sentence is "every entry must carry a `fetch_date`", and it is the sentence this cycle
was asked for. It is wrong, and the repository already contained the proof: it fires on all four
entries of `core/tests/fixtures/pack-acme/docs-manifest.yaml`, which is deliberately a manifest
authored before its first fetch — bare `url`/`role`/`note`, no outcome fields, no dates. That is the
normal state of a pack under construction, and ADR-0056's `ungated_reason` had already identified it
as the reason the check was not taken there.

A gate that forbids the ordinary way a pack is written is answered by writing dates that no fetch
produced. That is the one outcome this rule exists to prevent, so the rule that would have invited it
is the wrong rule. `test_the_unfetched_reference_fixture_is_that_shape` pins the counterexample to
the real fixture, so a future cycle that dates the acme pack has to notice it is removing this rule's
only live evidence.

### It blocks on a cohort where it costs nothing

Run against every pack manifest reachable from this machine: **20 packs, 0 errors.** Both clauses
fire on **0 of 438** entries, and on **0 of 4** acme entries. Nothing is being repaired here. What is
being fixed is that the manifest schema's most externally load-bearing field was unenforced, and the
gate is added while the cohort is clean rather than after an undated entry has been published.

## Consequences

- `fetch-docs` output passes the validator on all three of its paths, and a test now checks the
  robots-refusal path specifically — the one path no test in this file previously exercised, and the
  one whose date matters most, since a robots rule is a permission that can change and the manifest
  is the only record of when it was read.
- A pack author can still run `validate` on a freshly written, never-fetched manifest.
- **What this cannot do.** The rule proves an entry *says* when it was fetched. It cannot prove the
  date is true. A hand-edited or back-dated `fetch_date` passes, and no artifact in this repository
  can corroborate a capture date — the cached bytes that would are gitignored by licence. Registered
  as a hazard rather than left in this paragraph.
- The reproducibility boundary this ADR relies on is filed as public issue **#102**, so the precise
  statement of what a third party can and cannot reproduce from a clean checkout lives somewhere a
  reader can find it without reading this ADR.

## The correction, stated plainly

An earlier report in the session that dispatched this cycle claimed the 29 entries carried an empty
`fetch_date`. That report was wrong, and it was wrong about the public founding case, whose numbers
are the ones cited externally. It was not re-derived from the file before being repeated. The check
that caught it is the same one this project applies to a suspect instrument: read the artifact, print
the field values, and count — which is recorded here rather than only in the pull request, because a
false premise about a published pack is exactly the kind of thing that decays into a fact if the only
place it was corrected is a conversation.
