# ADR-0015: a recorded hazard with no gate and no queue is a note that decays

## Status
Accepted. Adds no measurement and closes no hazard. Makes standing the practice that
[ADR-0010](adr-0010-ground-truth-round-trip-control.md) applied to one control — write down what the
instrument cannot do — by requiring every such note to declare a disposition.

## Context

Fourteen ADRs have accumulated **47 recorded instrument hazards**: places where a tracked decision
admits a measurement, gate, or control of this project can be blind, misleading, or is knowingly
unfixed. They are stated well and stated once, then buried in the ADR that discovered them. Nothing
listed them, nothing checked that a claimed guard still existed, and nothing noticed when a new ADR
added one.

**ADR-0011 named this decay mode in its own words**, about its own open item:

> Left there, "recorded as open work" is a note that decays.

It then built two things — a pin test and a card disclosure — to stop that one item decaying. The
practice was right and was never generalized. Two cycles later the cost was paid twice:

- **[ADR-0014](adr-0014-answer-format-repair.md)** repaired a parser failure that the previous
  cycle's report card had **predicted in writing** — a bare bracketed parameter "would register as a
  format failure rather than a wrong answer" — and left unfixed because it did not bite in those 100
  runs. It bit in the next pack, discarding six substantively correct answers.
- **[ADR-0013](adr-0013-spec-server-prefix.md)** found an `endpoint` dimension reported at **13.7%**
  when the model was in fact right in 98% of runs. The entire gap was one path segment. What caught it
  was a human remembering the suspect-instrument rule and reading transcripts, after the grid had
  already been paid for.

Both were foreseeable from something already written down. Neither was foreseen, because the writing
down was the end of the process rather than the start of one.

### What this must not become

A registry that lists a hazard and claims a guard is worse than no registry if the guard has since
been renamed away: it reports coverage that is gone, in a file whose whole purpose is to be trusted at
a glance. So the claims have to resolve, or the file is a wall of text with a table of contents.

## Decision

**1. One registry, and every entry declares a disposition.** [`docs/hazards.yaml`](../hazards.yaml)
carries every recorded hazard. Each entry is either:

- **`gated`** — `gated_by` names one or more tests that fire on the hazard; or
- **`ungated`** — `ungated_reason` says why no test does, and `fix_queued_to` says where the fix is
  queued, *including* "not queued", said plainly.

An entry declaring neither fails [`core/tests/test_hazards.py`](../../core/tests/test_hazards.py).
That is the whole gate, and it is deliberately the only thing an author is forced to think about.

**2. Every claimed test must resolve.** Each ref is `path.py` or `path.py::test_name`, checked against
the file on disk with `ast` — the file exists and defines that top-level function. This is the "no
unlinked claims" working agreement applied to a file that consists entirely of claims. The resolver is
itself proven to reject a dead link, because a link checker that has never failed is not known to work.

**3. `drift_pin` is a property of an ungated hazard, and never a substitute for a disposition.** This
is the load-bearing distinction and the reason the file needs a vocabulary rather than a checkbox.

A test can fire on a hazard in two very different ways:

- **gated** — the test prevents the hazard from occurring or from regressing silently.
- **drift-pinned** — the test fires if the hazard's *state* is edited, while the hazard itself stays
  live.

ADR-0011's single OAuth example is the type case. `test_prompt_contract.py` pins the example string, so
an edit fails the suite. That pin does not remove the bias every measured model has already read — it
makes changing it a deliberate cohort re-baseline instead of a silent edit. Recording that as "gated"
would be true about a test and false about the world.

So a `drift_pin` may only appear on an `ungated` entry, it is never consulted when deciding whether an
entry is adequately declared, and
`test_a_drift_pin_never_satisfies_the_gated_requirement` asserts exactly that by feeding the validator
a synthetic entry that offers a pin and nothing else. Five entries are drift-pinned today; all five are
still ungated, and the registry says so.

**4. Omission is not an option.** Every ADR on disk appears in an entry or is named in
`adrs_with_no_recorded_hazard`. A future ADR cannot add a hazard and stay silent, because silence is
indistinguishable from oversight — which is the failure mode that cost ADR-0014 a cycle.

**5. Scope is instrument hazards, not backlog.** Included: recorded ways a measurement, gate, or
control can be wrong, blind, or silently misleading. Excluded, and stated as excluded in the file:
deferred features such as ADR-0004's richer cross-vendor views and ADR-0006's `cmd_run` refactor. A
registry that mixes "this number may be wrong" with "this would be nicer" reads as neither.

## Consequences

**The picture the registry produces is not flattering, which is the point.** Of 47 hazards, **14 are
gated and 33 are ungated** — 26 of those 33 queued nowhere at all, and two more carried as follow-up
work against no named cycle. That ratio was always the case; it had simply never been in one place. A
reader can now see it without reading fourteen ADRs.

**Three separate ADRs turn out to be queued behind one trigger.** ADR-0008's missing spelling for an
absent version, ADR-0011's single OAuth example, and ADR-0014's flow-sequence example are all prompt
changes, all blocked for the same reason — a prompt change cannot be re-applied to archived
transcripts, so it makes every previously measured vendor incomparable — and all waiting on the same
next deliberate cohort re-baseline. Three notes in three files read as three small deferrals. In one
file they read as one accumulating change that grows more expensive to keep deferring.

**No measurement moves.** No scorer, parser, prompt, condition or fixture is touched. The frozen
reference tables reproduce unchanged, and the full suite grows from 236 to 430 tests, the addition
being this registry's own checks over 47 entries and 38 test references.

**A renamed test now breaks the build.** Any refactor that renames a cited test must update the
registry, which is the mechanism that keeps the file true. Verified by breaking each rule on purpose —
a dead ref, a missing `fix_queued_to`, a hazard downgraded to `gated` on the strength of a drift pin,
and a new ADR added silently — and confirming each fails.

### What this deliberately does not do

- **It does not fix any hazard.** Every entry describes the same state of the world as before. The
  registry reports; it does not repair. The one hazard whose disposition changes this cycle changes in
  a **separate PR**, precisely so that reporting state and altering the instrument sit in different
  reviews.
- **It cannot find a hazard nobody wrote down.** The registry lists what somebody recognized and
  recorded. An unrecognized blind spot is exactly as invisible as it was before. This is a decay gate,
  not a discovery method, and reading a complete-looking registry as a complete list of what can go
  wrong would be the same error as reading a green round-trip as proof a key is right.
- **It does not grade a hazard's severity.** There is no priority field. Ranking 33 ungated hazards
  would invent an ordering no evidence supports, and the fields that matter — is anything watching
  this, and what is it waiting on — are already required.
- **It adds no `core/` module and no CLI command.** The validator lives in the test that enforces it.
  A `hazards` subcommand mirroring `validate` and `roundtrip` is an obvious extension and is not
  load-bearing for this slice.
- **It does not enforce that an ADR's hazards are *completely* transcribed.** Rule 4 forces an ADR to
  be accounted for, not to be exhaustively mined. Grepping ADR prose for hedging words and demanding a
  row per match was considered and rejected as too noisy to survive contact with real writing.
