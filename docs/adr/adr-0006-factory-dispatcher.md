# ADR-0006: the factory — an unattended, gated pipeline dispatcher

## Status
Accepted

## Context
Through cycle 3, every grid was driven by hand: an operator issued `run` per condition, watched it, then
hand-wrote the report card. That does not scale to a ranked pipeline of many vendors, and hand-transcribing
numbers into a card invites error. We want an unattended dispatcher that works a ranked target queue
through the same fixed pipeline and stocks the drawer with DRAFT report cards — **producing unattended,
shipping gated**: the factory fills the drawer; nothing leaves it toward a prospect without human review.

The load-bearing risk is that "automate pack production" is misread as "let the machine invent ground
truth." A model asked to write a vendor's endpoints/scopes/params would fabricate exactly the answer key
the method scores against — the cardinal sin ("never score a guess"). So the automation boundary must be
drawn deliberately.

## Decision
Add `core/factory.py` and a `factory` subcommand (`next` | `run` | `status`). The dispatcher is
vendor-agnostic like the rest of `core`: it names no vendor. The ranked `queue.yaml` (which names targets)
and the packs it drives both live **outside this repo** and reach the dispatcher only as a queue path and a
packs dir.

**The pipeline is the deterministic spine; authoring feeds it.** `run_pipeline` drives one target through:

    recon → validate → anchoring → mock → canary → grid → compare → card → advance

Each stage is a **hard gate**. On failure it sets the target's `status = blocked` with a written reason and
stops — the factory never guesses past a gate, never scores a guess, and never reduces N to fit a window
(it waits/pauses on throttle instead). Authoring a pack's tasks + anchored ground truth is **not** the
factory's job; that is an external human/agent step whose output must clear the `validate` and `anchoring`
gates before any grid burns. The gates:

- **recon** — the pack's `specs.yaml` records a scored spec-availability finding with a license. A spec
  marked available (`yes`/`partial`) must be vendored + licensed, or the pack is incoherent and blocks. A
  pack with **no** machine-readable spec is not blocked — it runs in doc-anchored mode and the
  spec-availability finding leads its card (ADR-0005 lineage).
- **validate** — the shared schema (`core/validate.py`) is green.
- **anchoring** — every `spec_ref` resolves to a real operation in the vendored spec (operationId, with
  method+path agreeing); every `doc_ref` URL appears in the docs-manifest. This is the "never score a
  guess" enforcement in code.
- **mock** — a `--mock` run writes a report (plumbing proof, no model).
- **canary** — the existing sterile/control pre-flight gate (`_preflight_gate`) proves sterility before any
  burn; run once, then resumed conditions skip it.
- **grid → compare → card** — reuses the existing per-condition engine (`cmd_run`, resumable,
  transcript-asserted), joins the conditions, and writes a `REPORT.scaffold.md` carrying the
  `DRAFT — UNREVIEWED, NOT FOR OUTREACH` banner with the headline table, spec-availability finding, and
  invented-endpoints exhibit computed (never hand-transcribed). The executor fills the prose findings.

The dispatcher reuses the existing `cmd_*` handlers in-process (via a built `argparse.Namespace`) rather
than re-implementing the run loop or refactoring the monolith — the seam is small and covered by the
mock-pack pipeline test.

**Auto-authoring packs via sub-agents is deferred** to its own future cycle, revisited only after several
packs exist as reusable patterns. Until then, an un-authored target blocks with a written reason.

## Safety rails (restated)
- **No live vendor-API calls, ever.** The method is read-only: no tenants, no credentials, no vendor
  endpoints are called. The factory scores what a model *says*, never executes it.
- **No vendor names in the public repo.** The dispatcher and the queue schema are name-free; the guard test
  (`test_core_no_vendor`) fails if a prospect name lands in `core/` or any tracked public file. The real
  queue and packs live in the private repo.
- **Block, don't guess. Pause, don't degrade.** Every gate records a reason and moves on; N is never reduced
  to fit a window.

## Consequences
- The whole spine is exercisable offline: `factory ... --provider mock` runs recon→…→card with the mock
  model, so `core/tests/test_factory.py` covers carding a clean pack and blocking-with-reason on a broken
  one without a model burn.
- A card is never hand-transcribed: its numbers and invented-endpoint exhibit are generated from the graded
  runs; only the plain-English findings are authored.
- The operator surface is three commands (`next` / `run` / `status`) documented in the private README; the
  queue is readable at a glance without touching dispatcher code.

## Alternatives considered
- **Factory auto-authors ground truth via sub-agents** — rejected for this cycle: an LLM inventing
  endpoints/scopes is the "scored guess" the method forbids, and validation catches shape, not correctness.
  Deferred until packs exist as patterns.
- **Shell out to `python -m core run` per condition** — rejected in favor of in-process reuse: same engine,
  no subprocess/quoting fragility, and the return codes/exceptions are handled directly as gate outcomes.
- **Refactor `cmd_run` into a library function first** — deferred: the Namespace seam is small and tested;
  a larger refactor is not load-bearing for this slice.
