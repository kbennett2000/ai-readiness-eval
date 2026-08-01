# ADR-0043 — The standard library caught up, and the module stays for a different reason

**Status:** Accepted · **Date:** 2026-08-01 · **Supersedes:** nothing (amends the "WHY NOT" argument
in ADR-0036)

## Context

ADR-0036 made `robots.txt` a **fetch permission** rather than a crawl suggestion, and implemented
RFC 9309 directly in `core/robots.py`. Its stated reason for not using `urllib.robotparser` was that
the standard library got the two directives at issue wrong, in opposite directions:

- `Disallow: /*/api-next` matched nothing, because `RuleLine.applies_to` was `path.startswith(...)`
  and no path begins with a literal `/*/`;
- `Disallow: /wfm$` matched everything under `/wfm$…` and nothing else.

A single test carried that claim, and its docstring said what it was for:

> Non-vacuity for the whole module. If `urllib.robotparser` ever became correct, this fires and the
> argument in the docstring can be re-examined rather than inherited.

**It fired.** On 2026-08-01, on the first CI run of this repository that was armed and had the
private packs available, on a runner at Python 3.14.6 against an authoring machine at 3.14.4.

CPython rewrote `urllib.robotparser` between those two patch releases. The module docstring now cites
RFC 9309 in place of the 1996 draft; `_add_entry` was replaced with agent-group merging, and the
`normalize`/`normalize_path` helpers were removed. Run against the same fixture, the two parsers now
agree on **every** case, including both forms that motivated writing ours:

| path (`BODY_WILDCARDS`) | ours | stdlib 3.14.4 | stdlib 3.14.6 |
|---|---|---|---|
| `/wfm/api-next/v2/branches/x/apis/people.json` | False | **True** | False |
| `/hcm/api-next/v2/branches` | False | **True** | False |
| `/wfm` | False | **True** | False |
| `/wfm/reference/welcome` | False | **True** | False |
| `/wfmx/reference` | True | True | True |
| `/api-next/v2` | True | True | True |
| `/general/docs` | True | True | True |

So the reason recorded in ADR-0036 is now **false on a current interpreter and true on an older one**.
Left alone, the test asserts a property of whoever's machine is running it.

## Decision 1 — the claim is corrected rather than quietly kept

The "WHY NOT `urllib.robotparser`" paragraph in `core/robots.py` said the standard library mis-reads
both forms. That is no longer true, it is a tracked claim, and this project's standing rule is that a
tracked claim links to the artifact backing it. It now records both states and which release moved.

Restating the *old* behaviour as the *current* reason would have been the cheap option, and it is
exactly the failure mode ADR-0015 built the hazard registry for: an argument that was true when
written, inherited afterwards because nobody re-read it.

## Decision 2 — the module stays, on a reason the original argument did not have

Being right where the standard library was wrong was never a durable justification; a bug can be
fixed, and this one was. What replaces it is stronger:

**The standard library's answer to a robots question changed between two patch releases of one minor
version.**

A fetch-permission decision here is a conduct claim — *this project was permitted to retrieve that
page* — recorded in a pack's `robots_finding`, published on a card, and expected to be reproducible
from the record years later on whatever interpreter is to hand. A decision that silently depends on
the runner's patch level cannot carry that weight. Two people re-running the same audit on the same
`robots.txt` would get different permissions and no diff between them would show why.

`core/robots.py` also decides things `can_fetch` does not return: the `SOURCE_*` distinctions, the
4xx-is-unrestricted / 5xx-is-disallowed / NXDOMAIN-is-a-fourth-thing rulings, and a fixed
`USER_AGENT`. Those were always the larger part of the module, and none of them moved.

Deleting the module once 3.14.6 is the floor is a real option and is **not taken here** — it is a
separate decision with its own migration, and it is filed rather than folded into a CI fix.

## Decision 3 — the test asserts a property of this repository, not of CPython

The old test is replaced by two that cannot rot with an interpreter upgrade:

- `test_this_module_does_not_delegate_to_the_standard_library` — resolves `core/robots.py`'s imports
  with `ast` and refuses any `robotparser` among them. This is the claim that was always the real
  one: the module decides for itself. Checking the *import* rather than the source text matters,
  because the docstring names `urllib.robotparser` on purpose and a substring test failed on its own
  explanation.
- `test_our_answers_do_not_move_when_the_standard_library_does` — runs both parsers over the same
  body and asserts **only ours** against the pinned table. The stdlib is exercised and deliberately
  not asserted.

The pinned table in `test_wildcard_and_anchor_forms` is untouched and still what the project acts on.

## Decision 4 — "no cached page" and "the matcher is broken" are different findings

The same CI run failed a second test, `test_the_matcher_finds_paths_that_are_really_there`, which
asserts that *some* ground-truth path is found in *some* cached page — the positive claim that keeps
a file of negative assertions from passing vacuously.

`docs-cache/` is gitignored. On a clean checkout there are no cached pages, the count is zero, and
the assertion reported **"the matcher is broken"** when the truth was "there was nothing to read".
That is the identical shape CI found in the private repository's `test_anchors_are_never_injected.py`
the day before, and it is worth naming as a class: **a control that cannot distinguish *absent* from
*broken* reports the alarming one.**

Counting them apart took three attempts, and the two failures are the more useful record.

**There are three ways to have nothing to search, and only one of them raises.** A missing cache file
raises `FileNotFoundError`, which `audit_docs_truncation` records as `error` on the task. A pack whose
every manifest page failed to fetch returns an **empty string and raises nothing** — that is a
published finding, not a fault. And a pack whose docs host serves a JavaScript shell extracts to a
**single byte**, which is neither an error nor empty.

The first fix keyed on the absence of an `error` and CI stayed red. The second keyed on a non-zero
byte count and CI stayed red, on the one-byte pack. Both were reasoned; neither was run against a
checkout that actually looked like CI's. What settled it was building one — `git archive HEAD` of the
private packs into a temp directory, which reproduces a clean checkout by definition — and running
the suite against it. The answer arrived in one command and had been guessed wrong twice.

The signal is now `searchable`, recorded per record by the audit: **the cached text is at least as
long as the shortest spelling being looked for.** That takes no magic number and states the actual
question — below that length a miss is arithmetic, not evidence. With no searchable record in any
pack the control **skips**, naming what it could not check and pointing at the hazard entry; with at
least one, zero is still a failure and says which packs did have a cache.

The skip is not free, and the registry says so rather than the summary line implying coverage:
`the-truncation-sweep-is-unexercised-without-a-docs-cache` records that the entire file — every
truncation assertion, not just this one — verifies nothing on a CI runner.

## Consequences

- `core/robots.py` — docstring corrected; **no code change**, no behaviour change, no rule moved.
- `core/tests/test_robots.py` — one test replaced by two; the pinned table untouched.
- `core/conditions.py` — `audit_docs_truncation` records `full_len` and `searchable` per record.
  Additive; no existing field, verdict or caller behaviour changes.
- `core/tests/test_docs_truncation.py` — absent-vs-broken separated.
- `docs/hazards.yaml` — `the-truncation-sweep-is-unexercised-without-a-docs-cache` (ungated, queued)
  and `a-tracked-claim-about-a-dependency-can-stop-being-true` (gated).
- Public issue for the open question: whether to drop `core/robots.py` once 3.14.6 is the floor.
- No scorer, parser, prompt, condition, fixture or task file touched. No `scores.json` moves.
  **73/68/93 unmoved. $0, no model run.**

## What this does not do

**It does not claim the module is still necessary.** It claims the module is still *justified*, on a
different ground, and that the two are not the same sentence. On a fleet pinned to 3.14.6 or later,
`can_fetch` would answer these seven cases correctly. The argument for keeping ours is reproducibility
across interpreters plus the rulings `can_fetch` does not make — not superiority, which has expired.

**It does not check the other direction.** Nothing here tests our matcher against a *newer* stdlib
than the one running, and nothing can: an interpreter cannot tell you what its successor will do. If
CPython moves again, the test that used to notice has been deliberately retired, and what notices now
is the pinned table failing only if **we** move. That is a narrowing, taken knowingly — the retired
test could only ever fire once, and it had already fired.
