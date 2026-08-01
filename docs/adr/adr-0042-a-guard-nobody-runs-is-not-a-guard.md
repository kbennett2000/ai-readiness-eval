# ADR-0042 — a guard nobody runs is not a guard

**Status:** Accepted
**Date:** 2026-07-31
**Follows:** ADR-0015 (a recorded hazard declares a gate or a queue), ADR-0016 (fix what is
load-bearing, file the rest), ADR-0018 (the leak guard was the leak — load prospect names at
runtime), ADR-0019 (a git ref is published too).

**CI, one environment variable, and a non-vacuity checker. No scorer, parser, prompt, condition,
fixture or task file is touched. No committed `scores.json` moves. The frozen 73/68/93 is unmoved.
No model was run. $0.**

## Context — the guard was correct, armed, and absent

`core/tests/test_core_no_vendor.py` asserts that no tracked file and no git ref in this public
repository names a measured prospect. Since ADR-0018 the name list is loaded at runtime from the
private packs repo, because writing the list into this repository was itself the leak. The price of
that fix was recorded honestly at the time and entered `docs/hazards.yaml` as
`guard-skips-where-the-private-repo-is-absent`:

> Because the name list now lives outside this repository, the guard SKIPS wherever
> `AIRE_PACKS_DIR` is unset […] The suite then reports green with its privacy guard never having
> run, and green is exactly what a reader takes as proof the rule held.

That entry named its own fix, in a repository that then had no CI at all:

> If this project ever gains CI, requiring the variable there — and failing without it — is the
> cheapest real improvement, because a CI runner has no legitimate reason to be missing it.

Between the entry being written and this ADR, the hazard fired. An ADR sentence naming a measured
prospect was committed and pushed; the guard was not run against that commit; the pull request was
merged; **the name reached the default branch of a public repository and stayed there.** The
instrument was never wrong. Run against that tree it fails, immediately and precisely, naming both
lines. Nothing ran it.

This is worth stating flatly because the flattering version is available and false. There was no
gap in the guard's logic, no missing token, no clever evasion. There was a person who was supposed to
export a variable, and a moment when they didn't.

## Decision 1 — an environment may DECLARE itself armed, and a declared-armed skip fails

`AIRE_GUARD_REQUIRED` is a third state beside the two `_Prospects` already had:

| state | meaning | outcome |
|---|---|---|
| `skip` | `AIRE_PACKS_DIR` unset — nobody configured this | **skip** (unchanged) |
| `error` | it IS set and the source is broken | **fail** (unchanged, ADR-0018) |
| `skip` **+ `AIRE_GUARD_REQUIRED`** | this environment claimed it could run the guard, and could not | **fail** (new) |

The default does not change, and that is deliberate. Making a bare skip fail would break every
outside clone of a public repository for a reason unrelated to its own tree — the argument the hazard
entry already made against exactly that fix. What changes is that an environment can now assert
something about itself: *I own the private packs repo, so a skip here is my configuration being
broken, not this checkout being an outsider's.*

Rejected: **flipping the default and exempting outsiders by detection.** Any such detection is a
guess about who is running the suite, and a guess that lands wrong in the lenient direction restores
the silent skip while looking like a fix.

## Decision 2 — a green pytest run is not evidence a test executed

Arming pytest closes the skip for tests that were *collected*. It says nothing about three other ways
a guard reports success while asserting nothing, all of which this project has already met:

- **An empty parametrize is one silent skip.** That shape produced a vacuous verification pass in the
  private cohort gate this same cycle.
- **A test that is never collected reports nothing at all** — a renamed file, an edited `testpaths`,
  a swallowed collection error.
- **A shallow clone empties the ref half without failing it.** `git ls-files` cannot see branches,
  which is why ADR-0019 exists; a runner cloned at `fetch-depth: 1` has one ref, so the ref scan
  passes by having nothing to read. The one real leak that scan ever caught was on a branch.

So CI does not read pytest's exit code. `tools/assert_guard_ran.py` reads the JUnit report and
asserts **by name** that the seven checks carrying the privacy rule were present and passed, that
nothing in that file skipped, and that the report is not empty. A required name that no longer
resolves fails a test in this repository first — the same discipline `docs/hazards.yaml` applies to
a `gated_by` reference, and for the same reason: a requirement naming a renamed test reports coverage
that is gone.

The ref-scan case is closed on both sides: the workflow clones at depth 0, and an armed run asserts
it saw more than one ref.

## Decision 3 — no step on a public runner prints a pytest message

This is the part that is easy to get backwards, and the first draft of the workflow got it backwards.

A failing `test_public_repo_names_no_prospect` prints the offending line. The offending line contains
the prospect's name. **A public repository's Actions logs are public.** Left alone, the guard firing
would publish the very string it exists to keep unpublished — to a wider, more durable, more indexed
audience than the tracked file it caught.

And it is not only the guard. Every job here loads the private packs repo, so a failing manifest or
robots assertion prints private vendor URLs just as readily; the second draft of this workflow had a
whole-suite job that would have done exactly that. So the rule is uniform rather than special-cased:
**no step prints a pytest message, a traceback, or a JUnit `<failure message=…>`, and no artifact
carries one.** pytest writes to files nobody prints; `tools/assert_guard_ran.py` reports which tests
failed, by name, and nothing else. Both behaviours are pinned by tests that feed a marker string
through the reporter and assert it does not come out.

CI therefore reports *which* check failed and tells the operator to reproduce locally. That is a
worse debugging experience and the only correct one.

The private repository is the mirror image: its logs are private, so its job prints everything, which
is the useful half of running the same guard from both sides.

### There is no "outside clone" job, because there cannot be an honest one

The first draft had one: the full suite with no private repo, guard skipping, meant to stay green for
forks and for anyone who cloned this repository on its own terms. It does not stay green, and never
did. `test_the_sweep_below_is_not_vacuous` and `test_the_matcher_finds_paths_that_are_really_there`
are themselves anti-vacuity gates — written to refuse a run too thin to be evidence — and they fail
without the private packs, on `main`, today. That was found by running the job's own command rather
than by reasoning about it.

Shipping a job that is red for a reason already known is how people learn to ignore red, which costs
more than the job is worth. The honest statement is that **this public repository's suite does not
pass without the private packs repo**, and both jobs say so by requiring it. A fork therefore gets no
CI; a fork's commits reach this repository only through a merge, and the merge fires both jobs.

## Decision 4 — the private repo runs the public guard, because one direction of drift is invisible

The public guard loads its name list from the private repo. So a name entering `queue.yaml` can turn
an **already-committed** public file into a leak with nothing in the public repository having
changed. Public CI fires on pushes to the public repository and would not notice until the next
unrelated commit — which is to say, whenever.

Every push to the private repo therefore re-runs the public guard against public `main` with that
branch's name list. It needs no secret (the public repo is public) and its logs are private.

## Consequences

- `AIRE_GUARD_REQUIRED` + `_guard_is_required()` in `core/tests/test_core_no_vendor.py`, with the
  falsey vocabulary pinned, both directions of the promotion tested, and an armed-run non-vacuity
  assertion.
- `tools/assert_guard_ran.py` — the JUnit non-vacuity checker, pure over its input, with a
  `--names-only` mode for the whole-suite job.
- `core/tests/test_ci_arms_the_guard.py` — 38 tests holding the workflow to what it claims: both
  variables set, no advisory step, depth-0 checkout, the checker invoked, no artifact upload, every
  pytest-running job redirecting its output and reporting by name, no job attempting the suite
  without the private packs, every required name resolved with `ast`, and each refusal verified one
  at a time rather than in aggregate.
- `.github/workflows/ci.yml` here; `.github/workflows/ci.yml` + `tests/test_ci_arms_the_guard.py` in
  the private packs repo.
- The public workflow needs one repository secret, `PACKS_REPO_TOKEN` (fine-grained PAT,
  Contents:Read on the packs repo). **Until it exists the `privacy-guard` job fails**, with a message
  saying exactly that. Failing is correct: a build that is green because the privacy guard was
  unreachable is the failure this ADR exists to end.

## What this does not do

**It does not remove anything from git history.** The name is in this repository's history at the
commit that added it and at the merge that carried it to `main`. The only removal is a history
rewrite, which the contract classes as unwalkbackable and forbids, and which is futile once a commit
has been public — forks, clones, caches and the API retain it. The residue stays where it already
was: the hazard entry `prospect-names-remain-in-this-repository-git-history`.

**It does not close the ordering hole.** The guard matches a list, so a target with no queue entry
contributes zero tokens, and cycles naturally write prose before the entry exists. No list-based
guard can close that and CI does not change it; the standing rule — queue entry first, with product
tokens, before any public prose — is still ordering enforced by a human. That is recorded in the
guard's own docstring and remains ungated.

**It does not test itself end-to-end.** Nothing here proves the workflow *runs* on GitHub; the tests
prove the file says what it should say. The first push is the experiment, and if the job never
appears, no test in either repository will say so. That is registered as its own ungated hazard
rather than left implied.

**It cannot assert it was run.** A test that could verify its own execution would not have been
needed. What CI adds is that nobody has to remember — which is the whole of the fix, and is smaller
than it sounds only if you have not just watched the remembering fail.
