# ADR-0055 — A tolerance must cite the vendor that writes it

**Status:** Accepted
**Date:** 2026-08-03
**Amends:** [ADR-0017](adr-0017-endpoint-base-prefix.md) and
[ADR-0039](adr-0039-a-vendor-may-disagree-with-itself-in-more-than-one-place.md), which gave a pack an endpoint-base tolerance and
then a list of them, both on a prose bar.
**Related:** [ADR-0023](adr-0023-either-of-auth-styles.md) (the evidence rules this copies
verbatim), [ADR-0013](adr-0013-spec-server-prefix.md) (a path may be written from any
point inside a declared prefix), [ADR-0015](adr-0015-hazard-registry.md) (a rule a human must
remember is a rule that decays).

## Context

Two declarations in this project can make an answer count as correct when it otherwise would not.
Only one of them was ever asked for evidence.

`auth_flow_alternates` has carried an evidence requirement since ADR-0023: a first-party URL, not on
a rehosting host, plus a written note, all blocking at `roundtrip`. `endpoint_base_prefix` carried
none — a bare list of strings beside a prose argument in a comment.

The asymmetry was measured this cycle, across every declared tolerance in the cohort: **77 entries,
20 base prefixes and 57 alternates.** Of the alternates, **46 of 57** hold up when the cited page is
actually opened and searched for the style it claims. Of the base prefixes, **3 of 20** have no
first-party artifact writing them at all.

One of those three is the case that decides this ADR. A pack declared a gateway prefix while
recording, **in the same file and before its own grid**, that it had searched every readable
first-party artifact and found the string zero times — zero in the eight OpenAPI documents it
anchors to, zero in a 617,538-byte service directory, zero in a 1,734,934-byte bundle. It declared
the tolerance anyway, on an argument that is not stupid: absorbing a prefix from an *answer*,
symmetrically with ground truth, is not the same act as inventing it into the key. Under a prose
bar, that argument is simply a paragraph, and a paragraph has no way to lose.

### Why this could not wait

The obvious objection is that pre-registration already covers this: write the tolerance down before
the grid, and it cannot be a response to a result.

**Pre-registration is prose, and prose is exactly what was in force one cycle ago.** It let six of
eight uncited spellings through on a single pack — and **three of those six had been
pre-registered**, which is the strongest form the prose bar has. Writing an entry down early makes
it *disclosed*; it does not make it *citable*. What the early writing actually supplied was a better
alibi: by the time anyone asked which of the vendor's documents wrote the gateway that way, the
answer "it was declared before the runs" was available and sounded like evidence.

The cost was not hypothetical. Removing those six moved that pack's cold `endpoint` dimension from
**17.6% to 0.0%** — every run the tolerance had credited was credited by a spelling **only the
measured model produced**. That is the project supplying the one string that turns a wrong address
into a right one, and then reporting the result as the model's knowledge.

ADR-0015 is about precisely this decay: a rule a human must remember to apply is a rule that stops
being applied, and the registry exists because "recorded as open work" is a note that rots. Deferring
this one would have added a 48th recorded hazard whose fix was queued nowhere, in the same cycle that
measured what the hazard costs. The gated form already exists, already works on the sibling field,
and costs an author who has the evidence nothing but the paste.

## Decision 1 — `endpoint_base_prefix` takes `{prefix, evidence, note}`, and nothing else passes the gate

A pack declares each entry as a mapping:

```yaml
endpoint_base_prefix:
  - prefix: /gateway
    evidence: https://developer.example.test/reference/get-widget
    note: >-
      The vendor's own reference page prints the deployed address as
      https://host.example.test/gateway/widgets/v1/... while the operation's `paths` key omits it.
```

`scorer.base_prefix_problems` blocks on: a missing or non-path `prefix`; a missing `evidence:`, one
that is not an http(s) URL, or one on a host `rehosting_host()` names; a `note:` under 40
characters; and a duplicate prefix. Rules 1–3 are ADR-0023's, word for word, because the claim being
made is the same claim.

The duplicate rule is new and small: `_strip_base_prefix` takes the first match, so a repeated
prefix is either dead or a sign the list was assembled from two sources — which is how two entries
for APIs no task addresses ended up in a nine-item list in the first place.

### The bare-string form was counted for one merge, and the reason was deployment

Rule 5 refuses the shape which let three uncited entries stand. It did **not** arrive blocking, and
the one-merge delay is worth recording, because how it was found matters more than that it happened.

The gate ships in this repository; the packs ship in a separate one whose CI clones this
repository's default branch. A `core` that blocks bare strings fails every unconverted pack, and a
converted pack fails against a `core` that cannot read its shape. Neither half can land first. The
first check of this gate reported the armed suite green — against the **converted** packs, the one
baseline on which the conflict is structurally invisible. Run against the unconverted cohort, it
failed eight packs at `roundtrip`. The claim "backward-compatible, blocks nothing" was made from the
wrong control: the same error class the audit that forced this ADR was written to catch, committed
on the audit's own instrument.

So rule 5 landed as a non-blocking count (`scorer.bare_prefix_entries`, reported in the `roundtrip`
control's notes), the cohort was converted in the packs repository, and rule 5 then flipped to
blocking on a set where **17 entries across 8 packs carry citations and 0 are bare**. The counter is
deleted with the state it counted. The sequence is checkable in the merge order: gate → conversion →
flip, each green before the next.

What that ordering bought is the thing prose could not give. A rule asserted to cost nothing, and a
rule *demonstrated* to cost nothing against the exact set it governs, are different claims, and this
ADR exists because the first kind was believed once already.

## Decision 2 — parsing and permitting are separate, so no archived score can move

All three shapes still **parse**. `Pack.declared_base_prefixes` yields the same literal strings
whether they came from a string, a list of strings, or a list of mappings, and
`base_prefix_segments` is unchanged, so every archived `scores.json` re-scores identically. Only the
`roundtrip` **gate** refuses the older shapes.

That split is deliberate. A pack whose numbers are already published must keep reproducing them from
its archives — that is what `rebuild-report` and the reproduction gate are for — while a pack that
wants to *run* must carry its citations. Tying the two together would have forced a choice between
breaking published history and letting the old shape live forever.

## Decision 3 — the gate names itself even when it has nothing to say

`check_pack` always appends an `(endpoint-base-evidence)` control, including for the majority of
packs that declare no tolerance at all. A control that appears only when it fires cannot be observed
to be absent, and a reviewer reading a gate report should be able to see that the check ran.

## What this does not do

- **It checks that a vendor writes the address, not that the address works.** No live vendor API is
  called, here or anywhere in this project.
- **It cannot open the cited page.** The gate checks that a first-party URL is present and is not a
  rehosting host. The audit that forced this ADR found the matching hole in the sibling field: on
  one vendor, eleven alternates cite a page the same repository's manifest records at `byte_size:
  0` — client-rendered, and readable by nobody. A URL that returns nothing satisfies every rule
  either gate has. Requiring the cited URL to be one the pack fetched *with readable content* is the
  next step, filed as issue #97 against both fields rather than assumed.
- **It cannot tell a derived prefix from an invented one.** ADR-0013 licenses writing a path from
  any point inside a declared base, so a suffix of a cited string is legitimately derivable. The
  note is where that distinction has to be stated in words; nothing mechanical enforces it. The
  difference is not subtle in practice — a suffix of the vendor's own base URL is derivable, a
  string appearing in none of the vendor's material is not — but it is the seam where the next
  version of this failure will arrive.
- **It says nothing about the scorer's uniform normalization.** `normalize_path` and its siblings
  widen matching for every pack at once; they are argued in their own ADRs and there is no per-pack
  claim to cite.

## Consequences

- Nine packs declared a tolerance; one had its only entry removed as uncited, and the remaining
  seventeen entries across eight packs were rewritten with citations in the same cycle. The gate
  therefore lands on a set that already passes it and **blocks nothing on arrival** — which is the
  order it was built in deliberately: audit, strip, re-score, then gate.
- Private packs written in the new shape require this change on `main` first. That ordering is
  stated in both pull requests rather than left to be discovered.
- `core/tests/test_base_prefix_evidence.py` breaks every rule on purpose in both directions, and
  pins the must-not-inflate property for the new shape: an entry that carries its citation may not
  match anything the bare string did not.
