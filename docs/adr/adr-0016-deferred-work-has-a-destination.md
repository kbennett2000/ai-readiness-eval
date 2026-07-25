# ADR-0016: a deferred fix now has a destination, so "not queued" has to mean something narrower

## Status

Accepted. Adds no measurement, closes no hazard, and changes no field, schema or validator rule. Narrows
the vocabulary [ADR-0015](adr-0015-hazard-registry.md) established for `fix_queued_to`, now that the
premise it was written under — that this project has no queue — is no longer true.

## Context

ADR-0015 required every ungated hazard to name where its fix is queued, and allowed `"not queued"`, said
plainly, because at the time there was no queue to name: the cycle contract declared no issue tracker,
and a destination that does not exist cannot be cited. Twenty-six of the thirty-three ungated entries say
exactly that, and the file is honest about it.

What the honesty hides is that one phrase is doing three jobs at once — *this cannot be closed at all*,
*this was considered and declined*, and *nobody has decided* — and only the third was ever a defect a
registry could report. Read the entries and the difference is plain even though the field is not: the
privacy grep's entry says the half it cannot close is the half that matters, the ranking entry says an
ordering would be invented rather than measured, and several others say nothing about why at all. The
first two are rulings. The third is an omission wearing the same words.

The cycle contract now files deferred work as a GitHub issue in the repo that owns it (`CLAUDE.md`, "Fix
what is load-bearing; file the rest"). That is a workflow rule and it belongs there, not here. What
belongs here is its consequence for this file: the third meaning stops being unavoidable and starts being
a choice, so continuing to spell all three the same way would now be a decision to blur them.

### The move this decision exists to refuse

The tempting response is to open twenty-six issues, cite a number in every entry, and watch "26 queued
nowhere" fall to zero. That would improve the ratio the registry prints without changing one thing about
the world — the precise error ADR-0015 was built to catch, committed by the file that was built to catch
it. A structural limit does not become tractable because someone filed a ticket about it.

## Decision

**1. `fix_queued_to` must distinguish three states, in prose, using the field that already exists.**

- **Not closable** — a structural limit, not a defect. Say *why it is not closable*, not merely that it
  is not queued. The registry cannot list a hazard nobody recognized; that is a property of registries.
- **Considered and declined** — closable, but the cost is not judged worth it. Say so in those words, so
  a reader can tell a ruling from an omission.
- **Queued** — cite the destination: `Queued to ai-readiness-eval#N.`

**2. No field, no schema change, no validator rule.** `ALLOWED_FIELDS` in
[`core/tests/test_hazards.py`](../../core/tests/test_hazards.py) is closed and stays closed; the three
states live in the prose `fix_queued_to` already requires to be non-empty. A `state:` enum was considered
and rejected: it would make the registry gate assert that an author picked a word, which is not the same
as asserting the word is true, and this file's whole discipline is refusing coverage that reads stronger
than it is.

**3. An issue is filed only for the third state.** Filing against a structural limit is noise that makes
the tracker less trustworthy, not more.

**4. The workflow rule is cited, not restated.** It lives in `CLAUDE.md`. Two copies of one rule is the
drift mode this project already pays for elsewhere; this ADR records only what changes about the
instrument.

## Consequences

**The registry's headline number stops being comparable across this line.** "26 queued nowhere" was a
single fact. After triage it becomes three smaller facts, at least two of which are not defects, and the
count that remains — genuinely undecided hazards — is the only one that was ever worth reporting. That is
a smaller, truer number, and it will be less quotable.

**The triage pass is filed, not performed.** Sorting the twenty-six is exactly the class of work the new
rule says to file: it moves no published number. Doing it inside this cycle, beside the decision that
authorizes it, is how a decision gets graded by its own author. It is queued as an issue on the public
repo, with the mechanical trap recorded there — selecting the set by grepping the literal string `Not
queued` finds **25**, not 26, because one entry begins `Deliberately not queued:`.

**Two new hazards are recorded, and one of them is this decision's own.** The triage rule sorts by a
judgement an unattended run makes with no second opinion, and the two most expensive faults this project
has found — ADR-0013's endpoint dimension and ADR-0014's format failure — would **both have sorted as
"file it"** on the evidence available before they cost a cycle. That is not an argument against the rule;
it is the argument for writing it down where the next reader will see it.

**No measurement moves.** No scorer, parser, prompt, condition or fixture is touched. The frozen
reference tables reproduce unchanged.

### What this deliberately does not do

- **It does not make `fix_queued_to` checkable.** Unlike `gated_by`, which is resolved against the tree
  with `ast`, this field is prose and stays prose. An entry may cite an issue that was closed without the
  fix, and nothing will notice. That is recorded as a hazard rather than papered over with a `#\d+` shape
  check, which would prove the text looks like a reference and not that the reference is live.
- **It does not make the tracker a source of work.** No cycle is dispatched from an issue; an agent
  files and never assigns or closes. The tracker is where deferred work goes to be findable, not where
  the next cycle comes from.
- **It does not define the fix/file line more precisely than one sentence.** A sharper rule would be a
  taxonomy of defects, which is a thing to maintain and get wrong. The line is a judgement, the judgement
  is recorded in the PR, and a misfiled item is now filed rather than forgotten — recoverable at review
  time instead of decaying.
