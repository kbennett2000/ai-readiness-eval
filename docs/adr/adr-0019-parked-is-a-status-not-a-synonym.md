# ADR-0019: `parked` is a status the dispatcher knows, and the status vocabulary is now checked

## Status

Accepted. Dispatcher and queue-model only; no scorer, parser, prompt or fixture is touched, and the
frozen 73/68/93 regression is unmoved.

## Context

The factory's queue gave a target one `status`, and `next_target` dispatched the first entry whose
status was not in `DONE_STATUSES = {"carded", "blocked"}`. Two things about that were wrong, and they
compounded.

**First, `parked` was prose, not a value.** The word appears in `core/factory.py`'s own comment on
`DONE_STATUSES` ("either finished or **parked**"), in `next_target`'s docstring, in the packs repo's
README, and in the queue file's own header — every time as English describing what `blocked` means.
An author reading any of those and writing `status: parked` would have produced the exact opposite of
the intent: `parked` is not in `DONE_STATUSES`, so the entry becomes **the next target the factory
dispatches**, at a target somebody had just decided not to measure. It would also have been counted as
"open" in the status tally, and its written reason silently dropped, because the reason line was keyed
off the literal string `blocked`.

**Second, nothing validated `status` at all.** Not `QueueEntry`, not `load_queue`, not `core/validate.py`
(which validates packs), not any test. The vocabulary existed only as a comment at the top of a queue
file in a different repository. Any unrecognized value — a typo, or a word the code did not happen to
know — was accepted silently and then read as *not done*, which is to say *dispatch this next, and
spend on it*.

This was found the good way rather than the expensive way: a cycle was asked to park a target, and the
instruction could not be carried out literally without arming the dispatcher at it.

## Decision

**`parked` becomes a real terminal status, and the whole vocabulary becomes enforced.**

`DONE_STATUSES = {"carded", "blocked", "parked"}`, with the three meanings kept distinct:

| status | meaning | who writes it |
|---|---|---|
| `carded` | measured; a card exists | the pipeline |
| `blocked` | a gate refused it, or this instrument structurally cannot describe it | the pipeline, or an author |
| `parked` | it *could* be measured; we decided not to, for now | only an author |

**`blocked` and `parked` are not synonyms and must not collapse.** `blocked` is a property of the
target — something about it stopped the work. `parked` is a decision about the target — nothing stopped
us; we chose. Recording a deliberate deferral as `blocked` would file our own judgement under the
target's shortcomings, which is precisely the kind of claim this project refuses to make about a vendor
it has not measured.

Both are terminal, both are skipped by `next_target`, and both print their `blocked_reason` in
`factory status` — keyed off the status rather than off the literal `blocked`, so a third terminal
state cannot be added later and silently print nothing. The field keeps its name: renaming it would
touch every carded entry for no gain, and the wart is preferable to the churn.

`STATUSES = {"queued", *STAGES, *DONE_STATUSES}` is derived rather than restated, and `load_queue`
raises on anything outside it, naming both the offending entry and the allowed set. Deriving it means
adding a pipeline stage cannot leave the validator behind.

## Consequences

- A queue file with a typo'd or invented status now fails to parse instead of dispatching. That is the
  cheap end of the mistake; the expensive end was a grid burning on a target nobody selected.
- `factory status` reports parked targets in their own tally column rather than folding them into
  "open", so the operator's headline count stops overstating the work remaining.
- The vocabulary is enforced in the public engine while the queue that uses it lives in a private repo.
  That is the correct direction: the engine owns what a status *means*, the queue owns which targets
  have which.
- Existing queues are unaffected — every status any pipeline has ever written is in `STATUSES`.

## What this does not do

It does not check that a status is *appropriate*, only that it is *known*. Nothing stops an author
marking an unmeasured target `carded`; the gates, not the vocabulary, are what make a card mean
something. And a parked target's reason is free text, so the quality of the record still rests on the
author who wrote it.
