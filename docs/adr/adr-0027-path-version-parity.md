# ADR-0027 — A version segment is stripped from a path whatever its spelling

**Status:** Accepted
**Date:** 2026-07-27
**Amends:** ADR-0025 (dotted numeric versions) — removes the exception it carved out.
**Extends:** ADR-0004 (`normalize_path` strips version segments).

## Context

`normalize_path` has always deleted version segments before comparing an address, and the reason is
written at the top of `core/scorer.py` in the project's own words:

> *the v3-vs-v1 difference is captured by the api_version dimension, not the path dimension*

So `/v3/accounts` and `/v99/accounts` compare **equal** on `endpoint`. One version mistake costs one
dimension. That is deliberate, it is how all ten previously measured packs were scored, and it is
what makes their `endpoint` numbers mean the same thing.

**ADR-0025 broke that for one notation.** Earlier in this same cycle it added dotted numeric
versions (`2.0`, `v2.1`) to `normalize_version` but deliberately kept them **out** of
`normalize_path`, with a must-not test pinning the exception. The argument was that stripping `2.0`
would make the 404-ing `/api/v2.0/jobs/create` compare equal to the real path, manufacturing an
endpoint score.

That argument is true. It is also true of `/v99/accounts` — which this scorer has compared equal to
`/v3/accounts` since ADR-0004. The exception protected against something the design does everywhere
else on purpose.

## What it cost, measured

The first pack to use that notation numbers its paths `/api/2.0/…`, `/api/2.1/…`, `/api/2.2/…`. Its
cold grid produced three tasks scoring **0% endpoint and 0% version**, and the transcripts show why:

| ground truth | the model answered |
|---|---|
| `POST /api/2.2/jobs/create` | `POST /api/2.1/jobs/create` |
| `GET /api/2.2/jobs/runs/list` | `GET /api/2.1/jobs/runs/list` |
| `POST /api/2.1/clusters/create` | `POST /api/2.0/clusters/create` |

Every one names the **right resource at the wrong version**. Under the ADR-0025 exception each paid
in two dimensions; under the rule every other vendor is scored by, each pays in one.

That is not a harsher number, it is an **incomparable** one. This project's entire output is the
comparison between vendors and between conditions. A per-vendor scoring rule invalidates the
product, not merely the cell.

The exception was invisible for exactly one cycle because no measured vendor had used the notation
before — which is the general shape of the thing: **a rule that is only exercised by one pack is a
rule nobody has compared to anything.**

## Decision

`normalize_path` strips a dotted numeric version segment, exactly as it strips `vN`, `beta` and
`oauth`. `_DOTTED_VERSION_RE` is now used by both normalizers; the ADR-0025 exception and its
must-not test are removed.

The `api_version` dimension is unchanged and keeps its teeth: answering `2.1` against a ground truth
of `2.2` still scores **0**. What changes is that it is scored **once**.

### The must-not that survives

The dot is what separates a version from an identifier, and now does double duty. A bare integer is
never stripped, because if it were, `/jobs/123/reset` and `/jobs/456/reset` would compare equal —
and that *is* a manufactured endpoint score. Pinned by
`test_stripping_a_version_segment_never_reaches_an_identifier`.

## Evidence

Re-normalizing every archived path in the ten measured packs with the shipped implementation:

| | |
|---|---|
| path strings whose normalization changes | **0** |
| compared path pairs | **666** |
| pairs whose endpoint match flips | **0** |

No archived path segment anywhere in the cohort is a dotted numeric. Regression gate: 17 passed,
frozen **73/68/93** unmoved.

## The thing that should worry a reader

**This ADR was written in the cycle whose grid it re-scores, by the same author, and it moves that
pack's numbers in the direction of the hypothesis the cycle set out to test.** A scoring change made
after seeing a result is the hardest bias to detect from the artifact, because nothing about the
resulting table looks wrong.

It is recorded as an ungated hazard rather than argued away. What is offered against it:

- The rule is **vendor-agnostic** and restores parity with ten existing packs; it is not a new
  allowance fitted to one vendor.
- It is argued from the scorer's **own pre-existing design comment**, written many cycles before
  this grid existed.
- It is **provably inert** on every archive — the table above.
- **The finding does not change sign.** `api_version` still scores 0 on all three tasks, so
  "the model is stale on the versions of the older surfaces" survives; only the double-counting
  goes.
- The card publishes **both** splits — under this rule and under the superseded one — so a reader
  can see the size of the correction rather than take it on trust.

The durable protection is procedural and already the standing rule: **decide a scoring question
before the grid.** ADR-0025 did exactly that, which is why this was caught as an instrument suspect
during transcript reading rather than published as a finding. The lesson is not that pre-committing
failed; it is that pre-committing a rule **no existing pack exercises** gets you one cycle of
confidence you have not earned.

## Consequences

- One scoring rule for every vendor, whatever the version notation.
- `endpoint` and `api_version` are genuinely independent dimensions again, as ADR-0004 intended.
- Scorer-only and archive-neutral: nothing re-runs, nothing costs anything, and the affected pack
  re-scores from its own transcripts at `$0`.
