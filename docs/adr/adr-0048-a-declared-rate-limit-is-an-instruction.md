# ADR-0048 — A declared rate limit is an instruction in the same file as the one we already obey

**Status:** Accepted
**Date:** 2026-08-03
**Follows:** [ADR-0036](adr-0036-robots-txt-is-a-fetch-permission.md) (robots.txt is a fetch permission,
not a crawl suggestion), [ADR-0047](adr-0047-a-control-that-was-run-twice-is-code.md) (a control that
was run twice by hand is code), [ADR-0009](adr-0009-throttled-docs-fetch.md) (the pack
fetcher paces itself from a declared delay), [ADR-0015](adr-0015-hazard-registry.md) (a note that
decays).
**Refs:** issue #87.

**No scorer, parser, prompt, fixture, task or `results/` path is touched. Every committed `scores.json`
is byte-identical and the frozen 73/68/93 is unmoved. $0, no model run.**

## Context

`core/robots.py` reads a vendor's `robots.txt` and refuses to fetch what it disallows. It has done that
unconditionally since ADR-0036, across thirteen packs and 242 manifest URLs, and the refusal is reported
as a measured finding rather than routed around.

The same file, on the same hosts, also carries `Crawl-delay`. The parser did not keep it. It kept
`user-agent`, `allow` and `disallow`, and every other field fell off the end of the loop without ever
being looked at — so a host asking to be read slowly was obeyed on the half of its file that says *what*
and ignored on the half that says *how fast*.

That was invisible while `docs_fetch` was the only fetcher, because it paces itself from a delay the
pack declares (ADR-0009). ADR-0047 then added `core/controls.py`, which issues **seventeen requests to
one host** — two nonsense paths for the soft-404 baseline, fifteen well-known specification paths — as
fast as the host answers. The first target measured with it declared `Crawl-delay: 10` in the group we
fall under. That recon was paced correctly, by wrapping the injected `get` in a sleep, **by hand, in a
scratch script**, and the gap was filed as issue #87 the same cycle rather than fixed.

Filing was the right call under ADR-0016 — it changed no published number and could not put a wrong
claim in front of a vendor. Fixing it now is also the right call, and the reason is ADR-0047's own: the
control is code that cannot emit the wrong answer, and the *conduct* around it went back to being
something a cycle has to remember. The next recon would have been the third in a row paced by memory.

**A correction to the issue's premise, recorded because the issue is the record.** #87 states that
`core.robots.parse` "already reads the directives and discards this one." It does not. There is no
branch for `crawl-delay` to be discarded by; the value was never seen. The fix is a parse change, not a
plumbing change, and the difference matters to anyone reading #87 to check this work.

## Decision 1 — `Crawl-delay` is parsed, per group, and carried on the policy

`parse()` returns `(directives, agent_group, crawl_delay)` and `RobotsPolicy` gains `crawl_delay`. The
delay is read for **the group that governs this agent**, by the same longest-substring selection already
used for rules, so a rate declared for `*` does not reach a group that names us.

It is not part of RFC 9309 and Google ignores it. This project does not, because the question here is
not what a search crawler may skip — it is what a vendor asked an automated reader to do, in the one
file this project already treats as binding. Obeying the `Disallow` and discarding the rate three lines
below it was never a considered position. It was what happened when a parser kept two field names.

Four rulings inside that, each of which is a judgement rather than a lookup:

- **`None` and `0.0` are different answers.** `None` is a host that never raised the question; `0.0` is
  a host that considered it and declared no delay. A caller that collapses them cannot tell *unpaced by
  permission* from *unpaced by default*, and only one of those is a fact about the vendor.
- **A malformed or negative value is `None`, not `0.0`.** `0.0` would read downstream as "this host
  permits an unpaced burst" — a permission a typo did not grant.
- **A group stating the delay twice gets the slowest of them.** Duplicates are malformed and no
  convention rules on them, so the tie breaks towards the host. Waiting longer than asked can only be
  more polite; the other direction cannot say that.
- **A `crawl-delay` line neither opens nor closes a rules group.** Only `allow`/`disallow` set
  `in_rules`, exactly as before. This is the ruling with teeth, and the case that forced it is a **fetch
  permission**, not a rate: given

  ```
  User-agent: ai-readiness-eval-docs
  Crawl-delay: 5
  User-agent: *
  Disallow: /
  ```

  treating the delay as a group terminator leaves our named group holding no rule at all, which reads as
  an absent robots.txt — and this host's site-wide `Disallow` never reaches us. A rate-limit directive
  must not be able to hand this project a green light. Gated by
  `test_a_crawl_delay_line_does_not_re_cut_the_rules_groups`.

**A named group that states no delay is unpaced, and that is deliberate.** A named group *replaces* the
wildcard group — this module already asserts that for rules — and the delay follows the same semantics,
or the policy in force is half one group and half another, which is a thing no host wrote. The tension
is real (the wildcard rate is evidence about intent) and is resolved towards consistency with the
permission semantics, because those are load-bearing and this is not.

## Decision 2 — the controls pace themselves, and one pacer covers the seam

`Pacer` holds the rate, its source, and the running count; `soft_404_baseline`, `well_known_spec_probe`
and `run_controls` take `delay_seconds`, `sleep` and an optional shared `pacer`. Absent an explicit
delay, **the host's own is used**. A caller reaching straight for the sweep is paced without asking for
it — the hazard was never that `run_controls` bursts, it was that pacing lived outside the module.

- **One pacer, built once in `run_controls` and passed down.** Two pacers would each treat their own
  first request as owing nothing, so the last baseline probe and the first sweep probe would fire back
  to back — the one gap a per-function pacer structurally cannot see.
- **The robots.txt retrieval counts as a request.** It goes to the same host moments earlier, so the
  first content probe genuinely owes a wait. A pacer starting at zero would fire it back-to-back with
  the very file that asked for the delay.
- **A refused path costs no wait.** `before_request` sits at the point of retrieval, and a robots
  refusal never reaches it. Pacing a request nobody issued would be theatre, and would make the record
  overstate its own conduct.
- **The unrelated reachability host is not paced by the target's rate.** One host's declared rate is not
  an instruction the next host issued.

## Decision 3 — the robots check belongs to every control at once, not to whoever remembered

Found while reading this module before pointing it at a real host, which is the only reason it is in
this ADR rather than in a later one: **`reachability_control` did not consult robots.txt.** It called
`_probe` directly and would have issued a request to whatever unrelated host a recon named, without
asking that host whether an automated reader was welcome.

That is the **third** function in this module to need the check said out loud. ADR-0047 records the
baseline probe missing it while the sweep had it. This one missed it while both the others had it. Two
instances is a bug; three is a shape, and the shape has a cause worth naming: **a control reads like
instrumentation rather than retrieval, and instrumentation feels exempt.** It is not. It issues a
request to somebody's server, and being an unrelated third party is not consent.

So the rule is now asserted **over every entry point at once** rather than wherever someone thought of
it. `test_every_control_that_fetches_consults_robots_first` parametrises the module's fetching entry
points and asserts, on the **call log**, that a `Disallow: /` host receives nothing from any of them.
Its companion derives the same set from the source with `ast`, so a fourth control added later fails
*there* instead of quietly escaping the sweep — the list the sweep iterates is the sweep's real
weakness, and it is now checked against the code rather than against memory.

Two further rulings fall out:

- **The unrelated host owes its own robots.txt.** `run_controls` deliberately does not pass the
  target's policy down to the reachability control; inventing permission for one server out of another
  server's file is not a smaller error than not asking at all.
- **A refused reachability control is not a passing one.** It joins the thin case in `notes`: an
  absence of evidence about the fetcher, not evidence that the fetcher works.

## Decision 4 — an over-budget run is refused, never quietly paced faster

A host is free to declare `Crawl-delay: 3600`. Seventeen probes at that rate is seventeen hours, which
in an unattended cycle is a hang — and the tempting repair is to pace faster than asked, or to cap the
delay at something "reasonable". Both are the same move: deciding that this project's schedule outranks
the vendor's instruction.

`MAX_TOTAL_WAIT_SECONDS = 600` bounds the **waiting**, not the delay. The whole projected wait is
checked before any request is issued, and exceeding it raises `PacingRefused` with the arithmetic
stated. Nothing is requested, so nothing is claimed either way: that is a blocked probe, not a failed
one, and a recon records it as a host left unprobed. The budget is raised by a deliberate argument
(`--max-wait`); pacing faster than a host asked is not an option the command offers.

## Decision 5 — the record states the rate, its source, and what was actually waited

`as_record` emits `pacing: {delay_seconds, delay_source, requests_issued, total_waited_seconds}`, and
`delay_source` is one of `robots` / `explicit` / `none-declared`. *"We paced"* and *"we paced because
the host asked us to"* are different claims, and a record carrying only the first is not evidence. An
explicit delay that undercuts a declared one also lands in `notes`, because overriding a vendor's stated
rate is a decision and belongs on the record where a reviewer will meet it.

`total_waited_seconds` is the **observed** total, not `delay × requests`. A derived restatement of the
intent would stay right while the pacing broke, which is the vacuous-green shape this project keeps
closing.

## Consequences

- `parse()`'s return arity changes from 2 to 3. It had exactly one caller, inside its own module.
- `docs/hazards.yaml`: `the-controls-do-not-honour-a-crawl-delay` moves **ungated → gated**. Its
  `ungated_reason` argued that "a unit test asserting that `run_controls` sleeps would pin an
  implementation rather than the conduct". That is true of a test which patches `time.sleep`, and false
  of one handed a recording function — the same move that made ADR-0047's conduct tests assert on the
  call log rather than the verdict. The old reason is kept in the entry, superseded rather than deleted,
  so the record shows the objection was answered instead of forgotten.
- Twelve rules, each broken on purpose and each caught. **Two of the first four sabotages were not**,
  and both tests were rewritten: one asserted group re-cutting on a body where a `Disallow` had already
  opened the group, so the flag it meant to test made no difference; the other never gave the wildcard
  group a delay our group lacked, so a `delays.get(chosen) or delays.get("*")` fallback had nowhere to
  show. Recorded because a test that cannot fail is the exact thing this project keeps finding.

## What this does not do

**It paces this project's own probes. It is not a rate limiter.** Nothing here governs a recon script a
future cycle writes outside `core`, or a `WebFetch`, or a paced sweep done by hand. The `docs_fetch`
path still paces from the pack's declared delay rather than from the host's, which is now an
inconsistency with a name: the two fetchers read the same file and take their rate from different
places. Not fixed here — `docs_fetch`'s delay is pinned per pack and reaching into robots for it would
change the retrieval conditions under which thirteen measured packs were fetched.

**A delay obeyed is not a claim that the host was happy.** It is a claim about what was asked and what
was done, on a date, checkable from `pacing` in the committed record and from the robots body beside it.

**It cannot see a rate a host does not publish.** A host that throttles silently, or states its limits
in prose on a developer page, gets `none-declared` here — correctly, since no directive was issued, and
a default invented in this module would be a rate no vendor asked for.
