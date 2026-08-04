# ADR-0058 — A published number states which half of it a reader can re-check

**Status:** Accepted
**Date:** 2026-08-04
**Related:** [ADR-0046](adr-0046-a-published-overall-states-its-own-coverage.md) (the generated
disclosure this copies in shape, and whose rule this ADR found missing from the template that
generates cards), [ADR-0057](adr-0057-a-recorded-outcome-must-say-when.md) (a recorded outcome must
say when — the field this sentence reads),
[ADR-0002](adr-0002-extraction-and-regression-gate.md) (the gate the first sentence cites),
[ADR-0005](adr-0005-public-docs-fetch-fidelity.md) (the cache is fetched, not committed),
[ADR-0043](adr-0043-the-standard-library-caught-up.md) (whose hazard records what a clean checkout
cannot exercise without the cache),
[ADR-0015](adr-0015-hazard-registry.md), [ADR-0016](adr-0016-deferred-work-has-a-destination.md).
**Refs:** issue #102.

## Context

Every number this project publishes has two sides, pinned by different means.

The **spec side** is pinned to a public commit. `packs/sailpoint/specs.yaml` records
`spec_sha: 545c4ade…`, and every `spec_ref.file` in `tasks/*.yaml` resolves against that exact
commit. A third party can follow a ground-truth claim back to the vendor's own specification.

The **documentation side** is pinned by attestation. `docs-manifest.yaml` records, per page, a
`fetch_date`, a `content_hash` and a `byte_size` — 29 entries here, all captured `2026-07-23`. The
bytes those hashes were taken from are not in the repository: `.gitignore` excludes `**/docs-cache/`
because the snapshots are the vendor's copyrighted documentation. That exclusion is correct and this
ADR does not propose changing it.

The consequence is the sentence worth stating: **a reviewer on a clean checkout cannot re-derive
those hashes**, and a re-fetch of a live documentation site will not reproduce a 2026-07-23 hash in
any later year. The documentation condition is pinned by a statement about bytes, not by the bytes.

Both halves of that were already true and already written down — in issue #102, and in ADR-0057's
Consequences. Neither is a place a vendor's engineer reads. What they read is a report card and a
README, and [REPRODUCE.md](../../REPRODUCE.md), which is titled *"check the numbers yourself"* and
was silent about the half that cannot be checked. A reproducibility claim is made about these numbers
in writing, so the boundary belongs where the claim is met.

### What was found on the way

`render_card_scaffold` is the only report-card template in this project, and **it emitted no coverage
line either.** ADR-0046 requires every card to state which dimensions its overall is a mean of, built
the generator, and gated the cards — and the template that produces cards left the sentence to
whoever remembered to paste it. That is ADR-0046's own decay mode aimed at ADR-0046's own rule, and
it had no test of any kind: the template was untested code.

## Decision 1 — the sentence is generated, not typed

`core/report.py` gains two pure functions beside `coverage_line`:

```python
docs_provenance(manifest)                 -> {"entries", "retrieved", "dates"}
reproducibility_line(prov, *, adr_ref=…, manifest_link=…, gate_link=…)  -> one markdown line
```

An entry counts as **retrieved** iff it carries a non-null `content_hash` — exactly the set whose
bytes are attested but absent, which is the set the sentence is about. An entry that recorded a
`fetch_error` injected nothing and is not claimed as a captured page. An entry never attempted is not
claimed either. The capture dates are read off the **retrieved** set rather than off every entry, so
the sentence cannot cite the capture date of a page that was never captured.

Generated for the reason ADR-0046 records — *"hand-maintained derived numbers go stale silently while
the gated ones stay right"* — and with more force here, because this sentence carries a **count and a
date that move whenever a pack is re-fetched**. A typed version of it would be wrong the first time a
page is added and would still read as verified.

`adr_ref` is a parameter for the reason ADR-0046 gives (the two repos cite this repo's ADRs
differently). The two link parameters exist because one sentence has to be valid from the repo root,
from inside a pack, and from a card, and those paths point in different directions.

## Decision 2 — the branch that claims nothing is a real branch

A manifest with no retrieved page gets a different second sentence: it says the manifest records no
retrieval, so no snapshot is attested by hash. It does **not** say when anything was captured.

This is not defensive drafting. `core/tests/fixtures/pack-acme/docs-manifest.yaml` is deliberately a
manifest authored before its first fetch, and a pack whose every page was robots-refused (ADR-0036,
ADR-0052) has the same shape. A generator that produced "the 0 documentation pages this pack
retrieved were captured …" would be inventing a capture — the exact failure the line exists to
prevent. `test_a_never_fetched_pack_claims_no_capture_on_its_card` pins the branch to that real
fixture, so a future cycle that fetches the acme pack has to notice it is removing this branch's only
live evidence.

The first sentence is stated in that case too. What re-derives from the committed transcripts does
not depend on the cache — `core/rebuild.py` and `core/analyze.py` reference the docs cache nowhere —
so the claim holds for a pack that retrieved nothing.

## Decision 3 — the template emits both disclosures, above the first table row

`render_card_scaffold` now writes the coverage line and the reproducibility line between the
`**Method:**` line and the headline table. Position is the rule ADR-0046's card gate already states:
a disclosure a reader passes on the way to the number is a disclosure they can read past.

Both are recomputed from the pack's own data, and both refuse to render a false sentence. When a
card's conditions disagree about coverage the template **raises**, because one line cannot honestly
describe two arms that differ; the `card` stage catches it and blocks the target with the written
reason, which is the bargain every other stage in that pipeline already makes.

## Decision 4 — the line lands in all three places a reader meets a number

[README.md](../../README.md) (which publishes 73 / 68 / 93), [REPRODUCE.md](../../REPRODUCE.md)
(which is the reproduction document), and [`packs/sailpoint/README.md`](../../packs/sailpoint/README.md)
(which is the reference pack's card). All three are checked against the sentence recomputed from the
pack's own manifest.

Putting it in two of the three would be the discretion ADR-0046 Decision 2 argues against: a claim
made in writing is worth what the least careful of its statements says.

## Consequences

- Every card generated from now on states its coverage and its reproducibility boundary before its
  first number, without anyone remembering to paste either.
- The card template has tests for the first time.
- A pack that is re-fetched, gains a page, or loses one, fails the README gate until the sentence is
  regenerated — which is the sentence being right rather than being present.
- **No number is recomputed, re-scored or re-run.** No path under `results/` or `fixtures/` changes;
  73 / 68 / 93 unmoved; $0, no model call.

## What this does not do

**It does not make the capture reproducible.** It states that it is not. The bytes remain the
vendor's copyright and remain gitignored, and the alternatives — commit them, publish them outside
the repo and pin a digest, or record enough provenance that a re-fetch is *comparable* — are a licence
question for a maintainer, filed in issue #102 rather than decided here.

**It does not verify its own first sentence per pack.** The line says every number re-scores from the
committed transcripts and cites the gate that proves it; the gate proves it for the pack this
repository publishes, and a test here cannot read archives in another tree. Registered as
`the-reproducibility-line-restates-a-gate-it-does-not-run`.

**It does not reach a card already written.** A card is rendered once, when its pack is carded, and
is not re-rendered afterwards — so the sixteen already-measured cards were produced by a template
that emitted neither line, and no change to the template reaches them. That is a different limit from
ADR-0046's cross-repo one and is registered separately as
`a-disclosure-cannot-reach-a-card-already-published`, with the packs-repo gate that would name them
as its queue.
