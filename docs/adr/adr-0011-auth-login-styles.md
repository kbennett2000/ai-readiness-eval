# ADR-0011: a dimension the scorer cannot positively test is not allowed to score

## Status
Accepted. Refines [ADR-0010](adr-0010-ground-truth-round-trip-control.md) (the round-trip gate) and
follows the method set by [ADR-0008](adr-0008-unversioned-apis.md) (a scorer-only normalization rule,
re-applied to archived transcripts offline).

## Context

[`core/scorer.py`](../../core/scorer.py) recognized exactly two auth concepts, both by bare substring:
`bearer` and `client credentials`. Where a task's ground truth named neither, `auth_flow_matches` fell
back to comparing canonical labels — and both sides read `unknown`, so **the answer scored 1.0 as long
as it also named nothing recognizable**. Against a session-token answer key, "Basic auth with username
and password" and "no idea, some kind of API key" both earned full marks.

The standing round-trip gate found this on its first run across the working cohort and
[reported it as a thin instrument](adr-0010-ground-truth-round-trip-control.md) rather than fixing it,
because fixing it moves committed numbers. **20 of 63 tasks** were affected — every task of the two
packs whose products authenticate with a session token minted by their own login call.

Reading those 20 ground-truth strings showed the defect is worse than "free marks", in two directions.

**It was inverted on one task.** A session-token product's authenticate task documents, correctly:

> *"Not an OAuth2 flow: there is no `client_credentials` grant, no token endpoint, and no scopes."*

A substring matcher cannot read a negation. It extracted `client-credentials` as the **requirement**,
so answers calling the credential "OAuth2 bearer token (client credentials)" — the documented-wrong
answer — scored **1.0**. That single task was the entirety of that pack's published cold `auth` figure.

**And it suppressed correct answers.** The fallback credited an answer only if it named *neither*
concept. An answer that correctly said *"session token, sent in the Authorization header"* and also
used the word "bearer" in passing was scored **0** — for naming the right mechanism.

So the dimension was not merely generous. On these packs it was uncorrelated with the thing it claimed
to measure, in both directions at once.

## Decision

**1. The scorer names five login styles, matched in a fixed precedence order.** The two inline
substring checks become one ordered module-level table, `_AUTH_STYLES` — the `_NO_VERSION` pattern from
ADR-0008, generalized. `_auth_concepts` returns the set of styles a string mentions;
`canonical_auth_flow` returns the first present **in table order**; `auth_flow_matches` keeps its
containment semantics — the requirement is the ground truth's canonical style, and the answer matches
if it names that style. Naming additional styles as well does not hurt, as before.

| order | style | added |
|---|---|---|
| 1 | `session-token` | this ADR |
| 2 | `oauth2-client-credentials` | existing |
| 3 | `bearer-token` | existing |
| 4 | `basic-auth` | this ADR |
| 5 | `api-key` | this ADR |

Matching stays separator-insensitive, so `client_credentials`, `Basic-auth` and `sessionId` all land.
The two existing display labels are preserved verbatim, so no `detail` string moves for a reason
unrelated to this change.

**A marker list is itself an instrument, and the first draft of this one was a bad one.** It matched
exact phrases — `session token`, `sessionid`, `establishing a session`. Re-scoring with it produced a
`public-docs` auth figure of 20% for a session-token pack, which looked like a finding. Reading the
answers it scored 0 showed what it actually was:

> `session bearer token` · `session cookie (authString POST)` · `session-based authentication (login
> token)` · `Application Server session authentication`

Every one of those names the mechanism correctly and fails only on wording — 40 of that pack's 50
`public-docs` runs. The figure was measuring **our phrasebook**. The markers are therefore the concept
words `session` and `logon`, and the near-miss strings above are pinned as a regression test.

Two things follow, and both are stated rather than hidden. First, `session bearer token` **is** now
credited: the scored dimension asks whether the model names the session mechanism, and whether it
*also* reaches for bearer vocabulary is a separate, transcript-counted observation. Second, bare
`login` is deliberately **not** a marker — it appears in OAuth-shaped ground truth (*"Basic-auth login
… POST /api/login"*) and would reclassify a pack that legitimately requires `bearer`.

The general lesson is the suspect-instrument rule applied one level down: **a number produced by a rule
written this cycle is the rule's suspect first.** The check that caught it costs nothing — read the
answers the new rule scores zero, and ask whether they are wrong or merely worded differently.

**2. The order is load-bearing, and each position is argued rather than tuned.**

- `session-token` outranks the OAuth styles because a session token is minted by *one vendor's own
  login call*, which is the more specific claim — and because, as above, OAuth words appear inside
  session-token prose as negations. The reverse does not occur: no OAuth-shaped ground truth in the
  cohort mentions sessions at all.
- `basic-auth` and `api-key` rank **below** `bearer` deliberately. A pack in the cohort documents an
  HTTP Basic login that returns a bearer token used on every subsequent call. This dimension measures
  the **per-request credential**, so that task requires `bearer`. Ranking Basic higher would have
  changed a third, unrelated vendor's published number — which is the test that the order is a ruling
  and not a convenience.

**3. The safety property, stated and then proved.** ADR-0008's counterpart to *"cannot move a versioned
vendor's score"* is: **no task whose ground truth already named `bearer` or `client credentials`
changes its requirement.** Those two keep their relative order, nothing outranks them except
`session-token`, and `session-token` appears in no OAuth-shaped ground truth on disk. On the answer
side, adding styles can only *add* members to a concept set — it can never remove `bearer` — so
containment for an unchanged requirement is unchanged.

Proved, not asserted: the frozen 73/68/93 regression gate
([`packs/sailpoint/tests/test_regression_gate.py`](../../packs/sailpoint/tests/test_regression_gate.py))
reproduces every per-run and per-dimension cell unchanged, and re-scoring the cohort's three
OAuth-shaped packs leaves their committed `scores.json`, comparison and fact-sheet files **byte for
byte identical**.

**4. A login style the scorer cannot name now BLOCKS the `roundtrip` gate.** The fallback is the defect
itself: a dimension that reads as applicable while testing nothing. So
[`core/roundtrip.py`](../../core/roundtrip.py)'s non-blocking *"close to free"* note becomes a blocking
problem, and a pack whose auth style is unlisted cannot burn a grid. This costs nothing today — after
this change all 63 tasks on disk are recognized — and it converts an advisory note into the rule it
already stated.

**The fix is always a new style in `_AUTH_STYLES`, never a rewrite of the vendor's documented prose.**
Editing ground truth to satisfy a gate is how a measurement becomes a self-portrait; the gate exists to
force the scorer to grow, not the pack to bend. The blocking message names the known styles so the
operator is pointed at the right file.

**5. The prompt contract is not changed this cycle.** [`core/prompt.py`](../../core/prompt.py) offers
exactly one example for this field — `auth_flow: OAuth2 bearer token` — and every measured model has
been reading it. That is a plain bias toward one of five styles, and it is the more direct fix. It is
also the shared instrument: changing it makes every previously measured vendor incomparable and
requires re-running the whole cohort. A scorer-only rule is re-appliable to archived transcripts through
`rebuild-report` ([`core/rebuild.py`](../../core/rebuild.py)) at zero model spend, so past and present
vendors stay on the same footing. **The contract's single-example bias is recorded as open work**, to be
taken with the next deliberate cohort re-run — exactly as ADR-0008 recorded the `api_version` gap.

Left there, "recorded as open work" is a note that decays. Two things make it hold instead:

- **The example string is pinned by test.**
  [`core/tests/test_prompt_contract.py`](../../core/tests/test_prompt_contract.py) pins both places the
  contract shows the field, and asserts that `scorer._auth_concepts` finds **exactly one** login style
  in the whole suffix — so an edit that swaps the example *or* adds a second one fails the suite. The
  pin is not a claim the example is right; it is a claim that changing it is a **re-baseline**, and a
  re-baseline is a cycle of its own. Unlike a scorer rule, this change cannot be re-applied to archives
  by `rebuild-report` — the bias is baked into what the model was asked. So the pin's standing
  instruction is: **change it only in a deliberate cohort re-baseline, bundled with any model change**,
  since a model change already forces the whole cohort to re-run together.
- **The bias is disclosed where the number is read.** Every place a login score appears on an affected
  card carries one line naming the example and its direction. It is the *same* contract for every
  vendor, so cross-vendor comparison — which is what this method measures — is unaffected; the
  absolute figure for a non-OAuth product may be understated. A caveat that lives only in an ADR is a
  caveat the reader of the number never sees.

## What this still cannot do

- **It cannot read a negation.** "Not an OAuth2 flow" still contributes `client-credentials` to the
  concept set. The precedence order is what saves that case, not comprehension. A future ground truth
  that denies a *higher-ranked* style than the one it actually uses would still be scored wrongly, and
  no test on disk would catch it.
- **It cannot judge prose quality.** An answer naming the right style for the wrong reason scores the
  same as one that understands it.
- **The five styles are the five in the cohort.** A sixth — mutual TLS, HMAC-signed requests — is a
  one-line addition, and rule 4 guarantees it surfaces as a blocked pack at authoring time, before
  spend, rather than as a silent 1.0.
- **It does not vindicate the round-trip control.** That control passes a task by construction; it
  found this by reporting a *thin instrument*, which is a weaker signal than a failure and depends on
  someone reading the note. The blocking rule above is what makes the next one impossible to ignore.

## Consequences

- Two carded packs are re-scored from their archived transcripts — no re-run, no model call. The
  movement is large and goes **both ways**, which is the evidence that the old figure was not merely
  generous but uncorrelated:

  | pack (unnamed; both session-token products) | `auth` no-context | `auth` public-docs | overall gap |
  |---|---|---|---|
  | A — before | 10% | 36% | +16 pts |
  | A — after | **28%** | **100%** | **+25 pts** |
  | B — before | 2% | 100% | +38 pts |
  | B — after | **20%** | **100%** | **+35 pts** |

  Pack A's published finding — *"auth is the one dimension documentation does not mostly fix"* — does
  not survive: it is now the dimension documentation fixes **completely**, and by the largest margin on
  that card. Pack B's headline figure of 100% survives, but it is a different claim. It used to mean
  *the model stopped saying "bearer"*; it now means **50 of 50 answers name the session mechanism**,
  which is what the card said it meant all along and could not previously support. Both cards carry
  the before/after and the reason.
- Every claim resting on those figures is re-derived wherever it appears, including the cross-vendor
  ranking of documentation lift, which changes hands.
- **A published number can move because the instrument improved, and that has to read as normal.**
  Two cards change materially here with no new evidence and no model call. The archives make that
  cheap; the ADR trail is what makes it legible rather than suspicious.
- The general rule this sets, alongside ADR-0008's *"a uniformly-zero dimension is a suspect
  instrument"*: **a dimension that cannot be positively tested must not be allowed to score.** Free
  marks are harder to notice than zeros, because nothing looks broken.
