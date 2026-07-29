# ADR-0033 — a run record is a scored record, and a rebuild owes it the score

**Status:** Accepted
**Date:** 2026-07-29
**Follows:** ADR-0002 (the rebuild path and the frozen regression gate), ADR-0014 (the answer-format
repair whose result was the first stale field anyone noticed), ADR-0016 (fix what affects a published
number; file the rest), ADR-0032 (the breaker that reads these flags).
**Closes:** #52.

## Context

A run record holds two different kinds of thing, and nothing in this project had ever said so.

| kind | fields | who decides it |
|---|---|---|
| **evidence** | `raw_response`, `transcript`, `tool_uses`, `tool_discipline`, token counts, `cost_usd`, `duration_ms`, `mock` | the model and the transport, once |
| **score** | `format_failure`, `failure_reason`, `dimensions`, `endpoint_matches`, `format_repaired`, `repaired_block_text` | the scorer and the parser, *as they are today* |

`rebuild_report` re-scores every archived run from its stored `raw_response` and writes the results
into `scores.json` — and stops one file short. The run records keep whatever the scorer said the day
the grid ran. Every scorer ruling this project has taken since (ADR-0017, 0020, 0023, 0024, 0025,
0027, 0030) moved a published number without moving the record it was computed from.

### The measurement, which is worse than the issue that prompted it

Issue #52 reported **3 of 29 result directories, 8 stale flags**. Sweeping every archive on disk with
a comparison that reads *all six* derived fields rather than `format_failure` alone:

| | |
|---|---|
| archived conditions on disk | **32** (#52's glob missed `fixtures/imported/`, this repo's own frozen anchor) |
| directories that had ever been rebuilt | 24 |
| **of those, disagreeing with their own report** | **24 — every single one** |
| stale run records | **638** |
| stale fields | **929** |

| field | stale runs | directories |
|---|---|---|
| `dimensions` | 473 | 25 |
| `endpoint_matches` | 420 | 14 |
| `format_failure` / `failure_reason` / `format_repaired` / `repaired_block_text` | 9 each | 4 |

`format_failure` — the only axis #52 counted — is **1%** of the drift. The dimension scores are the
rest. And the rate is not 24 of 32; among directories the tool had actually touched it is **24 of 24**.
A tool that has corrupted its own inputs every time it ran, for the life of the project, with a full
test suite passing throughout.

### Why this is not hygiene

[core/__main__.py:409](../../core/__main__.py) — the resume path:

```python
prev = json.loads(run_path.read_text())
reusable, why_not = may_reuse_archived_run(prev, is_mock=mock is not None)
if reusable:
    records.append(prev)
```

The archived record is appended **verbatim** and `write_reports` publishes it. Resuming any of those
24 directories would have written the *pre-ruling* dimension scores into a **newly published**
`scores.json`. The ADR-0032 breaker reads the same records' `format_failure` flags and could
false-trip on a healthy grid. Under ADR-0016 this is squarely fix-now: it is a live path to a wrong
published number, not an untidy archive.

## Decision

### The reconciliation is a copy, never a re-score

`core/archive.py` copies the derived fields **out of the committed `scores.json` and into
`runs/*.json`**. `scores.json` is opened read-only and is never written. **No published number can
move — structurally, not by care.**

The obvious alternative is rejected on exactly that ground: re-running `rebuild-report` over an old
archive would re-score it with **today's** scorer, and the scorer has changed since these directories
were last rebuilt. The tool that caused the drift cannot be the tool that repairs it.

### The evidence is checked, not trusted

Every transport-derived field must be byte-identical on both sides before a single byte is written,
and a directory that fails aborts **entirely untouched** — as does a count mismatch or an unpaired
record. A record whose `raw_response` differs from the report's copy is not a stale score; it is two
records of different events, and syncing would overwrite a real score with one computed from a
different response. That is the harm this module exists to avoid, so it is the one thing it refuses.

A test asserts the two field lists do not overlap, and a second asserts that **every** field
`_record` writes is classified as one or the other — so a new field cannot be silently unprotected.

### The root cause closes, or the drift simply recurs

`rebuild_report` now calls the same sync after writing its reports. It had already computed these
values; it just never wrote them where the next run would read them. Sharing one code path with the
standing test is deliberate: the fix and the check cannot disagree about what "agrees" means.

ADR-0002's claim that "the transcripts in `runs/` are never rewritten" narrows to what is true and
load-bearing — **the evidence is never rewritten** — and the amendment is recorded rather than left as
a comment that has quietly become false.

### The standing sweep has no exemption list

`core/tests/test_archive_consistency.py` checks every archive on disk, in both repos, with a
non-vacuity guard and a second guard asserting it actually compared records rather than finding none.
No exemption mechanism exists. This repo's own frozen reference fixture was one of the stale
directories, and an exemption for it would have hidden the single most interesting case.

### The frozen anchor is reconciled, pinned, and its provenance corrected in the open

One imported record — the ADR-0014 repair — is regenerated with the other 637. Its `raw_response` is
untouched, and the regression gate re-scores *from* `raw_response`, so 73/68/93 cannot move; it was
re-run to confirm rather than argued. `test_frozen_fixture_diff.py` pins the changed values field by
field, pins the response by digest, and asserts no other imported record moved.

`fixtures/imported/PROVENANCE.md` said the import was byte-for-byte. It no longer is, so the file now
says which record changed, which fields, and why. **A provenance claim is a published claim; it gets
corrected openly rather than quietly broken** — and a test fires if that disclosure is edited away.

## What this cannot do

- **It cannot tell whether the score is right.** It makes the record agree with the report. If the
  report is wrong, this propagates the wrong value faithfully into one more file.
- **It cannot recover what the older scorer said.** After the sync, the pre-ruling per-run values
  exist only in git history. That is the intended direction — the report was always the published
  artifact — but it is a real loss of a second opinion, and it is why the operation is one commit.
- **It cannot fix an archive whose evidence has drifted.** It refuses those, by design, and a refusal
  is a finding for a human rather than something to work around.
- **It says nothing about `summary.md`.** Only `scores.json` is compared, because only `scores.json`
  carries the per-run detail.

## Consequences

- 929 fields across 638 records in 25 directories are reconciled. **Every committed `scores.json` and
  `summary.md` in both repos is byte-identical before and after** — verified by digest, 64 files — and
  the frozen 73/68/93 gate passes unchanged.
- A new `reconcile-runs` subcommand (`--check` reports without writing) and a new standing sweep.
- `rebuild-report` now leaves an archive self-consistent, and raises rather than returning quietly if
  it cannot.
- **No scorer, parser, prompt, task file or fixture answer key is touched, and no model ran. Spend for
  this ruling is $0.**
