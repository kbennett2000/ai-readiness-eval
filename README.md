# ai-readiness-eval

A vendor-agnostic measurement of how accurately an AI coding model completes a software vendor's common
API tasks — cold, with the vendor's public documentation, and (optionally) with a spec-derived context
layer — scored deterministically against spec-traceable ground truth.

It generalizes the method proved in `sailpoint-proof-of-concept` (now frozen): a vendor-agnostic `core/`
engine plus vendor `packs/`. SailPoint is the reference pack.

> **Cycle 1 in progress.** This README is expanded as part of the extraction cycle. See
> [docs/adr/](docs/adr/) for the architecture and [CLAUDE.md](CLAUDE.md) for how work runs here.
