# Eval results — mcp

## Run metadata

- **condition:** mcp
- **model:** claude-sonnet-4-6
- **provider:** cli
- **sampling:** cli default (temperature not configurable via CLI)
- **date:** 2026-07-23
- **spec_sha:** 545c4ade45715883f345d4f1021d3f28ada9ba64
- **runs per task (N):** 5
- **total runs:** 55
- **format failures:** 0
- **format repairs (ADR-0014):** 1
- **subscription cost (USD, as reported by CLI):** 5.938
- **tool discipline:** 0 violation(s) logged across 55 asserted runs; final all-ok: True

Cells are mean accuracy across the N runs for that task; `n/a` = the dimension does not apply to that task (e.g. no required scopes). `fmt-fail` counts runs whose `answer-summary` block was unparseable (excluded from the dimension means, never scored zero).

## Per-task × per-dimension

| task | endpoint | method | version | auth | scopes | params | fmt-fail |
|---|---|---|---|---|---|---|---|
| access-request | 100% | 100% | 100% | 100% | 100% | 100% | 0/5 |
| audit-report | 100% | 100% | 100% | 100% | 100% | 100% | 0/5 |
| auth-token | 50% | 50% | 50% | 100% | n/a | 100% | 0/5 |
| cert-campaign | 100% | 100% | 100% | 80% | 100% | 80% | 0/5 |
| find-identity | 60% | 60% | 60% | 100% | 100% | 100% | 0/5 |
| grant-revoke | 100% | 100% | 100% | 100% | 100% | 100% | 0/5 |
| identity-accounts | 100% | 100% | 100% | 100% | 100% | 100% | 0/5 |
| lifecycle-trigger | 100% | 100% | 100% | 100% | 100% | 100% | 0/5 |
| search-filter | 100% | 100% | 100% | 100% | 100% | 100% | 0/5 |
| source-aggregation | 75% | 75% | 75% | 100% | 100% | 100% | 0/5 |
| transform | 67% | 67% | 67% | 100% | 100% | 100% | 0/5 |
| **ALL** | 87% | 87% | 87% | 98% | 100% | 98% | 0/55 |

## Aggregate

- **overall accuracy (mean of applicable dimension scores):** 93%
- **format failures:** 0 of 55 runs

## Scoring notes (judgment calls — see ADR-0004)

- **required_scopes** is scored as *any-of overlap*: a run passes when it names at least one scope in the ground-truth acceptable set, because task ground truth mixes alternative scopes with jointly-required ones.
- **key_parameters** is scored over the *required-subset* of ground-truth parameters; optional params (paging, optional filters) are ignored.
- **method** and **api_version** are credited only on endpoints whose path was matched — a right method on an unidentified endpoint earns nothing.
