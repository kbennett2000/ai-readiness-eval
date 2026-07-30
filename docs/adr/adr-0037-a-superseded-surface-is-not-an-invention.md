# ADR-0037: A real endpoint from a superseded surface is not an invention

## Status

Accepted. A new read-only `core/surfaces.py`, a pack-declared reporting axis, a control wired into the
existing `roundtrip` gate, and one correction to a published card heading. **No scorer, parser, prompt
or ground-truth rule is touched, no committed `scores.json` changes, and the frozen 73/68/93 regression
is unmoved.**

## Context

A vendor may publish more than one live API surface at once. The target that forced this publishes
**four**: a current REST surface, a REST surface the vendor's own documentation marks deprecated, a
legacy graph-shaped API it still documents, and an inference API that shares both the host and the
version prefix of the current one.

Two problems, and the second is worse than the first.

### The instrument cannot see the distinction

`scorer.normalize_path` strips the scheme, the host, and every version segment. That is deliberate and
long-standing — it is what makes `/v3/search` and `/search/v1` compare equal so the version dimension,
not the path dimension, carries the version question. But it means an answer written against a
deprecated surface and an answer written against the current one normalize to the **same path** wherever
the two surfaces share a resource. On those resources the endpoint dimension is structurally blind to
the difference, and only `api_version` can see it — and only when the model states a version.

So the six dimensions record a miss and cannot say *why* it missed. A model that answered with a real,
documented endpoint from a surface that was current when it was trained scores **identically** to a
model that fabricated an endpoint outright. Those are different findings about a vendor's readiness:
one says the documentation of the change did not reach the model, the other says the API was never
learned at all. A method that cannot tell them apart reports the harsher one by default.

Nothing in the codebase classified an answer beyond a 0..1 score per dimension and a binary
`format_failure`. `analyze.unmatched_endpoints` came closest and its own docstring is explicit that it
does not do this: the endpoints it returns are *"the raw material for the invented-endpoints exhibit (a
human then curates which are genuinely non-existent vs. real-but-wrong)"*.

### That gap was already putting a wrong claim in front of vendors

The curation step the docstring describes does not exist. `factory.render_card_scaffold` prints the
uncurated list under the heading **`## Invented endpoints (verbatim)`**. A card in the drawer
accordingly lists, as "invented", two endpoints of that vendor's API that are real, documented and
published — its query interface and its OAuth2 token endpoint — each answered for a task whose ground
truth was a different endpoint. Eight occurrences across two tasks, in one card, unreviewed.

Calling an endpoint "invented" is a claim **about the world**; all the code establishes is that it was
not that task's ground truth. This is a wrong claim, in a vendor-facing artifact, generated
automatically, and it is the predictable consequence of having no way to say "real, but from somewhere
else". Under ADR-0016 triage it is fix-now, which makes this cycle's work a correction rather than a
feature. (The pack and the endpoints are named in the private packs repo, per ADR-0018.)

## Decisions

### 1. A pack may declare the surfaces it can tell apart, and core classifies against them

`answer_surfaces` in `pack.yaml`: an ordered list of surfaces, each with an id, a label, a written
rationale, version markers, and a path inventory. Exactly one is marked `measured: true` — the surface
ground truth anchors to. Every answer endpoint is placed against those inventories.

The buckets that are not a surface are named as observations about **our own evidence**, never as claims
about the model:

- **`ambiguous`** — more than one declared surface publishes this path, and the answer states no version
  that separates them.
- **`conflicted`** — the version in the path and the stated `api_version` name different surfaces.
- **`unrecognized`** — no declared inventory contains it. **Not "invented."**
- **`no-match`** (run level) — the answer identified none of the task's ground-truth endpoints, so the
  surface question is not posed. It already scores 0 on `endpoint`; counting it as a surface answer
  would count one miss twice.

### 2. It never touches a score, and that is enforced twice

This is the licence for the whole feature. The overlay reads archived runs and produces no run records;
declaring `answer_surfaces` leaves every dimension byte-identical. It can only ever redistribute
outcomes the scorer already recorded, among buckets a pack already declared — **there is no arrangement
of inventories that manufactures a point.**

Two tests, because one of them tests an input and the other makes the violation impossible: a
same-answers-same-scores comparison with and without a declaration, and a structural assertion that
`scorer.py`, `report.py`, `category.py` and `rebuild.py` never import `core.surfaces`. The dependency
runs one way only — surfaces imports the scorer's normalization, never the reverse.

### 3. It refuses rather than guesses, and declaration order is display order

Where two surfaces publish a resource and the answer says nothing that separates them, the honest
answer is that we cannot tell. Assigning it anyway would be inventing evidence, and every available
default is exactly the thing under test: resolving toward the measured surface manufactures the null
result, resolving toward the superseded one manufactures the finding.

So declaration order is **display order and nothing else**, pinned by a test that reverses the
declaration and asserts identical output. A tiebreak by declaration order would be a thumb on the scale
wearing a config field's clothing.

A ceiling is declared per pack (default 10%). Above it the split is **not printed at all** — the reason
is printed instead. A number published with a caveat gets quoted without the caveat.

### 4. The host is evidence, never a discriminator

The obvious way to tell two surfaces apart is the host, and it does not work here. The prompt contract
instructs the model: *"request path only — no scheme/host/tenant"*. Across **3,282 archived answer
endpoints in 34 results directories the host appears 0 times.** A host can only ever appear on an answer
that broke the contract, so ranking it above the version would make the highest-precedence signal the
one that fires least and least legitimately.

Version evidence is read from **both** the raw path's version segments and the stated `api_version` —
79% and 99% of archived endpoints respectively, two independent signals whose union is what makes this
work at all. The host is recorded and its rate **published on the card**, so "no rule uses the host" is
a checkable number rather than a claim in prose.

### 5. Core has no protocol branch; operation names never classify

A graph-shaped API is not special-cased. It is a surface whose inventory contains the one path a caller
writes, reached by the same rule as any other, and its id is pack data. Core knows nothing about any
particular kind of API — the same requirement that keeps a vendor string out of core.

Declared operation names are counted as **prose corroboration** in a separate column and never matched
against the path field. Two reasons. An operation name is not a path, so matching one against the other
is a category error. And a list of short names carries exactly the false-positive pathology this repo
has already been burned by twice — `_AUTH_STYLES` documents three separate near-misses, and an unbounded
product token once matched a longer English word in six ADR headers. Had operation matching run first,
a surface declaring an operation named for its own resource would have classified **every correct answer
as legacy**, with no dimension moving and no test failing. That counterexample is pinned.

### 6. A run is labelled by the endpoint that matched ground truth

58% of archived answers carry more than one endpoint and 28% already state more than one distinct
version, so the hypothesis is undefined for a quarter of the data without a stated rule — and any rule
is a substantive analytical choice that must be **pre-registered rather than discovered**. The rule:
label the run by the answer endpoint that matched ground truth. Where two surfaces share a resource,
that endpoint is precisely where the surface question lives; where nothing matched, `no-match`. Both
tables are printed side by side and asserted to reconcile.

### 7. The inventory has a known-good control, at the `roundtrip` gate

A mis-transcribed, stale or over-broad inventory produces a **confident, wrong split** that nothing
downstream can detect. So a pack's own ground truth must classify as the surface the pack says it
measures — the same register as ADR-0010's answer-key control, and checked at the same gate, so it
blocks **before a grid burns**.

Note the limit, in ADR-0010's own terms: this catches an inventory that cannot place the pack's ground
truth. It cannot tell whether the inventory is a faithful copy of what the vendor publishes today. That
is what the sibling inventory file's `source_url` / `fetched_at` / `digest` are for, and re-verifying
them is a fetch, not a test.

### 8. Long inventories live in a pinned sibling file

`task_groups` is declared inline because a grouping is *an argument the card makes*. A surface inventory
is the opposite: a transcription from a published artifact, and something in the world can check whether
it is still true. Transcriptions rot; arguments do not. So a surface may declare `paths:` inline for a
short list, or `inventory: surfaces/<id>.yaml` for one that wants provenance — `source_url`,
`fetched_at`, `digest`, `extracted_by`, and a `coverage` string stating what the inventory does and does
not claim. `unrecognized` is reported **with that coverage string attached**, so the bucket cannot be
read as "these endpoints do not exist".

### 9. The exhibit is renamed to what it computes

`## Invented endpoints (verbatim)` becomes `## Endpoints outside ground truth (verbatim, uncurated)`,
carrying a caveat that some are real endpoints answered for the wrong task or drawn from another
published surface. The **CLI command keeps the name `invented`**: a committed card cites
`python -m core --pack <p> invented`, and breaking a citation to improve a word is not a trade worth
making. A rename is filed instead.

## Consequences

- Optional and absent from every existing pack. No manifest, task file, scorer rule, prompt or published
  number is touched, and **no dimension gets easier** — the overlay cannot reach a dimension at all.
- The frozen reference pack declares no surfaces, asserted by a test, so the 73/68/93 anchor stays an
  anchor.
- A pack declaring surfaces gains a card section per condition — per condition rather than merged,
  because the whole question is whether showing a model the current documentation moves it off a
  superseded surface, and a union across conditions would average away exactly that.
- `validate` now refuses a declaration that cannot discriminate: fewer than two surfaces, no measured
  surface, an empty inventory, a missing rationale, or an overlap the declared markers cannot resolve.

## What this does not do

It does not read the model's reasoning. Classification uses the emitted answer block, so a model that
reasons in one surface's idiom and emits another's path is classified by what it emitted — which is what
an integrator would actually call. The prose signal is counted beside the table rather than folded into
it, and this is recorded as an ungated hazard.

It does not establish that an `unrecognized` endpoint does not exist. That bucket is bounded by
inventory completeness, which is a pin date rather than a fact — the same limit the renamed exhibit now
states in words, and the reason the word "invented" left both places.

It does not make the endpoint dimension able to see a superseded surface. The dimensions are unchanged
and still report a miss; this is a separate axis printed beside them, and a card that quoted the split
as if it were a score would be misreading it.
