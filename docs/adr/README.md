# Architecture Decision Records

Every load-bearing decision in this project is recorded here, numbered in the order it was made. Read in
sequence, they are the project's decision story. All are **Accepted**.

| # | Decision | In one line |
|---|---|---|
| [0001](adr-0001-purpose-and-core-pack-architecture.md) | Repository purpose and core/pack architecture | A vendor-agnostic `core/` measurement engine plus vendor `packs/`; two-condition mode first-class; spec availability + license scored; integrity kit carried over. |
| [0002](adr-0002-extraction-and-regression-gate.md) | Extraction method, pack manifest, and the regression gate | Vendor coupling parameterized through a declarative `pack.yaml`; a guard test proves `core/` is vendor-free; a permanent regression gate reproduces the frozen 73/68/93 tables exactly. |
| [0003](adr-0003-job-taxonomy.md) | The job-category taxonomy | A fixed, vendor-neutral set of job categories (`core/taxonomy.py`); tasks stay product-native, comparison happens at category level only; N/A is a first-class, recorded outcome. |
| [0004](adr-0004-category-cross-vendor-comparison.md) | Category-level rollup and cross-vendor comparison | `core/category.py` rolls a condition's per-task aggregate up to per-category numbers and renders a labeled `category × source` table; names no vendor, one condition fixed per table, verified against the reference pack's 1:1 map. |
| [0005](adr-0005-public-docs-fetch-fidelity.md) | public-docs models what a fetch actually retrieves | An un-fetchable page (manifest `fetch_error` or `byte_size: 0`) injects nothing instead of raising, so a vendor with a dead portal or SPA reference still runs a full grid; the forgot-to-fetch safety is preserved for pages that claim content. |
| [0006](adr-0006-factory-dispatcher.md) | The factory — an unattended, gated pipeline dispatcher | `core/factory.py` + a `factory` (next/run/status) command work a ranked queue through recon→validate→anchoring→mock→canary→grid→compare→card; every stage is a hard gate that blocks-with-reason; authoring stays external and anchoring-gated (auto-authoring deferred); names no vendor; no live vendor-API calls. |
| [0007](adr-0007-docs-fetch-user-agent.md) | A bot-gated docs host is a fetch policy, not an empty docs finding | A docs host that serves full pages to a browser agent and 404s a self-identifying one is measured on its documentation, via an opt-in `public_docs.user_agent`; the default agent stays honest, the override is recorded in the manifest, and the gate is reported as its own finding. Refines ADR-0005. |

New decisions get the next number in sequence; superseded ones are marked, not deleted.
