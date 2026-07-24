# ADR-0007: a bot-gated docs host is a fetch policy, not an empty docs finding

## Status
Accepted

## Context
[ADR-0005](adr-0005-public-docs-fetch-fidelity.md) established that `public-docs` models what a fetch
actually retrieves: a page the manifest records as unfetchable injects nothing, because "the docs are
un-fetchable" is the AI-readiness signal, not an error to route around.

A vendor encountered this cycle breaks that rule's assumption. Its documentation host returns **HTTP 404
to the fetcher's default self-identifying agent** (`ai-readiness-eval-docs`) and **HTTP 200 with the full
~122 KB page to a browser User-Agent** — same URL, same moment, difference entirely in one request
header. Verified directly with `curl` against a reference page, and reproduced for the bare
no-User-Agent case (also 404).

Under ADR-0005 alone, that vendor's snapshot would record `fetch_error` on every page, the condition
would inject nothing, and the card would report a zero public-docs lift. That number would be an
artifact of our own client, attributed to the vendor — the failure the method exists to avoid. It is
worth separating three situations that ADR-0005's machinery otherwise flattens into one:

1. **The host serves nothing to anyone** (portal de-published, DNS dead). A real pipeline gets nothing.
   A finding about the vendor.
2. **The host serves a JavaScript shell to everyone.** Text extraction yields ~1 byte for every client.
   A finding about the vendor.
3. **The host serves complete documentation, but only to clients that present as a browser.** The
   documentation exists and is public; a policy governs *which clients may read it*.

Only (1) and (2) are properties of the documentation. (3) is a property of the edge in front of it.

## Decision
A pack may declare `public_docs.user_agent` in `pack.yaml`. When set, `fetch-docs` presents that agent
for every page in that pack's manifest; when absent, the default self-identifying agent is used
unchanged.

- **The default stays honest.** A self-identifying agent remains the out-of-the-box behavior. That
  default is also what makes case (3) *detectable* — a fetcher that always presented as a browser would
  never have surfaced the gate at all.
- **The override is recorded, not silent.** Each page fetched under an override carries
  `fetched_with_user_agent` in the committed manifest, so a snapshot taken under an override can never
  be mistaken in review for a default-agent one.
- **The gate is itself a scored finding.** The pack's `specs.yaml` records that the docs host bot-gates
  non-browser agents, with the observed status codes. It is reported on the card as a retrieval-access
  finding — recorded clinically as a measurement, with the evidence, and never characterized as intent.

ADR-0005 is unchanged and still governs cases (1) and (2): a page that genuinely fetches empty for every
client still injects nothing, and a page claiming content with no snapshot still raises.

## Alternatives rejected
- **Send a browser agent by default.** Erases the signal (case 3 becomes invisible), and drops honest
  self-identification for every vendor to accommodate the few that gate.
- **Score the 404 as the measurement** — "an agent fetching these docs gets nothing." Rejected because
  it folds two independent vendor properties (documentation quality, bot policy) into one dimension, and
  makes the score depend on an incidental request header rather than on the docs. The bot gate is real
  and worth reporting; it belongs in the recon finding where a reader can see it, not buried inside a
  public-docs percentage where it is indistinguishable from thin documentation.

## Consequences
- A vendor whose docs are complete but bot-gated is measured on its documentation, and its retrieval
  policy is reported separately. The `public-docs` number keeps meaning one thing across vendors.
- Reviewers can tell from the manifest alone which agent produced a snapshot.
- **No prior pack is affected.** Re-checked every committed manifest URL for the three existing external
  packs under both the default and a browser agent: two vendors return byte-identical responses to both
  (one of them the JS-shell case), and the third fails to resolve under both. No published finding
  changes; this is the first gated docs host the method has met.
- Core stays vendor-agnostic: the behavior is driven entirely by pack config, and the guard test still
  proves no vendor token under `core/`.
