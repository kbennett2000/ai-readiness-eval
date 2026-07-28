# ADR-0030 — the authorization-code grant is a login style, and it outranks the token it produces

**Status:** Accepted
**Date:** 2026-07-28
**Refines:** ADR-0011 (a dimension the scorer cannot positively test is not allowed to score) and
ADR-0023 (either-of auth styles). Fourth recorded failure of the ADR-0010 round-trip control.

## Context

`scorer._AUTH_STYLES` named seven login styles. It did not name the **OAuth 2.0 authorization-code
grant** — the flow every user-context API on the web uses, and the one an integrator writes when a
human has to consent.

A vendor whose token endpoint is documented as an authorization-code exchange therefore produced this:

| | canonical style |
|---|---|
| ground truth: *"OAuth 2.0 authorization code grant with PKCE … the resulting access token is presented as `Authorization: Bearer <token>`"* | `bearer-token` |
| model's answer: *"OAuth2 authorization code with PKCE"* | **`unknown`** |

The dimension had **inverted**. The precise, correct answer scored **0**; a vaguer answer naming only
the bearer token would have scored **1**.

This is the exact fault ADR-0011 fixed for `hmac-signature`, in a new place, and for the same
structural reason: **prose describing a grant necessarily names the credential the grant produces.**
You cannot document an authorization-code flow without saying what you get at the end of it, so
`bearer` appears in every such ground truth, and with `bearer-token` ranked above it shadowed the
style that actually described the flow.

**Two packs read 0.0 on `auth_flow` in both conditions because of this, and one of them was already
published.** That is a wrong number in front of a vendor — the card understated it — so this is fixed
rather than filed (ADR-0016).

### Why no gate caught it

- **The round-trip control cannot.** It scores each task's ground truth against itself, and an answer
  key always matches itself: ground truth canonicalized to `bearer-token` on both sides and scored
  1.0. This is the fourth time that limit has been the reason a defect survived (after ADR-0013,
  ADR-0017 and ADR-0020), and the fourth time it was recorded in the ADR that found it.
- **ADR-0011's block cannot.** It refuses a pack whose ground truth canonicalizes to `unknown`. Here
  the ground truth canonicalized to a *listed* style — the wrong one. The guard fires on silence, not
  on being wrong.

What caught it was the standing rule: a dimension reading uniformly zero is a suspect instrument
before it is a finding, and the cheapest check is to read the transcripts.

## Decision

`oauth2-authorization-code` joins `_AUTH_STYLES`, with markers `authorization code`, `auth code`,
`pkce`, at a position that is the whole ruling:

```
hmac-signature → session-token → oauth2-client-credentials
              → oauth2-authorization-code → bearer-token → basic-auth → api-key → access-token
```

**Above `bearer-token`, necessarily.** This is not a preference. Below it, the style can never fire on
a realistic ground truth, because a realistic ground truth mentions the bearer token — so adding it
below would have been a change that looked like a fix and repaired nothing. Pinned by
`test_the_authorization_code_grant_outranks_bearer_or_the_dimension_inverts`, which asserts that a
realistic ground-truth sentence and the correct model answer canonicalize **to the same thing**.

**Below `oauth2-client-credentials`, conservatively.** The two grants are disjoint in practice, but a
ground truth that states client-credentials explicitly should keep it even when its prose also
mentions the authorization-code grant it is distinguishing itself from. The explicit statement is the
stronger signal.

**Markers are phrases, never the bare word `code`.** `code` alone would fire on `code_verifier`,
`status code` and every HTTP-code mention in the cohort. Pinned by a must-not test, because widening
these markers is the obvious and wrong next edit.

## What moved

Scorer-only, so every archive re-scored offline at **$0 — no model ran.**

| | |
|---|---|
| ground-truth keys that re-canonicalize | **2** (both genuinely authorization-code flows previously read as `bearer-token`) |
| published conditions whose overall moved | **2**, both **upward**: 79.1 → 80.6 cold, 80.8 → 82.3 documented |
| direction | a **correction**: the model was right and the instrument scored it wrong |
| frozen 73/68/93 regression anchor | **unmoved** |
| full public suite | 1109 passed |

The affected card is corrected with the pre-correction figures printed beside the new ones, and the
cohort table's ordering and its tie-group prose are updated, because the correction changes a
published comparative claim. That table is gated: `test_cohort_claims` failed the moment the numbers
moved and named exactly which row was stale, which is the control working.

A third archived cell — a `mock-preflight` run — also moved, because the mock provider echoes ground
truth through a phrase table that this ADR extends. Mock preflight is a synthetic dry run and never a
published number; the wider fact that mock archives no longer reproduce is separately filed (#46).

## What this cannot do

**It cannot tell a documented style from a described one.** The scorer reads prose for markers, so a
ground truth that mentions a flow only to rule it out is still classified by it; ADR-0011 handles the
worst case by ordering, and this ADR inherits that limit rather than removing it.

**It does not make `auth_flow` a multi-label dimension.** A real API often accepts several credentials,
and this dimension still picks exactly one. `auth_flow_alternates` (ADR-0023) remains the mechanism for
a vendor that documents more than one, and the underlying limitation remains open as issue #20.

**It cannot find the next missing style.** Seven became eight because a vendor exercised the gap. The
list is an author's judgement about what the world contains, non-vacuity is asserted, completeness is
not — and a style the cohort has not met yet still blocks at `roundtrip` rather than scoring, which is
the ADR-0011 property doing its job.

## Consequences

- A correct answer naming the authorization-code grant now scores, on both sides of the comparison.
- Two packs' `auth_flow` cells are corrected upward; the affected published card and the cohort table
  are updated and the corrections disclosed rather than quietly applied.
- The mock phrase table gains an entry that deliberately does **not** mention the bearer token, since
  it has to canonicalize to itself — that it cannot be written realistically is itself the evidence for
  the ordering this ADR chose.
- No parser, prompt, pack schema or fixture is touched. **The frozen 73/68/93 is unmoved.**
