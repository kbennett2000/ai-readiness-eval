# ADR-0021: A page that arrives whole and extracts to nothing is a fetch failure

## Status

Accepted. Extends ADR-0009 ("a 2xx with an empty body is a fetch failure, not a snapshot") to the
artifact that actually feeds the `public-docs` condition, and closes the hazard ADR-0009 recorded and
declined to fix: `a-near-empty-page-still-counts-as-a-page`.

## Context

ADR-0009 tests `raw.strip()` — the response body, before extraction. That catches a host which sends
nothing. It cannot catch a host which sends everything except the documentation.

A vendor measured in the cycle that produced this ADR publishes its entire operation reference as a
client-rendered application. A plain unauthenticated fetch of one endpoint page returns:

| | |
|---|---|
| status | HTTP 200 |
| raw body | 36,618 bytes |
| extracted text | **21 bytes** — `"Skip to main content\n"` |
| `<title>` in the static HTML | none; set by script |
| occurrences of the API's own path prefix | zero |

The body is emphatically not empty, so `EmptyDocument` never fires. `html_to_text` then yields a
navigation crumb, which hashes cleanly, records a plausible `content_hash`, and is written into the
committed manifest as a successful snapshot. Every check this project had would pass, and the
`public-docs` condition for that pack would be computed on documentation that was never delivered.

This is not a new observation. ADR-0005 wrote, in the module docstring that still ships:

> Extraction is lossy — that is stated in ADR-0005, and the manifest records the resulting byte_size
> so sparse (e.g. JS-rendered) pages are visible rather than hidden.

That was accurate and it was not enough. An earlier measured vendor's reference pages recorded
`byte_size: 1` for ten of eleven tasks, and those entries are still committed today. **Being visible
in the record is not the same as being checked**, which is the whole thesis of ADR-0015 restated as a
number: 1 byte, sitting in a tracked file, read by nobody.

### The objection ADR-0009 raised, which has to be answered

ADR-0009 considered a length floor and refused it. The hazard registry carries the refusal verbatim:

> Deliberate. A legitimately short page is still a page, and any minimum-length floor would be a guess
> that silently reclassifies real pages.

That objection is correct as stated, and the operative word in it is **silently**. A floor that
reclassifies a real page without anyone noticing is a bad instrument. A floor that a pack can overrule
in writing, on the record, is a different object: it converts a silent misclassification into a
declaration a reviewer can read and disagree with.

## Decision

**1. The floor is on extracted text, and it is 200 bytes.** `MIN_TEXT_BYTES = 200`, checked in
`fetch_all` against `len(html_to_text(html).encode())`. Chosen as the point below which a page cannot
state an endpoint, a method and a parameter — the minimum this project asks a reference page for. It is
a calibrated number, not a discovered one, and is recorded as such in the registry.

**2. A page may declare itself short, and must say why.** `short_text_ok: <reason>` on the manifest
entry keeps the page: it is fetched, hashed, sized and cached normally, and the reason is carried into
the written manifest. This is the same opt-in-with-its-reason-beside-it shape as `public_docs.user_agent`
(ADR-0007), `fetch_delay_seconds` (ADR-0009) and `endpoint_base_prefix` (ADR-0017). The tolerance is
never inferred and never global — it is granted one page at a time, by an author who looked.

**3. The reason must be a non-empty string.** `short_text_ok: true` is rejected. A waiver with no
argument behind it is exactly the artifact ADR-0015 exists to prevent: a tolerance nobody had to
justify decays into a tolerance nobody remembers granting.

**4. It is never retried.** The check sits *after* `_fetch_with_retry` returns, so it structurally
cannot enter ADR-0009's backoff. That schedule reaches a 180-second gap before giving up, and it answers
a throttle — a fact about our request rate, which can clear. A page that renders client-side will render
client-side again in three minutes. Retrying it costs nine minutes per page to reach the same answer.
The distinction is the one ADR-0009 already drew between a throttle and a 404, applied one layer up.

**5. `byte_size` is unchanged and is not massaged.** A page kept under the floor by a declared reason
records its real, small size. The pack does not get a flattering number for having declared something.

## Consequences

- **The hazard flips from ungated to gated.** `a-near-empty-page-still-counts-as-a-page` moves to
  `status: gated`, naming the tests below. ADR-0015's registry printing one fewer `fix_queued_to:
  "not queued"` is the intended kind of movement: the entry did not improve because it was re-worded.

- **Re-fetching an existing pack can now record a `fetch_error` where it previously recorded a 1-byte
  page.** No committed number moves — archived manifests are not re-fetched, and no scorer, parser or
  prompt rule is touched — but the behaviour change is stated here rather than discovered later by
  whoever next runs `fetch-docs` on an older pack. That pack's ten 1-byte pages would fail the floor,
  which is the correct result and a re-baseline nobody has asked for yet.

- **A declared reason is never rechecked against the page.** If a vendor later ships server-rendered
  documentation, the override goes stale and nothing in this repo notices. Recorded as an ungated
  hazard; the pack-side half of the gate lives with the packs, which is where the manifests are.

- **What this deliberately does not do.** It does not detect a page that arrives with plenty of text and
  the *wrong* text — a substitute document, a soft-404 with a full marketing page, an index page served
  for a missing operation. Those bodies clear 200 bytes comfortably. That class is separate and remains
  open; this ADR covers only the case where the documentation is absent rather than mistaken.

- **Five existing fetch tests were re-fixtured**, not re-scoped. They exercise hashing, provenance and
  pacing with a bare `<p>` body that happened to fall under the new floor; each now uses a page padded
  to the smallest realistic reference page. No assertion in them changed.
