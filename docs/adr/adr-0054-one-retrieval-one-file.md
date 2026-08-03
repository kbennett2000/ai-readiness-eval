# ADR-0054 — One retrieval, one file, and the manifest decides what a page contains

**Status:** Accepted
**Date:** 2026-08-03
**Amends:** [ADR-0051](adr-0051-a-filter-on-the-user-agent-is-a-finding.md), which got this half
right for one list and stopped one list short.
**Related:** [ADR-0034](adr-0034-an-anchor-is-not-an-injection.md) (an anchor is not an injection —
the guarantee this defect broke), [ADR-0021](adr-0021-extracted-text-floor.md).

## Context

ADR-0051 introduced a condition that retrieves the **same URLs** as `public-docs` under a different
agent, and it named the hazard correctly: two retrievals of one address must not share a cache file,
or whichever list is fetched last decides what every list reads back. It gave `gated_pages` its own
subdirectory and asserted the property.

It stopped one list short. **`anchors` are fetched too** — ADR-0034 has them retrieved so their
existence, size and hash are the evidence a citation rests on — and on a filtering host they are
fetched with the same conventional agent, because otherwise the citation cannot be verified at all.
An anchor and a `pages` entry naming one URL therefore resolved to **one file**, and the anchor won
the write.

The result, on the first pack to hold the same URL in both lists:

    infor/add-a-document: anchor URL reached the public-docs prompt

`public-docs` — the column whose entire published finding is that a compliant reader receives
**nothing** — injected the full operation page, which is also that task's **answer key's own
source**. Every dimension would have read near-perfect, the "documentation is refused" finding would
have been false, and nothing in any report would have looked unusual. That is ADR-0034's
catastrophic case, arriving through a door ADR-0051 opened and did not finish closing.

**What caught it was a pack gate running on real cached documents**, not the core fixtures. The
fixture asserted the property it was written for — `gated_pages` does not share a path — and was
right. `test_anchors_are_never_injected` asserts the rule over every task in every pack with the
documents actually on disk, and its own docstring says why it exists: *the fixture cannot fail in the
way a 145 KB cached document can.*

## Decision 1 — the cache path is keyed by list, for every list except `pages`

`cache_path_for(..., prefix=<manifest key>)` now puts `anchors`, `spec_documents` and `gated_pages`
each under their own subdirectory. `pages` keeps the bare path.

- **The rule is one retrieval, one file.** Until ADR-0051 no two lists could hold the same URL, so
  one file per `(task, url)` was the same rule; a filtering host broke the equivalence and the code
  kept the older spelling.
- **`pages` keeps the bare path deliberately**, so the 269 committed `cache_file` values across the
  cohort do not move. The 55 anchor and 10 spec entries do move on their next fetch. That is a
  derived field pointing into a gitignored, regenerable cache, and the churn is stated here rather
  than discovered.

## Decision 2 — the manifest decides whether a page has text; the filesystem does not get a vote

`_load_text` asked whether a cached file **existed**, and consulted `fetch_error` / `byte_size: 0`
only in the branch where it did not. So a page the manifest recorded as refused would read whatever
happened to sit at its path.

The check now runs **first**, before any path is computed. A page that failed to fetch injects
nothing, whatever the cache contains and however it is laid out.

**This is the half that matters**, and the ordering is the reason. Decision 1 removes today's
collision; Decision 2 removes the *class*, because no failed retrieval can read any file even if some
future list, some future prefix rule, or some hand-edited cache puts one there. A fix that only
separated the paths would have been correct and one refactor away from being wrong again.

The genuine "forgot to run `fetch-docs`" case is untouched: a page that CLAIMS content — `byte_size`
above zero and no `fetch_error` — with no cached snapshot still raises, so a real fetch is never
silently skipped.

## Consequences

- `public-docs` on the first pack to hold one URL in two lists now injects nothing, which is what
  that pack's committed manifest says happened.
- Anchor and spec cache files move on their next fetch. Nothing committed changes; no published
  number moves.
- The registry entry for the ADR-0051 hazard is corrected in place to name **three** routes rather
  than two, with the third marked as the one that was missed.

## What this does not do

**It does not make the cache authoritative about anything.** A manifest and a cache can still
disagree — a stale hash, a hand-deleted file — and this only fixes which of them is asked first
about emptiness.

**It does not verify that an anchor and a page holding one URL SHOULD hold one URL.** That they do is
a property of a filtering host and is disclosed per task by ADR-0051's overlap gate. Nothing here
checks that the disclosure is true of the world, only that the two retrievals stay apart.

**It was found by a downstream gate, not by this repository's own tests.** That is worth recording
rather than smoothing over: the core suite asserted the property that had been thought about, and the
property that had not been thought about was caught by a test that runs over real packs. The cheap
lesson is that a rule about "two lists holding one URL" should have been enumerated over **all**
pairs of lists the moment one such pair existed, and the assertion added here does exactly that.
