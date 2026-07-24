# ADR-0009: A 2xx with an empty body is a fetch failure, not a snapshot

## Status
Accepted

## Context

`core/docs_fetch.py` fetches each page in a pack's `docs-manifest.yaml`, extracts text, caches it,
and records `content_hash` + `byte_size` back into the manifest. The `public-docs` condition is then
built from those cached pages. If a page fetches as nothing, the condition is fed nothing — and the
run reports a low or zero documentation lift *as a finding about the vendor*.

Recon on a prospect whose reference pages live on a support portal (One Identity) surfaced a failure
mode the fetcher could not see. The host serves the full page to a first request, but after a burst
of automated requests it begins answering:

```
HTTP 202, Content-Length: 0
```

Not 429. Not 503. A **success status with a zero-length body**, and it persists for roughly two
minutes of quiet before the host serves real pages again. Measured directly: a rapid loop over 13
pages tripped it; the same URL then returned `HTTP 202 / 0 bytes` at +60s and `HTTP 200 / 210,098
bytes` at +150s.

Under the previous code that response was indistinguishable from a real page. `urlopen` raised
nothing, `html_to_text("")` returned a single character, and the page was recorded with a valid
`sha256:` hash and `byte_size: 1`. The manifest — the committed record of what the snapshot
contained — would have asserted a clean fetch of an empty document.

This is the same class of defect as ADR-0007 (a docs host 404ing our self-identifying agent) and the
same class of error as the two dimensions that read 0.00 in the CyberArk grid: **our instrument
producing a number that reads as a fact about the vendor.** The difference is that this one leaves no
trace at all — a `fetch_error` is visible in review, an empty page that hashes cleanly is not.

## Decision

1. **An empty body on any status is an error.** `_fetch` raises `EmptyDocument` when the response
   body is empty or whitespace-only, carrying the HTTP status in the message. It travels the same
   path as a 404: `content_hash: null`, `byte_size: 0`, and a `fetch_error` recorded on the page.
   The check is on the raw body, not on a minimum-length heuristic over extracted text — a
   legitimately short page is still a page, and guessing a floor would trade one silent
   misclassification for another.

2. **Throttles are retried; facts about a page are not.** `_fetch_with_retry` retries only
   `EmptyDocument`, `DEFAULT_RETRIES = 3` attempts with linear backoff (`MIN_BACKOFF_SECONDS = 15`
   floor). A 404 or a connection error describes the page or the network and is recorded on the
   first attempt.

3. **Packs may declare pacing: `public_docs.fetch_delay_seconds`.** It defaults to `0`, so every
   existing pack fetches exactly as it did before and no committed snapshot moves. The delay
   separates pages and never precedes the first fetch.

4. **The throttling is recorded, not worked around.** A pack that needs pacing says so in
   `pack.yaml`, and its recon ADR states what the host does. As with the ADR-0007 User-Agent
   override, the point is that the accommodation is visible in the committed record — a reader can
   see that this vendor's docs required pacing to retrieve, which is itself a fact about how
   retrievable the vendor's documentation is to an automated reader.

## Consequences

- No existing numbers move. `fetch_delay_seconds` defaults to 0 and the empty-body check only fires
  where the old code would have written a bogus hash. The full suite (172 tests), including the
  frozen SailPoint 73/68/93 regression gate, passes unchanged.
- A vendor whose docs host throttles now costs wall-clock time proportional to its declared delay
  (~11 pages × 10s ≈ 2 minutes), paid once per snapshot.
- A pack can still legitimately record `fetch_error` on every page — that remains a real and
  reportable finding about a vendor's documentation (Saviynt's dead portal). What it can no longer
  do is record a *successful* fetch of an empty page.
- The rule generalizes the working note the CyberArk cycle produced: a measurement that is uniformly
  empty is a suspect instrument before it is a vendor finding. This ADR makes one instance of that
  class impossible to miss, by refusing to write the misleading artifact in the first place.
