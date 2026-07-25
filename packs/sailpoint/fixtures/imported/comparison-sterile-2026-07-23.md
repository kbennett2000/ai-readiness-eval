# Condition comparison — no-context vs public-docs vs mcp

> **Note:** STERILE re-run of the cycle-6 headline (ADR-0009). Every claude -p runs from a fresh empty temp cwd, so no repo CLAUDE.md is auto-loaded into any condition; deny-all built-ins (init reports tools:[] for tool-free conditions); mcp server started via an absolute-path config. Hard-gated on canaries (sterile=ignorant, repo-root control=recites) + server health. Same pinned model (claude-sonnet-4-6), transport, scorer, N=5, 165 runs, transcript-asserted (0 violations). Cycle-6 results are superseded (contaminated-floor), archived not deleted. The delta table below quantifies what the ambient CLAUDE.md was worth to each condition.

## Run metadata

- **no-context:** model claude-sonnet-4-6, provider cli, 2026-07-23, N=5 — tool discipline: 0 violation(s) / 55 asserted, all-ok=True
- **public-docs:** model claude-sonnet-4-6, provider cli, 2026-07-23, N=5 — tool discipline: 0 violation(s) / 55 asserted, all-ok=True
- **mcp:** model claude-sonnet-4-6, provider cli, 2026-07-23, N=5 — tool discipline: 0 violation(s) / 55 asserted, all-ok=True
- **spec_sha:** 545c4ade45715883f345d4f1021d3f28ada9ba64

## Overall accuracy by dimension

| dimension | no-context | public-docs | mcp | Δ(mcp−no-context) | Δ(mcp−public-docs) |
|---|---|---|---|---|---|
| endpoint | 76% | 81% | 87% | +10 pts | +5 pts |
| method | 76% | 81% | 87% | +10 pts | +5 pts |
| version | 76% | 59% | 87% | +11 pts | +27 pts |
| auth | 98% | 100% | 98% | +0 pts | -2 pts |
| scopes | 22% | 2% | 100% | +78 pts | +98 pts |
| params | 87% | 87% | 98% | +11 pts | +11 pts |
| **overall** | 73% | 68% | 93% | +20 pts | +24 pts |
| format failures | 0/55 | 0/55 | 0/55 | | |

## Per-task accuracy (mean of applicable dimensions)

| task | no-context | public-docs | mcp |
|---|---|---|---|
| access-request | 83% | 83% | 100% |
| audit-report | 80% | 83% | 100% |
| auth-token | 70% | 70% | 70% |
| cert-campaign | 54% | 57% | 93% |
| find-identity | 58% | 67% | 80% |
| grant-revoke | 83% | 87% | 100% |
| identity-accounts | 87% | 83% | 100% |
| lifecycle-trigger | 90% | 63% | 100% |
| search-filter | 83% | 67% | 100% |
| source-aggregation | 68% | 47% | 88% |
| transform | 50% | 57% | 83% |

## Per-task × per-dimension (no-context / public-docs / mcp)

| task | endpoint | method | version | auth | scopes | params |
|---|---|---|---|---|---|---|
| access-request | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 0% / 0% / 100% | 100% / 100% / 100% |
| audit-report | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 80% / 100% / 100% | 0% / 0% / 100% | 100% / 100% / 100% |
| auth-token | 50% / 50% / 50% | 50% / 50% / 50% | 50% / 50% / 50% | 100% / 100% / 100% | n/a / n/a / n/a | 100% / 100% / 100% |
| cert-campaign | 55% / 75% / 100% | 55% / 75% / 100% | 55% / 75% / 100% | 100% / 100% / 80% | 60% / 0% / 100% | 0% / 20% / 80% |
| find-identity | 50% / 100% / 60% | 50% / 100% / 60% | 50% / 0% / 60% | 100% / 100% / 100% | 0% / 0% / 100% | 100% / 100% / 100% |
| grant-revoke | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 0% / 20% / 100% | 100% / 100% / 100% |
| identity-accounts | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 20% / 0% / 100% | 100% / 100% / 100% |
| lifecycle-trigger | 100% / 70% / 100% | 100% / 70% / 100% | 100% / 40% / 100% | 100% / 100% / 100% | 40% / 0% / 100% | 100% / 100% / 100% |
| search-filter | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 0% / 100% | 100% / 100% / 100% | 0% / 0% / 100% | 100% / 100% / 100% |
| source-aggregation | 50% / 50% / 75% | 50% / 50% / 75% | 45% / 40% / 75% | 100% / 100% / 100% | 100% / 0% / 100% | 60% / 40% / 100% |
| transform | 33% / 47% / 67% | 33% / 47% / 67% | 33% / 47% / 67% | 100% / 100% / 100% | 0% / 0% / 100% | 100% / 100% / 100% |
## Delta vs cycle-6 contaminated: what the crib sheet (CLAUDE.md) was worth

> cycle-7 sterile − cycle-6 contaminated, per condition per dimension (matched by condition name). Positive = cycle-7 sterile scored higher; negative = the condition leaned on ambient CLAUDE.md.

| condition | endpoint | method | version | auth | scopes | params | overall |
|---|---|---|---|---|---|---|---|
| no-context | +0 pts | +0 pts | +2 pts | +2 pts | -4 pts | +4 pts | +1 pts |
| public-docs | +2 pts | +2 pts | +2 pts | +4 pts | -8 pts | +5 pts | +1 pts |
| mcp | -1 pts | -1 pts | -1 pts | -0 pts | +12 pts | -2 pts | +1 pts |
