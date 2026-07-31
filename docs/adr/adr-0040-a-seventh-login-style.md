# ADR-0040 — a seventh login style, because a spec may declare one the scorer cannot name

**Status:** Accepted
**Date:** 2026-07-31
**Follows:** ADR-0011 (a dimension does not score unless it can be POSITIVELY tested; an unlisted
auth style BLOCKS `roundtrip` rather than drawing a note), ADR-0023 (an alternate login style needs
first-party evidence; `access-token` ranks last so its addition is provably score-neutral),
ADR-0010 (the round-trip control), ADR-0002 (the six dimensions).

**Scorer-only. Every committed `scores.json` across the cohort is byte-identical and the frozen
73/68/93 is unmoved — proved by an A/B rebuild rather than asserted. No model was run. $0.**

## Context

`scorer._AUTH_STYLES` named six login styles. The next queued target's own published specification
declares a seventh:

```
securityDefinitions:
  OAuth2:
    type: oauth2
    flow: implicit
    authorizationUrl: https://<host>
```

There is no token URL and no scope list. The implicit grant is what the first-party artifact states,
so it is what that pack's ground truth states — and `roundtrip` refused all twelve of its tasks with
the message ADR-0011 wrote for exactly this case: *"auth_flow names no login style the scorer
recognizes, so the dimension scores 1.0 for any answer that also names none — it would read as
applicable while measuring nothing."*

That refusal is the control working. A pack cannot route around it, and this cycle did not: the
alternative was to write "bearer token" into ground truth, which would have made the gate pass by
describing the vendor's specification as something other than what it says.

**This was predicted in the cycle plan before the gate ran.** The previous cycle's plan asserted "no
core change" and was wrong; this one named the change, the precedence argument, and the proof
obligation up front. Recording that is the point — a plan that predicts where it will break is
cheaper than one that discovers it.

## Decision 1 — `oauth2-implicit`, with two narrow markers

```python
("oauth2-implicit", ("implicit grant", "implicit flow")),
```

Both markers are two-word phrases. **Bare `implicit` is deliberately not a marker**, and that is the
whole risk in this change: `implicit` and `implicitly` appear in ordinary prose across the cohort
("the tenant is implicit in the host name", "scopes are granted implicitly by the security group"),
and a marker that fired on them would re-canonicalize published ground truth and move archived
cells. The counterexample is pinned as a must-not-fire test.

## Decision 2 — it ranks above `bearer-token`, below the other two OAuth grants

Placed after `oauth2-authorization-code` and before `bearer-token`.

**Above `bearer-token` and `access-token`,** for the reason `oauth2-authorization-code` is already
placed there: the implicit grant's defining property is that it returns the access token straight
from the authorization endpoint, so prose describing it NECESSARILY names the token it hands back.
With `bearer` above it, ground truth stating the implicit grant would canonicalize to `bearer-token`
while an answer saying precisely "OAuth2 implicit flow" canonicalized to `unknown` — the dimension
would INVERT, scoring the exact answer 0 and a vaguer one 1. That inversion has happened twice in
this project's history (ADR-0011, ADR-0023's note on two packs reading 0.0), which is why the
ordering is argued rather than chosen.

**Below `oauth2-client-credentials` and `oauth2-authorization-code`,** which is the conservative
direction: prose that states either of those explicitly keeps it even when it also mentions the
implicit grant it is contrasting itself against. That protects already-published ground truth, and
it is the same tie-break ADR-0011 used when it put client-credentials above authorization-code.

## Decision 3 — score-neutrality is PROVED, not asserted, and the first attempt at proving it was wrong

Two checks, in order.

**Static.** `implicit grant` and `implicit flow` occur ZERO times across every task file, vendored
spec, `scores.json` and archived run in the packs repo, outside the pack that forced this.

**Dynamic, and this is the one that counts.** Every one of the 36 archived result directories was
re-scored from its archived transcripts twice on today's core — once with the change stashed, once
with it applied — and the two sets of `scores.json` compared. All 36 byte-identical.

The first attempt at this proof was invalid and is recorded because the failure mode is reusable.
It compared freshly rebuilt files against the COMMITTED ones, and every hash differed — which looked
alarming and meant nothing: the differences were a dropped `rebuild_note` metadata field and
display-only `answer_api_version` casing left by an older core, none of it touched by this change.
Comparing a rebuild to an archive measures every core change since that archive was written. Only
an A/B on one core isolates the change under test. An earlier version of that same loop had also
failed 36 times in a row on a wrong flag while printing a cheerful "byte-identical", because
nothing had been rebuilt at all — a vacuous pass, the same shape as issue #70's silently-skipping
leak guard.

## Consequences

- One entry in `scorer._AUTH_STYLES`; `KNOWN_AUTH_STYLES` gains `oauth2-implicit`, so a pack may
  now declare it in `auth_flow_alternates`.
- `core/tests/test_scorer_oauth_implicit.py` — 10 tests: the two markers, the spec-shaped ground
  truth, three precedence assertions, and four must-not-fire assertions. Each was verified by
  breaking it on purpose.
- No parser, prompt, fixture or pack file changes. No published number moves.

## What this does not do

It does not make the implicit grant a good idea, and this project takes no view on that: the job is
to record what a vendor's own artifact declares and to measure whether a model can state it. It does
not claim the six styles plus this one are exhaustive — the next vendor may declare an eighth, and
the correct behaviour then is the same refusal that produced this ADR. And it cannot help a pack
whose auth ground truth is merely VAGUE rather than unlisted; `roundtrip` catches the unnameable, not
the imprecise.
