# Imported regression fixture — provenance

These directories are **imported byte-for-byte** from the frozen `sailpoint-proof-of-concept`
repository and are the regression fixture for the extraction-equivalence gate (ADR-0002). They are
**not** produced by this repository — they are the canonical evidence this repository's core must
re-score to the same numbers.

## Source

- **Repo:** `sailpoint-proof-of-concept` (frozen pitch artifact; read-only)
- **Commit (HEAD at import):** `f401a54`
- **Imported:** 2026-07-24
- **Original path:** `eval/results/` in the source repo

## What was imported

| Imported here | From (source repo) | What it is |
|---|---|---|
| `2026-07-23-sterile-no-context/` | `eval/results/2026-07-23-sterile-no-context/` | no-context condition, N=5, 55 runs — overall **73%** |
| `2026-07-23-sterile-public-docs/` | `eval/results/2026-07-23-sterile-public-docs/` | public-docs condition, N=5, 55 runs — overall **68%** |
| `2026-07-23-sterile-mcp/` | `eval/results/2026-07-23-sterile-mcp/` | mcp context-layer condition, N=5, 55 runs — overall **93%** (1 format failure) |
| `2026-07-23-sterile-canary/` | `eval/results/2026-07-23-sterile-canary/` | the sterility pre-flight canary transcripts + verdict (not a scored condition) |
| `comparison-sterile-2026-07-23.md` | `eval/results/comparison-sterile-2026-07-23.md` | the canonical cross-condition comparison (the 73/68/93 headline table) |

Each condition dir holds `runs/<task>-run<0..4>.json` (the archived raw transcripts), `scores.json`
(`{metadata, aggregate, runs}`), and `summary.md`. The `runs/*.json` are the load-bearing evidence:
the gate re-scores each from its stored `raw_response` and must reproduce `scores.json`'s `aggregate`
and every per-run `dimensions`/`endpoint_matches` exactly.

Only the canonical cycle-7 **`-sterile-*`** set is imported. The source repo's earlier cycle-4 baselines
(`2026-07-23-no-context/`, `2026-07-23-public-docs/`, N=3) and cycle-6 `tri-*` grid
(contaminated-floor, superseded 72/67/91) are deliberately **not** imported — they are not the
canonical tables.

## Not imported (by design)

- **`docs-cache/`** — the public-docs snapshot is SailPoint's copyrighted documentation; it is
  gitignored in the source repo. Reproducibility comes from the committed `docs-manifest.yaml`. The
  gate re-scores archived transcripts and does not need the cache.
- **The MCP context-layer server (`mcp-server/`)** — referenced as external (see `../../pack.yaml`),
  not vendored. The gate re-scores the archived mcp-condition transcripts offline; it never starts the
  server.

## Allowed byte-differences on re-score (the run-provenance metadata class)

Per the source repo's `AUDIT.md` §2, a re-score reproduces every score-bearing figure exactly. The
only differences are run-provenance metadata that cannot be reconstructed from the transcripts: the
`cli_policy` block, the `tool_discipline_summary` aggregate, and `reused_runs` are absent on a rebuild,
which instead adds `rebuilt_from_runs: true`, and the matching one-line tool-discipline note disappears
from `summary.md`. No accuracy figure moves. The regression gate asserts exactly this.

## Correction (2026-07-29, ADR-0033): this import is **no longer byte-identical** to its source

The statement above that these files are a byte-for-byte import is now false for **one file**, and the
correction is recorded here rather than left implied.

**File:** `2026-07-23-sterile-mcp/runs/access-request-run3.json`
**Fields regenerated:** `format_failure`, `failure_reason`, `dimensions`, `endpoint_matches`,
`format_repaired`, `repaired_block_text` — the scorer- and parser-derived fields, and only those.

**Why.** That record disagreed with the `scores.json` sitting beside it. The ADR-0014 answer-format
repair had been applied to the report — where the run scores 6/6 with `format_repaired: true` — and
never written back to the record, which still declared `format_failure: true` with six null
dimensions. `rebuild-report` rewrites `scores.json` and `summary.md` but historically not
`runs/*.json`, so every archive it ever touched carried the scorer's older opinion. This was not
cosmetic: a resumed grid reads a run record and re-publishes it verbatim, so a stale record is a live
path to a wrong published number (ADR-0033).

**What was not touched, and why the frozen table is unmoved.** The regenerated values were copied out
of the committed `scores.json`; nothing was re-scored, no model ran, and `scores.json` was opened
read-only. Every transport-derived field — `raw_response`, `transcript`, `tool_uses`,
`tool_discipline`, the token counts, `cost_usd`, `duration_ms` — was verified byte-identical *before*
anything was written, and is unchanged. Because the regression gate re-scores from `raw_response`,
which is untouched, the 73/68/93 table provably cannot move; it was re-run to confirm rather than
argued.

**Where this is pinned.** `../../tests/test_frozen_fixture_diff.py` asserts the regenerated values
field by field, pins `raw_response` by digest, and asserts that no *other* imported record was
regenerated. Any further edit to this fixture fires deliberately.

The raw evidence in this directory is still exactly as imported. What changed is one record's copy of
what the scorer said about it.
