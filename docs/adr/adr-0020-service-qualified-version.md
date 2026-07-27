# ADR-0020: a service-qualified version is the same version

## Status

Accepted. Completes the pair begun by [ADR-0013](adr-0013-spec-server-prefix.md) and
[ADR-0017](adr-0017-endpoint-base-prefix.md): those two taught the anchoring gate and the scorer that
the *path* may legitimately be written from more than one starting point. This one says the same about
the *version*.

## Context

> **Amended 2026-07-27 (ADR-0028), for the privacy rule only.** As first written, this ADR and its
> tests illustrated the problem with the measured vendor's *real* service names and the *real* name of
> its query language — enough for any reader in the space to identify it, in a public repository whose
> standing rule is that it names no measured prospect. Those literals are now neutral stand-ins
> (`ledger/v1`, `report/v1`, `ledgerquery`). The strings were only ever synthetic fixture inputs, so
> **no assertion, decision, measurement or published number changes** — including the 55-of-55 and 1%
> figures below, which come from the private pack's archives and never depended on these spellings.
> Recorded rather than done quietly: silently editing a merged ADR is the move this project's own
> conventions forbid.

The prompt contract has always offered the model two spellings of an API version. Verbatim, from
[core/prompt.py](../../core/prompt.py):

```
  api_version:      # the version segment: v3, beta, oauth, v2025, or <service>/v1
```

`<service>/v1` is not a model invention. It is an option this project put in front of the model in
writing, and it exists because it is how several real APIs are versioned — per service rather than per
product, so `ledger/v1` and `report/v1` are independent v1s that can move apart.

`normalize_version` never accepted the form it offered. It lowercased, stripped a leading slash and
collapsed the "no version" sentinels, and otherwise compared the string as given — so `ledger/v1` and
`v1` compared unequal.

`normalize_path` had already solved the same problem on the path side, and says so in a comment that
has been sitting directly above the version code the whole time:

> A path segment that is a version marker (stripped anywhere before path compare, so `/v3/search` and
> the newer per-service `/search/v1` both reduce to the resource `search`; the v3-vs-v1 difference is
> captured by the api_version dimension, not the path dimension).

The path dimension knew about per-service versions. The version dimension, which that comment names as
the place the difference is captured, did not.

### How it surfaced

A vendor whose documentation states plainly that the version is per-service, and where the model had
read that documentation. Under `public-docs` the model answered `ledger/v1` and `report/v1` — the
contract's own second form, and the vendor's own notation — on **55 of 55** endpoints. Ground truth was
written `v1`. The dimension reported **1%**.

A dimension reading 1% across every task in a condition is the signature this project already has a
standing rule for: *the instrument is a suspect before the vendor is*. Checking took one tally of what
the model actually wrote. The corrected reading is **86%**, and the vendor's documentation gap moves
from **−10 points to +2** — a headline that would otherwise have said this vendor's documentation makes
the model worse overall, on the strength of a dimension measuring our own string comparison.

## Decision

**`normalize_version` collapses a `<service>/<version>` pair to the version**, where the trailing
segment is a version marker by the existing `_VERSION_SEG_RE` and the leading part is a single
segment. `a/b/v1` is left alone; so is `beta`, `v3`, and every sentinel.

Three properties make this a correction rather than a loosening:

- **It is symmetric.** The same normalization applies to ground truth and answer, so a pack may write
  either form and neither is privileged. This is the ADR-0013 principle: ground truth has to be free to
  follow the vendor's own notation, because that is what the measured model has read.
- **It cannot credit the wrong service.** `api_version` is scored only on an endpoint whose **path**
  already matched, and the path is where the service segment lives. An answer that named `report/v1` for
  a record-service endpoint fails the endpoint dimension first and is never reached here.
- **It cannot move a vendor that does not use the form.** A per-product-versioned API answers `v3`, and
  `v3` normalizes to `v3` exactly as before.

**The exhibit keeps what the model actually wrote.** `endpoint_matches[].answer_api_version` now records
the raw answer and the comparison normalizes separately. Recording the normalized form there would erase
the evidence needed to tell a wrong version from a differently-spelled right one — which is precisely
the investigation that found this defect, and precisely what the frozen regression fixture caught when
the first version of this change quietly rewrote `search/v1` to `v1` in a committed exhibit.

## Alternatives rejected

- **Write ground truth in the service-qualified form instead.** It moves the problem rather than fixing
  it: the same pack's no-context answers are overwhelmingly the bare `v1`, so the same mismatch
  reappears pointing the other way, and the cold number falls for the same non-reason. Worse, it makes
  the pack's notation depend on which condition happens to be read.
- **Make it an opt-in pack setting, like `endpoint_base_prefix`.** ADR-0017 was opt-in because absorbing
  a path prefix could mask a genuinely different endpoint, so a pack has to assert the equivalence. Here
  there is nothing for a pack to assert: the contract already told every model that both spellings are
  acceptable, for every vendor. A pack-level flag would make a promise this project made globally
  conditional on remembering to opt in, which is the shape of the defect, not its fix.
- **Change the prompt contract to permit only one form.** The better long-term fix, and unavailable
  here for the reason ADR-0008 and ADR-0014 both record: the prompt is the shared instrument, changing
  it makes every previously measured vendor incomparable, and it cannot be re-applied to archives. A
  scorer-only change re-scores every existing transcript offline at zero model spend. The contract's
  two-spelling wording is now a **third** item queued behind that deliberate cohort re-run.

## Consequences

- **The frozen 73/68/93 gate is unmoved, and it earned its keep.** The first attempt at this change
  passed every score check and still failed the gate, because it altered ten archived `answer_api_version`
  strings in the SailPoint public-docs exhibit from `search/v1` to `v1`. No score moved — every one of
  those answers was `v1` against a ground truth of `v3` and stayed wrong — but the evidence record would
  have been silently rewritten. That is exactly the class of change the byte-identical assertion exists
  to catch, and it caught it.
- Every existing pack re-scores identically; no committed number in the cohort moves.
- One vendor's version dimension moves 1% → 86% under docs and 56% → 71% cold, and its overall
  documentation gap moves −10 → +2. That correction is disclosed on the card rather than quietly
  applied, and the pre-correction figure is printed beside it.
- The rule generalizes the standing one this project keeps re-learning: **a dimension that reads near-zero
  uniformly is a suspect instrument before it is a vendor finding.** This is the third instance
  (ADR-0008, ADR-0013, now this), and the second in which the answer was that the contract and the
  scorer disagreed about what a legal answer looks like.
