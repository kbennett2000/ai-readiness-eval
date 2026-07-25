# ADR-0022: the format repair asks the parser which line is broken, instead of scanning for a bracket

## Status

Accepted. Narrows the trigger condition of ADR-0014; every rule that ADR established stands unchanged.

## Context

ADR-0014 added a repair that runs only after an answer block has already failed YAML parsing. It
rewrites a single-line flow sequence into a block sequence, on the two list-valued contract keys, and
abandons itself entirely if any item it would produce fails an item guard. That decision is unchanged
and is what makes the repair safe.

What was wrong is how it decided **which line** to rewrite:

```python
# A flow sequence that is already valid YAML is never rewritten.
if "[" not in inner and "]" not in inner:
    continue
```

The stated intent — do not rewrite a line that is already valid — is right. The test is a proxy for
it, and the proxy is wrong. ADR-0014 was written against `sortBy[0].name`, the indexed-parameter
notation, so a square bracket was the visible marker of every failing line it had seen. It is not the
only way to write an item that a flow sequence cannot hold.

A model that does not know a tenant-specific value writes a placeholder:

```yaml
required_scopes: [scp.pc.{registered_role_name}]
```

That is invalid YAML — inside a flow sequence, `{` opens a mapping — and it contains no square
bracket. So the guard classified the one broken line in the block as "already valid", skipped it,
found nothing else to rewrite, and returned "nothing repairable". The block was discarded whole.

**The cost is not confined to the key that broke.** A format failure discards the whole run: it is
excluded from every dimension's denominator (`report.aggregate` keeps only `not r["format_failure"]`)
and reported separately as a count. One of the two runs that hit this named
`path: /common/v1/activities` — the ground-truth endpoint — with the correct method, version and auth
flow beside it. A brace in a *scope* list removed all four from the measurement. That is the same
failure ADR-0014 exists to prevent, arriving through a notation it had not enumerated.

There is a second cost, on the card rather than in the arithmetic. A published "format failures: 2 of
50 runs" reads as *the model could not follow the answer contract*. Here the model followed it, wrote
a placeholder for a value it correctly did not know, and our trigger rejected the line. Publishing
that as a model failure would put a wrong claim in front of a vendor, which is the test this project
uses to decide what a cycle fixes.

Found the same way as the last three instrument defects: a dimension looked wrong, and the transcripts
were read instead of the number being believed.

## Decision

**The trigger asks the YAML parser whether a line is valid, rather than inferring it from
punctuation.**

```python
def _is_valid_yaml_line(line: str) -> bool:
    try:
        yaml.safe_load(line.strip())
    except yaml.YAMLError:
        return False
    return True
```

The repair only ever runs on a block YAML has already rejected. The question a per-line guard has to
answer is therefore not "is this block valid" but "is *this* the line that broke it" — and the parser
answers that exactly, where a character test answers a correlated question and is wrong whenever the
correlation fails.

A line that is valid alone but invalid in context is safe to skip: skipping only declines to rewrite
it, and some other line is what actually failed.

### What this does not change

- **Still only the two list-valued keys.** `_FLOW_LIST_RE` is untouched.
- **Still only after YAML has already failed.** The repair is not a parser; it is a second attempt.
- **Still abandoned whole if any produced item fails `_REPAIR_ITEM_RE`.** This is the guard that
  matters, and it is the reason widening the trigger is safe to do. Both dimensions the repair can
  reach are containment-scored, so a careless split can only ever manufacture a score **upward**. The
  quoted-comma counterexample stays pinned as a must-not-repair test and still abandons.
- **Multi-line flow sequences and other keys stay out of scope**, pinned by their existing tests.

### Why the direction of the correction is stated plainly

This section originally argued the opposite of what happened, and the error is left on the record
rather than quietly rewritten, because it is the more useful artifact.

The draft claimed the fix **could only move numbers up**, reasoning that a format failure already
scores zero on every dimension, so rescuing one can only add. That premise is false. `report.aggregate`
does not score a failed run zero — it **excludes it from the denominator** and reports it as a separate
count (`scored = [r for r in runs if not r.get("format_failure")]`), and `format_failure_score` says so
in its own docstring: *"distinct, never zeroed."*

So a rescued run enters the average as a real observation and can move a number in **either**
direction. On re-scoring, this one moved **down**: public-docs overall **71.7% → 71.2%**, because the
two rescued runs scored below the mean of the 48 that were already counted. Every dimension they touch
moved down with it.

That is the evidence ADR-0014 could point to and this ADR expected to lack — a correction that costs
the vendor being measured is not one fitted to a desired result. It was available all along; the draft
asserted the scoring behaviour from memory instead of reading `report.py`, which is the same class of
error as ADR-0013 (assuming what a spec's leftover path meant) and ADR-0021 (assuming `byte_size`
recorded raw HTML). Three cycles, three assumptions about our own instrument that a single read would
have settled.

The procedural mitigations still stand and were done: the fix was written against a mechanism — a
demonstrably invalid line the guard demonstrably skipped — not against a target number; and the blast
radius was measured from `scores.json` before the fix was designed, rather than from the per-run files,
which retain their original `format_failure` flag and had made the cohort-wide count look four times
larger than it was.

## Consequences

- **Two archived runs are rescued**, both in the pack measured this cycle, both the brace shape.
  No other pack has a live format failure, so **no published card moves** — verified by diffing all
  24 `scores.json` in the packs repo before and after: exactly one changed. Re-scored from archived
  transcripts at **$0, no model runs**.
- **The pack being measured this cycle scored lower afterwards**, 71.7% → 71.2% on public-docs, for
  the reason set out above.
- **The frozen 73/68/93 regression gate is unmoved** — its transcripts contain no line the old trigger
  skipped.
- The trigger no longer has to enumerate notations in advance. The next unanticipated shape — a
  model writing `[a: b]`, or a flow sequence holding an anchor — is handled by the same predicate
  without another ADR, provided its items still pass the item guard.
- **The better permanent fix remains unbuilt and its deferral is now compounding.** The prompt
  contract still demonstrates the single-line flow style in its own worked example, which is what
  teaches models to write it. Rewriting that example as a block sequence would make this entire class
  structurally impossible — but it changes what the model was asked, so it cannot be re-applied to
  archives and would break comparability with every grid already run. That item is now behind its
  fourth ADR (0008, 0011, 0014, and this one) waiting on the same trigger: a full cohort re-run.
  Recorded in `docs/hazards.yaml`, not as a note.
