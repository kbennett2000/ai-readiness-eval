# ADR-0041 — a key the pack itself cannot corroborate does not get to score

**Status:** Accepted
**Date:** 2026-07-31
**Follows:** ADR-0011 (a dimension does not score unless it can be POSITIVELY tested), ADR-0021
(a tolerance this project grants is one a pack asked for **in writing**), ADR-0023 (an alternate
login style needs first-party evidence), ADR-0029 (availability and vendorability are two findings),
ADR-0036 (robots.txt is a fetch permission), ADR-0040 (the seventh login style, same cycle).

**Scorer + schema only. Every committed `scores.json` outside the forcing pack is byte-identical,
proved by an A/B rebuild on one core. The frozen 73/68/93 is unmoved. No model was run. $0.**

## Context

ADR-0011 refuses to score `auth_flow` when the **scorer** cannot positively test the style. This
cycle produced the same problem one level up: a pack whose **own answer key** cannot be established.

The forcing vendor's only readable statement about its login style is a single generated
`securityDefinitions` block, identical in all eight of its specification documents:

```
OAuth2:
  type: oauth2
  flow: implicit
  authorizationUrl: https://<tenantAuthorizationHostname>
```

Three things about it matter, and each was checked rather than assumed.

1. The `authorizationUrl` is a **placeholder**, not a URL, and there is **no `tokenUrl`**.
2. In Swagger 2.0, `implicit` is the only flow whose declaration requires *solely* an
   `authorizationUrl`; `application` (client credentials) requires a `tokenUrl`. **A generator with
   no token URL to publish emits `implicit` by default.** So the line is as consistent with a
   generation artifact as with a statement of intent, and nothing readable distinguishes them.
3. Corroboration was searched for and does not exist. The vendor's authentication guide is
   **robots-forbidden**, and the one auth-adjacent document that should settle it ships placeholder
   Latin — *"Lorem ipsum dolor sit amet…"* — as the example for **both** `grantType` and
   `tokenEndpoint`.

Meanwhile **all 60 cold runs** named OAuth2 client credentials or bearer, which is the flow that
vendor's integrators actually use.

So scoring the dimension would have published `auth_flow: 0%` — "the model does not know this
vendor's authentication" — on the authority of a key the pack's own author does not believe. That is
a wrong claim in front of a vendor, which under ADR-0016's triage is fixed in the cycle rather than
filed.

## Decision 1 — `auth_flow_not_corroborable: <reason>`, and the reason IS the mechanism

A task may declare, in ground truth, a **non-empty string** explaining why its own `auth_flow` key
cannot be corroborated. When present, the dimension reports **n/a** and the reason travels into the
score detail, so a reader can disagree with the judgement instead of being asked to trust it.

Three shapes were rejected:

- **`auth_flow: null`** — a silent opt-out indistinguishable from an authoring omission, and worse,
  it re-opens the exact hole ADR-0011 closed: an absent style canonicalizes to `unknown` on both
  sides and scores **1.0** against any answer that also names none.
- **`auth_flow_not_corroborable: true`** — refused at read time and unexpressible in the schema, for
  the argument `short_text_ok` already makes (ADR-0021). A tolerance without a written reason is a
  tolerance nobody can review.
- **Switching the key to the flow the model named.** No readable first-party artifact says it. That
  is the same standard this cycle's pack applied when it refused to write the deployment prefix
  `/ccx/api` into ground truth, and applying it in one place and not the other would be incoherent
  inside a single pack.

## Decision 2 — n/a means unmeasurable in BOTH directions

The field removes the cell whichever way it would have gone. Declaring it on a task whose answers
happen to *match* converts a 1.0 into n/a and **removes a correct cell from the mean** — that is
pinned by a test, because the flattering abuse of this field is to reach for it only where the
number is bad. The dimension is not measured; it is not quietly forgiven.

## Decision 3 — it does not excuse prose the scorer cannot NAME

`roundtrip` reads the `auth_flow` prose independently and still blocks an unlisted style. Without
that separation the field would become a way around ADR-0011: any pack with vague auth prose could
declare itself uncorroborable and sail past the gate. This is pinned by a test that declares the
field *and* writes unnameable prose, and asserts the pack still blocks.

That is also why ADR-0040 remains load-bearing rather than superseded by this one. The forcing pack
must still state a style the scorer can name — it simply does not get to score it.

## Decision 4 — this is the SECOND dimension in the cohort ruled unmeasurable rather than scored low

The first was ADP (private ADR-0023/0024): zero `securitySchemes` across 48 documents and 283
operations, so `required_scopes` is n/a on every task and that pack measures **five** of six
dimensions. This is the second, and it reaches the same verdict by a different route — not a
dimension the vendor never declared, but one the vendor declared in a form that cannot be trusted.

**Both times the cause was the vendor's own documentation being unreachable, not the model failing.**
ADP's token endpoint appears in no published document; this vendor's authentication guide is closed
to automated readers by its own `robots.txt`. In neither case did the model do anything wrong, and in
both the honest report is a missing column with its reasons attached rather than a zero.

That is a pattern worth naming, because two instances make it a shape rather than an accident: **when
a vendor's documentation is unreachable, the dimension that documentation would have anchored becomes
unmeasurable — and reporting it as a low score would attribute the vendor's publishing posture to the
model.** Any card carrying an n/a column must therefore state which dimensions are scored and that
its overall is the mean of those, so a five-dimension result is never read against a six-dimension
one.

## Consequences

- `scorer.uncorroborated_auth_reason()`; one branch in the `auth_flow` scoring block; one optional
  string in the task schema (`core/validate.py`).
- `core/tests/test_scorer_uncorroborated_auth.py` — 13 tests: inertness when undeclared, the
  declaration itself, the both-directions rule, six malformed-value refusals, and the
  does-not-excuse-unnameable-prose property. Each verified by breaking it.
- **Inert everywhere it is not declared.** A/B rebuild on one core: all 36 other archived result
  directories byte-identical with and without the change.

## What this does not do

It does not decide what that vendor's login style actually is — it records that this method cannot
tell, and why. It is not a general escape hatch for a dimension a pack finds inconvenient: it applies
to `auth_flow` only, it demands a written reason, it removes correct cells as readily as wrong ones,
and it leaves the round-trip gate's independent check intact. And it cannot detect misuse — a pack
that declares a *bad* reason passes, exactly as a pack that writes a bad `short_text_ok` reason
passes. What stands behind it is review of a string in a committed file, which is the same
protection every other written-reason field in this project has.
