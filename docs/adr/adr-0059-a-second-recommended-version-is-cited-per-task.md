# ADR-0059 — A second recommended version is cited, and cited per task

**Status:** Accepted
**Date:** 2026-08-06
**Related:** [ADR-0023](adr-0023-either-of-auth-styles.md) (the evidence rules this copies, and the
declaration site it copies them from), [ADR-0055](adr-0055-a-tolerance-must-cite-the-vendor.md) (a
tolerance that can only move a dimension up must cite the vendor),
[ADR-0008](adr-0008-unversioned-apis.md) (every spelling of "there is no version" collapses to one
token), [ADR-0025](adr-0025-dotted-numeric-version.md) and
[ADR-0027](adr-0027-path-version-parity.md) (`26.2` and `v26.2` are one version),
[ADR-0010](adr-0010-ground-truth-round-trip-control.md) (an answer key always matches itself),
[ADR-0058](adr-0058-a-number-states-what-can-be-rechecked.md) (a number states which half of it a
reader can re-check). Files public issue #108.

## Context

Three of the six API dimensions can be widened by a declaration in a pack. Two of them had to cite
the vendor; the third could not be widened at all.

- `auth_flow_alternates` — declared **per task**, in `ground_truth`, as `{style, evidence, note}`,
  under five argued rules in `scorer.alternate_problems`, blocking at `roundtrip` since ADR-0023.
- `endpoint_base_prefix` — declared **per pack**, in `pack.yaml`, as `{prefix, evidence, note}`,
  under the same three evidence rules plus two structural ones, blocking since ADR-0055.
- `api_version` — a single non-empty string per endpoint, and nothing else. `core/validate.py`
  types it that way and there is no alternate mechanism of any kind.

That gap is not theoretical, and the shape it takes is ordinary rather than exotic: a vendor
publishes a current GA release **beside** a current pre-GA release, both listed on the reference
root, neither deprecated, with its own documentation telling an integrator that either is a
supported target. There are two right answers and the scorer can hold one.

Both ways of resolving that by hand are wrong in a way this project has already named:

- **Name only the GA.** The dimension then marks a model wrong for following the vendor's own page.
  That is not a measurement of the model; it is a measurement of which of two documented answers we
  happened to transcribe.
- **Name every published version.** A surface with twenty-nine live version paths would accept
  twenty-nine strings, and the dimension could no longer separate a model that has read the current
  documentation from one that has not. Applicable, and unfalsifiable — the state
  `alternate_problems` rule 5 exists to refuse for login styles.

The third option is the one the other two dimensions already take: **widen it, and make the widening
cite the vendor.**

### Why this lands before the pack that needs it, and not with it

A version tolerance can only ever move a dimension **up**. That asymmetry is the whole argument of
ADR-0055, and it applies here without modification: an uncited version alternate is
indistinguishable from a score rescue until someone opens the page by hand, and the round-trip
control cannot help — an answer key matches itself whatever set of versions it accepts (ADR-0010).

So the mechanism lands in a cycle that declares **no** alternate anywhere, against **no** number.
A key chosen after seeing the numbers is not a pre-registration, and a mechanism built around one
pack's needs is not a mechanism. The pack that raised the question authors its declaration in a
later cycle, against a gate that already exists and that it had no hand in shaping.

## Decision 1 — the declaration is per task, in `ground_truth`, and this is the load-bearing choice

```yaml
ground_truth:
  endpoints:
    - method: GET
      path: /objects/users
      api_version: v26.1
      operation_id: retrieve-all-users
  api_version_alternates:
    - version: v26.2
      evidence: https://developer.example.test/reference/
      note: >-
        The reference root lists this beside the GA version under "Recommended Versions",
        with neither marked deprecated and both linked as current targets.
```

`endpoint_base_prefix` is the nearer precedent by subject — both are endpoint-shaped tolerances —
and it is the **wrong** one to copy. A pack-level declaration grants the widening to every task in
the pack, including tasks whose page nobody opened. That is the exact failure the citation gate
exists to prevent, arriving through the gate's own front door: one checked page would buy acceptance
on twelve unchecked ones, and the file would read as though twelve citations had been made.

`auth_flow_alternates` is the precedent worth copying, and per task is strictly the more general
shape. A pack-wide need is expressible as the same citation repeated on each task; a per-task need
is not expressible pack-wide at all. The repetition is a feature rather than a cost — it is what
forces the evidence to be **per alternative**, which is what the gate means by a citation.

It is also free. `score_task` already holds the task, so the value is read where it is used:

> `contract.py`, `rebuild.py`, `__main__.py`, `factory.py`, `roundtrip.py`, `surfaces.py`,
> `docs_scorer.py` and `archive.py` are **untouched**, and no function signature changes.

A pack-level field would have needed a new argument threaded through eight call sites, each one a
place a caller can silently drop it — and a dropped tolerance fails *quietly*, by scoring the
un-widened answer, which is the failure mode nothing downstream can see.

## Decision 2 — six rules, and the two that are not ADR-0023's

`scorer.version_alternate_problems` blocks a pack at `roundtrip` — the gate that runs before any
grid burns — on each of the following. Rules 3 and 4 are ADR-0023's word for word, because the claim
being made is the same claim: that *the vendor* publishes this as a current version.

1. **An alternate may not normalize to empty.** `normalize_version` collapses `none`, `n/a`, `null`,
   `nil`, `unversioned`, `-`, `--` and the empty string to `""` (ADR-0008), so declaring one of them
   would accept **every answer that names no version at all** against a key that names one. That is
   the maximal possible widening of this dimension, and it is invisible in the file, because
   `version: none` reads like a version. It is the version-space form of `alternate_problems` rule
   5: the dimension would be applicable and unfalsifiable.
2. **An alternate must differ, after normalization, from every `api_version` the task's own
   endpoints declare.** Declaring the key's own version widens nothing while making the key read as
   though it covers two. Compared normalized rather than literally, because `26.2` and `v26.2` are
   one version (ADR-0025/0027) and a redundant declaration spelled the other way would otherwise
   pass — the same trap rule 5 below closes from the other side.
3. **A first-party `evidence:` URL**, refused on a host `rehosting_host()` names. A copy of a
   document is not the vendor's claim (ADR-0017).
4. **A `note:` of at least 40 characters.** A bare URL grants the tolerance for free; the note is
   what makes it reviewable by someone who was not there.
5. **No duplicate after normalization.** `v26.2` and `26.2` in one list is one tolerance recorded
   twice — either dead or a sign the list was assembled from two sources, which is how ADR-0055's
   nine-item prefix list came to hold entries no task addressed.
6. **The bare-string form is refused.** `api_version_alternates: ["v26.2"]` blocks rather than
   parsing as an uncited alternate.

Plus the shape refusal `alternate_problems` already carries: a non-list, or an empty list, blocks
with *omit the key entirely if there are none* — an empty declaration is not a declaration of
nothing, it is a declaration nobody finished.

### Rule 6 arrives blocking, and that is only possible because of when it arrived

ADR-0055 had to spend a merge with its equivalent rule as a non-blocking **count**, for a deployment
reason rather than an evidence one: the gate ships in this repository, the packs ship in another
whose CI clones this repository's default branch, and neither half could land first. It recorded
that sequence in its own text as the price of retrofitting a rule onto a field already in use.

Nothing declares `api_version_alternates` today, so rule 6 lands blocking from the first commit,
against a cohort of zero. There is no transitional shape to grandfather, and there never will be —
which is the argument for landing a widening mechanism *before* the pack that wants it rather than
alongside.

## Decision 3 — a widened cell says so, on the record

When and only when a match is credited **through an alternate**, the endpoint record carries
`version_via_alternate: "<the alternate>"`. This is the `format_repaired` shape: a conditional field,
written only when it fires, absent everywhere else — so every archived run record stays
byte-identical while a reader of a widened cell can see which half of it to re-check (ADR-0058).

A tolerance that leaves no trace in the artifact is a tolerance that has to be remembered, and
ADR-0015 exists because this project has already measured what remembering is worth.

## Decision 4 — neutrality is proved as a before/after diff, not as an absolute

The obvious proof — recompute every archived run and assert it equals its committed `scores.json` —
was run first, and it does not hold **before this change**: 11 of 2,403 archived runs across 20
packs and 50 archived conditions already disagree, all of them in one pack's
`2026-07-31-mock-preflight` directory, all the same cell, `auth_flow: 1.0 → None`, because twelve of
that pack's tasks adopted ADR-0041's `auth_flow_not_corroborable` after that mock was archived. That
directory records `provider: mock` and `model: mock-model`; **no published grid is involved, and
that is checkable from the provider field rather than from this sentence.**

Asserting the absolute would therefore have required an exemption list, and an exemption list is how
a sweep stops seeing the thing it was written for — the reason `test_archive_consistency.py` refuses
to carry one, in a case where the exempted directory would have been this repository's own frozen
anchor.

So the proof is the **diff of the same recomputation, before and against**: all 2,403 runs re-scored
from their committed `raw_response` on the merge base, all 2,403 re-scored on this branch, compared
key for key. Zero cells differ. The 11 pre-existing disagreements appear identically in both runs,
which is part of the proof rather than a footnote to it: had any of them moved, this change would
have been touching them.

This is stronger than the absolute assertion, not weaker. It isolates the delta to the change under
test and is immune to drift that predates it, with no exemption list anywhere.

## What this does not do

- **It has no analogue of `alternate_problems` rule 4, and cannot.** That rule requires the
  alternate's markers to appear in the `auth_flow` prose itself, so that the answer key a human
  reads visibly says both styles are accepted rather than the acceptance living in a field nobody
  opens. `api_version` has no prose half — it is a bare value — so the acceptance necessarily lives
  in a field. Decision 3's record field mitigates this at the artifact end; it does not close it at
  the answer-key end. Recorded here rather than papered over, and carried into `docs/hazards.yaml`.
- **It cannot open the cited page.** Same hole ADR-0055 recorded for the two sibling fields, filed
  as issue #97 against all of them: a URL that returns nothing satisfies every rule any of the three
  gates has.
- **A citation is a pin date, not a subscription.** Nothing re-checks that the vendor still
  recommends the alternate. A version that was current when the note was written and has since been
  deprecated will keep scoring 1.0, and the only signal is the `evidence:` URL somebody re-opens.
- **The round-trip control cannot catch a wrong alternate.** An answer key matches itself whatever
  set it accepts (ADR-0010). The gate checks that a citation is *present and first-party*; whether
  the cited page says what the note claims is a human reading, exactly as it is for the other two.
- **It does not widen the `endpoint` dimension.** `api_version` is credited only on an endpoint
  whose **path** already matched, and the path is where a service segment lives, so a version
  alternate cannot credit the wrong resource or the wrong service. Pinned as a must-not-inflate
  test.
- **It repairs nothing in an archive.** The 11 stale mock-preflight cells are disclosed and filed,
  not rewritten.
- **It declares no alternate anywhere.** No pack in either repository carries the new key, and no
  published number moves.

## Consequences

- One optional key in the API task schema; `build_docs_schema` is untouched and its
  `additionalProperties: false` already refuses the key, which is the right answer for a cohort with
  no `api_version` dimension.
- `core/tests/test_version_alternates.py` breaks every rule on purpose in both directions, and
  carries the three checks `tools/assert_guard_ran.py` now requires **by name** in the suite job:
  that the tolerance fires when cited, that it is refused when uncited, and that a task declaring
  nothing scores exactly as before. Each of the three is then broken deliberately to prove it is not
  vacuous, because a green run is not evidence a test executed.
- `tools/assert_guard_ran.py` grows a per-file required-name map. The privacy-guard view keeps its
  exact present meaning, including the strict rule that no test in that file may skip in an armed
  run; the new names are required in `--names-only` mode, which is what the job that actually runs
  them already invokes. No workflow file changes.
- The frozen 73/68/93 reference tables are unmoved, and so is every other archived cell in both
  repositories.
