# ADR-0052 — A refusal is not an absence, even though it permits the same things

**Status:** Accepted
**Date:** 2026-08-03
**Amends:** [ADR-0036](adr-0036-robots-txt-is-a-fetch-permission.md) (the four-state ruling — this
makes it five).
**Related:** [ADR-0043](adr-0043-the-standard-library-caught-up.md) (a control confused absent with
broken), [ADR-0051](adr-0051-a-filter-on-the-user-agent-is-a-finding.md) (the host that forced it),
[ADR-0031](adr-0031-a-prompt-must-name-its-target.md), [ADR-0045](adr-0045-a-dimension-with-no-task.md)
(a written reason, never a boolean).

## Context

`core/robots.py` has four states, and ADR-0036 argued each of them: `robots.txt` (rules served and
applied), `no-robots-txt` (4xx or a body with no directives → unrestricted), `robots.txt-unreachable`
(5xx or network failure → the whole host disallowed), `host-does-not-resolve` (NXDOMAIN, distinct
because a host that is not a server never issued an instruction).

The 4xx branch was one line: `if status >= 400: SOURCE_ABSENT`. That is RFC 9309 §2.3.1.3 and it is
correct about permission. It is silently wrong about the record.

**Found by reading a record this project generated.** A recon consulted `robots.txt` on fourteen
candidate hosts under two agents, before any content request, and wrote an audit table. For the host
that refuses this project's plain agent on **every path including `/robots.txt`**, the table said:

    developer.<host>    source: no-robots-txt    verdict: PERMITTED

Both cells are defensible under RFC 9309 and the first one is not true. The host has a robots.txt. It
serves it — to a reader that opened with a different `User-Agent`. What it did to us was **decline**,
and "no robots.txt" is a claim that it never had one to decline with.

This is ADR-0043's fault class — a control that cannot tell *absent* from *broken* — arriving in the
module that makes this project's conduct claims, which is the worst place for it. A conduct record is
the one artifact where "nothing was asked of us" must not stand in for "we were told no".

RFC 9309 says so itself: §2.3.1.3 permits a crawler to access resources after a 4xx and notes that a
401 or 403 may indicate the crawler is not authorized. The standard distinguishes; the code did not.

## Decision 1 — a fifth state, for 401 and 403 only

`SOURCE_REFUSED = "robots.txt-refused"`.

**It permits exactly what `SOURCE_ABSENT` permits.** No URL becomes forbidden, no fetch is prevented,
no number moves. A test asserts the permission half over all four 4xx statuses precisely so a later
edit cannot quietly turn a recording change into a prohibition.

What changes is the string a manifest publishes and a card cites. And one more thing worth stating,
because it is the reason this is not pedantry: a 401/403 on `robots.txt` is a decision about the
**requesting agent**, not about the file, so the same host may serve the file to a different reader.
An absence is a fact about the host. A refusal is a fact about a conversation, and it does not
generalise.

Statuses 404 and 410 keep `SOURCE_ABSENT` and mean what they always meant.

## Decision 2 — a refused host must be named in the pack, in writing

`check_recon` refuses a pack that has a manifest page annotated `robots.txt-refused` for a host its
`specs.yaml` says nothing about. The declaration is `robots_refusals: {host: reason}`.

A written reason and not a boolean, for ADR-0031's and ADR-0045's argument: a flag records that
someone clicked past the question and a sentence records what they thought, which is the thing a
reviewer can disagree with.

The obvious sentence — *the host filters on the User-Agent string; a conventional self-identifying
agent was served the file and it declares no rules* — is exactly the disclosure a reader of a
`gated-docs` column needs, and it should cost a pack something to write it.

Two rules, not one, because the second is where the first decays:

1. A refusal with no declaration **blocks**.
2. A declaration for a host that did **not** refuse also blocks — and that check runs *before* the
   "nothing refused, nothing to do" early return. Without that ordering, a pack whose host stopped
   refusing keeps a sentence describing a refusal that no longer happens, and the gate reports "no
   host refused its robots.txt" and passes. A disclosure that is not true is worse than none: it
   teaches a reader to discount the ones that are.

The check reads the annotation the fetcher already writes, across **every** manifest list. An anchor
or a gated page that was refused is as real as an injected page that was.

## Consequences

- The conduct record can now say *we were refused* where before it could only say *there was nothing
  there*.
- **Measured over every pack on disk: 0 have a refused host, so 0 manifests and 0 numbers move.** The
  first pack to record one is the pack whose target forced this ADR.
- A recon on such a host now has to write a sentence it could previously omit without noticing.

## What this does not do

**It does not detect a host that serves a different robots.txt to different agents.** Only a refusal
is visible, and only because a refusal has a status code. A host that returns `Disallow: /` to one
agent and `Allow: /` to another is undetectable without fetching twice, and nothing here requires
that. Registered as an ungated hazard rather than dressed up as a guard.

**It does not decide whether to read a refusing host.** RFC 9309 permits it and this project's answer
is recorded per pack, in the sentence the gate demands, rather than legislated here for cases nobody
has met yet. The one case that IS legislated lives in ADR-0051: a host whose robots.txt can be
obtained *only* by impersonation has not granted permission that impersonation could establish.

**It does not backfill.** Existing manifests were annotated under the old ruling, so a host that
refused a past fetch is recorded as absent and this ADR cannot tell which. Re-fetching would
re-annotate; nothing forces it, and that is a real limit rather than a hidden one.
