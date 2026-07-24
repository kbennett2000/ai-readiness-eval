# ADR-0001: Repository purpose and core/pack architecture

## Status
Accepted

## Context
`sailpoint-proof-of-concept` proved a method: measure how accurately an AI coding model completes a
software vendor's common API tasks, across context conditions, scored deterministically against
spec-traceable ground truth. Its headline — no-context 73%, public-docs 68%, spec-derived MCP context
layer 93% — is a statement about *how much good context is worth*, demonstrated on one vendor. That repo
is now frozen as a pitch artifact.

This repository generalizes the method so it runs against any vendor, not just SailPoint. The unit of
reuse is the measurement harness; the unit of variation is the vendor. The purpose is to make "what is
this vendor's API worth to an AI coding tool, and how much does good context change that?" a repeatable,
auditable measurement rather than a one-off.

## Decision

### Core / pack split
- **`core/` is vendor-agnostic.** It contains the whole measurement engine and carries no vendor string,
  path, or task assumption. A guard test (`core/tests/test_core_no_vendor.py`) enforces this by grepping
  `core/` for vendor tokens and asserting none. Core comprises: the conditions interface + name-keyed
  registry, the prompt contract + answer-block parser, the deterministic scorer + normalization rules,
  sterile per-run invocation (a fresh empty working directory so no ambient context loads), runtime tool
  discovery, transcript tool-discipline assertions, the resumable runner, `rebuild-report`, the canaries,
  and the model-pin guard.
- **`packs/<vendor>/` holds everything vendor-specific:** `tasks/*.yaml`, `specs.yaml` (spec source +
  pinned SHA + license finding), `docs-manifest.yaml`, `pack.yaml` (the vendor config that feeds core),
  an optional context-layer config, and any imported fixtures. Vendor specifics reach core only through a
  loaded `Pack` object — never through a literal in core.

### Two-condition mode is first-class
A pack with no context layer runs `no-context` vs `public-docs` and still produces a full report. The
third (context-layer) condition is optional per pack. Measuring the gap between conditions must never
require first building the fix, because a large part of the finding *is* the gap without a fix.

### Spec availability and license are scored findings
Every pack's `specs.yaml` records whether a machine-readable spec exists, where it lives, under what
license, and whether that license permits the vendoring this method prefers. A vendor with no public
spec, or a spec under a license that forbids redistribution, fails that dimension explicitly in the
report rather than silently. This makes "is this vendor even set up to be built against by AI?" a
measured outcome.

### Integrity kit carried over
The working agreements from the frozen repo carry over unchanged: ADR-first with sequential numbering
(superseded decisions marked, not deleted), vertical slices, plan-then-execute, test-heavy, and the
privacy rule (`docs/private/` gitignored, never committed or referenced). Two conventions the frozen
repo only *practiced* are named explicitly here: **no unlinked claims** (every factual claim in a tracked
doc links to its backing artifact) and **no vendor-dunk language** (findings stated clinically as
measurements with evidence, never as a jab at a vendor).

## Consequences
- A new vendor is added by authoring a pack, not by editing core — the "add a vendor in five steps" path
  in the README.
- The guard test makes "core is vendor-agnostic" a continuously-checked property, not a claim.
- Because core is shared, an equivalence obligation exists: re-scoring the frozen SailPoint archives
  through this core must reproduce the frozen tables exactly. ADR-0002 records how that is proven.
- The privacy rule requires a pre-push check: `git ls-files | grep -i private` returns nothing.
