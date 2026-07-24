# ADR-0002: Extraction method, pack manifest, and the regression gate

## Status
Accepted

## Context
ADR-0001 splits the harness into a vendor-agnostic `core/` and vendor `packs/`. The extraction is only
credible if it provably changed no measurement: the frozen `sailpoint-proof-of-concept` published
per-task, per-dimension tables and a 73 / 68 / 93 headline, and a skeptical reader must be able to
confirm that this repository's core reproduces them from the same evidence. This ADR records how the
vendor coupling is parameterized and how equivalence is proven and kept proven.

## Decision

### Pack configuration is declarative data
Each pack carries a `pack.yaml` read by `core/pack.py` into a `Pack` object. It supplies the vendor
strings core must not hardcode: the vendor id and display name; the tasks/manifest/specs locations;
the public-docs source label and token budget; and — only when the pack has a context layer — the MCP
server key, tool prefix, discovery tool, expected tool names, and spawn command (which may point at an
external server). Conditions and preflight take a `Pack` and read these fields; the registry is built
per-pack by a factory rather than instantiated at import.

The schema also allows optional `scoring` overrides (the version-segment vocabulary and the auth-concept
vocabulary) for vendors whose API versioning or auth model differs. Core ships sensible defaults —
generic REST versioning (`v3`, `beta`, `oauth`, `v20xx`) and OAuth concepts (`client-credentials`,
`bearer`) — and the **SailPoint pack omits the overrides on purpose**, so core's defaults apply
unchanged. This is what keeps the scorer's output byte-identical to the frozen repo (see the gate below).

### The guard test
`core/tests/test_core_no_vendor.py` greps every file under `core/` for vendor tokens (`sailpoint`,
`isc_spec_context`, `developer.sailpoint`, `idn/`) and asserts none appear, and separately asserts that
the pack-supplied fields are actually consumed (not shadowed by a constant). "Core is vendor-agnostic"
is thereby a continuously-checked property.

### The regression gate
`core rebuild-report` re-scores every archived `runs/*.json` from its stored `raw_response` with the
current scorer and the pack's task ground truth, then rewrites `summary.md` + `scores.json`. The gate
(`packs/sailpoint/tests/test_regression_gate.py`, marked `regression`) does this over copies of the three
imported canonical sterile directories and asserts:

1. The recomputed `aggregate` and every per-run `dimensions` / `endpoint_matches` / `format_failure`
   equal the imported committed values.
2. The only top-level differences fall in the documented **run-provenance metadata class** — the
   `cli_policy` and `tool_discipline_summary` blocks and `reused_runs` (which a rebuild replaces with
   `rebuilt_from_runs: true`), plus the single matching tool-discipline note line in `summary.md`. This
   class is exactly the one the frozen repo's AUDIT.md §2 documents as the only allowed diff.
3. The regenerated multi-condition comparison reproduces the imported
   `comparison-sterile-2026-07-23.md`, and the headline overall values are literally **73 / 68 / 93**
   with every published per-task/per-dimension cell unchanged.

If any score-bearing cell moves, that is an extraction bug: the gate fails loudly and the cycle stops and
reports it, rather than re-baselining. The gate is a permanent test, not a one-time diff, so the
equivalence claim stays true as core evolves.

### The context-layer server is referenced, not vendored
The SailPoint pack's context-layer config points at the frozen repo's `mcp-server/` as external. The gate
re-scores archived transcripts offline and never starts the live server, so three-condition scoring
reproduces without it. Live re-runs of the MCP condition require the external server to be present; that
is out of scope for the equivalence claim.

## Consequences
- The equivalence obligation from ADR-0001 is discharged by a single command
  (`pytest -m regression`) that anyone can run.
- The scorer, answer-block parser, prompt contract, and report renderer are ported as close to verbatim
  as possible; parameterization is confined to the conditions, preflight, and analysis layers, keeping the
  scoring path — and therefore the gate — stable.
- A boundary is made explicit: the answer-block contract (endpoints / method / version / auth / scopes /
  params) assumes a REST-API-shaped readiness task. It is kept in core as *the method*; a vendor whose
  readiness is not API-shaped would need a different contract, which would be a new ADR, not a pack.
