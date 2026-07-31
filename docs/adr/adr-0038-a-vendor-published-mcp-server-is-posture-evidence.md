# ADR-0038: A vendor's own MCP server is posture evidence, not a condition

## Status

Accepted. A recording rule and a naming rule. **No code changes: no scorer, parser, prompt, condition,
fixture or manifest is touched, no committed `scores.json` moves, and the frozen 73/68/93 regression is
unmoved.** The study that forced it ran at **$0 with no model invocation**; its vendor-level table lives
in the private packs repo, per ADR-0018.

## Context

Vendors have started publishing their own MCP servers over the same APIs this project measures. A sweep
of every measured pack plus the public reference — recon and source analysis only, no server run and no
credential anywhere — found **eleven of fifteen** vendors shipping something MCP-shaped. That is a large
enough share of the cohort that the method needs a stated position before a card reaches a vendor, and
two things make the position non-obvious.

### Core already owns the word

`core/conditions.py` declares `KNOWN_CONDITIONS = ("no-context", "public-docs", "mcp")`, and
`McpCondition` means one specific thing: **the spec-derived context layer this project builds** and
points the measured model at. It is the `93` in 73/68/93. A vendor-published MCP server is a different
object with a different author, and nothing in the repo said so.

The collision is not cosmetic. A card carrying an `mcp` column beside a note that the vendor publishes
an MCP server invites exactly one reading — that the column measures the vendor's server — and that
reading would be false. This is the "wrong claim in front of a vendor" half of ADR-0016 triage, which
is why it is ruled on now rather than filed.

### The obvious question about these servers has a non-obvious answer

The question worth asking is whether a vendor's own server closes the knowledge gap this project
measures — whether its tool definitions carry endpoint paths, methods, required parameters, scopes and
versions, or expose named actions whose implementation hides the surface entirely.

The answers do not sort into two piles, and **the pile is not predicted by whether the source is open**:

- Servers whose source is fully public and readable, whose tool handlers nonetheless bottom out in a
  vendor SDK call. No path, no method, anywhere in the tool layer — but **scopes stated explicitly**, as
  decorators and README tables. Open source that still cannot tell you an endpoint.
- Servers that put the surface in the tool contract: literal method-and-path pairs in tool bodies or
  docstrings, version strings in the argument schema. One is a dispatcher whose documented tool takes a
  **bare versioned path** as an argument and whose companion discovery tool searches the vendor's API
  catalogue **by HTTP method**. One ships the vendor's complete machine-readable specification inside
  the MCP repository.
- Servers that cannot be read at all from public sources — hosted-only gateways, container images behind
  a marketplace agreement, documentation behind a login or a visitor-auth redirect.

The third group is why this needs a rule rather than a column. "Could not be read" and "carries no
surface knowledge" are different findings, and the first renders as the second unless something stops it.

## Decisions

### 1. A vendor-published MCP server is posture evidence, never a measured surface

It may be recorded in a pack's `specs.yaml` and cited on a card, in the same register as spec
availability, licence and distribution durability. It may not contribute a condition, a table row, a
dimension or a number without its own ADR arguing for that specifically.

The naming follows: a vendor's server is never called *the `mcp` condition*, and the `mcp` condition is
never described as measuring anything a vendor published. Where both appear on one card they are named
by author, not by protocol.

### 2. It is never executed, never connected to, and never credentialed

The study is source and published-documentation analysis. A hosted server is read *about*, not spoken
to; an installable is read, not installed. No token, no tenant, no marketplace subscription, no
`tools/list` call to a vendor endpoint.

This is stated because an MCP server is the artifact in this whole method most likely to erode the
standing no-live-vendor-call rule. It arrives with installation instructions. Running one is one command
and it would feel like reading. It is not: it is an authenticated call to a vendor's production API,
made by a measurement project the vendor has not agreed to be measured by.

### 3. Five axes, recorded separately, because they come apart

*Obtainable* without a tenant · *inspectable* (source public and readable) · *licence* as stated · *tools
enumerable* without credentials · **surface knowledge carried**.

They are not one axis with five names. The sweep found artifacts obtainable but not inspectable,
inspectable but not licensed for use, and enumerable-from-documentation while wholly closed in source. A
single "open?" verdict would average all of that into a word that is wrong about each of them.

`surface knowledge` takes a closed vocabulary — paths-and-methods, scopes-only, named-actions,
unreadable, none-found — so the third group above records **unreadable**, which is an observation about
our evidence, not a claim about the artifact. Same discipline as ADR-0037's `unrecognized`: a bucket that
names the limit of what we could see is never spelled as a finding about what exists.

### 4. Covering the estate is not covering the measured surface

A finding records *which* product in the vendor's estate the server covers, and whether that is the
surface the pack scored. Several vendors in the sweep ship a first-party server for a **different
product than the one measured** — an adjacent product in the same suite, a newer platform rather than
the established management API, developer tooling rather than the business API.

This is not a detail. It is `AGGREGATE-FINDINGS` Pattern 7 and ADR-0037 arriving one layer up: the same
substitution of a sibling surface for the one asked about, made this time by the vendor rather than the
model. A company-level "yes" reported as coverage of the measured surface would be the identical error
ADR-0037 exists to prevent, committed by the party that wrote the correction.

### 5. "Source readable" and "licensed for use" are independent findings

Public repository therefore open source is false, and the sweep found it false in three distinguishable
ways: a permissive-looking repository under a proprietary licence tying use to an active service
agreement; a licence the hosting platform could not classify at all; and an OSI licence whose copyright
line names an **individual** rather than the company that announced the server.

So the licence field records what was read *and the file it was read from*, and names the holder. This
is the same axis a prior pack already recorded for a vendored specification — licence provenance is not a
new question here, only a new place it shows up.

### 6. A negative requires exhaustion evidence

Four vendors publish nothing MCP-shaped that public sources reveal. That is a finding, and it is only a
finding if it records where it looked: which organisations, which package registries with which query,
which documentation hosts, and **where evidence ran out** — a bot wall, a login wall, a search endpoint
returning empty.

Without that, "no server found" is a fact about the search reported as a fact about the vendor. The
block-record precedent already established this shape for an unmeasurable target; it applies unchanged
to an absent artifact.

### 7. Third-condition eligibility is recorded, never scheduled

A vendor's own server is, in principle, a candidate for a third condition: measuring the lift from the
vendor's published context layer rather than one this method builds. The sweep identifies which packs
could support that. Recording it is not deciding it, and this ADR deliberately does not.

Building it would need its own ADR, because it would mean running a vendor's server against a vendor's
API — which decision 2 forbids as currently written — and because a condition whose treatment is
authored by the party being measured is a different experiment from one whose treatment is authored here.

## Consequences

- Optional and absent from every existing pack in this repo. The reference pack records nothing new and
  its numbers are untouched.
- `KNOWN_CONDITIONS` is unchanged. No new condition, no new dimension, no new score.
- A card may cite a vendor's server as posture and must state, where both appear, which one the `mcp`
  column measures.
- The registry gains four entries; the ruling itself is unenforced by any test, and says so below.

## What this does not do

It does not measure any vendor's MCP server. Nothing was run, connected to, or authenticated against.
Every claim in the private study rests on published source, published documentation, or a recorded
failure to reach either.

It does not establish that the four vendors with no findable server publish none. It establishes that a
recorded search did not find one, on a date.

It does not gate itself. No test in this repo reads a card's prose, so nothing prevents a future card
from describing the `mcp` column as the vendor's server — the same class of gap ADR-0035 recorded for
issue-closing keywords, and recorded here the same way rather than claimed as solved.
