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
