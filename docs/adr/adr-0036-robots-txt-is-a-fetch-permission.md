# ADR-0036: `robots.txt` is a fetch permission, not a crawl suggestion

## Status

Accepted. Fetcher, condition and a new `core/robots.py`; no scorer, parser, prompt or ground-truth rule
is touched, no committed `scores.json` changes, and the frozen 73/68/93 regression is unmoved.

## Context

This method retrieves a vendor's own documentation and injects it as the `public-docs` condition. For
the whole life of the project, the question of whether the vendor's host *permitted* that retrieval was
never asked. `docs_fetch.fetch_all` opened a URL because a manifest named it. Thirteen packs, 271
manifest URLs across 16 hosts, every one fetched on that basis.

The question arrived attached to a target. A vendor's developer portal serves its API reference openly,
unauthenticated, server-rendered — and its `robots.txt` Disallows the entire documentation tree,
including the machine-readable specification endpoints. Nothing in the harness would have noticed. The
grid would have run, the card would have rendered, and the numbers would have been produced from pages
we had been told not to take.

Two things then had to be settled, and only one of them is about this vendor.

**First, what the harness does.** A fetcher that reads a host's instruction and proceeds anyway is not
a measurement instrument with an edge case; it is a badly-behaved crawler with a report generator
attached. Every finding this project publishes rests on the claim that it observed a vendor's public
surface the way a well-behaved integrator's tooling would. That claim cannot survive selective
compliance.

**Second, what a Disallow *is*, for a project that measures documentation.** It is not an obstacle. It
is one of the most consequential facts that can be true about an API's documentation, and it is
measurable: content excluded by `robots.txt` is excluded from the general web crawls that build
pretraining corpora, so a Disallowed API reference is absent from retrieval today *and* absent from the
corpus that would otherwise teach any model that API. Stated clinically, that is a finding about
reachability with a larger blast radius than any gap this project has measured — and it is the vendor's
own instruction, which is what makes it citable rather than inferred.

## Decision

**The harness never fetches a Disallowed URL, for any vendor. A Disallowed documentation set is a
measured finding, recorded and quoted, and never routed around.**

### `core/robots.py`, and why not `urllib.robotparser`

The standard library's matcher is `path.startswith(pattern)` with no wildcard or anchor support. On the
two directive forms that decided this cycle it is wrong in both directions: `Disallow: /*/api-next`
matches nothing (no path begins with a literal `/*/`), and `Disallow: /wfm$` matches only paths that
begin with the characters `/wfm$`. A parser that mis-reads the only two rules at issue cannot carry a
conduct claim, so RFC 9309 is implemented directly: `*`, `$`, longest-match precedence, `Allow` winning
an exact-length tie, and `Disallow:` with an empty value meaning *allow all*.

### Four states, because collapsing them fabricates claims

| the host | ruling | why |
|---|---|---|
| served directives | apply them | the ordinary case |
| answered 4xx, or served a body with no directives in it | unrestricted | RFC 9309 §2.3.1.3. Four cohort hosts rely on it; one answers `/robots.txt` with its site-wide JavaScript shell |
| answered 5xx, refused the connection, or timed out | **the whole host is disallowed** | §2.3.1.4. A fetcher that reads a timeout as a green light has a preference, not a policy |
| **does not resolve** | unrestricted, recorded as `host-does-not-resolve` | a server declining to state a policy and the absence of a server are different facts |

The fourth row was not in the plan. Folding NXDOMAIN into "unreachable" made the first cohort-wide run
report **eleven violations against a pack whose documentation host had simply ceased to exist** some
time after it was measured. That is a conduct accusation the evidence does not support, and it would
have been published in a card's disclosure. The branch exists because the collapsed version produced a
false claim on the first real input — which is the argument for the split, and also the reason it is
recorded here rather than fixed quietly.

### The group is chosen by the agent actually used

A pack may present a browser User-Agent to a bot-gated host (ADR-0007); one does. It must then be
judged against the group that host publishes for that browser. Judging a browser-string request against
the `*` group would describe a request nobody made.

### Permission is read at the point of use, not only at fetch time

`PublicDocsCondition` skips any page marked `robots_disallowed`. This is not redundant with the fetch
refusal, and the redundancy is the point: refusing to *re-*fetch leaves any snapshot an earlier fetch
already took sitting in the gitignored cache, so a host that adds a Disallow after we fetched would
otherwise keep being injected from disk indefinitely. The refusal also deletes the stale snapshot —
the cache is regenerable, and keeping bytes we are no longer permitted to retrieve is the thing being
refused.

### The disclosure is checked evidence, not authored prose

Every manifest URL — `pages` and `anchors` alike, because an anchor is fetched to verify the citation
it carries (ADR-0034) — records five fields: the verdict, the matching directive verbatim, which of the
four states produced it, when the host was read, and which agent group applied. `annotate-robots`
writes them; `--check` re-reads the hosts and reports drift, so a host tightening its `robots.txt` after
a pack was authored is a detectable event.

**The suite that enforces this is offline.** It reads the committed annotations and never opens a
socket. A test that fetched would make every run depend on sixteen vendors' uptime, and a green suite
would then mean "the hosts were up" rather than "we were permitted".

## Consequences

- **The audit is clean, and now it stays checkable.** 271 URLs across 16 hosts: none is Disallowed. No
  published card needs a retraction and no vendor was fetched against instruction. That was worth
  knowing before the next grid, and it was worth knowing as a checked property rather than as a result
  someone once ran.
- A pack may not name a page its host disallows. The Disallow is recorded in `specs.yaml` as a finding
  and stated on the card instead.
- A vendor whose documentation is entirely Disallowed cannot be measured by this method at all, because
  ground truth may not anchor to a document the manifest may not name. That is a **block**, and the
  block record is the deliverable.
- `MIN_TEXT_BYTES` (ADR-0021) and the `short_text_ok` waiver are untouched: a refused page never reaches
  the text floor, because it never reaches a fetch.

## What this does not do

It does not make the project a general web crawler with a compliance layer; it fetches a small,
hand-enumerated set of URLs, once, with an honest self-identifying agent (ADR-0007) and a declared pace
(ADR-0009). The ruling narrows what that set may contain.

It does not re-check anything automatically. The annotations are a snapshot with a date on them, and
they go stale exactly as a docs snapshot does. `--check` is the refresh, and a cycle has to run it; the
suite can prove the record is complete and internally consistent, never that it is current.

It says nothing about what a vendor *should* publish or how they should configure their host. The
finding is a measurement of reachability, stated with its evidence, and the reasons a vendor may have
for excluding crawlers are their own.
