# ADR-0023 — A surface may document two valid login styles, and the answer key may say so

**Status:** Accepted
**Date:** 2026-07-25
**Supersedes:** nothing. Extends ADR-0011 (login styles) and ADR-0004 (deterministic scoring).

## Context

ADR-0011 gave the scorer five login styles in an argued precedence order and made an *unlisted*
style blocking: `roundtrip` refuses a pack whose `auth_flow` names nothing the scorer can positively
test, because that dimension would score 1.0 for any answer that also named nothing. The guarantee it
claimed was **no dimension scores unless it can be positively tested.**

Recon on a payments flagship broke that guarantee without tripping the guard.

The surface signs every request with an HMAC over a canonical string. The key it signs with travels
in an `Api-Key` header, so the vendor's own prose necessarily names both. Run against the scorer as
it stood:

| | |
|---|---|
| ground truth (HMAC request signing) | canonicalizes to **`api-key`** — not `unknown`, so ADR-0011's block never fires |
| answer *"HMAC-SHA256 request signature in the Authorization header"* | scores **0.0** |
| answer *"Send your API key in the Api-Key header. That's it."* | scores **1.0** |

The dimension was **inverted**: the answer that correctly described the vendor's authentication
failed, and the naive wrong answer passed. This is ADR-0011's own failure mode — *"on a task whose
prose denies OAuth, the substring matcher credited the documented-wrong answer"* — recurring for the
structural reason that a marker for one style appears verbatim inside another style's prose.

**And it was already live on a published card.** One measured pack's ground truth names a
proprietary **key** header *and* an established **session** from a sign-in call, on 11 of its 12 tasks. Both styles
are named; precedence silently picks `session-token`; a model naming that key — the vendor's own
credential, the thing the header is called — scored 0. That card publishes **auth −25**, a claim
that the vendor's documentation made authentication *worse*. It did not. Re-scored from the archived
transcripts, the model was right on **100%** of documented runs.

The underlying fault is not the marker list. It is that `auth_flow` can require exactly **one** style
while a real surface may document **two as co-equal**. The measured payments flagship states this
outright: a required `Auth-Token-Type` header whose documented values are `HMAC` **or**
`AccessToken`. Under a one-style dimension, one of two vendor-documented correct answers is scored
wrong by construction. That was already filed as issue #20 and had been open for four cycles.

## Decision

### 1. Ground truth may declare a *set* of acceptable login styles — authored, never inferred

`ground_truth` gains one optional key:

```yaml
  auth_flow_alternates:
    - style: api-key                                   # a name from scorer.KNOWN_AUTH_STYLES
      evidence: https://docs.<vendor>.com/...          # first-party page documenting it
      note: >                                          # >= 40 chars: why the vendor treats it as valid
```

`auth_flow_matches` accepts an answer naming **any** style in `{required} ∪ alternates`.

The set is **never inferred from the prose.** Prose mentions a style for many reasons, including to
deny it — ADR-0011 records a key that says *"not an OAuth2 flow: there is no client_credentials
grant"* — and reading intent out of a substring is exactly what made this dimension wrong. Widening
is an authored, reviewable act or it does not happen.

### 2. Five blocking rules, because a set is otherwise a way to make any answer right

Enforced in `scorer.alternate_problems`, run by the `roundtrip` gate before any grid. Each is
blocking rather than a note, because a bad declaration never fails loudly at scoring time — it
silently changes what counts as correct.

| # | rule | why |
|---|---|---|
| 1 | `style` must be a known style name | a typo would widen nothing while *reading* as if it had — the declaration would look honoured and score as though absent |
| 2 | `style` must differ from the required style | a redundant declaration must never be mistakable for evidence that two styles were weighed |
| 3 | `evidence` must be a first-party URL | the claim is that **the vendor** documents this style; a copy of a document is not the vendor's claim (ADR-0017) |
| 4 | the style's markers must appear in `auth_flow` itself | the answer key a human reads has to visibly say both styles are accepted, rather than the acceptance living in a field nobody reads beside prose that contradicts it |
| 5 | the accepted set must stay a proper subset of the known styles | a dimension that accepts everything is applicable and unfalsifiable |

Rule 4 is the one that does the work. Rules 1–3 and 5 bound what can be declared; rule 4 makes the
declaration *legible in the artifact a reviewer actually reads*.

### 3. Two new styles, placed where they cannot move a published number

- **`hmac-signature`**, ranked **first**. Request-signing prose necessarily names the key it signs
  with, so any lower slot is shadowed by `api-key` and the inversion above returns. Markers are
  deliberately narrow — `hmac`, `message signature`, `request signature`, `request signing`. Bare
  `signature`/`signed` would recapture *"signed JWT client assertion"*, which is OAuth prose in two
  already-published packs.
- **`access-token`**, ranked **last**. `access token` appears inside OAuth prose across the cohort
  (*"send the returned value as `Authorization: Bearer <access_token>`"*), so any higher slot would
  re-canonicalize published ground truth. Ranked last it can only fire where nothing else did.

### 4. The invariance is proved, not asserted

A single-style key's accepted set is `{required}` and nothing else, so the change is score-neutral
**structurally**. It was also checked empirically: every archived run in the cohort — **1,014 runs
across nine packs and eighteen condition-directories** — was re-parsed and re-scored with the new
scorer. **Every row is byte-identical.** The frozen 73/68/93 regression gate is unmoved.

That check found something else, which is recorded here because it is the reason the check exists
rather than a separate story: **one pack's committed `scores.json` no longer reproduced from its own
archives**, and had not since cycle 15. See ADR-0020 — the service-qualified version rule — which
moved three archived runs from 0 to 1 on a pack that was never rebuilt. Handled in the packs repo.

## Consequences

- **Closes issue #20.** Four cycles open; it took a vendor whose documentation makes the one-style
  assumption untenable to force it.
- **One card moves, and it moves upward on a vendor.** That pack's auth goes 35% → 82% cold and
  10% → 100% documented; its overall goes 39% → 49% and 71% → 89%, and its documentation gap goes
  +32 → +41. **No model was run; the transcripts were already on disk. $0.** The vendor is named in
  the private packs repo, never here (ADR-0018).
- **A correction that raises a vendor's score is still a correction.** The instrument was wrong in
  the vendor's disfavour, on a card queued for outreach. It would have been published as a finding
  about that vendor's documentation and it is a finding about our scorer.
- **What this still cannot do.** Rule 4 checks that the prose *names* the alternate; it cannot check
  that the vendor genuinely treats the two as interchangeable **for that operation**. That rests on
  the author reading the evidence link. Recorded in the hazard registry, ungated, rather than
  claimed as covered.
- **The prompt contract is untouched** and still shows exactly one login-style example. That is now
  the **fourth** item queued behind a single cohort re-baseline (ADR-0008, ADR-0014, ADR-0020, and
  this). Read the count as a scheduling signal.
- Every rule above was **verified by breaking it on purpose** and confirming the named test fails.
