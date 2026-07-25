# ADR-0010: a task that cannot score its own answer key is an instrument, not a measurement

## Status

Accepted. Refines [ADR-0006](adr-0006-factory-dispatcher.md) (adds a gate to the factory pipeline).

## Context

A pack's grid came back with `endpoint` and `method` both reading **0.00 — across every task and both
conditions**. A dimension that is uniformly empty is a suspect instrument before it is a vendor
finding, so the question was which half of the harness was at fault: the scorer, or the answer key.

Answering it took an ad-hoc script written after the grid had already cost $7.25. The script scored
each task against an answer equal to its own ground truth and required 1.0. All ten passed. That
cleared the scorer and pointed at the answer key, where the fault was: ground truth had baked a
deployment path prefix into every endpoint, while the vendor's guide treats that prefix as part of the
base URL and writes every path relative to it. The model had reproduced the documented paths verbatim
and been scored zero for it. The archives were re-scored with `rebuild-report` at no additional model
spend and the headline moved from 1%/34% to 4%/42%.

The control worked. The problem is that it was improvised, after the money was spent, by someone who
happened to remember the suspect-instrument rule. Nothing made it repeatable and nothing made it
mandatory.

Two facts shaped what the control should become:

- It is **cheap** — no model, no network, milliseconds per pack. There is no reason to run it once
  rather than always.
- It is **weaker than it looks**, in a way that must not be papered over. See below.

## Decision

**A pack must score each task's own ground truth against itself, perfectly, before any grid runs.**
This is `core/roundtrip.py`, the `roundtrip` stage in the factory pipeline, and a `roundtrip` CLI
command. The pipeline is now:

    recon → validate → roundtrip → anchoring → mock → canary → grid → compare → card → advance

1. **It is its own gate, not part of `validate`.** The obvious alternative was to fold it into the
   existing schema check, and the earlier working note proposed exactly that. Rejected on two grounds.
   The failures mean different things and want different operator responses: `[validate]` says a task
   file is the wrong shape, `[roundtrip]` says a task is unscoreable even when correctly shaped —
   which is precisely the distinction the incident above turned on. And `core/validate.py` is a pure
   schema layer; folding would make the validator import the scorer it is meant to be independent of.

2. **Both paths are checked.** The *direct* path builds an answer object straight from ground truth
   and scores it. The *text* path serializes that same answer into an answer-summary block, parses it
   back through the contract, and scores the result. The direct path checks the scorer; the text path
   checks that the documented answer key is expressible in the contract at all — that a model
   returning exactly the right answer would be scored rather than counted a format failure.

3. **The control emits the ground truth's own auth prose, verbatim.** The `--mock` provider replaces
   it with a canonical phrase to avoid `": "` sequences in prose. A control that did the same would be
   testing a string it invented rather than the answer key the pack documents, so it does not:
   `yaml.safe_dump` quotes the prose correctly and the raw text round-trips. Both callers now share
   one serializer (`answer_block.render_block`) so the mock provider cannot drift from the gate.

4. **A perfect score means every applicable dimension is exactly 1.0, and n/a is not a failure.** A
   dimension reads n/a for documented reasons — ground truth listing no scopes, or no parameter marked
   required — and failing those would block every pack with a scopeless task. They are reported, not
   counted against.

   Shapes that *score* but measure less than they appear to are surfaced as **non-blocking notes**:
   a `key_parameters` list with nothing marked `required: true`, and ground truth naming no auth
   concept the scorer recognizes. The second was found by running this control: the scorer knows
   bearer and client-credentials, so a pack whose vendor authenticates some other way — an API key,
   a session identifier — scores 1.0 on `auth_flow` against any answer that also names neither. The
   dimension reads as applicable and is close to free. That is a scorer gap, and the fix belongs in
   the scorer rather than in a pack workaround, so the control reports it instead of blocking on it.

5. **The gate never raises.** `check_pack` converts any per-task explosion into a written problem,
   because the dispatcher's gate loop has no exception handling and an unattended run must block with
   a reason rather than crash without one.

6. **The suite enforces it too, not only the factory.** `core/tests/test_pack_roundtrip.py` discovers
   packs by glob — including `AIRE_PACKS_DIR`, where external packs live — so a pack nobody has
   dispatched yet, or one edited after it was carded, is still covered.

## What this does not prove

An answer key equal to itself always matches itself. **This control cannot detect a wrong answer
key.** It would have passed the pack that produced it — every path carried the same mistaken prefix on
both sides of the comparison, so every task scored 1.0. Anyone reading a green `roundtrip` as evidence
that a pack's ground truth is *correct* has misread it.

What it does prove is narrower and still worth having:

- Every task is **scoreable** — the documented answer key can reach 1.0 and survives the answer-block
  contract's serialize→parse boundary.
- The scorer treats ground truth and answers **symmetrically**. This is true by construction today,
  which makes the control a tripwire rather than a strong test: its value is that it fires the moment
  anyone adds a normalization rule that applies to the answer side and not the ground-truth side. Such
  a rule would drive a dimension to 0.00 for every pack and read exactly like a finding about vendors.
- The scorer is **excluded as a suspect** mechanically and in advance, so when a dimension does read
  0.00 across the board, the remaining explanations are the answer key or the model.

## Consequences

- Anchoring, not this gate, remains the "never score a guess" enforcement. The two are complementary:
  anchoring proves ground truth is traceable to something durable, the round-trip proves it is
  scoreable. Neither proves it is right; only a human reading the source does that.
- **A `roundtrip` failure on the reference pack is a stop-and-record, never a ground-truth edit.**
  Editing `packs/sailpoint/**` to satisfy a gate is the one move that could shift the frozen
  73/68/93 numbers, and a gate that can be satisfied by editing the thing it measures is not a gate.
- `STAGES` and the dispatcher can no longer drift: the gates are declared as data (`factory.GATES`)
  and a test asserts they are the leading prefix of `STAGES`. The previous code inlined the order
  inside `run_pipeline`, with `validate` spliced into a loop over the other two gates.
- The reference pack (11 tasks) and the synthetic fixture (3 tasks) pass on both paths, so the gate
  blocks nothing that works today. The full suite, including the frozen 73/68/93 regression gate,
  passes unchanged.
