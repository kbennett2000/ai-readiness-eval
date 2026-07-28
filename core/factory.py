"""The factory: an unattended dispatcher that works a ranked target queue through a fixed pipeline
and stocks the drawer with DRAFT report cards (ADR-0006).

Vendor-agnostic, like the rest of `core`. It carries no vendor name: the ranked `queue.yaml` (which
names targets) and the packs it drives both live outside this repo and reach the dispatcher only as a
queue path + a packs dir. The pipeline is a chain of **hard gates** — recon, validate, roundtrip,
anchoring, mock, canary — each of which, on failure, marks the target `blocked` with a written reason
and stops. The
factory never guesses past a gate, never scores a guess, and never reduces N to fit a window. Producing
is unattended; shipping is gated: every card it writes carries a DRAFT/UNREVIEWED banner and nothing
leaves the drawer toward a prospect without human review.

Authoring a pack's tasks + anchored ground truth is deliberately NOT the factory's job (that would be
fabricating the very ground truth the method scores against). Authoring is an external, human/agent step
whose output must pass the validate + roundtrip + anchoring gates here before any grid burns. See
ADR-0006 and ADR-0010.
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .pack import Pack
from .report import _DIM_LABELS
from .scorer import DIMENSIONS

# Pipeline stages, in order. A target advances through these; its `status` records how far it got.
STAGES = ["recon", "validate", "roundtrip", "anchoring", "mock", "canary", "grid", "compare", "card"]
# A target is "done" (skipped by next_target) when it is finished or parked, in one of three senses:
#   carded  — measured, a card exists. The pipeline put it here.
#   blocked — a gate refused it, or it cannot be measured at all. The pipeline or an author put it here.
#   parked  — it COULD be measured; we decided not to, for now. Only an author puts it here.
# `blocked` and `parked` are both terminal and are not interchangeable: blocked is a property of the
# target, parked is a decision about it. See ADR-0019.
DONE_STATUSES = {"carded", "blocked", "parked"}
# The whole status vocabulary. `load_queue` rejects anything outside it, because until it did, a
# plausible-looking value that the code did not know silently meant "dispatch this next" — the exact
# trap `parked` walked into before it was a real status (ADR-0019).
STATUSES = {"queued", *STAGES, *DONE_STATUSES}
_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


# --------------------------------------------------------------------------- #
# Queue model
# --------------------------------------------------------------------------- #

@dataclass
class QueueEntry:
    """One target in the queue. Unknown YAML keys round-trip via `extra` so hand-authored notes and
    future fields survive a save."""
    id: str
    display_name: str = ""
    tier: int | None = None
    status: str = "queued"
    spec_state: str = "unknown"          # verified | partial | unknown
    notes: str = ""
    blocked_reason: str = ""     # why it is not being worked — read for `blocked` AND `parked`
    spend_usd: float = 0.0
    wall_seconds: float = 0.0
    last_run: str = ""
    # Strings that identify this target to the public repo's leak guard. The guard holds no names of
    # its own (ADR-0018); it derives them from here, so a name lives in exactly one place — the
    # private queue that already had to name the target anyway.
    #   guard_tokens       REPLACES the default (the id, and the id with separators collapsed).
    #                      Replacement, not extension, because some ids must NOT be matched: a bare
    #                      id that is also an ordinary word would fire on unrelated prose.
    #   guard_tokens_cased is matched as written, for names that are ordinary words capitalized.
    guard_tokens: list | None = None
    guard_tokens_cased: list = field(default_factory=list)
    # What the target SELLS, as opposed to what it is called. A vendor is identifiable by its
    # distinctive product names alone — naming four of them identifies it as surely as naming it —
    # and nothing above can match one, because a product name is not derivable from an id (ADR-0028).
    # Both fields EXTEND; neither replaces, because there is no default to replace.
    #   guard_product_tokens        case-insensitive, for coined names that are never ordinary prose.
    #   guard_product_tokens_cased  as written, for products named with ordinary technical English.
    #                               The distinction is not cosmetic: matching such a name
    #                               case-insensitively fires on every unrelated use of the words, and
    #                               a guard that cries wolf is a guard someone turns off.
    guard_product_tokens: list = field(default_factory=list)
    guard_product_tokens_cased: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    _KNOWN = ("id", "display_name", "tier", "status", "spec_state", "notes",
              "blocked_reason", "spend_usd", "wall_seconds", "last_run",
              "guard_tokens", "guard_tokens_cased",
              "guard_product_tokens", "guard_product_tokens_cased")

    @classmethod
    def from_dict(cls, d: dict) -> "QueueEntry":
        known = {k: d[k] for k in cls._KNOWN if k in d}
        extra = {k: v for k, v in d.items() if k not in cls._KNOWN}
        return cls(**known, extra=extra)

    def to_dict(self) -> dict:
        out: dict = {"id": self.id, "display_name": self.display_name}
        if self.tier is not None:
            out["tier"] = self.tier
        out.update({"status": self.status, "spec_state": self.spec_state})
        if self.notes:
            out["notes"] = self.notes
        if self.blocked_reason:
            out["blocked_reason"] = self.blocked_reason
        if self.spend_usd:
            out["spend_usd"] = round(self.spend_usd, 4)
        if self.wall_seconds:
            out["wall_seconds"] = round(self.wall_seconds, 1)
        if self.last_run:
            out["last_run"] = self.last_run
        if self.guard_tokens is not None:
            out["guard_tokens"] = list(self.guard_tokens)
        if self.guard_tokens_cased:
            out["guard_tokens_cased"] = list(self.guard_tokens_cased)
        if self.guard_product_tokens:
            out["guard_product_tokens"] = list(self.guard_product_tokens)
        if self.guard_product_tokens_cased:
            out["guard_product_tokens_cased"] = list(self.guard_product_tokens_cased)
        out.update(self.extra)
        return out

    def leak_guard_tokens(self) -> tuple[list[str], list[str]]:
        """(case-insensitive, case-sensitive) strings that identify this target.

        Lives on the entry rather than in the guard so the public repo can compute the list without
        containing it. `guard_tokens: []` is meaningful and is NOT the same as omitting the field: it
        says "my id must never be matched case-insensitively", which is the only way to declare an id
        that is also an ordinary English word.

        Returns NAME tokens only. Product names are a separate declaration returned by
        `leak_guard_product_tokens`, because the guard compares the two differently (ADR-0028) and a
        caller that merged them would apply one kind's boundary rule to the other.
        """
        if self.guard_tokens is None:
            collapsed = re.sub(r"[-_\s]+", "", self.id)
            default = [self.id] + ([collapsed] if collapsed != self.id else [])
        else:
            default = list(self.guard_tokens)
        return ([str(t) for t in default if str(t).strip()],
                [str(t) for t in self.guard_tokens_cased if str(t).strip()])

    def leak_guard_product_tokens(self) -> tuple[list[str], list[str]]:
        """(case-insensitive, case-sensitive) names of what this target SELLS (ADR-0028).

        Kept apart from the name tokens for two reasons. The guard matches these WHOLE-WORD, because
        a product name is often ordinary technical English and an unbounded match is unusable. And
        `guard_tokens` REPLACES its default — the way an id that is also an English word opts out of
        case-insensitive matching — which must never reach across and disarm a target's products,
        since that would switch off a second guard invisibly while the entry still declared products.
        """
        return ([str(t) for t in self.guard_product_tokens if str(t).strip()],
                [str(t) for t in self.guard_product_tokens_cased if str(t).strip()])


def load_queue(path: str | Path) -> list[QueueEntry]:
    """Load the ranked queue. Accepts either a top-level `targets:` list or a bare list.

    A status outside `STATUSES` is an error, not a passenger. Until this check existed the vocabulary
    was documented only in a comment at the top of the queue file, so an unrecognized value — a typo,
    or a word an author reasonably expected the code to know — was accepted silently and then read as
    "not done", i.e. *dispatch this next*. Failing to parse is the cheap end of that mistake.
    """
    data = yaml.safe_load(Path(path).read_text()) or []
    rows = data.get("targets", []) if isinstance(data, dict) else data
    entries = [QueueEntry.from_dict(r) for r in rows]
    bad = [(e.id, e.status) for e in entries if e.status not in STATUSES]
    if bad:
        raise ValueError(
            f"{Path(path)}: unknown status "
            + ", ".join(f"{status!r} on {tid!r}" for tid, status in bad)
            + f". Known statuses: {', '.join(sorted(STATUSES))}."
        )
    return entries


def save_queue(path: str | Path, entries: list[QueueEntry], *, header: str | None = None) -> None:
    """Write the queue back, preserving order. `header` is an optional leading comment block."""
    body = yaml.safe_dump({"targets": [e.to_dict() for e in entries]},
                          sort_keys=False, default_flow_style=False, allow_unicode=True)
    text = (header.rstrip() + "\n\n" if header else "") + body
    Path(path).write_text(text)


def next_target(entries: list[QueueEntry]) -> QueueEntry | None:
    """The first target not yet finished or parked (skip-done, like a per-item worklist loop)."""
    for e in entries:
        if e.status not in DONE_STATUSES:
            return e
    return None


# --------------------------------------------------------------------------- #
# Gates (deterministic, model-free) — each returns (ok, detail)
# --------------------------------------------------------------------------- #

def _load_spec_file(path: Path) -> dict:
    text = path.read_text()
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


def _spec_prefix_segments(spec: dict) -> list[str]:
    """The path segments a spec declares to be in front of every one of its paths.

    OpenAPI 3 puts them in `servers[0].url`, Swagger 2 in `basePath`. A spec is free to split the
    address between the two — `servers[0].url: /Vendor/api` with paths `/v1/things` describes exactly
    the same URL as `servers[0].url: /Vendor` with paths `/api/v1/things`. That split is the spec
    author's convenience and says nothing about the API.
    """
    raw = ""
    servers = spec.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        raw = str(servers[0].get("url") or "")
    if not raw:
        raw = str(spec.get("basePath") or "")
    if "://" in raw:  # an absolute server URL: keep only its path component
        rest = raw.split("://", 1)[1]
        raw = rest[rest.find("/"):] if "/" in rest else ""
    return [s for s in raw.split("/") if s]


def _anchor_paths(spec_path: str, prefix_segments: list[str]) -> list[str]:
    """Every path a pack may legitimately write for one spec path.

    The bare spec path, plus that path prefixed by any SUFFIX of the spec's declared server prefix.
    For a prefix of `/Vendor/api` and a spec path of `/v1/things`, a pack may write `/v1/things`,
    `/api/v1/things`, or `/Vendor/api/v1/things` — all three name the same endpoint, and which one is
    right depends on where the VENDOR'S OWN documentation says the base URL ends. Ground truth has to
    be free to follow the documentation, because that is what the model being measured has read.
    """
    base = spec_path.strip().rstrip("/") or "/"
    out = [base]
    for i in range(len(prefix_segments) - 1, -1, -1):
        out.append("/" + "/".join(prefix_segments[i:]) + base)
    return out


def _index_operations(spec: dict) -> dict[str, tuple[str, list[str]]]:
    """operationId -> (METHOD, [acceptable paths]) for every operation in an OpenAPI spec."""
    prefix = _spec_prefix_segments(spec)
    idx: dict[str, tuple[str, list[str]]] = {}
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() in _METHODS and isinstance(op, dict) and op.get("operationId"):
                idx[op["operationId"]] = (method.upper(), _anchor_paths(path, prefix))
    return idx


#: The two recon findings as a pack may write them. `partial` is meaningful only for availability —
#: vendorability is a yes/no question about a licence, and "partly permitted" is a question no vendor
#: has posed. It is accepted by the normalizer and rejected by the caller, so the refusal carries a
#: message about vendorability rather than a shrug about parsing (ADR-0029).
_AVAILABILITY: tuple[str, ...] = ("yes", "partial", "no")
_RULINGS: tuple[str, ...] = ("yes", "partial", "no")


def _ruling(value: object) -> str:
    """One of `yes` / `partial` / `no` as pack authors actually write it — or `''`, meaning unreadable.

    Packs on disk write these findings three ways, all legitimate and all already committed. A bare
    `yes`/`no`, which YAML hands back as a **bool**. A quoted string. And a folded paragraph whose
    FIRST WORD is the ruling and whose remainder is the argument for it — one pack rules both ways in
    a single field, yes for the copy it vendors and no for a second published copy carrying no licence
    file. Reading the leading token is therefore not a shortcut; it is the convention these packs were
    written in, and forbidding prose to get a clean flag would discard the argument that makes the
    finding worth reading while moving packs that are already published.

    Everything else returns `''`, and every caller treats `''` as a block. The direction is the point:
    a value the gate cannot read is not a weaker assertion than a false one, it is *no* assertion, and
    the whole purpose of this gate is that the pack has to say. The previous code did the opposite by
    accident — it compared availability literally after `.lower()`, so `unknown`, a typo or a trailing
    space fell through to the doc-anchored PASS. The one value that most needed to block was the only
    one that passed silently, and the pack then ran a full grid in a mode nobody had chosen for it.
    """
    if isinstance(value, bool):  # YAML unquotes bare yes/no to booleans
        return "yes" if value else "no"
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    word = text.split()[0].strip(".,;:—–-()\"'").lower()
    return word if word in _RULINGS else ""


def check_recon(pack: Pack) -> tuple[bool, str]:
    """Recon gate (step zero): can the method anchor this vendor at all, and on what terms?

    TWO FINDINGS, ASSERTED SEPARATELY, because they are two different facts about a vendor. Does a
    machine-readable description of this API **exist** (`machine_readable_spec_available`), and are we
    **permitted to keep a copy** of it (`permits_vendoring`)? ADR-0001 scores those as separate
    dimensions, and this gate used to collapse them: it read availability, never once read
    `permits_vendoring` — a field every pack in the cohort records — and demanded a vendored file from
    any pack that said `yes` or `partial`.

    A vendor publishing a real, first-party, machine-readable spec under an all-rights-reserved licence
    therefore had **no passable honest encoding**. The two ways through were to write
    `machine_readable_spec_available: no`, which puts a false claim on a published report card and
    destroys the very finding the card exists to report, or to commit a copyrighted document, which
    breaks both a standing rule and the licence. Packs already in the cohort took the first, and say so
    in a comment directly above the flag explaining that the value does not mean what it says. When a
    gate's own inputs have to be written wrong to pass it, the gate is measuring itself (ADR-0029).

    So the branches are now the four the two facts actually make:

    * **available + permitted** — vendor it. Unchanged, *including its failure text*: this is the
      pipeline's one original hard failure, the INCOHERENT pack that claims a spec and ships nothing,
      and nothing below may offer a way around it.
    * **available + NOT permitted** — the new branch, and it is not a waiver. See the exchange below.
    * **unavailable, either way** — doc-anchored mode, as before. Not a block: "no spec is published"
      is a finding this method exists to report, and it leads the card (ADR-0005).
    * **either finding unreadable** — a block, in both directions. Defaulting an unreadable
      `permits_vendoring` to yes would re-create the trap this ruling removes; defaulting it to no
      would hand every pack the exemption for free.

    WHAT `permits_vendoring: no` COSTS, so that it cannot be written to skip work:

      1. **The pack must NOT carry a vendored spec.** Mirror-image incoherence to the original failure,
         and the only clause here a machine can genuinely check. A pack declaring it may not
         redistribute this document and redistributing it anyway has either mis-stated the licence or
         breached it, and both are worse than a missing file. Checked regardless of availability,
         because it is a fact about a licence and not about a finding.
      2. **The pack must say WHERE the document it may not copy is** (`where` or `where_now`; both
         spellings are in use across the cohort and neither is going to be renamed by a gate). A claim
         that a spec exists which no reviewer can follow is the "no unlinked claims" working agreement
         failing at the level of a whole scored finding.
      3. **Everything else follows from (1) with no new rule anywhere.** `validate` already requires
         every endpoint to carry EITHER a `spec_ref` OR `coverage: doc-only` + a `doc_ref`, and
         `check_anchoring` resolves every `spec_ref` against the vendored spec — of which, by (1),
         there is none, so any `spec_ref` fails there. Every endpoint in such a pack is therefore
         FORCED to be doc_ref-anchored into a docs-manifest that pins each page by URL, byte size and
         hash. That is the substitute for vendoring: not the bytes, which the licence forbids, but a
         committed fingerprint of them. Writing that out a second time here would duplicate a rule two
         gates already enforce, and duplicated rules drift (ADR-0013/0017 paid for that once).

    The net cost of writing `no` is one manifest entry and one hand-authored `doc_ref` per endpoint,
    forever, instead of one file copied once. **The escape hatch is the long way round**, which is
    precisely why it is safe to open. What this cannot do is check whether the licence claim is *true*;
    no test here can read a vendor's terms of use, and that is recorded as a hazard rather than dressed
    up as a guard.
    """
    try:
        specs = yaml.safe_load(pack.specs_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        return False, f"specs.yaml unreadable: {exc}"
    finding = specs.get("spec_finding") or {}

    # --- both findings must be present and readable ------------------------------------------- #
    raw_avail = finding.get("machine_readable_spec_available")
    if raw_avail is None:
        return False, "specs.yaml has no spec_finding.machine_readable_spec_available (recon incomplete)"
    avail = _ruling(raw_avail)
    if avail not in _AVAILABILITY:
        return False, (f"spec_finding.machine_readable_spec_available reads {str(raw_avail)[:40]!r}, "
                       "which is not yes, partial or no")
    if not finding.get("license"):
        return False, "spec_finding names no license (license is a scored dimension)"
    raw_permits = finding.get("permits_vendoring")
    if raw_permits is None:
        return False, ("spec_finding has no permits_vendoring — whether the licence lets us keep a copy "
                       "is a finding in its own right, not a consequence of availability")
    permits = _ruling(raw_permits)
    if permits not in ("yes", "no"):
        return False, (f"spec_finding.permits_vendoring reads {str(raw_permits)[:40]!r}; it must resolve "
                       "to yes or no (prose is fine — lead with the ruling, then argue it)")

    vendored = pack.root / "vendored-spec"
    spec_files = [p for p in sorted(vendored.glob("*")) if p.suffix in (".json", ".yaml", ".yml")] \
        if vendored.is_dir() else []

    # A licence fact, so it is checked before and independently of the availability finding: a pack may
    # not redistribute a document it has just declared it may not redistribute.
    if permits == "no" and spec_files:
        return False, (f"spec_finding says permits_vendoring is no, but vendored-spec/ carries "
                       f"{len(spec_files)} spec file(s) — the pack redistributes what it says it may not")

    if avail in ("yes", "partial"):
        if permits == "yes":
            if not spec_files:
                return False, f"spec_finding says spec is '{avail}' but vendored-spec/ has no spec file"
            if not (vendored / "LICENSE").exists():
                return False, "vendored spec present but no vendored-spec/LICENSE"
            return True, f"spec available ({avail}); vendored + licensed ({finding['license']})"
        if not (finding.get("where") or finding.get("where_now")):
            return False, ("spec is available but not vendorable, so spec_finding must record `where` "
                           "(or `where_now`) the document is — nothing else in the pack points at it")
        return True, (f"spec available ({avail}) but not vendorable "
                      f"({str(finding['license']).strip()[:60]}) — doc-anchored by force; "
                      "every endpoint anchors to the docs-manifest")
    return True, f"no machine-readable spec ({avail!r}) — doc-anchored mode; availability leads the card"


def check_validate(pack: Pack) -> tuple[bool, str]:
    """Validate gate: every task file matches the schema, and the suite is coherent.

    Thin adapter over `validate.validate_pack` so the schema check is an ordinary entry in `GATES`
    rather than a special case spliced into the loop. The import stays deferred so `jsonschema` is
    only imported when a pack is actually being gated.
    """
    from .validate import format_report, validate_pack

    _text, total = format_report(validate_pack(pack))
    if total:
        return False, f"{total} schema problem(s); run `validate` for detail"
    return True, "task files match the schema"


def check_roundtrip(pack: Pack) -> tuple[bool, str]:
    """Round-trip control: every task scores its own ground truth 1.0 (ADR-0010).

    A task whose documented answer key cannot score a perfect mark against itself is an unscoreable
    instrument — a grid run against it would produce a number about our harness, not about the
    vendor. This gate settles that before any spend. It does NOT check whether the ground truth is
    *right*: an answer key always matches itself. See `core/roundtrip.py` for the full limit.
    """
    from .roundtrip import check_pack, summarize_failures

    controls = check_pack(pack)
    failures = summarize_failures(controls)
    if failures:
        return False, failures
    n_na = sum(len(c.na_dimensions) for c in controls)
    return True, f"{len(controls)} task(s) score their own ground truth 1.0 ({n_na} n/a dimension(s))"


def check_anchoring(pack: Pack) -> tuple[bool, str]:
    """Anchoring gate: every spec_ref resolves to a real operation in the vendored spec (operationId,
    with method+path agreeing), and every doc_ref URL appears in the docs-manifest. This is the
    "never score a guess" enforcement — ground truth that isn't anchored to something durable is a
    hard stop, not a warning.
    """
    vendored = pack.root / "vendored-spec"
    ops: dict[str, tuple[str, str]] = {}
    if vendored.is_dir():
        for f in sorted(vendored.glob("*")):
            if f.suffix in (".json", ".yaml", ".yml"):
                ops.update(_index_operations(_load_spec_file(f)))
    try:
        manifest = pack.docs_manifest()
    except (OSError, yaml.YAMLError):
        manifest = {}
    manifest_urls = {
        page["url"]
        for entry in (manifest.get("tasks") or {}).values()
        for page in entry.get("pages", [])
    }

    problems: list[str] = []
    n_spec, n_doc = 0, 0
    for task in pack.load_tasks():
        for ep in task["ground_truth"]["endpoints"]:
            ref = ep.get("spec_ref")
            doc = ep.get("doc_ref")
            if ref:
                n_spec += 1
                oid = ref["operation_id"]
                if oid not in ops:
                    problems.append(f"{task['id']}: operationId '{oid}' not in vendored spec")
                    continue
                method, accepted = ops[oid]
                if method != ep["method"].upper():
                    problems.append(f"{task['id']}/{oid}: method {ep['method']} != spec {method}")
                want = ep["path"].strip().rstrip("/").lower()
                if want not in {p.strip().rstrip("/").lower() for p in accepted}:
                    problems.append(
                        f"{task['id']}/{oid}: path {ep['path']} != spec {accepted[0]}"
                        + (f" (nor with the spec's server prefix: {', '.join(accepted[1:])})"
                           if len(accepted) > 1 else "")
                    )
            elif doc:
                n_doc += 1
                if doc["url"] not in manifest_urls:
                    problems.append(f"{task['id']}: doc_ref {doc['url']} not in docs-manifest")
    if problems:
        return False, "; ".join(problems)
    if pack.spec_ref_file_prefix and n_spec == 0:
        return False, "pack declares spec anchoring (spec_ref_file_prefix) but no endpoint is spec-anchored"
    return True, f"{n_spec} spec-anchored + {n_doc} doc-anchored endpoint(s) resolve"


# The deterministic gates, in the order the dispatcher runs them. Declaring them as data (rather than
# inlining the order in `run_pipeline`) is what keeps STAGES and the dispatcher from drifting apart —
# a test asserts these names are the leading prefix of STAGES.
GATES: tuple[tuple[str, Callable[[Pack], tuple[bool, str]]], ...] = (
    ("recon", check_recon),
    ("validate", check_validate),
    ("roundtrip", check_roundtrip),
    ("anchoring", check_anchoring),
)


# --------------------------------------------------------------------------- #
# Draft report card scaffold (name-free renderer; the vendor label is pack data, not core source)
# --------------------------------------------------------------------------- #

def render_card_scaffold(pack: Pack, results: list[tuple[str, dict, dict]], invented: dict) -> str:
    """Render the DRAFT report-card scaffold from the graded conditions. `results` is a list of
    (condition, aggregate, metadata); `invented` is {task_id: Counter((method, path): count)}. The
    executor fills the Findings prose; the numbers, the headline table, and the invented-endpoints
    exhibit are computed here so the card is never hand-transcribed."""
    dims = list(DIMENSIONS)
    meta = results[0][2] if results else {}
    lines = [
        f"# {pack.display_name} — AI API-readiness report card",
        "",
        "> **DRAFT — UNREVIEWED, NOT FOR OUTREACH.**",
        "",
        f"**Method:** {len(pack.load_tasks())} tasks, {len(results)} condition(s), "
        f"model `{meta.get('model', '?')}`, transport `{meta.get('provider', '?')}`, N="
        f"{meta.get('n', '?')}, sterile per-run, tool-discipline asserted every run. "
        "Scored deterministically on six dimensions.",
        "",
        "## Headline",
        "",
        "| condition | overall | " + " | ".join(_DIM_LABELS[d] for d in dims) + " |",
        "|" + "---|" * (len(dims) + 2),
    ]

    def _pct(v):
        return "n/a" if v is None else f"{round(v * 100)}"

    for cond, agg, _m in results:
        row = [cond, _pct(agg.get("overall_accuracy"))]
        row += [_pct(agg["overall_dimensions"].get(d)) for d in dims]
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "## Findings",
        "",
        "1. _(scaffold — replace with 3–5 plain-English findings, each with an `*Evidence:*` link "
        "to a task file, results dir, ADR, or manifest entry.)_",
        "",
        "## Spec availability (scored)",
        "",
        f"_See `specs.yaml` `spec_finding`._ Recon: {_recon_line(pack)}",
        "",
        "## Invented endpoints (verbatim)",
        "",
    ]
    exhibit = _format_invented(invented)
    lines += exhibit if exhibit else ["_(none — no endpoint outside ground truth was proposed)_"]
    lines += [
        "",
        "## Coverage, exclusions & disclosures",
        "",
        "- _(scaffold — list any excluded dimensions/tasks and why.)_",
        "",
        "## Bottom line (draft)",
        "",
        "_(scaffold)_",
        "",
    ]
    return "\n".join(lines)


def _recon_line(pack: Pack) -> str:
    ok, detail = check_recon(pack)
    return detail


def _format_invented(invented: dict) -> list[str]:
    lines: list[str] = []
    for task_id in sorted(invented):
        entries = invented[task_id]
        if not entries:
            continue
        lines.append(f"- **{task_id}**")
        for (method, path), count in entries.most_common():
            lines.append(f"  - `{method} {path}` (×{count})")
    return lines


# --------------------------------------------------------------------------- #
# Status rendering
# --------------------------------------------------------------------------- #

def render_status(entries: list[QueueEntry]) -> str:
    """The at-a-glance queue table an operator reads without touching dispatcher code."""
    if not entries:
        return "(queue is empty)"
    header = f"{'#':>2}  {'tier':>4}  {'status':<9}  {'spec':<8}  {'spend':>7}  {'wall':>6}  target"
    lines = [header, "-" * len(header)]
    for i, e in enumerate(entries, 1):
        spend = f"${e.spend_usd:.2f}" if e.spend_usd else "-"
        wall = f"{e.wall_seconds/60:.0f}m" if e.wall_seconds else "-"
        tier = str(e.tier) if e.tier is not None else "-"
        label = e.display_name or e.id
        lines.append(f"{i:>2}  {tier:>4}  {e.status:<9}  {e.spec_state:<8}  {spend:>7}  {wall:>6}  {label}")
        # A parked target's reason is as load-bearing as a blocked one — it is the whole record of a
        # decision not to measure something. Keyed off the status so a third terminal state cannot be
        # added later and silently print nothing.
        if e.status in ("blocked", "parked") and e.blocked_reason:
            lines.append(f"                                              ↳ {e.status}: {e.blocked_reason}")
    done = sum(1 for e in entries if e.status == "carded")
    blocked = sum(1 for e in entries if e.status == "blocked")
    parked = sum(1 for e in entries if e.status == "parked")
    lines += ["", f"{done} carded · {blocked} blocked · {parked} parked · "
                  f"{len(entries) - done - blocked - parked} open"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #

def _run_namespace(pack_root: Path, *, condition: str, n: int, model: str | None,
                   provider: str, mock: bool, out: Path | None, packs_dir: str | None,
                   skip_preflight: bool) -> argparse.Namespace:
    """Build the argparse.Namespace `cmd_run` expects, so the dispatcher reuses the exact per-condition
    engine (resumability, discipline retries, report writing) instead of re-implementing it."""
    return argparse.Namespace(
        pack=str(pack_root), packs_dir=packs_dir, condition=condition, n=n, tasks=None,
        model=model, out=str(out) if out else None, overwrite=False,
        provider=provider, mock=mock, skip_preflight=skip_preflight, allow_unpinned_model=False,
    )


def _read_scores(out_dir: Path) -> dict:
    return json.loads((out_dir / "scores.json").read_text())


def run_pipeline(entry: QueueEntry, pack: Pack, *, today: str, model: str | None = None, n: int = 5,
                 provider: str = "cli", packs_dir: str | None = None,
                 log=print) -> dict:
    """Drive a target through recon → validate → roundtrip → anchoring → mock → canary → grid →
    compare → card.

    Each stage is a hard gate: on failure the target is marked `blocked` with a written reason and the
    function returns. On success `status` advances to `carded`. `provider="mock"` runs the whole spine
    offline (no model burn) for tests and dry-runs — it skips the canary and grids with the mock model.
    Returns a report dict {vendor, outcome, stage, reason, conditions, spend_usd, wall_seconds, card}.
    """
    from . import conditions as conditions_mod
    from .__main__ import EXIT_OK, cmd_run

    report: dict = {"vendor": pack.vendor_id, "outcome": None, "stage": None, "reason": "",
                    "conditions": [], "spend_usd": 0.0, "wall_seconds": 0.0, "card": None}

    def _block(stage: str, reason: str) -> dict:
        entry.status = "blocked"
        entry.blocked_reason = f"[{stage}] {reason}"
        entry.last_run = today
        report.update(outcome="blocked", stage=stage, reason=reason)
        log(f"  BLOCKED at {stage}: {reason}")
        return report

    # --- deterministic gates (model-free) --- #
    for stage, fn in GATES:
        entry.status = stage
        ok, detail = fn(pack)
        log(f"  {stage}: {'ok' if ok else 'FAIL'} — {detail}")
        if not ok:
            return _block(stage, detail)

    # --- mock plumbing proof (always, even before a real grid) --- #
    entry.status = "mock"
    mock_out = pack.root / "results" / f"{today}-mock-preflight"
    rc = cmd_run(_run_namespace(pack.root, condition="no-context", n=1, model=None,
                                provider="mock", mock=True, out=mock_out, packs_dir=packs_dir,
                                skip_preflight=True))
    log(f"  mock: {'ok' if rc == EXIT_OK else 'FAIL'}")
    if rc != EXIT_OK:
        return _block("mock", "mock run did not produce a report (plumbing broken)")

    # --- the grid: every condition the pack exposes (mcp only if it declares a context layer) --- #
    grid_conditions = [c for c in conditions_mod.build_registry(pack).keys()]
    entry.status = "grid"
    result_dirs: list[Path] = []
    is_mock = provider == "mock"
    canaried = False
    for cond in grid_conditions:
        out_dir = pack.root / "results" / f"{today}-{cond}"
        # Canary once (the first real cli condition); resumes/later conditions skip the re-run.
        skip_pre = is_mock or canaried
        try:
            rc = cmd_run(_run_namespace(pack.root, condition=cond, n=(1 if is_mock else n),
                                        model=(None if is_mock else model),
                                        provider=("mock" if is_mock else "cli"), mock=is_mock,
                                        out=out_dir, packs_dir=packs_dir, skip_preflight=skip_pre))
        except Exception as exc:  # a malformed pack/condition must block, not crash the dispatcher
            return _block("grid", f"condition '{cond}' raised {type(exc).__name__}: {str(exc)[:160]}")
        if rc != EXIT_OK:
            # EXIT_BLOCKED (3) = a gate (canary/transport/pin) refused; record and stop, don't guess.
            return _block("grid", f"condition '{cond}' returned exit {rc} "
                                  "(canary/transport/model-pin gate or run error)")
        if not is_mock:
            canaried = True
        result_dirs.append(out_dir)
        scores = _read_scores(out_dir)
        meta = scores.get("metadata", {})
        report["spend_usd"] += meta.get("total_cost_usd", 0.0)
        report["wall_seconds"] += meta.get("total_duration_ms", 0) / 1000.0
        report["conditions"].append(cond)
        log(f"  grid[{cond}]: ok  (${meta.get('total_cost_usd', 0.0):.4f})")

    # --- compare + card scaffold --- #
    entry.status = "compare"
    graded: list[tuple[str, dict, dict]] = []
    from .report import aggregate
    for d in result_dirs:
        scores = _read_scores(d)
        graded.append((scores["metadata"].get("condition", d.name),
                       aggregate(scores["runs"]), scores["metadata"]))

    entry.status = "card"
    invented = unmatched_for_dirs(result_dirs, pack)
    card = render_card_scaffold(pack, graded, invented)
    card_path = pack.root / "REPORT.scaffold.md"
    card_path.write_text(card)
    report["card"] = str(card_path)
    log(f"  card: wrote scaffold → {card_path.name}")

    # --- advance --- #
    entry.status = "carded"
    entry.spend_usd += report["spend_usd"]
    entry.wall_seconds += report["wall_seconds"]
    entry.last_run = today
    report.update(outcome="carded", stage="card")
    return report


def unmatched_for_dirs(result_dirs: list[Path], pack: Pack) -> dict:
    """Union the invented (non-ground-truth) endpoints across every graded condition dir."""
    from collections import Counter

    from .analyze import unmatched_endpoints
    tasks_by_id = pack.tasks_by_id()
    merged: dict[str, Counter] = {}
    for d in result_dirs:
        for tid, counter in unmatched_endpoints(d, tasks_by_id).items():
            merged.setdefault(tid, Counter()).update(counter)
    return merged
