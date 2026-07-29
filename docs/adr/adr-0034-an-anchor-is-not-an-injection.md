# ADR-0034 — an anchor and an injection are two different jobs

**Status:** Accepted
**Date:** 2026-07-29
**Follows:** ADR-0005 (public-docs models what a fetch retrieves), ADR-0021 (the extracted-text
floor), ADR-0029 ("a spec exists" and "we may keep a copy" are two findings), ADR-0031 (why a waiver
flag was refused).

## Context

`docs-manifest.yaml` has always answered two questions with one list:

1. **Where is this answer documented?** — what `ground_truth.endpoints[].doc_ref.url` is checked
   against by the anchoring gate, so a reviewer can follow any key back to the vendor's own words.
2. **What is the model shown?** — what `PublicDocsCondition` fetches, budgets and injects.

These are different claims about different artifacts, and forcing them to be the same list means a
pack can only cite what it is willing to inject.

That has already cost something. One published pack in this cohort has a first-party, unauthenticated
machine-readable document for **every** endpoint it measures, and could not use it as an anchor. Its
task files say so in prose, once per task:

> "It is undocumented — nothing on any page mentions it — so it is recorded here as the corroboration
> of this key, never as an anchor: it is not in docs-manifest.yaml and the model is never shown it."

The best available evidence for that pack's ground truth is a comment, because citing it properly
would have meant injecting the answer key's own source into the measurement.

### The case that removes the workaround

A vendor now measured in the cohort publishes a developer portal that is a client-rendered
application returning a **byte-identical response for every URL, including URLs that do not exist**.
No 404 exists on the host; `robots.txt` and `sitemap.xml` return the same shell as everything else;
roughly 70 bytes of text extract from any of them, far under the ADR-0021 floor.

The earlier pack could at least verify its reference pages by title before anchoring to them. Here
there is **no observation that distinguishes citing a real page from citing a fabricated one** — the
response is the same either way. A page like that cannot be an anchor; it is not evidence of
anything. The only citable first-party artifact is the vendor's machine-readable document, which is
publicly fetchable and individually versioned.

So the conflation now forces a choice between two bad options: anchor ground truth to a page that
demonstrably contains nothing, or inject the answer key's source and publish a number that measures
our own manifest.

## Decision

A manifest task entry carries **two** lists:

```yaml
tasks:
  <task_id>:
    pages:      # what the model is SHOWN — unchanged
      - { url: ..., role: api-reference, note: ... }
    anchors:    # what the answer key is CITED to — never injected
      - { url: ..., note: ... }
```

- `check_anchoring` resolves a `doc_ref.url` against **`anchors ∪ pages`**.
- `PublicDocsCondition` reads **`pages` only**, through its own accessor, and has no code path that
  can reach `anchors` — including `full_text`, which is the truncation audit's baseline.
- `fetch-docs` fetches anchors as well as pages, recording each one's `byte_size`, `content_hash` and
  `fetch_date`. **An anchor that has never been retrieved is an unverified claim**, and the cache is
  gitignored, so verifying costs nothing and redistributes nothing.
- `anchors` is optional and absent from every existing pack; a manifest that declares none behaves
  exactly as before, which a test asserts.

### A separate key, not a `pages[].inject: false` flag

The flag is the obvious spelling and it is the wrong one. It leaves the injected list one boolean away
from showing the model the answer key's own source, and **that failure is silent**: the grid runs
normally, the reports render, the numbers look plausible, and they measure nothing. A separate key
makes the mistake unrepresentable rather than merely discouraged. This is the same reasoning ADR-0031
used to refuse a waiver flag on the prompt gate.

### The disclosure travels with the pack

A pack that anchors to something it never injects has to say so on its card: **ground truth rests on a
first-party artifact the documentation condition is never shown.** The gap such a pack measures is
"how much does the vendor's *reachable* documentation help", and the answer key's source is not part
of it. Without that sentence a reader would reasonably assume the two were the same corpus, which is
what they were until this ADR.

## What this cannot do

- **It cannot judge whether an anchor is any good.** It checks that a cited URL was declared and
  retrieved. A pack that anchors to a first-party document that is wrong, stale, or describes a
  different surface gets a green gate on a bad citation; only review catches that.
- **It cannot make an empty docs condition informative.** For the vendor above, `public-docs` injects
  nothing and the measured gap will be near zero by construction. This ruling makes the *anchoring*
  honest; it does not manufacture documentation that the vendor does not serve.
- **It does not decide whether a spec should ever be injected.** Injecting a machine-readable
  specification is a legitimate *third* condition — the same shape as a vendor-published context
  layer — and belongs in a study designed for it, with its own baseline. Folding it into a
  two-condition diagnosis would change what the cohort's `public-docs` column means, silently, for one
  vendor. Filed, not done.
- **It cannot retro-fit the pack that needed it first.** The existing corroboration notes stay prose
  this cycle: re-encoding a published pack moves no number and can wait for a cycle that is not also
  burning a grid. Filed.

## Consequences

- `check_anchoring` widens; **no dimension gets easier and no scorer rule changes.** An endpoint still
  has to be either spec-anchored or doc-anchored to a declared, fetched URL.
- One new accessor, `docs_fetch.manifest_urls`, shared by the gate and the fetcher. The injecting
  condition deliberately does **not** use it, so no future change there can widen what reaches a
  prompt.
- **No committed manifest, task file, prompt, scorer rule or published number is touched.**
