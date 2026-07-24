# ADR-0008: an unversioned API is scored on whether the model knows it, not on which word it picked

## Status
Accepted

## Context
The answer-block contract ([core/prompt.py](../../core/prompt.py)) asks for a version per endpoint:

```
api_version:      # the version segment: v3, beta, oauth, v2025, or <service>/v1
```

Every example is a version that exists. The contract explicitly handles the empty case for one other
field — `required_scopes: # list of OAuth scope strings ([] if none)` — and does not for this one. A
model answering about an API with **no version segment at all** therefore has no sanctioned spelling.

A vendor measured this cycle has exactly that shape: paths carry no version, so the ground truth is the
unversioned marker `"/"`, which [`normalize_version`](../../core/scorer.py) reduces to `""`. Across 110
scored endpoint records, the answers to "what version?" fell into three groups:

| what the model did | count | previously scored |
|---|---|---|
| named a version the API does not have (`v1`, `v10`, `api`, `gen2`, `passwordvault/api`) | 95 | 0 — correct |
| said there is no version (`<none>`, `none`) | 8 | **0 — incorrect** |
| named the wrong path, so version was not credited either way | 7 | 0 — correct by design |

The middle row is the problem. A model that correctly identified the API as unversioned scored the same
as one that invented `v10`, purely because it wrote the word rather than leaving the field blank. The
dimension read 0.00 in both conditions, and would have been published as a finding about the vendor
while partly measuring our own contract's silence.

This is the same class of error as [ADR-0007](adr-0007-docs-fetch-user-agent.md): an instrument
artifact presented as a vendor property. It is worth stating the general rule, because the
`api_version` dimension has a meaning on an unversioned API and it is a useful one — *does the model
know this API is unversioned, or does it pattern-match a `/v1/` that was never there?* That question is
answerable. "Which synonym for nothing did it choose?" is not.

## Decision

**`normalize_version` treats every spelling of "there is no version" as the empty version.** The
sentinel set is `none`, `n/a`, `na`, `null`, `nil`, `unversioned`, `no version`, `-`, `--`, each
optionally wrapped in `<>`, `()`, or `[]` so `<none>` reads as `none`.

Three properties make this safe rather than generous:

- **It is symmetric.** The same normalization applies to ground truth and answer. A pack author writing
  `api_version: none` and one writing `api_version: "/"` produce the same ground truth.
- **It cannot move a versioned vendor's score.** A sentinel compares equal only to the empty version, so
  `none` against a ground truth of `v3` is still wrong. Verified by the frozen SailPoint regression gate
  (`packs/sailpoint/tests/test_regression_gate.py`), which reproduces 73/68/93 and every per-dimension
  cell unchanged.
- **The dimension keeps its teeth.** Asserting `v1` on an API that has no version still scores 0. That
  is the error worth catching, and it remains caught — 95 of the 110 records above.

**The prompt contract is not changed this cycle.** Adding "or `none` if the API is unversioned" to
[core/prompt.py](../../core/prompt.py) would be the more direct fix, and it is the better long-term one,
but the prompt is the shared instrument: changing it makes every previously measured vendor
incomparable and requires re-running the whole cohort. A scorer-only change is re-appliable to archived
transcripts offline via `rebuild-report` ([core/rebuild.py](../../core/rebuild.py)) at zero model spend,
so past and present vendors stay on the same footing. **The contract gap is recorded as open work**, to
be taken with the next deliberate cohort re-run rather than smuggled in beside a vendor measurement.

## Consequences

- Affected results are re-scored with `rebuild-report`, not re-run. No number changes for any vendor
  whose endpoints are all versioned.
- An unversioned vendor's `api_version` figure now means "correctly reported the absence of a version".
  That is a different question from a versioned vendor's "picked the right version", so a pack in that
  position says so on its card rather than letting the two average into one cross-vendor claim.
- Until the contract names the empty case, some models will still answer an unversioned endpoint with a
  plausible-looking `v1`. That is the measurement, and it is the one worth having.
- The general rule this sets: **when a dimension reads 0.00 across every task and both conditions, the
  instrument is a suspect before the vendor is.** Two of this cycle's findings came from checking.
