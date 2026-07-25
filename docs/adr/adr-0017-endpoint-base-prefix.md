# ADR-0017: the scorer had the same blind spot ADR-0013 fixed in the gate

## Status

Accepted. Refines [ADR-0013](adr-0013-spec-server-prefix.md), which ruled on this exact disagreement
for the **anchoring gate** and left the **scorer** comparing paths literally. Opt-in per pack, so no
pack that does not declare it can move; the frozen 73/68/93 reproduces unchanged.

## Context

A grid reported an `endpoint` dimension of **3%** under `no-context` and **85%** under `public-docs`,
with `method` and `api_version` tracking it exactly — they are only credited on a matched path, so
three dimensions moved as one. A +82-point documentation lift on three dimensions at once is not a
finding, it is a symptom, and ADR-0013 had already paid for that lesson once: an endpoint dimension
read 13.7% while the model was right in 98% of runs, and the whole gap was one path segment.

Reading the transcripts, the cold answers were right. The model wrote:

```
path: /VendorBase/api/public/v3/Auth/SignIn
```

against a ground truth of `/api/public/v3/Auth/SignIn`. One leading segment apart, and the segment
is the vendor's own name — the base the vendor's **documentation** teaches, in a page that states the
base URL as `https://<host>/VendorBase/api/public/v3`. The pack had written its paths from the point
the vendor's **machine-readable fragments** start theirs, where `servers[].url` is `/vendorbase` and
the `paths` key carries the rest.

Counted over the grid: of 70 ground-truth endpoint slots under `no-context`, 2 matched exactly, **20
were right but for that one leading segment**, and 48 were genuinely wrong or absent. Correcting it
moves the cold endpoint dimension from **3% to 31%** — a tenfold difference, and the difference between
"this model has no idea" and "this model gets a third of it right cold".

### The asymmetry is the whole diagnosis

Under `public-docs` the artifact does not appear at all: 57 of 70 matched exactly, 0 were prefix-off.
The two conditions disagree about notation because **they read different documents**. Cold, the model
recalls the vendor's prose and writes the full documented address. With docs, it reads the embedded
OpenAPI fragment and writes that fragment's `paths` key.

Both are correct addresses for the same operation. **No single literal ground truth can accept both** —
whichever notation the pack picks, it scores one condition and penalizes the other. A pack-level fix is
therefore not available, and that is what makes this a core decision rather than an authoring mistake.

## Decision

**1. A pack may declare one endpoint-base prefix the scorer will absorb.** `endpoint_base_prefix` in
`pack.yaml`, normalized to segments by `Pack.base_prefix_segments`, stripped from the front of both
sides before comparison by `scorer._strip_base_prefix`.

**2. Opt-in, and absent by default.** A pack that does not declare it is scored exactly as before ADR-0017,
so no archived run can be re-scored differently and no committed number moves. This is the same shape
ADR-0007 used for `public_docs.user_agent` and ADR-0009 for `fetch_delay_seconds`: a tolerance a pack
must ask for, with its reason recorded beside it.

**3. It is never derived from `base_url`.** The obvious implementation — take the path component of
`specs.yaml: base_url` — was written, tested, and rejected. For three packs in the cohort `base_url`
points at a **spec repository**, not an API base (`/sailpoint-oss/api-specs/blob/545c4ade…/`), and
stripping that would be nonsense. For another, ground-truth paths already contain the base, so
stripping it would have silently made a published number easier. A field that means different things
in different packs cannot be load-bearing; the new field means one thing.

**4. Only the declared prefix, only at the front.** Not a suffix match, not a substring. The
must-not-inflate counterexample is pinned as a test: `/admin/users/{id}` must not match `/users/{id}`.
A rule of "the answer ends with the ground truth" would have manufactured scores upward, which is the
failure [ADR-0014](adr-0014-answer-format-repair.md) pinned its own counterexample against.

## Consequences

**One dimension gets easier for one pack, deliberately, and it is stated on the card.** The pack that
opts in scores its endpoint dimension higher than it would have. That is the point — the previous
number was measuring agreement about where a base URL ends, not whether the model identified the
operation. The card reports the corrected figure and says which rule produced it.

**Every other pack is byte-identical.** Guaranteed by construction rather than by inspection: the
default is an empty prefix and the code path is `if not prefix: return segments`. The frozen 73/68/93
regression gate and all 453 tests pass.

**The `no-context` condition was the one being damaged, which is the direction that matters.** An
artifact that suppresses the cold number and spares the documented number inflates the measured value
of documentation — the single quantity this project exists to report. A +52-point gap was on its way to
a report card; the real gap is smaller, and the smaller number is the true one.

**The round-trip control cannot catch this, for the third time.** An answer key written in one notation
still matches itself perfectly, so `roundtrip` was green throughout. ADR-0013 recorded that limit,
ADR-0015 registered it as a hazard, and it has now cost a second grid. What caught it was the
suspect-instrument rule and reading transcripts — the same method, applied on purpose this time rather
than after a human noticed.

### What this deliberately does not do

- **It does not detect the condition.** A pack author must notice the disagreement and declare the
  prefix. Nothing warns that a pack's cold endpoint score is suspiciously below its documented one,
  which is the signal that would have caught this automatically. Recorded as an ungated hazard.
- **It does not allow more than one prefix.** A vendor whose estate disagrees with itself in two
  different ways would need a second decision, and inventing that now would be designing for a case
  nobody has met.
- **It does not change what the dimension means for packs that do not opt in.** For them the endpoint
  address is still compared as written, version segments aside.
