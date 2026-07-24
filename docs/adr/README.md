# Architecture Decision Records

Every load-bearing decision in this project is recorded here, numbered in the order it was made. Read in
sequence, they are the project's decision story. All are **Accepted**.

| # | Decision | In one line |
|---|---|---|
| [0001](adr-0001-purpose-and-core-pack-architecture.md) | Repository purpose and core/pack architecture | A vendor-agnostic `core/` measurement engine plus vendor `packs/`; two-condition mode first-class; spec availability + license scored; integrity kit carried over. |
| [0002](adr-0002-extraction-and-regression-gate.md) | Extraction method, pack manifest, and the regression gate | Vendor coupling parameterized through a declarative `pack.yaml`; a guard test proves `core/` is vendor-free; a permanent regression gate reproduces the frozen 73/68/93 tables exactly. |

New decisions get the next number in sequence; superseded ones are marked, not deleted.
