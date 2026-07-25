# CLAUDE.md

<!-- Everything above the PROJECT CONTEXT marker is inherited from project-template.
     Do not edit per-project. Project-specific content is appended below the marker
     by the factory generator from the new-project issue. -->

## How work runs here

- Work is executed one cycle at a time by a headless `claude -p` run — no persistent session, and no human watching the run.
- Each cycle starts fresh. Current state lives in `HANDOFF.md`, the ADRs under `docs/adr/`, and this file — not in remembered conversation. Read them at the start of every cycle.
- End each cycle by updating `HANDOFF.md` so the next cycle can pick up cleanly.

## The cycle contract

**Never pause or wait for a human.** No one is watching the terminal. You must never end by printing a question and stopping. Every cycle ends in exactly one of the two terminal states below, then exits.

**Do the work. Don't ask permission.** When files change, you ALWAYS — without asking, every time:
1. Work on a branch, never `master`/`main`.
2. Commit and push.
3. Open a PR for human review/merge.

Committing, pushing, and opening a PR are never optional and never require confirmation. A human reviews and merges the PR; you do not close the issue.

**Decide, don't stall.** If something is uncertain but you can proceed, make the reasonable choice and note it in the PR description. "Should I also do X?" is not a blocker — do the obvious thing or note it and move on. Non-blocking uncertainty never stops a cycle.

**Stopping early is rare and only for true blockers.** Stop only when you are missing information you genuinely cannot proceed without. Stopping means: record the blocker in the PR description (or, if no PR, the cycle report) and exit. This is recording, not asking — you never wait for a reply. A destructive or unwalkbackable action (force push, history rewrite, deleting branches/data) counts as a blocker: do not do it; record it and stop.

## End of cycle — the PR is the record

**No issue tracker.** This project uses no GitHub issue tracker — the kickoff prompt and the PR
description are the record. There is no "update the issue" / "comment on the issue" step; do not look
for an issue number. Before you exit, run exactly one case:

- **Completed** (files changed): open a PR against `main` (unmerged) whose description carries the full
  cycle report — what changed, why, evidence links, and any non-blocking decisions made. A human reviews
  and merges.
- **Blocked** (missing info you cannot proceed without): state the blocker plainly in the cycle report
  and exit. Recording, not asking.

## Conventions

- ADR-first: significant decisions get an ADR in `docs/adr/` before implementation.
- Keep changes small and reviewable.

<!-- ===== PROJECT CONTEXT (appended per repo — do not add content above this line) ===== -->

## What this project is

`ai-readiness-eval` measures how accurately an AI coding model completes a software vendor's common API
tasks, across context conditions, scored deterministically against spec-traceable ground truth. It is the
vendor-agnostic generalization of the method proved in `sailpoint-proof-of-concept` (now frozen): one
model, one transport, N tasks scored on six dimensions (endpoint / method / version / auth / scopes /
params), under **no-context**, **public-docs**, and an optional spec-derived **context-layer** condition.
The finding is the *gap between conditions* — how much good context is worth — not any single number.

## Core / pack architecture

- **`core/`** is vendor-agnostic. It carries no vendor string, path, or task assumption (a guard test
  proves it): the conditions interface + registry, the prompt contract + answer-block parser, the
  deterministic scorer + normalization rules, sterile per-run invocation, runtime tool discovery,
  transcript tool-discipline assertions, the resumable runner, `rebuild-report`, canaries, the
  ground-truth round-trip control, and the model-pin guard. Vendor specifics reach it only through a
  loaded `Pack`.
- **`packs/<vendor>/`** holds everything vendor-specific: `tasks/*.yaml`, `specs.yaml` (spec source +
  pinned SHA + license finding), `docs-manifest.yaml`, `pack.yaml` (vendor config), an optional
  context-layer config, and any imported fixtures.
- **Two-condition mode is first-class.** A pack with no context layer runs `no-context` vs `public-docs`
  and still produces a full report. Measuring the gap must never require building the fix.
- **Spec availability + license are scored findings.** Every pack's `specs.yaml` records whether a
  machine-readable spec exists, where, under what license, and whether it permits the vendoring this
  method prefers. A vendor with no public spec fails that dimension explicitly.

## Working agreements

- **ADR-first.** Every load-bearing decision gets a numbered ADR in `docs/adr/` before or with the
  implementation. Sequential numbering; superseded ones are marked, not deleted.
- **Vertical slices.** Each cycle ships the smallest reviewable, load-bearing unit — working end-to-end,
  however narrow.
- **Plan, then execute.** Present a plan at the start of each cycle before writing code.
- **Test-heavy.** Every functional unit ships with tests.
- **No unlinked claims.** Every factual claim in a tracked doc links to the artifact that backs it — a
  task file, an ADR, a results directory, or a spec reference.
- **No vendor-dunk language.** Findings are stated clinically as measurements with evidence links, never
  as a jab at any vendor. "The docs left scopes worse than cold (22% → 2%)" is a measurement; a sneer is
  not allowed anywhere in tracked files.

## Privacy rule (hard requirement)

`docs/private/` holds business/strategy material and is gitignored. Never commit it, never quote or
reference its contents in any committed file, ADR, commit message, or code comment. Before every push,
verify with `git ls-files | grep -i private` (must return nothing).

## Status

- **Cycle 1.** Extracted the harness into a vendor-agnostic `core/`; built the SailPoint reference pack
  from the frozen repo's committed artifacts; wired a regression gate that reproduces the frozen
  73/68/93 tables exactly. See ADR-0001, ADR-0002.
- **Cycle 2.** Added the job-category taxonomy (ADR-0003) and the pack validator (`core/validate.py`),
  retro-mapped the reference pack, and confirmed packs load from any path (external packs plug in by
  `--pack`/`--packs-dir`). Next up: the first external vendor packs, which live outside this public repo.
- **Cycle 3.** Added the category rollup + cross-vendor comparison renderer (`core/category.py`,
  ADR-0004): vendor-agnostic, renders a `category × source` table from any set of packs' committed
  scores, naming none of them. The first external grids run against packs in a separate private repo.
- **Cycle 4.** Built the factory (`core/factory.py` + a `factory` next/run/status command, ADR-0006):
  an unattended dispatcher that works a ranked queue through recon→validate→roundtrip→anchoring→mock→
  canary→grid→compare→card, every stage a hard gate that blocks-with-reason. It reuses the existing
  per-condition engine in-process, names no vendor, and makes no live vendor-API call. Pack authoring
  stays external and anchoring-gated (auto-authoring deferred). The real queue + packs live in the
  private repo.
- **Cycles 5–6.** Driven from the private packs repo; the public core gained the fetch-fidelity rulings
  those grids forced — a bot-gated docs host is a fetch policy (ADR-0007), an unversioned API is scored
  on whether the model knows it (ADR-0008), and a 2xx with an empty body is a fetch failure rather than
  a snapshot of an empty page (ADR-0009).
- **Cycle 7.** Made the ground-truth round-trip control a standing gate (`core/roundtrip.py`, a
  `roundtrip` command, and a `roundtrip` stage between `validate` and `anchoring`; ADR-0010). Every pack
  must score each task's own answer key against itself, perfectly, before any grid burns; the suite
  enforces it over every pack on disk, not just packs the factory happens to dispatch. The ADR records
  what the control cannot do: an answer key always matches itself, so it catches an *unscoreable* key,
  never a *wrong* one. The gates are now declared as data (`factory.GATES`) so `STAGES` and the
  dispatcher cannot drift.
- **Cycle 8.** Closed the auth-scoring hole that gate reported (ADR-0011). `auth_flow` recognized only
  bearer and client-credentials, so ground truth naming neither scored 1.0 against any answer that also
  named neither — and on a task whose prose *denies* OAuth, the substring matcher credited the
  documented-wrong answer. `scorer._AUTH_STYLES` now names five login styles in an argued precedence
  order, and an unlisted style **blocks** `roundtrip` instead of drawing a note: no dimension scores
  unless it can be positively tested. Scorer-only, so the two affected packs re-scored from archived
  transcripts at zero model spend; the frozen 73/68/93 gate and every OAuth-shaped pack are byte-identical.
  The prompt contract's single `auth_flow` example is recorded as open work for the next cohort re-run.
- **Cycle 9.** Driven from the private packs repo, which measured its first vendor whose flagship
  publishes a real public OpenAPI document. That forced one core ruling: **where a spec ends its server
  URL is not where the vendor's docs start the path** (ADR-0013). An OpenAPI 3 `servers[].url` (or a
  Swagger 2 `basePath`) may absorb any prefix of an endpoint's address, and the anchoring gate had
  assumed the spec's leftover path was the path a caller writes — so a pack was forced to adopt its
  vendor's spec notation even when the vendor's own documentation, which is what the measured model has
  read, drew the base URL elsewhere. `_index_operations` now accepts a path written from any point
  inside the declared prefix. The gate widened; no scorer rule changed and no dimension got easier.
  Found the expensive way: a first grid reported an endpoint dimension at 13.7% when the model was in
  fact right in 98% of runs, and the whole gap was one path segment. The round-trip control (ADR-0010)
  structurally cannot catch this — an answer key written in the wrong notation still matches itself —
  so what caught it was the suspect-instrument rule plus reading the transcripts.
- **Cycle 10.** Closed the format-failure hole the previous cycle reported rather than bundled
  (ADR-0014). A model naming an indexed API parameter inside the single-line flow sequence **the prompt
  contract itself demonstrates** produces invalid YAML, and the parser discarded the entire answer —
  endpoint, method, version and auth along with the parameter list. One narrow repair now runs, only
  after YAML has already failed, only on the two list-valued keys, with quote-aware splitting and an
  item guard that abandons the repair rather than guess: both dimensions it can reach are
  containment-scored, so a careless split could only ever manufacture a score *upward*, and that
  counterexample is pinned as a must-not-repair test. Repairs are counted and the repaired text is
  archived. Parser-only, so the whole cohort re-scored from archives at **$0, no model runs**; 7 of 826
  archived runs were rescued and the frozen 73/68/93 reproduces — though only because the one rescued
  reference answer scored 6/6, which the ADR records as luck rather than safety. The fix moved cells
  **down** as well as up, which is the evidence it repairs an instrument instead of inflating a result.
  Changing the prompt's example is the better permanent fix and is deferred to the next cohort re-run,
  because it cannot be re-applied to archives.
