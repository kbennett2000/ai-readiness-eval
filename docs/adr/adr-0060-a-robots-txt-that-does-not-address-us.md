# ADR-0060 — A robots.txt that does not address us is not an absent robots.txt

**Status:** Accepted
**Date:** 2026-08-06
**Amends:** [ADR-0052](adr-0052-a-refusal-is-not-an-absence.md) (the five-state ruling — this makes
it six), which itself amended [ADR-0036](adr-0036-robots-txt-is-a-fetch-permission.md).
**Related:** [ADR-0007](adr-0007-docs-fetch-user-agent.md) (the agent a retrieval is judged
as), [ADR-0048](adr-0048-a-declared-rate-limit-is-an-instruction.md) (`Crawl-delay` is a directive
in this file too), [ADR-0056](adr-0056-an-entry-cannot-be-both-retrieved-and-refused.md) (a record
may not assert two incompatible things about one entry), [ADR-0043](adr-0043-the-standard-library-caught-up.md)
(a control that cannot tell *absent* from *broken*), [ADR-0058](adr-0058-a-number-states-what-can-be-rechecked.md)
(what a reader can re-check).

## Context

ADR-0052 split `no-robots-txt` because a 401/403 is a host declining to show a policy it has, and
recording that as "there was nothing there" made this project's conduct record say *nothing was
asked of us* about a server that had just said no. It found five states where there had been four.

There are six. The state it missed leaves no status code, which is why it was harder to see.

`policy_from_response` classified a 200 by asking one question — *did any directive come back?* —
and a host can serve a real, well-formed robots.txt that yields none:

```
User-agent: GPTBot          User-agent: ClaudeBot        User-agent: Bingbot
Allow: /                    Allow: /                     Allow: /
```

`parse` selects the group governing the agent we present, falls back to `*`, and returns
`groups.get("*", [])`. Where the file declares **no `*` group** and names no group matching our
agent, that is the empty list — the same empty list a 404 produces, the same empty list a JavaScript
shell produces. All three fell through `if not directives:` to `SOURCE_ABSENT`, and every manifest
page on that host published `robots_source: no-robots-txt`.

**The measured case.** The documentation host that raised public issue #107 serves a **386-byte**
robots.txt over HTTP 200 as real `text/plain`, naming **ten** crawler groups and granting each of
them `Allow: /`, with no `*` group anywhere in it. The recon record that captured it wrote down, in
the same file and before the pack's manifest existed, that the permission was right and the recorded
provenance was not.

That is ADR-0052's distinction reached from the other direction, and its argument transfers whole:

> **It permits exactly what an absence permits, and it says something different about the world.**
> And, like a refusal, it is a fact about a **conversation** rather than about the host — the same
> file addresses ten other readers by name. An absence generalises; this does not.

The asymmetry worth naming is that a refusal was *visible*. A 403 has a status code, so the record
had somewhere to look. This state's only trace is an empty directive list, which is precisely what
the state it was collapsed into also leaves. Nothing was going to surface it except reading a body.

## Decision 1 — a sixth state, for a served file that declares groups and names none of ours

```python
SOURCE_NO_GROUP = "robots.txt-no-group-for-agent"
```

Named for the fact rather than the shape, and prefixed like `robots.txt-refused` and
`robots.txt-unreachable` so a reader sees at a glance that a **file was served**. The suffix carries
the half that matters: not that the file is empty, but that it does not address the reader that
arrived.

The condition is `group_names and not governed` — the body declared at least one `User-agent` group,
and neither a named group matching our agent nor a `*` group is among them. `parse` could not report
either fact, and widening its three-value contract would have meant editing a dozen callers and
twenty tests to carry something only `policy_from_response` uses; so the parse moved into `_Parsed`
and `parse` became the narrow view of it. **No caller changed.**

In this branch `directives` is empty **by construction and not by coincidence** — the lookup returns
`groups.get("*", [])` and `"*"` is absent in exactly this case — so the branch ordering rests on no
property of any particular body.

**Permission does not move.** `verdict()` special-cases only `SOURCE_UNREACHABLE`; a state with no
directives allows every URL, identically to `SOURCE_ABSENT`. That was already true and is now
asserted over a path matrix rather than reasoned about, because it was equally derivable in ADR-0052
and that ADR wrote the test anyway. **No URL's `robots_disallowed` moves, in any pack.**

`crawl_delay` is `None` here for the same structural reason, which is also the right answer: a rate
a host asked of a crawler it named is not a rate it asked of us (ADR-0048).

## Decision 2 — the annotation says `(none)`, not `*`

`agent_group` is the field that lets a reviewer re-derive the verdict: *which group applied*. In
this state the old code recorded `*`, because that is what the directive lookup fell back to.

There is no `*` group. A row reading `robots_source: robots.txt-no-group-for-agent` beside
`robots_agent: '*'` asserts both that no group addressed us and that the wildcard group applied —
one entry, two incompatible claims, which is the shape ADR-0056 refused. `AGENT_GROUP_NONE =
"(none)"` is truthy, so the standing sweep's *every page says which agent decided it* assertion is
unweakened, and unambiguous in YAML.

Zero manifests carry the new state, so this moves nothing today. It is written down because the
first pack to carry it would otherwise inherit the contradiction.

## Decision 3 — the two neighbouring cases are deliberately NOT split

Both remain `no-robots-txt`, and the boundary is what makes this a state rather than a catch-all:

- **A body declaring no group at all.** One measured host answers `/robots.txt` with its site-wide
  JavaScript shell. ADR-0036's argument is untouched and still right — the question is whether the
  host stated a rule, and a page with no rules in it did not.
- **A group that does govern us and states no `Allow`/`Disallow`.** `User-agent: *` followed only by
  `Crawl-delay: 7` is a host that **addressed us** and asked one thing of us. Being addressed and
  asked nothing is a different fact from not being addressed, and the delay still travels (ADR-0048).

Splitting either would have made the new state mean "we got no directive", which is the reading that
produced the defect in the first place.

## Decision 4 — the record's vocabulary is enumerated, not restated

`test_robots_annotations` validated every committed `robots_source` against a hand-written set of
five, and its own comment recorded why that was a defect: the list *"went stale the moment ADR-0052
landed and was caught by the first pack to carry the new state — which is the argument for
enumerating it from `core.robots`"*.

A sixth state would have gone stale the same way, in the same file, one ADR later. The set is now
derived from the module that defines the vocabulary, so a seventh state is admitted to the sweep
automatically and cannot reach a **manifest** silently. Taking a fix a file has already written
about itself is cheaper than paying for it twice.

## The offline question, and why it is the larger finding

Before any of the above could be applied to an archive, one question had to be answered: **can a
committed annotation be reclassified from the record?** That needs the robots.txt bytes at their
pinned fetch. They are not there.

`ANNOTATION_FIELDS` is five keys and neither the body nor the HTTP status is among them.
`RobotsPolicy.body` is populated in-process and never persisted — no manifest field, no cache file,
no results artifact, in either repository. Measured across the cohort:

| | |
|---|---|
| annotated manifest entries | **438** across **20** packs |
| entries recording `no-robots-txt` | **140** across **8** packs |
| distinct `robots_agent` values recorded, cohort-wide | **1** — `'*'`, on **409 of 409** |

The four inputs that produce `no-robots-txt` and the one that now produces `SOURCE_NO_GROUP` are
indistinguishable once the body is dropped, and `robots_agent` cannot break the tie because it is
`'*'` for all of them by construction. **So no archived pack is reclassified by this ADR, and none
moves.**

Re-fetching is refused rather than merely skipped: it would record today's policy against a date the
archive pins, which is evidence about now. The one host whose bytes exist proves the point rather
than softening it — they exist because a person hand-transcribed them into a recon `specs.yaml`. The
fetcher that produced all 438 annotations stores nothing.

Filed as **public issue #110** in its general form, which is where the interest is: *a provenance
field records a conclusion and discards the evidence for it.* Robots is the instance; the class
covers any field recording a verdict about a fetched artifact. It is not fixed here because it
changes the manifest schema and rests on design calls nobody has made — per-page or per-host, full
body or hash, status code separately — and bundling it would have decided them by default.

## Consequences

- The conduct record can now say *this host served a policy and did not address us*, where before it
  could only say *there was nothing there*.
- **Zero manifests, zero annotations and zero numbers move.** No pack can be reclassified into the
  new state, and the pack whose recon raised #107 has no manifest yet — so landing the state now
  means its record is written correctly the first time rather than repaired later.
- The first pack to record the state fails `test_no_archived_manifest_records_the_new_state` by name,
  which is the disclosure that test exists to force rather than a defect.

## What this does not do

**It does not backfill, and now there is a measured reason.** ADR-0052 recorded the same limit as a
possibility — *"a host that refused a past fetch is recorded as absent and this ADR cannot tell
which"*. This one can say why: the inputs were never stored. That is issue #110, not a footnote.

**It demands no written declaration in `specs.yaml`.** ADR-0052 Decision 2 made a refused host cost
a pack a sentence, and the symmetry is tempting. It is refused here on two grounds: #107 is a record
fix and a gate is a permission change by another route, and a gate would be **vacuous on arrival** —
nothing can be reclassified into the state, so it would guard a set that is empty for reasons
unrelated to compliance. The first pack to record one is the place to decide it, with a real case in
hand.

**It does not detect a host serving different files to different agents.** ADR-0052's standing
hazard, and this state sharpens rather than closes it: a file that names ten crawlers and not us is
the clearest possible evidence that what a host says depends on who asks, and nothing here fetches
twice to find out. Registered ungated.

**It does not let us take a named crawler's grant.** The measured body grants `ClaudeBot` `Allow: /`,
and this state is one header away from claiming it. ADR-0007 settles it — the policy a retrieval is
judged against has to be the policy for the agent it presented itself as — and the answer is still
no. Pinned as a test on the exact body that offers the grant, rather than left as a sentence.

**Its archive sweep checks the classifier, not the record.** `test_robots_state_archive` asserts that
every committed provenance string still means what the classifier says it means, so a state stealing
cases from another fails by pack name over 438 real entries. It cannot recover an entry's inputs, and
the assertion that no manifest records the new state is true on arrival and unable to fail today —
both stated in the test rather than left for a reader to notice.
