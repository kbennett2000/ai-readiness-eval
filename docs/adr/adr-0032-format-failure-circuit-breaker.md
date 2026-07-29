# ADR-0032 — a condition whose format-failure rate exceeds 20% stops the grid

**Status:** Accepted
**Date:** 2026-07-29
**Follows:** ADR-0031 (the static half of the same problem), ADR-0014 and ADR-0022 (the parser
repairs that make a format failure mean what it says).

## Context

ADR-0031 closes the failure mode it can see statically: a prompt that names nobody. It cannot see a
prompt that names its target and is still unanswerable as asked — under-specified in some other way,
contradictory, or asking for something the vendor does not have.

The grid that motivated both rulings gave the signal in its own output long before anyone read it:
**45 of 60 cold runs were format failures, against 0 in the documented condition.** A 75%-to-0% split
is not a fact about a model; it is the signature of a broken instrument. Nothing acted on it. The run
completed, wrote its reports, and printed a headline of 20% → 98% that was better than the truth.

So the second half of the ruling has to be empirical and has to fire **mid-flight**, while the money
is still unspent.

## Decision

`cmd_run` stops the condition when, after a floor of completed runs, the running format-failure rate
exceeds a threshold. Both numbers are derived from this project's own record, not chosen.

### The threshold — 20%

Every non-mock condition this project has ever published — **26 conditions across 12 vendors** — plus
the one grid known to have had a broken question:

| | format-failure rate |
|---|---|
| 22 of 26 published conditions | **0.0%** |
| worst published condition (3/55) | **5.5%** |
| two n=10 pilot conditions (1/10 each) | 10.0% |
| **the discarded grid (45/60)** | **75.0%** |

The widest legitimate rate ever observed is 5.5%; the one broken question produced 75%. **20% is the
geometric midpoint** (√(0.055 × 0.75) ≈ 0.203): 3.6× above anything the cohort has legitimately
produced, 3.75× below the case it must catch. Strictly greater — exactly at the threshold survives.

### The floor — 20 runs

A rate without a denominator false-aborts on clustering, because grids run task-major and one bad
task's runs are adjacent. The floor was set by replaying every archived grid on disk and taking the
worst rate over **any prefix at least as long as the floor**:

| floor | worst prefix rate across every archived grid | headroom under a 20% threshold |
|---|---|---|
| 10 | **20.0%** | **none** — one more failure in one real grid's opening runs and it aborts healthy work |
| 15 | 13.3% | 1.5× |
| **20** | **11.4%** | **1.75×** |

A 10-run floor is not conservative, it is exactly on the line. 20 clears the worst real prefix by
1.75× while still tripping a 75%-broken grid **at run 20**, saving two thirds of the spend.

This replay is a standing test, not a one-off calculation: it re-runs against every archive on disk,
so a threshold that would abort published work fails the suite.

**The replay is deliberately pessimistic, and the reason is worth recording.** It reads each run
record's own `format_failure` flag, and for a grid later re-scored by `rebuild-report` those flags
are **stale** — the rebuild rewrites `scores.json` and `summary.md` but not `runs/*.json`. Three
archived conditions carry 8 such flags that the published numbers no longer count (filed as #52).
The breaker is therefore being replayed against a *worse* failure record than the cohort actually
published, and still never fires.

### Reused runs count

A resume that ignored archived runs could work through a grid that already had a broken question and
never trip. That is laundering, not resuming.

## It is a circuit breaker, not a verdict

On trip it stops the loop, writes the reports for what already ran, prints the failing-task
breakdown, and exits `EXIT_BLOCKED` — which the factory already maps to `blocked` with a written
reason. **Nothing is deleted, nothing is re-scored, and the run archive stays resumable.**

That restraint is the whole design, because the honest counter to this ADR is real: **a model can
legitimately refuse when it genuinely does not know an obscure API.** A high cold-condition rate is
evidence about the question, not proof. The breaker's job is to stop the spend and demand a human
ruling, not to make one.

`--format-failure-threshold` overrides it (`1.0` disables), and **the value in force is written into
`scores.json` metadata whether or not it fired**. A grid published past a high failure rate is a
deliberate decision, and the decision belongs in the artifact rather than in someone's memory of the
terminal — the same shape as `--allow-unpinned-model`.

## What this cannot do

- **It cannot distinguish a broken question from a genuine refusal.** Stated above; it is the reason
  the breaker blocks rather than concludes, and it is recorded as an ungated hazard.
- **It cannot catch a broken question that produces parseable answers.** A prompt that is misleading
  rather than unanswerable yields confident, well-formed, wrong answers at a 0% failure rate. This
  guard is blind to it, and so is ADR-0031.
- **It cannot see across conditions.** Each `run` invocation is one condition, so the 75%-to-0%
  *asymmetry* that was the clearest signal is not what fires — the absolute rate is. Comparing
  conditions requires both to have finished, which is after the spend.
- **It costs 20 runs to work.** That is the price of being empirical, and on a 60-run grid it is a
  third of one condition.

## Consequences

- A grid whose question is broken now stops at run 20 instead of completing and publishing a number.
- `scores.json` metadata gains `format_failure_threshold` on every new run, and `stopped_early` with
  a written reason on a trip. Existing archives are untouched; `rebuild-report` reuses stored
  metadata, so no committed artifact changes.
- `--mock` is exempt: its failure rate comes from a fixed phrase table and says nothing about a
  question.
- **No scorer, parser, prompt or fixture is touched. No published number moves. The frozen 73/68/93
  is unmoved.**
