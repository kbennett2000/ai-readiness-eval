# ADR-0014: an answer we cannot parse is not the same as an answer that is wrong

## Status
Accepted. Follows the method set by [ADR-0008](adr-0008-unversioned-apis.md) and
[ADR-0011](adr-0011-auth-login-styles.md) — a parser/scorer-only rule, re-applied to archived
transcripts offline at zero model spend. Names a limit of
[ADR-0010](adr-0010-ground-truth-round-trip-control.md) that [ADR-0013](adr-0013-spec-server-prefix.md)
also ran into.

## Context

The previous cycle produced the cohort's first non-zero `format_failures`: **6 of 110 runs** on one
pack, all on one task, all the same shape. The model answered

```yaml
key_parameters: [id, skip, take, sortBy[0].name, sortBy[0].direction]
```

`sortBy[0].name` is how that API indexes a sort parameter. It is also invalid YAML: inside a flow
sequence, `[` opens a nested sequence, so `safe_load` raises `ParserError` and the parser discarded
the **entire answer** — endpoint, method, version and auth along with the parameter list.

**The contract induced the style it then punished.** The prompt's worked example is

```yaml
required_scopes: [widgets:read]
key_parameters: [filters]
```

([`core/prompt.py`](../../core/prompt.py)) — a single-line flow sequence. The harness demonstrated
that shape, the model copied it, and the harness threw the result away the moment a parameter name
legitimately contained a bracket. Nothing about the answer's API knowledge was measured. What was
measured was our formatting choice.

**It was predicted before it happened.** The previous pack's report card recorded that a bare
bracketed parameter "would register as a format failure rather than a wrong answer," noting that it
did not bite in those 100 runs. It bit in the next pack.

**The round-trip control could not have caught it, structurally.**
[`render_block`](../../core/answer_block.py) serializes with `default_flow_style=False`, so the
harness's own renderer emits block sequences and can *never* produce the construct its parser was
rejecting. Ground truth containing `sortBy[0].name` round-trips perfectly. ADR-0010 said the control
"catches an *unscoreable* key, never a *wrong* one"; this adds a second blind spot — it cannot catch a
**dialect the harness accepts from itself but not from a model**. That is the third consecutive cycle
in which this control's blind spot was the thing that mattered.

### What the corpus actually contains

Across **826 archived runs** the complete failure taxonomy is:

| shape | count | disposition |
|---|---|---|
| `ParserError` — bracketed item in a single-line flow sequence | 7 | repaired by this ADR |
| no `answer-summary` block found | 3 | all in `*-mock-preflight` dirs; deliberate mock artifacts, still failures |

No other malformed-YAML family occurs even once. The tolerance below is written against that evidence
and no further.

## Decision

**1. One repair, attempted only after YAML has already failed.** A block that parses is never
rewritten. If the repair does not itself produce valid YAML, the original `FormatFailure` is returned
**unchanged** — so the repair can only ever rescue, never reclassify.

**2. It is narrow, and the narrowness is the safety argument.** It applies only to `required_scopes` /
`key_parameters` (the two list-of-string contract keys), only written as a single-line flow sequence,
and only when an item actually carries the bracket notation that made the line invalid. Items are
split on commas at bracket/brace depth zero **with quote tracking**, and re-emitted through
`yaml.safe_dump` rather than by hand-rolled quoting.

**3. Any item the repair cannot vouch for abandons the repair for the whole block.** Every produced
item must look like a scope or parameter path — no whitespace, no quote characters, no commas.

This third rule is load-bearing, not defensive decoration. Both dimensions this repair can reach are
scored by **containment** (`required_scopes` any-of overlap, `key_parameters` required-subset), so
splitting one item into several can only ever *raise* a score. Consider:

```yaml
key_parameters: ["requestedFor, requestedItems", requestedItems[].id]
```

A naive split yields the two exact ground-truth names `requestedFor` and `requestedItems` and scores
**1.0**. The same content as valid YAML is one hedging string and scores **0.0**. Without the item
guard the repair would manufacture a score out of a comma — and would do so monotonically upward. It
is pinned as a must-not-repair case in the tests, together with quoted scope sentences, prose items,
unterminated quotes, and trailing comments containing brackets.

**4. A repair is recorded, not absorbed.** `format_repairs` is always present in the aggregate and in
`summary.md` — including as `0`, so a reader can distinguish "nothing needed repair" from "this report
predates the counter." Per run, `format_repaired: true` and the `repaired_block_text` actually parsed
are archived, so a repaired score stays reproducible from the raw response. The per-run keys are
written only when the repair fires, and are explicitly cleared before each rebuild re-decides them —
a conditionally-set key that is never cleared would otherwise survive as a stale `true` forever.

**5. No scorer rule changes and no dimension gets easier.** A rescued answer is scored normally.

## Consequences

**The frozen reference tables reproduce: 73 / 68 / 93 is unmoved.** One archived `mcp` answer is
rescued; that condition's underlying cells move (86% → 87% on three dimensions, `format_failures`
1 → 0) and the headline still rounds to 93.

**That the headline held is luck, and should be read that way.** The rescued answer happened to score
6/6. Sweeping its score shows anything below ~0.917 would have moved the published 93 to 92. "The
anchor didn't move" is a fact about this corpus, not a property of the change.

**The derived fixture files were re-derived, and how matters.** Running `rebuild-report` over them
would have destroyed the gate: a rebuild drops `cli_policy` / `tool_discipline_summary` / `reused_runs`
and adds `rebuilt_from_runs`, which would make the metadata assertion compare a rebuild to a rebuild
forever and delete the tool-discipline line another assertion requires. So only the score-bearing parts
(`runs`, `aggregate`) were recomputed, with run-provenance metadata preserved verbatim and `summary.md`
re-rendered against it. **The transcripts in `runs/` were not touched**, `EXPECTED_OVERALL` remains a
hand-written anchor, and a new assertion pins the repair count at exactly 1 across 165 transcripts — so
a future widening of tolerance fails loudly instead of arriving inside a headline.

**One card's published numbers move**, in both directions: its cold overall rises 77% → 79% while two
of its documented-condition dimensions *fall* (70% → 69%), because two rescued answers name a wrong
path and now score 0 instead of being excluded. That the fix lowers cells as well as raising them is
the evidence that it repairs an instrument rather than inflating a result.

**`format_failures` is not comparable across this ADR.** The metric's definition is unchanged; the
instrument's tolerance is not. Any cross-cycle reading of that number must say which side of ADR-0014
it sits on.

### What this deliberately does not do

- **It does not change the prompt contract.** Rewriting the worked example as a block sequence would
  make this failure structurally impossible for every future run, and it is the better long-term fix —
  but it changes what the model was *asked*, so it cannot be re-applied to archives and would break
  comparability with every grid already run. Carried as **open work for the next cohort re-run**,
  alongside the `auth_flow` single-example item still open from ADR-0011. The two are complementary:
  fix the parser for the archives that exist, fix the prompt for the runs that don't yet.
- **It does not rescue any other malformed-YAML family** — a missing block, a non-mapping block, a
  multi-line flow sequence, tab indentation, alias sigils, or `": "` inside unquoted prose. None occurs
  in the corpus. `": "` in `auth_flow` is the most plausible future candidate and would hit an
  always-applicable dimension; it stays out of scope until a run actually produces it, and this
  sentence is the record that the boundary was chosen rather than overlooked.
- **It does not fix the stale `dimensions` cached in `runs/*.json`.** `rebuild-report` rewrites
  `scores.json` and `summary.md` only, so a re-scored archive's per-run files keep their pre-rebuild
  dimension values. Nothing reads them today (every consumer reads `scores.json`, or `raw_response`),
  but it is a live trap and is recorded here as follow-up work rather than widening this cycle.
- **It does not annotate repaired runs in the invented-endpoint exhibit.** `core/analyze.py` skips
  format failures, so a rescued run now enters that exhibit's denominator without a marker. Low impact,
  recorded for the same reason.
