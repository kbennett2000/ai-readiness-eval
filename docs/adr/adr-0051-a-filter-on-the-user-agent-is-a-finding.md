# ADR-0051 — A filter on the User-Agent is a finding, and the column that prices it says what it said

**Status:** Accepted
**Date:** 2026-08-03
**Builds on:** [ADR-0050](adr-0050-a-specification-is-not-documentation.md) (a fourth condition, and
the `_InjectedTextCondition` extension point it created),
[ADR-0034](adr-0034-an-anchor-is-not-an-injection.md) (a separate key, not a per-page flag),
[ADR-0007](adr-0007-docs-fetch-user-agent.md) (a bot-gated docs host is a fetch policy),
[ADR-0036](adr-0036-robots-txt-is-a-fetch-permission.md),
[ADR-0017](adr-0017-endpoint-base-prefix.md) (why a denylist, not an allowlist).

## Context

Some documentation hosts decide what to return from the `User-Agent` string.

The next queued target is one. Every path on its developer portal — including `/robots.txt` — answers
**HTTP 403 from a load balancer** to this project's plain self-identifying agent, and **HTTP 200 from
the application** to a conventional one. Measured across four surfaces, twice each, at the same
moment: the responses to `Mozilla/5.0 (compatible; ai-readiness-eval-docs/1.0)` and to a current
browser string are **byte-identical, hash for hash**. `curl/8.5.0` and `Python-urllib/3.14` are
refused exactly as the plain agent is.

So the filter is a **`Mozilla/` prefix rule**, not a browser check. What it excludes is precisely the
agents honest enough not to open with a vestigial browser token.

That leaves `public-docs` injecting nothing for every task, and the resulting gap measuring our own
prompt rather than the vendor — the shape three consecutive packs have now published, and the one
issue #67 exists about. It would be a *true* finding and a nearly useless one: it would say a
compliant reader is refused, and say nothing about whether the documentation behind the filter would
have answered the question.

## Decision 1 — a fourth condition, named for what it injects

`gated-docs` injects the vendor's own documentation **as served to a conventional self-identifying
agent**. Registered only for a pack declaring a `gated_docs` block, exactly as `raw-spec` is gated on
`raw_spec` and `mcp` on `context_layer` — never on the manifest happening to carry a list, because a
column is a claim.

`public-docs` is unchanged and stays honest-agent for every task and every vendor. Where it comes
back empty, that is the finding and it leads the card.

**What the pair measures is the filter, not the documentation.** Every other input is held constant
on purpose: the same URLs, the same budget, the same prompt, the same tasks, the same model. The only
variable is the string this project puts in one header, so the difference between the two columns is
the price of that string and nothing else.

Subclassing `_InjectedTextCondition` is what made this small. ADR-0050 built that base class to hold
the budget, the role priority, the robots re-check at point of use and the drop-then-truncate
assembly once, with `manifest_key` as a class attribute. A fourth condition is therefore a name, a
key and a label. This cycle is the evidence that abstraction was worth building rather than a guess
that it would be.

## Decision 2 — a fourth manifest key, and this is the case where a flag would be worst

`gated_pages` is its own list beside `pages`, `anchors` and `spec_documents`.

The tempting alternative here is stronger than it was for either previous key, because the two lists
hold the **same URLs**. `pages[].user_agent` reads like a small, local annotation.

It is the worst of the three cases. ADR-0034 refused `pages[].inject: false` to make one mistake
unrepresentable; refusing `pages[].user_agent` makes the mirror-image mistake unrepresentable, and
here the two bodies come from **one address** — a 403 stub and the document. A per-page flag would
make it one typo's work to inject the document into the column whose entire finding is that the
document did not arrive, and nothing downstream could show it: a transcript of a model that read the
document is a transcript of a model that read the document.

Two consequences follow and both are enforced rather than remembered:

- **The agent is selected by LIST, not by page.** `fetch_all` takes `key_user_agents`, a mapping from
  manifest key to agent, and resolves each host's robots policy *with the agent that will make the
  request* — a policy fetched as one agent says nothing about what another is permitted.
- **The two retrievals of one URL do not share a cache file.** `gated_pages` caches under its own
  subdirectory. Without that, one file is written twice and whichever list is fetched last decides
  what *both* columns inject. Every other key resolves to the path it always did, byte for byte, so
  no cached snapshot is invalidated and no committed `cache_file` moves.

## Decision 3 — the declared agent must name this project, and a browser string is refused in code

`gated_docs.user_agent` is required, has no default, and is published verbatim on the card.

`pack.py` refuses to load a pack whose declared agent impersonates a browser. Two independent tests,
because either alone lets a real browser string through: any rendering-engine or browser-product
token (`AppleWebKit`, `Chrome/`, `Gecko/`, `Safari/`, `Firefox/`, `Edg/`, `Trident/`, `Version/`,
`Mobile/`, …), or a `Mozilla/`-prefixed string whose parenthetical does not open with `compatible;`.

**`Mozilla/5.0` alone is deliberately legal**, and that is the load-bearing exclusion. It is a
vestigial token every conventional crawler carries; banning it would ban the one honest form that
passes a filter of this kind, leaving impersonation as the only route through — the opposite of the
rule. The denylist is a denylist and not an allowlist for ADR-0017's reason: an allowlist fails
**open** on the string nobody thought of, and the string nobody thought of is what a cycle under time
pressure pastes in.

The argument, stated so it can be rejected: a column obtained by claiming to be a browser would
measure what a vendor shows a reader it was deceived about. That is not a fact about AI readiness,
and no honest number can be built on it. Whether a host's filter *intends* to admit conventional
crawlers is not knowable from here and is not claimed — what is claimed is only what this project
said about itself, which is why the string is a field a reviewer reads rather than a default anyone
can inherit.

**The precondition this ADR does not get to skip.** If a host's `robots.txt` were retrievable *only*
under a browser string, permission could not be established honestly at all, and fetching it that way
would be using the disguise to obtain the authorization for the disguise. The condition would then
not run, and the filter would be the pack's lead finding on two conditions. That branch is written
down here because the target that forced this ADR happens to fall the other way, and a rule tested
only where it is free has not been tested.

## Decision 4 — the same budget, and the same disclosure

**Budget:** `public-docs`'s, with no field to change it. ADR-0050's argument, sharper here: these two
columns are drawn from the same URLs, so any budget difference between them would be
indistinguishable from the effect being measured.

**Disclosure:** where a task's `gated_pages` and its `anchors` are the same URL, the condition is
scored against its own source and the pack must say so in writing, per task. This bites harder than
it does for a specification and the reason belongs in the record: on a filtering host the withheld
pages are also the only first-party artifact a ground-truth citation can point at, so the **overlap
is the expected case rather than the exception**. A pack reporting a large `gated-docs` number
without saying so would be publishing a ceiling as a readiness measurement.

The rule and its gate are shared with `raw-spec` rather than copied — one `_overlap_disclosure`, one
`_check_disclosure_records`, one `disclosure` stage covering both. Two copies would drift, and the
way they would drift is that one of them quietly stops being run.

## Consequences

- A pack on a filtering host can report three columns: cold, what a compliant reader is given, and
  what the vendor serves a reader that opened with the conventional token.
- **The column is comparable to no other vendor's `public-docs`**, and the card must say so.
- No existing pack declares `gated_docs`, so no registry, no manifest and no published number moves.

## What this does not do

**It does not establish that the filter is deliberate.** A WAF rule is a configuration, not a policy
statement, and this ADR claims only what was measured: which strings were served and which refused,
on a date.

**It does not make the empty `public-docs` column meaningful.** That column still carries the
excerpt-promise contamination issue #67 describes. A pack must cite the measured cost from the pack
that quantified it rather than re-derive it as a fact about this vendor.

**It cannot tell a filter from an outage.** A host returning 403 to one agent for an hour and to
everyone the next is indistinguishable here from a standing rule. The three-agent comparison is run
at one moment and is a snapshot, which is why the card carries the date and the raw byte counts.
