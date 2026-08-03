# ADR-0053 — A substitute page is not a document, and every fetch gate passes one

**Status:** Accepted
**Date:** 2026-08-03
**Related:** [ADR-0009](adr-0009-throttled-docs-fetch.md) (an empty body is a fetch failure),
[ADR-0021](adr-0021-extracted-text-floor.md) (the floor is on extracted text),
[ADR-0047](adr-0047-a-control-that-was-run-twice-is-code.md) (a baseline is required, not optional),
[ADR-0013](adr-0013-spec-server-prefix.md) (the suspect-instrument fault class).
**Refs:** #35.

## Context

This project already refuses three ways for a page to arrive and not be a document: an empty body
(ADR-0009), a whole body that extracts to nothing (ADR-0021), and a path robots forbids (ADR-0036).
There is a fourth, and until now nothing could see it.

A host can answer a path **that does not exist** with HTTP 200 and a real, substantial page — usually
a section index or a project overview. Issue #35 filed one shape of this in cycle 18 (a sign-in page
at 1,096,946 bytes extracting to 1,317 bytes of form). This is the other shape, and it is worse,
because the substitute is genuine documentation of *something*.

Measured on the target that forced it: `/{project}/openapi.json`, `/{project}/swagger.json`,
`/{project}/postman.json` and `/{project}/v1/openapi.json` all return **HTTP 200 with the same
167,882-byte project overview page**, extracting to 4,207 bytes, signature identical. The host's
**root** namespace 404s honestly; the **project** namespace does not. A probe run during recon read
one of those as a real documentation page for several minutes before the signature comparison caught
it.

Every gate in the pipeline passes such a page: the status is 200, the body is not empty, the
extracted text is twenty times the 200-byte floor, and robots permits it. So a manifest can import
one substitute under ten distinct URLs, and `public-docs` will inject one page ten times while the
pack believes it injected ten. Nothing downstream can tell: the transcript of a model that read a
substitute is the transcript of a model that read a document. That is the ADR-0013 fault class — a
dimension reading one thing while the world is another — with no symptom at all.

## Decision — different URLs may not have returned the same document

A new gate, `check_substitution`, in its own stage between `anchoring` and `truncation`. It refuses a
pack in which **two entries with different URLs carry the same `content_hash` and a `byte_size` at or
above the ADR-0021 text floor**.

Every clause is doing work:

- **Different URLs.** One URL cited by several tasks is the normal, correct case — a shared concept
  page belongs in every task that needs it — and it is not a substitution. Keying on the URL set
  rather than the entry count is what separates the two.
- **Identical `content_hash`.** Not similar, not overlapping, no threshold. The fetcher already
  writes the sha256 of the extracted text, so this compares what a reader received; a heuristic here
  would be a number someone could tune toward a result.
- **At or above the text floor.** Below it, a repeated body is the client-rendered shell case, which
  ADR-0021 already governs and which two published packs declare page by page with a written
  `short_text_ok`. Re-litigating that here would fail work that was disclosed correctly.

**Its own stage, and the order is the argument.** `anchoring` proves the answer key points at a real
published artifact; this proves each URL returned its *own* document rather than a substitute; only
then is it worth asking whether the budget kept the answer. Auditing truncation first would audit a
window onto the wrong page.

## Why this is a fix and not a rule imposed on existing work

Measured over **all 19 packs on disk before the gate was written: 0 trip it.** Two near-misses were
examined and are correctly out of scope — one pack has ten distinct operation-reference URLs whose
client-rendered bodies all extract to the same 21 bytes, each with a written `short_text_ok`; another
has twenty-four pages at one byte. Both are below the floor, both are already disclosed, and neither
is what this is about.

So the gate guards a hazard rather than legislating against published work, and the evidence for that
is a count rather than an assurance.

## Consequences

- A soft 404 that returns real content is now caught at authoring time instead of being injected.
- Recons inherit a rule the code cannot enforce but the failure message states: **establish the
  baseline at the path DEPTH each URL sits at, not only at the site root.** A host can 404 honestly
  at `/` and soft-404 two segments down, and this one does.
- No published number moves.

## What this does not do

**It does not detect a substitute served at only ONE of a manifest's URLs.** With nothing to collide
with, a single imported overview page is indistinguishable here from a real one. That is the larger
half of #35 and it stays open; the honest description of this gate is that it catches the *repeated*
substitution, which is the common shape because a soft-404 namespace usually swallows more than one
path a manifest wants.

**It cannot tell a substitute from a genuinely duplicated document.** A vendor that publishes the
same page at two canonical URLs would trip this, and the pack would have to say so. No such case
exists in the cohort today; if one arrives, the fix is a declared exception with a written reason and
not a loosened threshold, for the reason ADR-0021 gives about `short_text_ok`.

**It reads what the fetcher recorded, not the host.** A manifest whose hashes are stale describes a
retrieval that happened on `fetch_date`, and this gate is exactly as current as that.
