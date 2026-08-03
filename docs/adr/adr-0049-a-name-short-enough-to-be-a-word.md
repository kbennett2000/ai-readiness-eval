# ADR-0049 — A name short enough to sit inside a word

**Status:** Accepted
**Date:** 2026-08-03
**Follows:** [ADR-0028](adr-0028-product-name-guard.md) (the guard matches what a vendor sells, and the
bounded/unbounded asymmetry this ADR narrows), [ADR-0018](adr-0018-prospect-names-live-outside-this-repo.md) (the name
list lives outside this repository), [ADR-0042](adr-0042-a-guard-nobody-runs-is-not-a-guard.md) (a skipped guard reports
green), [ADR-0015](adr-0015-hazard-registry.md) (the decay mode).

**Reports and guards only. No scorer, parser, prompt, fixture, task or `results/` path is touched. The
frozen 73/68/93 is unmoved. $0 — no grid, no model call.**

## Context

The public leak guard matches a measured prospect's NAME as an **unbounded, case-insensitive
substring**, and its product names **whole-word**. ADR-0028 chose that asymmetry deliberately and
argued it in the code:

> A vendor name is distinctive, so over-matching it is free and catches `<name>-api` and `<name>'s`. A
> product name is frequently ordinary technical English, and unbounded it is not merely noisy but
> unusable.

Both halves of that are right about the vendors the cohort had. The first half is **not right in
general**, and the next target in the private queue is the counterexample: its name is a **three-letter
acronym**. Acronyms are an ordinary way for a company to be known, and a three-letter one is not
distinctive — it sits inside ordinary English words. Declared the way every other name has been
declared, it would fire on `CHARTER`, `SMART`, `PARTY`, `ARTICLE`, and on any all-caps identifier that
happens to contain it.

Those examples are stand-ins for a neutral acronym, and that is not fussiness. The first draft of this
paragraph illustrated the point with the two English words the **real** token actually collides with —
both of which begin with its three letters, so the list was a decent hint at the name. The leak guard
passed it, because the guard matches literal names and this is inference. ADR-0028 registered that exact
behaviour as a hazard (`prose-about-the-guard-is-where-the-leak-wants-to-live`) after the same thing
happened twice while building the guard: the natural way to explain a token rule is to show the real
token. It is now three times, in the ADR that widens the rule.

The consequence is the one ADR-0028 already named for products, arriving by the other door: not noise,
but what noise does to a guard. Its own source comment says it — *a guard that cries wolf is a guard
someone turns off.* The instrument at risk here is the one that keeps a prospect's name out of a public
repository.

## Decision 1 — this is a prerequisite, not deferrable work, and the argument belongs on the record

The standing triage rule fixes in-cycle only what affects a published number or could put a wrong claim
in front of a vendor, and files everything else. On its face this is neither: today the public tree
contains **zero** matches for the acronym in any case, so the guard is green and would stay green.

It is fixed now anyway, and the reason is that **declaring this target's tokens is itself part of this
cycle**. The choice is not "fix now or fix later"; it is "what does the declaration landing in this
cycle's first commit say". Both available answers without this change are bad ones:

- declare the acronym unbounded, and knowingly arm a token that will fire on innocent prose; or
- declare something weaker — omit it, or lean on the compound form alone — and leave a **live target
  under-guarded** while the record implies it is guarded.

Filing an issue defers the *code*, not the *declaration*. The declaration is due today. That is what
makes this a prerequisite rather than an exception to the triage rule: the rule asks whether leaving it
could put a wrong claim in front of a vendor, and shipping a knowingly-weaker guard for a prospect being
added right now is a disclosure risk taken on purpose.

Stated plainly so a reviewer can disagree with it: if you think the acronym could simply have been left
undeclared for a cycle, this decision is the one to argue with.

## Decision 2 — whole-word is opt-in PER TOKEN, never a global switch

`guard_tokens_cased_whole_word` is a fifth parallel token list, alongside the four the queue already
has. It is matched cased **and** `\b`-bounded. Every token in `guard_tokens_cased` keeps the unbounded
behaviour it was declared for.

Per-token rather than global, because ADR-0028's argument is **sound wherever it applies**. A coined,
distinctive name genuinely does profit from unbounded matching, and some existing declarations rely on
it. A global switch would trade a false-positive problem that affects one target for a false-negative
problem across every target — quietly, and in the direction that fails silent. The opt-in makes each
entry say which kind of name it has, which is a judgement the entry's author is in a position to make
and the matcher is not.

Not a flag on the matcher either. A boolean beside the pattern would be a third way to express the same
thing, and the file's existing idiom already distinguishes tokens by *how they must be compared* — four
lists for insensitive/cased × name/product. A fifth list is the shape that was already there.

## Decision 3 — cased only

No insensitive-bounded list is added. A short-name leak is written as the proper noun, so the
insensitive-bounded combination has no caller — and an unexercised code path is an ungated one, which is
the thing this registry exists to stop accumulating. Recorded as a decision rather than left as an
omission, so a future cycle that needs it adds it deliberately instead of discovering it missing.

## Decision 4 — the compound case is LOST, and the loss is paid at the declaration site

This is the honest cost and it is not a footnote. Whole-word matching **cannot see a name inside a
compound**. `\bART\b` does not match `artglobal.com` — and a docs hostname is precisely where this class
of leak lands, because a recon note names hosts.

So bounding a name is strictly weaker than not bounding it, on that one case. The repair is not in the
matcher; it is in the declaration: an entry that opts a name into whole-word matching is expected to
also declare the compound form (the squashed brand, the domain label) as its own insensitive token.

`test_the_compound_case_is_lost_and_a_companion_token_covers_it` asserts **both halves in one test on
purpose** — that the bounded pattern does not reach the compound, and that the prospect matcher as a
whole still does. Split them and one half becomes deletable: assert only the first and the guard looks
broken; assert only the second and the loss disappears from the record.

What is *not* lost: `\b` sits between a letter and a hyphen, an apostrophe or a bracket, so `ART-api`,
`ART's` and `cycle-37-ART` all still match. ADR-0028 wanted those, and bounding costs none of them.

## Decision 5 — declaring a token in both cased lists is a parse error, not a resolved conflict

`search()` consults both patterns, so the unbounded one wins any race. An entry listing the same token
in both would **read as opted-in in review and behave as unbounded in fact** — the exact failure this
field removes, wearing the label of the fix.

`leak_guard_bounded_name_tokens()` raises on the overlap, and `load_queue` sweeps every entry so it
surfaces at parse time, in the same place and for the same reason an unknown `status` does (ADR-0019):
the alternative is a declaration that is wrong in the quiet direction.

## Decision 6 — the mechanism's tests must not depend on anyone having opted in

Opting in is a deliberate per-target choice, so the list is legitimately empty for almost every target
and may be empty for all of them. Parametrizing the break-tests over the real list would therefore make
them **vacuous** the day the last opted-in target left — the cycle-18 failure shape, and the same one
ADR-0042 found in a skipped guard.

So the seven rules are exercised against a **synthetic queue driven through the real `_load_prospects`**
— not a hand-built fixture, which could pass while the loader was broken. Per-token coverage of the real
list exists too, and is allowed to skip when the list is empty, because asserting non-emptiness there
would make removing the last opted-in target a build failure.

Every rule was verified by breaking it: the boundary, the `search()` wiring, the clash check, the
`to_dict` round-trip, the per-token opt-in (by making bounding global), the `_KNOWN` field list, and the
parse-time sweep. Seven sabotages, seven failures, each for the intended reason.

## Consequences

- `QueueEntry` gains `guard_tokens_cased_whole_word` and `leak_guard_bounded_name_tokens()`; the guard
  gains one pattern. **No existing queue entry changes behaviour** — the field is absent everywhere.
- A queue that contradicts itself no longer loads.
- The next target can be declared with a bounded acronym plus a companion compound token, which is the
  first use and the reason this exists.

## What this does not do

**It does not make the guard whole-word by default**, and nothing here argues it should be. ADR-0028's
asymmetry stands wherever a name is distinctive.

**It does not detect that a name needs bounding.** An author who declares a short acronym in
`guard_tokens_cased` gets the old behaviour and no warning. Nothing in this tree knows which names are
short enough to be words — the name list lives in another repository by design (ADR-0018), and a
length heuristic would be a rule about English, not about tokens.

**It does not force the companion token.** Decision 4's repair is an expectation on the author, gated by
a test only for the synthetic case. A real entry that opts in and declares no compound form is strictly
weaker than before and nothing says so. That residue is registered as its own ungated hazard rather than
implied by this ADR having mentioned it.
