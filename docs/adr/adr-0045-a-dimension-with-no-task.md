# ADR-0045 — A dimension with no task, and a channel for a value class that is not one

**Status:** Accepted
**Date:** 2026-08-02
**Follows:** ADR-0010 (the round-trip control and what it cannot prove), ADR-0044 (the second
answer contract), ADR-0021 / ADR-0041 (a tolerance is granted to a pack that asked in writing).
**Refs:** issue #81.

## Context

The `docs` cohort's first measured pack declares three dimensions and exercises **two**.
`firmware_version` reads `n/a` on every task in both conditions, so its published overall is the
mean of two dimensions while the contract, the card and the results table all say three. The
**compatibility pairing** — a designed feature of ADR-0044 — is `None` on every run of the pack
that motivated it, because no task declares both halves.

Every gate passed.

- `roundtrip` (ADR-0010) asks whether each **task** can score *something*, and blocks a task whose
  every dimension is n/a. It never asked the converse: does every **dimension** have a task?
- `validate` reads task files against a schema that cannot see the contract's dimension set.
- The report renders `n/a` honestly, which is correct and easy to read past.

This is the vacuous-green shape this project keeps closing, one level up from where the existing
guards sit. `test_docs_truncation.py::test_the_sweep_enumerates_packs` exists because "a
parametrized sweep over an empty list is a green run that checked nothing". A dimension with no
task is the same fault about a **column** instead of a **row**, and it is harder to see: the cell
reads `n/a`, a word this project uses legitimately and often.

## Decision 1 — every declared dimension must have a task, or a pack must say why in writing

`roundtrip.check_pack` gains a pack-level `(dimension-coverage)` control, beside the
`(answer-surfaces)` one and for the same reason: it is a fact about the suite, not about a task, and
it must block **before a grid burns** rather than be discovered in a card. Placing it there makes it
reusable by construction — it fires in the factory's `roundtrip` gate *and* in the suite-wide sweep
that round-trips every pack on disk, not only packs the factory happens to dispatch.

A dimension is **exercised** when at least one task's `TaskControl` scores it. A pack may declare
one unexercised in `pack.yaml`:

```yaml
unexercised_dimensions:
  firmware_version: "No task declares a controller firmware revision, so this dimension is n/a on
                     every run and the pairing figure has no applicable task. …"
```

**A written reason, never a boolean** — the `short_text_ok` (ADR-0021) and
`auth_flow_not_corroborable` (ADR-0041) bargain. "This vendor's publications state a software
version for these capabilities and never a firmware revision" is a legitimate finding a reviewer can
check and disagree with; silence is not. The reason is **echoed in the report**, because a
declaration filed where nobody reads it is the decay mode ADR-0015 exists to catch.

**A stale declaration blocks too**, and that direction matters more than it looks: a pack that later
adds the missing task keeps a `pack.yaml` saying it has none, and the next reader believes the file.
So does a blank reason, and so does a name the contract does not declare — the unknown-category
check `validate` already applies to `na_categories`, pointed at dimensions.

## Decision 2 — the severity is cohort-scoped, and it was chosen by measurement

Run over every pack on disk for the first time, this gate found a declared dimension with no task in
**13 of 18 packs**:

| cohort | packs | with an unexercised dimension | which one |
|---|---:|---:|---|
| api | 17 | 12 | `required_scopes` (11), `auth_flow` (1) |
| docs | 1 | 1 | `firmware_version` |

That is a far wider condition than issue #81 described, and it is a finding in its own right: **more
than two thirds of this project's published overalls are means over fewer dimensions than their
contract declares, and nothing said so.** Blocking every cohort would have failed twelve
already-published packs over a pre-existing condition this cycle is not repairing, so:

- **`docs` blocks.** It has one measured pack and the next is being authored; there is nothing to
  grandfather.
- **`api` warns**, naming the dimension, with the count recorded here and each pack filed.

The split has a second axis, and it is the more important one. **Coverage** is cohort-scoped;
**a declaration that is wrong** — unknown name, blank reason, contradicted by a task — blocks in
every cohort. Those exist only because a pack opted in, so no existing pack is touched, and a false
statement in a pack file is worse than the silence it replaced.

This is the same shape `check_truncation` took last cycle, and it is worth naming as a pattern: a
gate that finds a widespread pre-existing condition either lands advisory with a count, or it lands
blocking and gets switched off.

## Decision 3 — an unscored observation channel, so a value class can be evidence without being a score

A vendor may put its load-bearing values in a class the contract has no dimension for. Scoring it
would mean widening a pre-registered instrument after seeing that vendor's material, which is the
failure pre-registration exists to prevent. Not recording it at all means a future revision has no
evidence base and must be argued from intuition.

So: `unscored_observations`, a `{key: written reason}` declaration that adds a key to the docs answer
block and a field to `TaskScore.exhibit`. It generalises what ADR-0044 already does with
`publication` — recorded per run, never scored, and the misattribution check got a mechanical signal
for free.

**The guarantee is structural, not asserted.** A declared key is not in `contract.dimensions`, so no
aggregate, no overall, no rendered table and no comparison can reach it; a test asserts the score is
byte-identical whether the observation is right, wrong or absent. Three refusals are pinned:

- a name colliding with a dimension or a contract key **raises** — a silent overwrite would make one
  stand in for the other, and both directions are invisible;
- a key with no written reason **raises** — a value class arriving in the archive without anyone
  having decided it should;
- an **undeclared** key a model volunteers is **ignored**, and an observation alone does not rescue a
  block from format failure, or a pack could improve its own format-failure rate by declaring a key.

**A pack declaring none gets the base contract object itself** — identity, not a copy — and renders
the frozen prompt byte for byte. That is ADR-0014's rule applied: a prompt cannot be edited
retroactively, because the archive stops being an answer to the prompt that produced it. This
channel had to be additive or not exist.

## Decision 4 — the docs contract's dimension set was derived from one vendor's shape, and it is not revised here

Two of the three docs dimensions (`firmware_version`, `software_version`) presume a **programmable
device**. The cohort's second target has no such thing anywhere on its surface — recon confirmed it
empirically, not by assumption — so it could exercise at most one of three.

That is evidence about the **instrument**, not about the vendor. ADR-0044 was written before its
first pack's tasks precisely so the answers could not shape it; it was not, and could not have been,
written before knowing what kind of vendor came first.

**The contract is not revised in this cycle, and this ADR forecloses revising it on one vendor's
material.** A revision must be argued from **at least two vendors' measured material**, or it is
just whichever target arrived next reshaping a pre-registered instrument — and the unscored channel
in decision 3 is what makes that evidence collectible in the meantime. Recorded as an ungated
hazard with a queued fix, because "a revision may be warranted" is exactly the note that decays.

## Consequences

- `unexercised_dimensions` and `unscored_observations` join `na_categories` as pack-level
  declarations; both are optional and both cost a written reason.
- The already-measured docs pack declares its gap in its own file rather than only on its card. **No
  number moves** — it is a statement about the pack, not a change to it.
- Twelve api packs now carry a named warning where they carried nothing.
- Every rule above was verified by breaking it on purpose in
  `core/tests/test_dimension_coverage.py`.

## What this does not do

**It does not make an overall a mean of three when a pack honestly has two.** It makes the fact
visible, declared and reviewable. Issue **#73** — print the scored-dimension count beside every
published overall — is the display half, and stays filed rather than folded in here.

**It does not check that the task is a good one.** It checks that a dimension has one. An answer key
always matches itself (ADR-0010), and a dimension exercised by a single weak task now passes a gate
that says nothing about its quality.

**It does not repair the twelve api packs.** They are warned and filed. A cycle that fixed them
would be adding scope tasks to twelve published packs on the strength of a gate written the same
day, and the numbers would move.

**It does not let an observation become a dimension later by default.** Promotion is an ADR argued
from at least two vendors, and decision 4 says so in advance.
