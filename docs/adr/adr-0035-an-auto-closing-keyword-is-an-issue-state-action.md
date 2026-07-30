# ADR-0035: An auto-closing keyword is an issue-state action, so the contract has to name it

## Status

Accepted. Contract wording only — no code, scorer, parser, prompt or fixture is touched, and the frozen
73/68/93 regression is unmoved.

## Context

The cycle contract has said, since it was written, that a cycle files issues and never changes their
state: *"A human reviews and merges the PR; you never merge your own, and you never assign or close an
issue — including one you filed this cycle."* The rule is unambiguous and was not in dispute.

It was nonetheless broken, by a cycle that had read it. The PR description contained the line
`(closes #52)`. A human merged the PR. GitHub closed issue #52.

Nothing about that sequence involved deciding to close an issue. GitHub resolves `close`/`closes`/
`closed`, `fix`/`fixes`/`fixed` and `resolve`/`resolves`/`resolved` immediately preceding an issue
reference into a state transition performed at merge time, in the author's name. The same resolution
runs on **commit messages** that land on the default branch, which is a second route to the same
outcome and was equally uncovered.

Two properties made this worth an ADR rather than a note:

- **The rule was correct and still did not bind.** The failure was not a misreading of the contract; it
  was a mechanism the contract did not know existed. Writing "don't close issues" more emphatically
  would have changed nothing.
- **The action is invisible at the moment it is taken.** The keyword is written in a PR body, where it
  reads as a cross-reference. The state change happens later, at a merge performed by someone else. No
  step in the cycle looks like closing an issue, so no amount of care at the point of writing catches
  it. That is the same shape as ADR-0018 (a world-visible branch name leaking what tracked files could
  not) and ADR-0019 (a status word that read as documentation and behaved as a dispatch instruction):
  a rule holding everywhere the author is looking, and not where the effect lands.

## Decision

**The contract names the mechanism and bans the wording, in both repos.**

Never write an auto-closing keyword before an issue reference in a **PR body**, a **PR title**, or a
**commit message**. Write `refs #NN` or `addresses #NN`.

Citing the issue is the point and is encouraged — an issue number in a PR description is how the
backlog stays connected to the record. What is refused is the state transition riding along with the
citation. The safe forms carry exactly the same information to a reader and none of it to GitHub's
resolver.

Commit messages are covered explicitly and not by implication, because the second route is the one an
author is least likely to think about: a PR body gets read before it is sent, and a commit message
usually does not get read again after it is written.

## Consequences

- The two safe forms are what every future cycle writes. `refs #NN` is the default; `addresses #NN`
  reads better when the PR does most of the work an issue describes without ending it.
- An issue that a cycle's work genuinely finishes still gets closed — by the operator, after review,
  which is where that judgement already belonged. The cycle's job is to say what it did, not to grade it.
- The already-closed #52 is **not** reopened. Reopening is itself an issue-state action, and performing
  one to tidy up the record of having performed one is not a correction. It is recorded here instead.

## What this does not do

**Nothing enforces it.** No test in either repo reads a PR body, a PR title, an issue, or a commit
message; the two existing guards read `git ls-files` and `git for-each-ref`, both of which are blind to
this. The hazard registry records the entry as `ungated` with that reason stated plainly, queued to the
core issue that would make PR and issue text checkable — the same shape as the standing issue for
enforcing the base-branch rule, and for the same reason: this project has repeatedly found that a rule
living only in prose is a rule with a decay date.

It also does not stop a human from writing the keyword, and does not detect one that was already
written and merged. It binds the cycle, not the repository.
