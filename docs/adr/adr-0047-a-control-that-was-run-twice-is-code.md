# ADR-0047 — A control that was run twice by hand is code, and one of its answers is unreachable by construction

**Status:** Accepted
**Date:** 2026-08-03
**Follows:** ADR-0021 (the extracted-text floor), ADR-0029 (availability and vendorability are two
findings), ADR-0036 (robots.txt is a fetch permission), ADR-0038 decision 6 ("did not find" is not
"does not exist"), ADR-0015 (a hazard nobody gated is a note that decays), ADR-0043 (a control that
cannot distinguish *absent* from *broken* reports the alarming one).

**Spend: $0. No model invocation, no grid, no scorer, parser, prompt, condition, fixture or task file
touched. Every committed `scores.json` is byte-identical and the frozen 73/68/93 is unmoved.**

## Context

A recon that reports "this host serves an automated reader almost nothing" draws two immediate and
entirely reasonable objections. Neither is optional to answer, and a record that leaves either open is
not evidence:

1. **"Your fetcher is broken."** Answered by retrieving an *unrelated* host through the same fetcher,
   same user agent, same session, and reporting what came back.
2. **"You mis-detected a soft 404 as a page."** Answered by asking the host what it returns for a path
   that cannot exist.

Two prior recons ran both by hand and recorded the results as prose in a `controls:` key. The second
one's ADR states, in its own words, what the first control caught:

> four probes for a specification — `/swagger.json`, `/openapi.json`, `/swagger/v1/swagger.json`,
> `/.well-known/openapi` — all returned **HTTP 200**, and all four are `text/html` shells. Without the
> control this cycle could have published "\<vendor\> serves an OpenAPI document at four well-known
> paths," which is false. The control is recorded because it caught something.

That is the whole argument for this ADR. The claim was one unexecuted habit away from being published,
in a card, to a vendor. Nothing required the control, nothing checked that it had run, and nothing
stopped a third recon from writing its own well-known-path list and forgetting the baseline — which is
the ADR-0015 decay mode with a false published claim as its failure mode rather than a stale note.

## Decision 1 — `baseline` is a required argument, not a recommended one

`core/controls.py` provides three probes. The middle one is the point:

```
soft_404_baseline(base_url)            -> Baseline      # what a nonexistent path returns
reachability_control(url)              -> Response      # an unrelated host, same fetcher
well_known_spec_probe(base_url, *, baseline)  -> [Finding]
```

`baseline` on `well_known_spec_probe` is **keyword-only and required**. A `Finding` may read `spec`
only when the body parses as JSON or YAML, is a mapping, carries an `openapi` or `swagger` key, **and**
its signature differs from what the host returns for a path that cannot exist. Otherwise it reads
`shell-indistinguishable`, `not-a-spec`, `honest-404`, `disallowed`, `unreachable`, or —
when no baseline could be established — `spec-unverified`.

The distinction this decision turns on is between *discouraging* a wrong answer and *removing* it.
A well-documented optional parameter would have been the former: every caller who omitted it would get
the false claim, correctly formatted. Here there is no code path that emits `spec` without a baseline,
and `test_the_probe_cannot_be_called_without_a_baseline` asserts the `TypeError` directly rather than
trusting the signature to stay that way.

**Disagreement is not averaged over.** A host that answers one nonsense path with 404 and another with
a 200 shell has no single baseline behaviour, so `Baseline.established` is False and every otherwise-
qualifying finding degrades to `spec-unverified`. The alternative — picking one probe's answer — would
invent a shell for other responses to be compared against.

**The signature hashes the extracted text, not the raw bytes.** A client-rendered shell commonly
carries a per-request nonce or a build hash inside a script tag, so two byte-different responses are
routinely the same page; extraction has already dropped the scripts. Comparing raw bytes would have
made the control fail open on exactly the hosts it exists for.

## Decision 2 — the well-known path list is module data, declared once

`WELL_KNOWN_SPEC_PATHS` is the **union** of the sets two prior recons each invented separately (eleven
paths and four, overlapping in three). A third recon extends one list instead of writing a third, and
a committed record diffs cleanly against a re-run because the order is stable.

This is a small thing that carries a real property: two recons probing different path sets produce two
"no specification found" findings that are not comparable, and nothing about either record says so.

## Decision 3 — a Disallowed path is recorded, never requested, and the test asserts the call log

Robots applies per path (ADR-0036). A refused path yields a `disallowed` finding carrying the matching
directive verbatim, and is not fetched.

The test for this asserts on the **list of URLs actually requested**, not on the verdict. A rule that
changed the label while still issuing the request would pass a verdict-only assertion and violate the
actual undertaking — and the undertaking is the part that is a conduct claim on a card.

## Decision 4 — the record is generated, and an inconclusive run exits non-zero

`python -m core controls <base-url> --unrelated <url>` prints the `controls:` block a recon record
commits. Generated rather than typed, for the reason `core/report.py` records in its own docstring:
hand-maintained derived numbers go stale silently while the gated ones stay right. A hand-copied byte
count in a block whose entire purpose is to be checkable is the failure this project keeps finding.

The command **exits non-zero when the controls did not establish what they exist to establish** — no
baseline, or a reachability control that itself returned nothing. That state is not a finding about the
vendor; it is a finding about the run, and ADR-0043's lesson is that a control which cannot tell
*absent* from *broken* must report the one that stops work rather than the one that looks like data.

## Consequences

- One new module, one new CLI subcommand, one new test file. 25 rules, each verified by breaking it on
  purpose.
- The two objections are answerable from a committed artifact rather than from a cycle's memory, and
  the answer for a target measured today can be re-derived years later from the same URLs.
- No pack is re-measured, no dimension changes, no `results/` path is touched.

## What this does not do

**It does not establish that a vendor publishes no specification.** It establishes that, on a date,
with this user agent, a named list of paths on a named host did not serve one to a compliant reader.
ADR-0038 decision 6 states the difference and it is restated here because the count now sits in a
generated block, where it reads more like a fact about the world than the fact about a run that it is.

**It does not look where robots forbids looking**, and a target whose specification sits behind such a
path is reported identically to one that publishes nothing. The record distinguishes them — the
`disallowed` verdict names the directive — but any *summary* count of "paths that served no spec"
merges the two, and no test can prevent a reader adding those numbers together.

**It does not judge documentation quality.** A host can pass every control here and document its API
badly, or fail them and document it well. These controls decide only whether a thin result is
attributable to the target, which is the precondition for saying anything at all.
