# REPRODUCE.md — check the numbers yourself

Every published number in this repository is meant to be checked, not taken on trust. The core claim
of cycle 1 is an **equivalence claim**: re-scoring the imported SailPoint archives through this
repository's vendor-agnostic core reproduces the frozen `sailpoint-proof-of-concept` tables exactly —
overall **73% / 68% / 93%** and every per-task, per-dimension cell. This is wired as a permanent test,
not a one-time diff. If a step here does not reproduce, that is a defect in this repo.

## 0. Install

```bash
pip install -r requirements.txt      # PyYAML + jsonschema + pytest (+ anthropic, only for live runs)
```

Everything below is offline: no network, no API key, no model call.

## 1. The regression gate (the headline)

```bash
pytest -m regression -v
# or just this file:
pytest packs/sailpoint/tests/test_regression_gate.py -v
```

**Expected:** all green. The gate copies each imported archive to a temp dir, re-scores it via
`core rebuild-report`, and asserts:

- overall re-scores to **73% (no-context) / 68% (public-docs) / 93% (mcp)**;
- the recomputed `aggregate` and every per-run `dimensions`/`endpoint_matches` are byte-identical to
  the committed fixture;
- the only metadata differences are the documented run-provenance class (`cli_policy`,
  `tool_discipline_summary`, `reused_runs` → `rebuilt_from_runs`), and the only `summary.md` difference
  is the single tool-discipline note line;
- the regenerated cross-condition comparison reproduces the score tables of
  [`comparison-sterile-2026-07-23.md`](packs/sailpoint/fixtures/imported/comparison-sterile-2026-07-23.md),
  including the literal `| **overall** | 73% | 68% | 93% |` row.

If any score-bearing cell moves, the gate fails — that would be an extraction bug, not a rounding note.

## 2. Do it by hand

Re-score one condition and read the overall back:

```bash
tmp=$(mktemp -d)
cp -r packs/sailpoint/fixtures/imported/2026-07-23-sterile-no-context "$tmp/"
python -m core --pack packs/sailpoint rebuild-report "$tmp/2026-07-23-sterile-no-context"
# -> Rebuilt ... (overall 73%, 0 format failures)
```

Regenerate the cross-condition comparison and read the headline row:

```bash
python -m core compare \
  packs/sailpoint/fixtures/imported/2026-07-23-sterile-no-context \
  packs/sailpoint/fixtures/imported/2026-07-23-sterile-public-docs \
  packs/sailpoint/fixtures/imported/2026-07-23-sterile-mcp | grep overall
# -> | **overall** | 73% | 68% | 93% | +20 pts | +24 pts |
```

## 3. The whole suite

```bash
pytest
```

**Expected:** all green — the vendor-agnostic engine suite (`core/tests/`, including the
`test_core_no_vendor` guard that proves `core/` names no vendor) plus the SailPoint regression gate.

## Provenance of the fixture

The archives under `packs/sailpoint/fixtures/imported/` are imported byte-for-byte from the frozen
`sailpoint-proof-of-concept` repo (HEAD `f401a54`). See
[`PROVENANCE.md`](packs/sailpoint/fixtures/imported/PROVENANCE.md) for the source paths, what is and
is not imported, and the allowed byte-difference class.
