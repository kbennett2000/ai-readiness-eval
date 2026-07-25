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
3. Open a PR **against `main`** for human review/merge — never against another cycle's branch, even when this work builds on one.

Committing, pushing, and opening a PR are never optional and never require confirmation. A human reviews and merges the PR; you never merge your own, and you never assign or close an issue — including one you filed this cycle.

**Decide, don't stall.** If something is uncertain but you can proceed, make the reasonable choice and note it in the PR description. "Should I also do X?" is not a blocker — do the obvious thing or note it and move on. Non-blocking uncertainty never stops a cycle.

**Fix what is load-bearing; file the rest.** Fix in this cycle only what affects a published number or could put a wrong claim in front of a vendor. Everything else — hygiene, refactors, conventions, cleanups, anything you noticed in passing — is filed as a GitHub issue in the repo that owns it, and the cycle continues. Filing is not deferring the decision; the issue is the decision, recorded where it cannot decay. When you cannot tell which side of the line something sits on, ask whether a reader of a published number, or a vendor reading a card, would be misled by leaving it: if yes, fix it now; if no, file it and move on.

**Stopping early is rare and only for true blockers.** Stop only when you are missing information you genuinely cannot proceed without. Stopping means: record the blocker in the PR description (or, if no PR, the cycle report) and exit. This is recording, not asking — you never wait for a reply. A destructive or unwalkbackable action (force push, history rewrite, deleting branches/data) counts as a blocker: do not do it; record it and stop.

## End of cycle — the PR is the record, the tracker is the backlog

**The PR is the record; issues are only the backlog.** No cycle is dispatched from an issue number — the
kickoff prompt and the PR description remain the record of what this cycle did, and there is no "update
the issue" / "comment on the issue" step. The GitHub tracker holds one thing: work this cycle
deliberately did not do. You file it; the operator assigns it. Before you exit, run exactly one case:

- **Completed** (files changed): open a PR against `main` (unmerged) whose description carries the full
  cycle report — what changed, why, evidence links, any non-blocking decisions made, and every issue you
  filed this cycle, by repo and number. A human reviews and merges.
- **Blocked** (missing info you cannot proceed without): state the blocker plainly in the cycle report
  and exit. Recording, not asking.

Filing an issue is never a third exit. Work you chose to defer is not a blocker, and a cycle that filed
issues and changed no file is still Blocked or Completed on the evidence above — never on the filing.

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
- **Cycle 11.** Built the hazard registry (`docs/hazards.yaml` + `core/tests/test_hazards.py`,
  ADR-0015). Fourteen ADRs had accumulated **47 recorded instrument hazards**, each stated once and
  then buried in the ADR that found it; nothing listed them, checked that a claimed guard still
  existed, or noticed when a new ADR added one. ADR-0011 had named that decay mode in its own words —
  "recorded as open work" is a note that decays — and the cost was paid twice before it was
  generalized: ADR-0014 repaired a failure the previous card had predicted in writing, and ADR-0013
  found a dimension reported at 13.7% when the model was right in 98% of runs. Every entry now declares
  **gated** (naming tests that are resolved against the tree with `ast`, so a renamed test breaks the
  build) or **ungated** (naming a reason *and* where the fix is queued, including "not queued", said
  plainly). `drift_pin` — a test that fires when a live hazard's *state* is edited, as the prompt
  contract's pinned example does — is a property of an ungated entry and can never satisfy the gated
  requirement; a test asserts that, because recording a drift pin as a gate would be true about a test
  and false about the world. Every ADR must appear in an entry or be declared hazard-free, so a new one
  cannot add a blind spot silently. **Reports state only — no scorer, parser, prompt or fixture is
  touched, and the frozen 73/68/93 is unmoved.** The picture is not flattering, which is the point:
  **14 of 47 gated, 26 queued nowhere**, and ADR-0008/0011/0014's three prompt items turn out to be one
  accumulating deferral behind a single trigger. Each rule was verified by breaking it on purpose.
- **Cycle 12.** Adopted the triage rule that decides what a cycle fixes and what it files (ADR-0016):
  fix in-cycle only what affects a published number or could put a wrong claim in front of a vendor;
  everything else is filed as a GitHub issue and the cycle continues. This **reverses** the contract's
  standing "no issue tracker" rule, which was written when there was no queue to name — and that absence
  is exactly what ADR-0015 had to encode as `fix_queued_to: "not queued"` on 26 of its 33 ungated
  entries. With a destination, that phrase stops being unavoidable and starts being a claim, so ADR-0016
  narrows it to three distinguishable states while **changing no field, schema or validator rule**. It
  refuses the flattering move on the record: opening 26 issues so every entry can cite one would improve
  the ratio the registry prints without changing the world, which is the error ADR-0015 exists to catch.
  The prospect guard also grew a second scan — **ref names, not just tracked files** — after a
  world-visible branch was found naming a measured prospect that `git ls-files` structurally cannot see.
  No scorer, parser, prompt or fixture is touched; the frozen 73/68/93 is unmoved.
