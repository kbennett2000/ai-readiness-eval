# ADR-0005: public-docs models what a fetch actually retrieves

## Status
Accepted

## Context
The `public-docs` condition injects a vendor's own documentation, snapshotted into the pack's cache, so
the measurement asks "how much do *today's public docs* help this model." The lineage assumption was
that every manifest page has cached text; a missing snapshot raised `FileNotFoundError` to catch a
forgotten `fetch-docs` run.

Real vendor docs break that assumption in ways that are themselves the finding:
- A developer portal that **does not resolve** (DNS failure, no archive capture) — a real AI pipeline
  fetching it gets nothing.
- An API reference that is a **JavaScript single-page app** — a plain fetch returns an empty shell
  (observed as ~1-byte snapshots).

If the condition errors on these, we cannot run the grid for that vendor at all — and "the docs are
un-fetchable" is precisely the AI-readiness signal we want to measure, not an error to route around. The
condition must model what the machine reader actually retrieves: nothing.

## Decision
`PublicDocsCondition` injects nothing for a manifest page the manifest **records as unfetchable** —
i.e. the page carries a `fetch_error`, or an explicit `byte_size: 0`. Such a page contributes no text
(exactly as a real fetch would) and does not raise.

The forgot-to-fetch safety is preserved: a page that **claims content** (no `fetch_error`, `byte_size`
absent or > 0) but has no cached snapshot still raises `FileNotFoundError`. The distinction is the
manifest's own record of what the fetch returned — so the committed manifest, not a silent skip, is what
says a page was un-fetchable.

This keeps the condition faithful to the fetch (an un-fetchable page is empty context, matching a page
that fetched empty), and it names no vendor — the behavior is driven entirely by manifest bookkeeping.

## Consequences
- A vendor whose public docs are wholly or partly un-fetchable can still run a full two-condition grid;
  the un-fetchable pages simply add no context, so the no-context vs public-docs gap they would have
  moved is zero — the honest measurement.
- The manifest is the load-bearing record of fetch outcomes (`fetch_error`, `byte_size`), consulted by
  the condition and auditable in review.
- Vendors whose reference is browser-only or whose portal is down are measured, not skipped — their
  low/zero public-docs lift is a reported finding, and the recurrence of that pattern across vendors is
  worth aggregating.
