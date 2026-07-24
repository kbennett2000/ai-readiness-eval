# ai-readiness-eval

A vendor-agnostic method for measuring how accurately an AI coding model completes a software
vendor's common API tasks — and how much that accuracy moves when you change the context the model is
given. It is the reusable generalization of the method proved in `sailpoint-proof-of-concept` (now
frozen), split into a vendor-agnostic engine (`core/`) and per-vendor packs (`packs/<vendor>/`).

## What the eval measures

One model, one transport, N tasks per vendor, each scored **deterministically** against
spec-traceable ground truth — no model judging another model. Every task answer is parsed from a fixed
`answer-summary` block and scored on six mechanical dimensions:

| dimension | what it checks |
|---|---|
| endpoint | did the model reach the right resource path (version-normalized)? |
| method | correct HTTP method on a matched endpoint? |
| version | correct API version? |
| auth | correct auth flow (concept containment)? |
| scopes | at least one acceptable OAuth scope named? |
| params | all required parameters present? |

The scorer is pure, offline, and reproducible from the archived raw responses — see
[`core/scorer.py`](core/scorer.py) and the normalization rules it documents.

## The three-condition design (and two-condition mode)

The finding is never a single number — it is the **gap between conditions**, i.e. how much good
context is worth:

- **`no-context`** — the model gets the task prompt and nothing else (the floor).
- **`public-docs`** — the vendor's own public documentation is injected as context.
- **`mcp`** *(optional)* — a spec-derived, read-only context-layer server offers the model tools.

**Two-condition mode is first-class.** A pack that declares no context layer runs `no-context` vs
`public-docs` and still produces a full report. Measuring the gap must never require first building
the fix — so a vendor can be assessed before anyone writes a context layer for it.

On the SailPoint reference pack, the three conditions score **73% → 68% → 93%**: a spec-derived
context layer raised accuracy by 20 points, while today's public docs moved it *down* 5 points from
cold. Those numbers, and every per-task/per-dimension cell behind them, are reproduced by this
repository's core from the imported archives — see [REPRODUCE.md](REPRODUCE.md).

## Spec availability and license are scored, not assumed

Whether a vendor is even set up to be built against by AI is itself a measured outcome. Each pack's
`specs.yaml` records whether a machine-readable spec exists, where, under what license, and whether
that license permits the vendoring this method prefers. A vendor with no public spec — or a spec under
a license that forbids redistribution — fails that dimension explicitly rather than silently. See
[`packs/sailpoint/specs.yaml`](packs/sailpoint/specs.yaml) for the finding format.

## Core / pack architecture

- **[`core/`](core/)** is vendor-agnostic — it names no vendor (a guard test,
  [`core/tests/test_core_no_vendor.py`](core/tests/test_core_no_vendor.py), proves it). It holds the
  conditions interface + registry, the prompt contract + answer-block parser, the deterministic
  scorer, sterile per-run invocation, runtime tool discovery, transcript tool-discipline assertions,
  the resumable runner, `rebuild-report`, the canaries, and the model-pin guard. Vendor specifics
  reach it only through a loaded `Pack` ([`core/pack.py`](core/pack.py)).
- **[`packs/<vendor>/`](packs/)** holds everything vendor-specific: `tasks/*.yaml`, `specs.yaml`,
  `docs-manifest.yaml`, `pack.yaml` (the vendor config), an optional context-layer config, and any
  imported fixtures.

## The integrity kit

The method's credibility is a feature, so the repo practices the assessment's own standards:

- **ADR-first** decisions in [`docs/adr/`](docs/adr/) — read in order, they are the decision story.
- **A permanent regression gate.** The extraction is only credible if it changed no measurement; the
  gate re-scores the frozen archives and fails loudly if any cell moves (ADR-0002).
- **No unlinked claims** — every factual claim in a tracked doc links to its backing artifact.
- **No vendor-dunk language** — findings are stated clinically as measurements with evidence, never as
  a jab at a vendor.
- **Privacy rule** — `docs/private/` is gitignored and never referenced in any tracked file.

## Add a vendor pack in five steps

1. `mkdir packs/<vendor>` and write **`pack.yaml`** (vendor id + display name; the public-docs source
   label; optionally a `context_layer` block — omit it for two-condition mode). A pack may live outside
   this repo entirely: `--pack <path>`, or a bare name resolved against `--packs-dir` / `AIRE_PACKS_DIR`.
   See [`packs/sailpoint/pack.yaml`](packs/sailpoint/pack.yaml).
2. Add **`tasks/*.yaml`** — the common API tasks with spec-traceable `ground_truth`
   (endpoints/auth/scopes/params), each tagged with a `job_category` from the taxonomy
   ([ADR-0003](docs/adr/adr-0003-job-taxonomy.md)). Model them on
   [`packs/sailpoint/tasks/`](packs/sailpoint/tasks/).
3. Write **`specs.yaml`** — the spec pin (repo + SHA) and the `spec_finding` (availability + license).
4. Write **`docs-manifest.yaml`** — the public-docs pages per task (the cache is fetched, not
   committed).
5. **Validate, then run:** `python -m core --pack packs/<vendor> validate` (the answer-key quality gate),
   then `run --condition no-context` (and `public-docs`, and `mcp` if declared), then
   `python -m core compare <results dirs...>`.

## Running

```bash
pip install -r requirements.txt
pytest                                   # full suite: core engine + every pack's gate
pytest -m regression                     # just the SailPoint extraction-equivalence gate
python -m core --pack packs/sailpoint rebuild-report <results_dir>   # re-score archived runs
```

Live model runs (the `run` / `canary` commands) use the Claude Code CLI on a subscription and are out
of scope for the regression gate, which re-scores committed transcripts entirely offline.

## Status

**Cycle 1:** extracted the vendor-agnostic core, built the SailPoint reference pack from the frozen
repo's committed artifacts, and wired the regression gate that reproduces 73/68/93 exactly. See
[adr-0001](docs/adr/adr-0001-purpose-and-core-pack-architecture.md) and
[adr-0002](docs/adr/adr-0002-extraction-and-regression-gate.md).

**Cycle 2:** added the job-category taxonomy ([adr-0003](docs/adr/adr-0003-job-taxonomy.md)) and the
pack validator (`core/validate.py`), and confirmed packs load from any path (`--packs-dir`). Next: the
first external vendor packs, which live outside this public repo and plug in by path.

**Cycle 3:** added the category rollup + cross-vendor comparison renderer (`core/category.py`,
[adr-0004](docs/adr/adr-0004-category-cross-vendor-comparison.md)) — vendor-agnostic, so the engine can
render a `category × source` table from any set of packs' committed scores without naming any of them —
and made `public-docs` faithful to the machine reader ([adr-0005](docs/adr/adr-0005-public-docs-fetch-fidelity.md)):
an un-fetchable page (dead portal, empty SPA) injects nothing instead of erroring, so a vendor with
un-fetchable docs is still measured. The first external grids run against packs in a separate private repo.
