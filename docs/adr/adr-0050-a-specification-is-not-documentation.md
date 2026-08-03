# ADR-0050 — A specification is not documentation, and the column that injects one says so

**Status:** Accepted
**Date:** 2026-08-03
**Follows:** [ADR-0034](adr-0034-an-anchor-is-not-an-injection.md) (an anchor is cited and never
injected — the ruling this condition deliberately steps outside of),
[ADR-0005](adr-0005-public-docs-fetch-fidelity.md) (`public-docs` models what a fetch
retrieves), [ADR-0021](adr-0021-extracted-text-floor.md) (the extracted-text floor),
[ADR-0013](adr-0013-spec-server-prefix.md) (a dimension read 13.7% while the model was right
98% of the time), [ADR-0045](adr-0045-a-dimension-with-no-task.md) (a written reason, never a
boolean), [ADR-0015](adr-0015-hazard-registry.md) (the decay mode).
**Answers:** issue #54 (*Study: injecting a machine-readable spec as a third condition*).

**Adds a condition. No scorer, parser, prompt or answer-contract rule changes, and no existing pack
gains a column: `raw-spec` is registered only for a pack that declares `raw_spec`, and none does. The
frozen 73/68/93 is unmoved.**

## Context

The cohort's `public-docs` column means one thing: **the vendor's human documentation, as a fetcher
retrieves it.** That definition is what makes the column comparable across vendors, and it is the
reason a number under it can be low without being unfair — a vendor whose documentation a machine
cannot read has been measured accurately.

Two vendors in the cohort now have the same awkward shape. Their human documentation is a JavaScript
shell — every URL returns the same bytes, including URLs that do not exist — while a **complete,
individually versioned, unauthenticated machine-readable specification** sits one hostname away, free
to fetch. Their `public-docs` condition injects nothing, so the pack measures whether the model knows
the API cold, twice, and reports the difference as a gap.

The tempting move is to inject the specification into `public-docs`. It would produce a number, and
the number would even be defensible sentence by sentence. It is refused, for the reason issue #54
gave when it was filed: doing that **silently changes what the column means for one vendor**, and
every cross-vendor table then compares two different things under one heading. ADR-0034 already
refused the smaller version of this move — a `pages[].inject: false` flag — on the grounds that the
mistake should be unrepresentable rather than discouraged.

There is also a question worth answering on its own, and this is the first surface that can answer
it. The reference pack's **curated** context layer is worth +25 points over its documentation
(68 → 93). Nothing has ever measured what the **raw** artifact is worth. The MCP posture sweep closed
by saying it did not schedule a third condition; #54 asked for this one specifically. Stated as the
question the column exists to answer:

> **Does injecting a vendor's own machine-readable specification close the gap on its own, or does it
> leave a residue that only a curated layer closes?**

## Decision 1 — its own condition, its own column, named for what it injects

`raw-spec` is a fourth entry in `KNOWN_CONDITIONS`, registered for a pack that declares a `raw_spec`
block and absent for every pack that does not. Its `source_label` must name the **artifact** — "…'s
OpenAPI 3 documents", not "…'s documentation" — and there is no default: constructing the condition
against a pack that has not declared one raises rather than guessing a heading. A block of
specification text under a heading that says "documentation" is precisely the confusion this ADR
exists to prevent, and a default label is how it would arrive.

Registration is gated on the **pack's declaration**, not on the manifest happening to carry a list. A
manifest that grew a `spec_documents` entry by accident would otherwise add a column to a cohort
table, and a column is a claim.

## Decision 2 — a third manifest key, because a role is one comparison away from a leak

ADR-0034 split `pages` (shown) from `anchors` (cited, never shown), and argued a separate key over a
flag: *"A separate key makes the mistake unrepresentable rather than merely discouraged."* Spec
documents get a **third key**, `spec_documents`, on the same argument. The obvious cheaper spelling —
a new `pages[].role` — puts the specification inside the list `PublicDocsCondition` already reads,
one string comparison away from being injected under the docs heading.

The two conditions share their machinery through a base class whose subclasses each name **one**
manifest key as a class attribute. The key a condition can reach is therefore fixed at
class-definition time and cannot be widened by a manifest, a role string, or a config value.
`test_a_spec_document_never_reaches_the_prompt_under_public_docs` asserts it on the fully built
message, which is what the model actually sees.

## Decision 3 — the SAME budget as `public-docs`, and no field to change it

`raw-spec` spends `public_docs_budget_tokens`. There is no `raw_spec.budget_tokens`, and the absence
is the decision, not an oversight: **a column with more room than the one it is set beside measures
this harness's generosity rather than the difference between an artifact and a page.** A pack that
wants more context moves the shared budget and moves both columns together, visibly.

The cost is real and is not hidden. Specifications run 40 KB–280 KB against a budget sized for prose
pages, so **this column truncates by construction**, and what fell off can decide it. That is
reported rather than engineered away, because both available repairs are worse: raising the budget
until the column stops truncating is the equalisation this decision refuses, and a per-condition
budget buys the column instead of measuring it.

Registered as an ungated hazard with a **drift pin** rather than claimed as gated, because what
exists is a *reported* loss and not a *prevented* one, and ADR-0015's rule is that recording a drift
pin as a gate is true about a test and false about the world.

## Decision 4 — document-level selection is retrieval; operation-level selection is curation

A pack may choose **which** spec document a task is shown — the same choice `public-docs` already
makes about pages, and the same choice a developer makes when they open the right file. A pack may
**not** slice inside a document to the operation a task asks about.

That line is where the two experiments separate. Slicing to the relevant operation is what a curated
layer does, and it is what the reference pack's 93 measures. A condition that did both would answer
neither question, and its number would belong to whichever behaviour happened to dominate. Nothing in
`RawSpecCondition` can slice: it reads whole cached documents, exactly as `public-docs` reads whole
pages, so the rule is a property of the code rather than a convention.

## Decision 5 — the overlap is COMPUTED and must be DECLARED

This is the sharp one, and #54 named it before the condition existed:

> A disclosure rule for packs whose ground truth is anchored to the same document being injected —
> otherwise the condition is scored against its own source.

Where a task's `spec_documents` and its `anchors` are the same URL, the column is a **ceiling** — can
the model read what it was handed — and not a measurement of what a model knows about the vendor.

**The overlap is not forbidden.** For a vendor whose only citable first-party artifact *is* its
specification, forbidding it would mean anchoring ground truth to something weaker or not running the
condition at all. What is forbidden is the overlap going **unsaid**. `spec_disclosure` computes it
from the manifest, and the `disclosure` gate refuses a pack that has one and does not explain it.

A **written reason, never a boolean**, on ADR-0045's and ADR-0031's argument: a flag records that
someone clicked past the question; a sentence records what they thought, which is the thing a
reviewer can disagree with. Whitespace is what a flag looks like once it is a string, and it is
refused too.

A **stale** disclosure is refused as well — a declaration on a task whose lists do not overlap. That
looks like harmless over-caution and is not: a disclosure that is not true teaches a reader to
discount the ones that are.

## Decision 6 — `disclosure` is a stage, not a branch inside `truncation`

The audit itself is a **parameter**, not a second implementation: `audit_docs_truncation` was always
written against `full_text` + `build_context` + the contract's ground-truth terms, and never against
anything specific to documentation, so it now takes the condition to audit and defaults to
`public-docs`. A copy per condition is how the two would drift and how one of them would quietly stop
being run.

The gate is a **new stage** rather than an extra branch, because the two ask different questions and
only one of them is about a window. `truncation` asks whether the answer survived the budget;
`disclosure` asks whether the pack's own record admits what the column is. A pack can pass either and
fail the other, and a target resting at `disclosure` names which. `GATES` is declared as data
(ADR-0010), so the drift pin fired the moment `STAGES` and `GATES` disagreed — which is exactly what
happened while writing this, and is the evidence that declaring gates as data was worth it.

## Consequences

- `Pack` gains `raw_spec`; `docs_fetch` gains `SPEC_KEY`; `conditions` gains `RawSpecCondition`,
  `audit_spec_truncation`, `spec_disclosure`, `check_spec_disclosure`; `factory` gains
  `check_disclosure` and a `disclosure` stage.
- `render_multi_comparison_md` needed **no change** — it has been N-condition and label-driven since
  it was written, so the third column costs nothing to render.
- Spec documents are fetched, hashed and robots-judged by the same loop as pages and anchors. Nothing
  is vendored by this ADR: the cache is gitignored, so a specification whose licence does not permit
  redistribution can still be injected without redistributing it.
- Every rule was verified by breaking it: the manifest key, the registry gate, the shared budget, the
  audit's condition label, the disclosure check, the stale-declaration branch, the overlap
  computation, and the gate's place in `GATES`. Eight sabotages, eight failures, each for the
  intended reason.

## What this does not do

**It does not make the third column comparable to anything.** A card carrying it must say that the
condition exists in no other pack in the cohort and that its number is not to be read against another
vendor's `public-docs`. That sentence is the pack's to write; nothing here can enforce it, and that
residue is real.

**It does not tell you whether the finding is about the vendor or about the harness.** #54 raised
this and it stands: "a model does better when handed the spec" may be a fact about context windows
rather than about anyone's API. One pack cannot separate them. Two vendors with this shape can, and
ADR-0045 decision 4's rule — a claim about a class of vendor needs two vendors' measured material —
governs when that claim may be made.

**It does not replace the curated layer, or measure it.** Raw-versus-curated is the comparison this
condition makes *possible*; making it needs a pack that has both, and no pack does.

**It does not resolve the truncation ambiguity.** A low `raw-spec` number can mean the model could
not use the specification or that the answer was past the cut. The audit reports the loss per task,
which narrows it; it does not settle it. Recorded as its own hazard rather than implied by this ADR
having mentioned it.
