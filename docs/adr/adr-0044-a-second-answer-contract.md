# ADR-0044 — A second answer contract, for a cohort with no API in it

**Status:** Accepted · **Date:** 2026-08-01 · **Supersedes:** nothing. Extends ADR-0002/0004 (the six
dimensions), ADR-0003 (the job taxonomy) and ADR-0029 (the docs condition) to a second cohort;
neither the API contract nor any published number is touched.

## Context

Every pack this project has measured is an **API** surface, scored on six dimensions —
`endpoint / method / api_version / auth_flow / required_scopes / key_parameters`. Those six were
derived from one reference pack and have carried fifteen more.

A recon cycle then cleared a target whose measured surface has **no API in it at all**. Its ground
truth is discrete engineering values — catalog numbers, firmware and software revision requirements
— published as a library of PDF manuals rather than as a machine-readable description. That recon
ruled the surface feasible with a bounded scope and stated what it was deferring, in as many words:

> The six-dimension API scorer does not apply to this cohort. A `docs`-cohort deterministic scorer
> keyed on discrete value classes is later-cycle work — **flagged here, not built.**

**Not one of the six applies.** There is no endpoint to name, no method to choose, no version segment
in a path, no login style, no scope and no request parameter. Scoring such a pack on the existing six
would report six n/a columns and a green run that measured nothing — the vacuous-pass shape this
project keeps closing. Re-interpreting them ("the publication number is the endpoint") would be
worse: it would make one word mean two things across a cohort table nobody could then read.

So the contract is written **first, and pre-registered**, before a single task of the forcing pack is
authored. A contract written after the tasks is a contract shaped by the answers.

## Decision 1 — an answer contract is a named, registered object, and the API one is assembled by reference

`core/contract.py` introduces `AnswerContract`: a cohort's question (`build_prompt`), parser
(`parse`), renderer (`render_block`), dimension set, task taxonomy, scoring rule, round-trip checks,
docs-context preamble, and the search terms its truncation audit looks for. A `Pack` declares
`cohort:` (default `api`) and everything contract-shaped is read from there.

**Every callable in the API contract is the same function object the code has always called**,
imported from the same module. That is the whole no-regression argument, and it is structural rather
than asserted: the API path cannot have changed behaviour, because there is no new API code to have
changed it. `contract_for` **raises on an unknown cohort** rather than falling back — a pack
declaring `cohort: dcos` would otherwise be scored on six dimensions its ground truth cannot supply,
report all six n/a, and pass green.

What a contract does **not** get to decide: the condition registry, sterile invocation, the archive
format, tool-discipline assertions, the resumable runner and the report writer are shared and
unreachable from it. Two cohorts differ in *what* is measured, never in *how honestly*.

## Decision 2 — three dimensions, and the pairing is reported rather than scored

| dimension | rule | precedent |
|---|---|---|
| `catalog_number` | any-of overlap against the acceptable set | the `required_scopes` judgment call (ADR-0004) |
| `firmware_version` | dotted-numeric, precision-asymmetric | ADR-0024's parameter-ancestry asymmetry |
| `software_version` | same | same |

Recon proved exactly two value classes complete, machine-checkable, first-party and unauthenticated.
The compatibility class is a **pairing** of two independently published values, and pairing them
correctly is what an integrator actually needs — but it is **not a fourth dimension**. With
`overall_accuracy` defined as the mean of applicable dimensions, adding it would let compatibility
drive three quarters of the headline and the catalog class one. It is computed per run into
`exhibit["pairing_ok"]` and reported on the card, the ADR-0037 treatment for a reporting axis that
must never move a number. It is `None` — not `False` — when a task asks for only one half, so no card
can average a pairing over tasks that had no pairing to get right.

`publication` is likewise **recorded and never scored**. It costs nothing and it is the mechanical
signal a pack needs to ask whether a model answered a question about one product line with a document
about a neighbouring one. Core records the string; which numbers count as a near neighbour is a
vendor fact and stays in the pack.

**Classes recon rated partial or absent are excluded and said so on the card, not scored thinly.**
Scoring a documented subset would report a dimension the vendor's coverage does not support.

### The two folds this scorer refuses

- **A variant suffix is never folded.** `XR-8300-K` and `XR-8300` never compare equal: a
  conformal-coated part is a different orderable part with a different rating. The dimension is
  containment-scored, so a fold here could only ever ADD a match — the direction that manufactures a
  score. Pinned by a must-not-fold test.
- **A vaguer answer never satisfies a precise requirement.** `12.003` requires `12.003`; `12` does
  not satisfy it, while `30.01` does satisfy a requirement of `30`. When a vendor states three
  components, the later ones are the point of stating them. Pinned by a must-not-credit test.

A leading zero inside a segment carries no meaning, so `12.003` and `12.3` compare equal. That fold
is **an assumption about the surface**, named here rather than buried: a vendor shipping `12.3` and
`12.003` as *different* revisions would make it wrong. It is the forgiving direction on notation, in
the family of ADR-0020 and ADR-0025.

Hedging is **counted, not punished**. `version_satisfies` is any-of, so a field naming five versions
is more likely to contain the right one; `hedge_count` puts that in the exhibit and on the card,
where a reader can discount it. A scorer that cannot see a hedge is a scorer that cannot report one.

## Decision 3 — this cohort's prompt is built without the excerpt-promise sentence, from day one

Public issue #67 records that `PublicDocsCondition.build_context` tells the model *"You have been
given excerpts from … Use them to answer accurately"* **whether or not anything was injected** — a
false statement in the prompt followed by a blank, on precisely the packs whose docs could not be
retrieved. #67 also argues, correctly, that the repair cannot be applied backwards: changing it
changes what was asked, so 215 archived runs would stop being answers to the prompt that produced
them.

The API contract's preamble is therefore emitted **verbatim and unchanged**, and is pinned to the
byte by a test so this work cannot drift into it. The docs contract's preamble is **empty**. This
cohort has no archive to invalidate, so it starts on the far side of #67 rather than inheriting a
defect and a queued repair.

Its answer-block example likewise teaches a **block sequence**, which is the permanent fix ADR-0014
named for the flow-sequence parse failure and recorded as un-appliable to an existing archive. This
cohort needs no repair path because it was never taught the broken form.

### Therefore: the docs cohort has its own baseline and is not comparable to the API packs

Three independent reasons, any one of which is sufficient:

1. a different dimension set (three, disjoint from the six — a test asserts the disjointness, because
   a shared name would let a docs cell be read into an API column);
2. a different prompt (no excerpt promise, a different answer block);
3. a per-pack context budget instead of a cohort constant (Decision 5).

**This is a deliberate re-baseline, not drift.** It is recorded here, enforced in core by
`category.cross_cohort_conflict` — which *raises* rather than captioning, because a table rendered
with a caveat leaves the numbers on the page for someone to quote without it — and enforced on prose
by the packs repo's cohort-partitioned card gate.

## Decision 4 — scalars are read as written, never as YAML resolves them

`yaml.safe_load` types an unquoted `firmware_version: 12.010` as a float and returns `12.01`. The
trailing digit is gone before anything compares it, and a version dimension that silently rewrites
the value it is scoring is the ADR-0013 fault class in miniature.

The docs parser therefore uses `yaml.compose`, which returns each scalar's **original text** plus its
resolved tag; the tag is consulted only to separate a genuine null from the four-character string
`"null"`. The schema closes the same hole on the answer-key side, requiring versions to be strings —
so a mis-typed key is refused at authoring time rather than compensated for at scoring time. Both
directions are pinned by tests, one of which asserts the stdlib behaviour in the same breath so it
cannot pass by describing a problem that no longer exists.

## Decision 5 — the docs-cohort budget policy, stated as a policy

**Every docs-cohort pack sets the smallest `budget_tokens` that puts every task's ground truth inside
the injected window, declared and argued in its own `pack.yaml`, and records the chosen number on its
card.**

The API cohort shares one budget so that its packs are comparable on it. That reasoning does not
transfer: a fixed count truncates a 40 KB publication and a 1.1 MB publication completely
differently, so holding the *number* constant across docs packs would hold nothing meaningful
constant. What this policy holds constant is the property that actually matters — **no task's answer
was truncated out of reach** — which is what makes a low score a finding about the vendor's manuals
rather than a measurement of a number we chose.

The number is an authored claim and is recorded as a hazard: nothing can check that a pack chose the
*smallest* qualifying budget, only that the one it chose qualifies.

## Decision 6 — the truncation audit becomes a standing gate, and its severity is the cohort's

The audit that asks "is the answer we are about to score still inside the text we inject?" existed
only as a test sweep. It is now a pipeline stage, `truncation`, between `anchoring` and `mock` —
declared in `GATES` and `STAGES` together, as ADR-0010 requires so the two cannot drift.

It is **contract-aware**: for the API cohort an item is a ground-truth endpoint path and its
base-prefix spellings; for the docs cohort it is the ground-truth **value**, because on that surface
the value *is* the answer.

Severity is a property of the cohort, not of a pack:

- **docs — blocks.** A value the budget cropped away does not make the question harder, it makes it
  unanswerable, and every point of the measured gap would be an artifact. **Having no cached text at
  all also blocks**, which is ADR-0043's lesson pointed in the direction a gate must fail: a control
  that cannot tell *absent* from *broken* has to refuse, because passing would certify a window
  nobody looked through.
- **api — advisory, exactly as before.** Every API pack on disk was authored under the old behaviour;
  a gate that newly blocked them would apply a rule retroactively to published work.

Making it a gate is also what makes Decision 5 a policy rather than an aspiration: the next docs pack
cannot skip it.

## Decision 7 — the docs cohort gets its own task taxonomy, and PDFs are extracted beside the bytes

`taxonomy.DOCS_CATEGORIES` — `select-hardware`, `verify-compatibility`, `plan-revision-upgrade`,
`identify-replacement`. The identity/API arc does not apply to a manual, and nine `na_categories`
lines arguing that a controller manual has no access-review concept would be a fiction dressed as a
finding. The two sets are disjoint and the schema enforces the split.

`docs_fetch._fetch` now detects `application/pdf` (by declared type **and** by magic bytes, since
literature hosts commonly serve `application/octet-stream`) and extracts with `pdftotext -layout`,
recording the extractor version on the page. `-layout` is not cosmetic: a specification table read
without it interleaves columns, which for this cohort destroys exactly what is being scored.
Extraction moved *into* `_fetch` because that is the only place the content type is known, and a PDF
decoded to a string cannot be re-encoded to the bytes an extractor needs. A missing `pdftotext`
**raises** rather than recording an empty page — otherwise a fact about this machine would be
published as a documentation-delivery finding about a vendor.

## Consequences

- New: `core/contract.py`, `core/docs_answer.py`, `core/docs_scorer.py`, `core/roundtrip_api.py`
  (the API's round-trip half, lifted unchanged so the driver could stop importing scorer internals).
- Threaded: `report`, `category`, `factory`, `rebuild`, `roundtrip`, `__main__`, `conditions`,
  `validate` take dimensions, labels, taxonomy and preamble from a contract, defaulting to the API's.
- `scorer.DIMENSIONS` is **unchanged and still exported** — tooling outside this repo imports it.
- `TaskScore.exhibit` and the run record's `exhibit` key are written only when a contract produced
  one, so every API record stays byte-identical; `archive.DERIVED_FIELDS` classifies it.
- 46 new tests. **Six rules were verified by breaking them on purpose** — folding a variant suffix,
  making the version rule symmetric, giving the docs cohort the excerpt promise, making its
  truncation gate advisory, parsing with `safe_load`, and letting an unknown cohort fall back — and
  each was caught.
- **No scorer rule, prompt, condition, fixture or task file of the API cohort is touched. Every
  committed `scores.json` reproduces byte-identically from its archive; 73/68/93 unmoved; $0, no
  model run.**

## What this does not do

**It does not make the two cohorts comparable, and it does not try.** Everything above is a reason
they are not. What core enforces is that nothing renders them as though they were; what it cannot
enforce is a human writing the comparison in prose somewhere no test reads.

**It does not validate the budget a pack chooses.** The gate proves the chosen budget clears every
task. Nothing proves it is the smallest such budget, and nothing can without re-running the audit
across a search — recorded as a hazard rather than implied away.

**It does not verify a transcribed publication revision.** The anchoring gate proves the cited URL
was retrieved. That the revision letter in the task file is the served document's own footer id is an
authoring claim, checkable by a reviewer against the cache and by nothing offline.

**It does not close the six-vs-three arithmetic question.** A docs pack's `overall_accuracy` is the
mean of three dimensions and an API pack's is the mean of six; both render as a bare percentage.
Disjoint names and a refusing renderer keep them out of one table, but the two numbers still look
alike on a page.
