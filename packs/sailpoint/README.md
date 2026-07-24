# SailPoint reference pack

The reference pack for `ai-readiness-eval`, built from the frozen `sailpoint-proof-of-concept` repo's
committed artifacts. It is both a working vendor pack and the fixture the extraction-equivalence gate
runs against.

## Contents

| Path | What it is |
|---|---|
| `pack.yaml` | Vendor config consumed by core — display name, docs source label, and a **context-layer** block that references the frozen repo's MCP server as *external* (not vendored here). |
| `tasks/*.yaml` | The 11 ISC API tasks, with spec-traceable `ground_truth` (endpoints/auth/scopes/params). Copied verbatim from the frozen repo. |
| `specs.yaml` | The pinned spec source (repo + SHA `545c4ade…`) plus the scored **spec-availability + license finding** (machine-readable spec: yes; MIT; permits vendoring: yes). |
| `docs-manifest.yaml` | The public-docs pages per task. The page cache itself is fetched, not committed (it is the vendor's copyrighted docs). |
| `fixtures/imported/` | The three canonical **sterile** results dirs (no-context 73%, public-docs 68%, mcp 93%) + the canary + the comparison table, imported byte-for-byte as the regression fixture. See `fixtures/imported/PROVENANCE.md`. |
| `tests/test_regression_gate.py` | The gate: re-scoring the imported archives through core must reproduce the frozen tables exactly. |

## This pack is three-condition, with an external context layer

`pack.yaml` declares a `context_layer`, so the pack exposes all three conditions. But the MCP
context-layer server lives in the frozen repo and is **not vendored here**. The regression gate
re-scores archived transcripts offline and never starts the server. A live `mcp`-condition run would
require the frozen repo checked out and the spawn command's `--directory` made absolute — see the
`external_note` in `pack.yaml`.

## Run the gate

```bash
pytest packs/sailpoint/tests/test_regression_gate.py     # from the repo root
```

See the repo-root [REPRODUCE.md](../../REPRODUCE.md) for the full reproduction path.
