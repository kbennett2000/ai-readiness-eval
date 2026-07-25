# ADR-0013: where a spec ends its server URL is not where the vendor's docs start the path

## Status
Accepted. Refines the anchoring gate introduced in
[ADR-0006](adr-0006-factory-dispatcher.md); shares its subject with
[ADR-0008](adr-0008-unversioned-apis.md) — scoring the address a caller has to write, rather than the
notation one artifact happens to use.

## Context

The anchoring gate requires that a spec-anchored endpoint's ground-truth `path` equal the path the
vendored spec gives for that `operationId`. That is the "never score a guess" enforcement, and it is
right: ground truth that is not tied to a durable artifact is not evidence.

But it silently assumed something that is not true in general — that **the spec's path is the path a
caller writes.** An OpenAPI 3 document splits an endpoint's address between `servers[].url` and the
key in `paths`, and a Swagger 2 document between `basePath` and the same. Where the split falls is the
spec author's convenience and describes nothing about the API:

```yaml
servers: [{ url: /Vendor/api }]      servers: [{ url: /Vendor }]
paths:   { /v1/things: ... }         paths:   { /api/v1/things: ... }
```

These describe the identical URL. The gate accepted the first form's `/v1/things` and rejected
`/api/v1/things`, so a pack was forced to adopt whichever notation its vendor's spec happened to pick.

**That is a problem because the model being measured has not read the spec — it has read the
documentation, and the documentation is where a vendor says its base URL ends.** A vendor whose spec
folds `/api` into `servers[0].url` may document "Base URL" as the host alone and write every worked
example as `/api/v1/...`. Ground truth pinned to the spec's notation then scores a correct answer as
wrong, on a difference of one path segment that neither the caller nor the model can be expected to
resolve.

This was found on a live pack, and the size of it is the argument. A first grid returned `endpoint` at
**13.7%** cold. Under the standing suspect-instrument rule that number was investigated rather than
published. The model was in fact naming the resource correctly in **98%** of runs; the entire gap was
one leading `/api` segment that ground truth omitted because the spec did. Corrected, the same
archived transcripts scored **94.1%**. Nothing about the model or the vendor changed — 80 points of a
reported dimension were an artifact of which artifact's notation ground truth had copied.

The round-trip control (ADR-0010) cannot catch this, and it is worth being precise about why: an
answer key always matches itself, so a key written in the wrong notation round-trips perfectly. The
control proves a key is *scoreable*, never that it is *right*. This is the second time that limit has
had teeth (the first cost a pack a re-grade for the mirror-image defect — a deployment prefix wrongly
included rather than wrongly omitted), which is what makes it worth a rule rather than a note.

## Decision

**1. A pack may write a spec-anchored path from any point inside the prefix the spec itself declares.**
`_index_operations` now returns, per `operationId`, the bare spec path *plus* that path prefixed by
every suffix of the spec's declared server prefix. For `servers[0].url: /Vendor/api` and a spec path
of `/v1/things`, all three of these anchor:

| ground-truth path | reading |
|---|---|
| `/v1/things` | base URL ends after `/api` — the spec's own notation |
| `/api/v1/things` | base URL ends after `/Vendor` — typically what the docs say |
| `/Vendor/api/v1/things` | base URL is the host |

The prefix comes from `servers[0].url` (OpenAPI 3) or `basePath` (Swagger 2); an absolute server URL
contributes only its path component.

**2. The choice among them is the pack's, and it is made on the vendor's documentation.** The gate
deliberately does not pick. Which form is correct depends on where the vendor tells a developer the
base URL ends, and that is a recon judgement belonging in the pack's ADR — the same class of decision
as which surface to measure. The gate's job is to stop a path that anchors to *nothing*; it is not to
impose one of several equally-anchored notations.

**3. This widens what the gate accepts, and never what the scorer credits.** No scoring rule changes
here, and no dimension becomes easier to satisfy. A pack whose ground truth was already spec-notation
is byte-identical, because the bare spec path is still the first accepted form.

**4. Wrong-prefix ground truth remains a defect the gates cannot detect, and the honest response is
disclosure.** Nothing here tells a pack it chose the wrong notation — the gate now accepts all three,
so an author who picks badly still gets a green gate and a depressed score. The detection that worked
was the suspect-instrument rule: an implausibly low dimension is the harness's fault until proven
otherwise, and the proof is reading the transcripts. That rule is what this ADR is really an argument
for, and it is why the affected pack's card carries the before/after rather than only the corrected
number.

## What this still cannot do

- **It cannot tell a pack which notation the vendor's documentation uses.** That is read by a human
  or an agent at recon time and argued in the pack's ADR. A pack can still be wrong; it can no longer
  be *forced* to be wrong by the gate.
- **It does not help an unanchored path.** A path matching no accepted form still blocks, with the
  alternatives named in the message so the author can see which notation the spec expects.
- **It does not address the scorer.** `normalize_path` still compares whole segment lists, so a
  ground-truth path and an answer that differ by a base segment still do not match. That is correct:
  the scorer's job is to compare what the model wrote against what a caller must write, and this ADR
  is about making sure ground truth *is* what a caller must write.

## Consequences

- The first external pack with a genuinely public spec could be anchored to its spec and scored
  against its documentation at the same time, which is the combination this method exists to measure.
- The gate's failure message now lists the accepted alternatives, so the next author who hits this
  sees the choice rather than guessing at a mismatch.
- The frozen SailPoint regression fixtures are unmoved: that pack's spec declares no server prefix, so
  the accepted set is exactly the bare path it already used.
