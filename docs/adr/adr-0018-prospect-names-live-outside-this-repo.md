# ADR-0018: the leak guard loads its name list at runtime, because it was the leak

## Status

Accepted. Supersedes the hashed-token design proposed in issue #23, which is declined rather than
deferred. Changes no scorer, parser, prompt or fixture; the frozen 73/68/93 regression is unmoved.

## Context

Since cycle 2 this repository has enforced a privacy rule: no tracked file may name a measured
prospect, because the prospects live in a private packs repo and this repository's visibility is
`PUBLIC`. The rule was implemented as `test_public_repo_names_no_prospect` — a plaintext grep over
`git ls-files` for a compiled alternation of names.

A plaintext matcher has to spell the literals it matches. So the guard listed every prospect, and then
had to exempt its own file from its own scan, or it would have reported itself. The consequence was
not subtle once anyone looked at it directly:

> The single tracked file excused from "no tracked file may name a measured prospect" was a
> better-organized roster of every measured prospect than any leak the rule prevents.

It named carded vendors, a vendor's former brand, and five targets no cycle had started. It had been
true for eleven cycles. The only acknowledgement anywhere was a parenthetical in a docstring, and the
list grew by five names in cycle 13 before anyone wrote down what the file was.

Worse, the exemption made the disclosure *load-bearing*. The project's own discipline (cycle 9) is that
a target's name joins the guard at the **start** of its life in the queue, before any recon note exists
to leak. Under a literal matcher, that discipline meant publishing a target's name in a public
repository was the first act performed on it.

### Why not hashed tokens

Issue #23 proposed storing salted hashes of the names instead of the names. It is declined:

- A salt committed beside the hashes buys "not casually readable", not secret. Anyone with a candidate
  list confirms or refutes it in a second.
- Failure messages stop being able to name what matched, so the guard gets less useful exactly when it
  fires.
- Multi-word and substring tokens do not tokenize cleanly, and this guard needs both.
- It is *more* machinery for a *weaker* guarantee than simply not having the names here.

## Decision

**The public repository holds zero prospect names. The guard builds its list at runtime from the
private packs repo**, which already had to name every target in order to be a queue at all.

- The source is `AIRE_PACKS_DIR` — the packs-root variable the engine already reads — plus `AIRE_QUEUE`
  for the queue path, defaulting to `<AIRE_PACKS_DIR>/queue.yaml`. No new configuration was invented.
- Two sources are combined, because neither subsumes the other: **queue entries** (every target,
  including unstarted ones) and **pack directory names** (vendors carded before the queue existed).
  A pack directory whose name matches a queue id defers to the entry, so an entry may *narrow* its
  tokens without the directory name silently restoring them.
- A queue entry declares `guard_tokens` (case-insensitive; **replaces** the default of the id and its
  separator-collapsed form) and `guard_tokens_cased` (matched as written). Replacement rather than
  extension is required, not stylistic: an id that is also an ordinary English word must be able to say
  *never match me case-insensitively*, and `guard_tokens: []` is the only way to say it.

### The skip/fail contract

| state | behaviour | why |
|---|---|---|
| `AIRE_PACKS_DIR` unset | **skip**, with a message naming the variable | an outside clone of a public repo genuinely cannot run this, and breaking it would be wrong |
| set, but not a directory | **fail** | |
| set, but no queue file | **fail** | |
| set, but the queue does not parse | **fail** | |
| set, but zero names derived | **fail** | a guard that matches nothing passes green, which is the worst outcome available |

The asymmetry is the point. *Not configured* is a legitimate state; *configured and broken* is a typo
away from silently disabling the leak guard, and must be loud.

### The self-exemption is gone, and a test says so

With no literals in the file there is nothing to excuse, so the scan reads its own source like every
other tracked file. `test_the_guard_does_not_exempt_its_own_file` asserts the file is genuinely in the
scanned set — so "just skip this one file" cannot come back quietly; it has to fail a test that says
why.

### What widening the list immediately found

Deriving from the queue did not merely relocate the old list — it **widened** it, from the eight carded
names someone had remembered to type to every target in the queue, including ten tier-2 and tier-3
targets that had never been guarded at all. The first run of the widened guard failed, on a name
appearing inside an **imported evidence archive**: a frozen model transcript in which the measured
model named a third-party product in an example JSON payload.

That is not a disclosure of our queue; it is a quotation of someone else's documentation. And the
archive cannot be edited — a published number rests on it, and redacting evidence to satisfy a guard is
the one repair this project must never make.

So the rule the guard enforces was stated slightly wrong, and had been since cycle 2. It is not *no
tracked file contains the string*. It is **no tracked file this project authored names a prospect**.
Imported archives (`packs/*/fixtures/imported/`) are excluded, except `PROVENANCE.md`, which is the one
hand-written file in that region. Because an exempt region is precisely how this guard failed the first
time, the exclusion's extent is itself asserted: nothing under `docs/`, `core/`, `tasks/`, no pack
config file, and no top-level file may ever fall inside it.

## Consequences

- The public repository names nobody. Not obfuscated names — none.
- A target added to the private queue is guarded **automatically**, by the same edit that adds it. The
  hazard "the token list can omit a prospect" — which happened, between cycles 2 and 6 — is closed by
  construction rather than by discipline.
- **Cost, stated plainly: an outside clone, and any CI runner without the private repo, skips this
  guard entirely.** A skip is quieter than a failure, and a suite that reports green while its privacy
  guard did not run is a real hazard, not a hypothetical one. It is registered as such. The mitigation
  available here is that skipping is *visible* (`-rs` prints the reason and names the variable) and
  that misconfiguration fails rather than skips; the residue is that nobody is forced to look.
- The guard now depends on a repository outside itself. That is a genuine coupling, and it is the price
  of the property; there is no way to hold a list of names without holding it.
- **Git history is not rewritten.** The names are in this repository's history since cycle 2 and in a
  merge from cycle 13. Removing them at HEAD is the achievable win; a rewrite is destructive, would
  invalidate every clone, and would still not clear merged pull-request diffs, issue bodies, forks or
  mirrors. Recorded with a recommendation in its own issue rather than acted on.

## What this does not do

- It does not make the names secret. It relocates them to a private repository and stops adding to a
  public one.
- It does not protect prose no test can read: pull-request titles and bodies, issue text and commit
  messages remain manual discipline, as recorded before this ADR and still after it.
