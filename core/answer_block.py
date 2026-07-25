"""Parse the ```answer-summary``` block out of a model response.

This is one of the two auditable cores (ADR-0004). It is strict-but-forgiving:
it finds the LAST fenced `answer-summary` block (the contract says "output it
once, last"; taking the last one tolerates the model echoing the example), parses
it as YAML, and validates the shape. Anything that is missing, unparseable, or
structurally wrong yields a FormatFailure — a distinct outcome from a wrong-but-
well-formed answer, never silently scored.

One repair is attempted, and only after YAML has already failed: a single-line
flow sequence on `required_scopes` / `key_parameters` whose items carry API
parameter notation (`sortBy[0].name`, `requestedItems[].type`) is re-emitted as a
block sequence. See ADR-0014 — the contract's own example teaches that flow style,
so this repairs our instrument rather than excusing the answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

# Match a fenced block whose info-string is exactly `answer-summary` (optionally
# with surrounding whitespace). Non-greedy body; DOTALL so it spans newlines.
_FENCE_RE = re.compile(
    r"```[ \t]*answer-summary[ \t]*\r?\n(.*?)\r?\n[ \t]*```",
    re.DOTALL | re.IGNORECASE,
)

# The only line shape the repair will touch (ADR-0014): one of the two list-valued
# contract keys, written as a single-line flow sequence.
_FLOW_LIST_RE = re.compile(
    r"^(\s*)(required_scopes|key_parameters)\s*:\s*\[(.*)\]\s*$"
)

# A repaired item must look like a scope or a parameter path — no whitespace, no
# quote characters, no commas. This is the guard that stops the repair from
# manufacturing a score: splitting a quoted sentence such as
# `["requestedFor, requestedItems", x[0]]` on its inner comma would hand the
# scorer two exact ground-truth names that valid YAML would never have produced,
# and both dimensions this repair can reach are containment-scored, so a bad
# split can only ever raise a score. Any item failing this abandons the repair
# for the whole block.
_REPAIR_ITEM_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_.:$*\[\]{}<>|/#@-]*$")


@dataclass
class Endpoint:
    method: str | None
    path: str | None
    api_version: str | None


@dataclass
class AnswerSummary:
    endpoints: list[Endpoint]
    auth_flow: str | None
    required_scopes: list[str]
    key_parameters: list[str]


@dataclass
class FormatFailure:
    """A response that did not honor the answer-block contract."""

    reason: str
    # If a block was found but failed to parse/validate, keep its raw text for audit.
    raw_block: str | None = None


@dataclass
class ParseResult:
    summary: AnswerSummary | None = None
    failure: FormatFailure | None = None
    # The raw text of the answer-summary block that was parsed (for archiving), if any.
    block_text: str | None = None
    # True when the block only parsed after the ADR-0014 flow-sequence repair.
    repaired: bool = False
    # What was actually handed to the YAML parser after repair. Archived so a
    # reviewer can reproduce a repaired score from the raw response — without it
    # the text that produced the score would exist nowhere.
    repaired_block_text: str | None = None

    @property
    def is_failure(self) -> bool:
        return self.failure is not None


def _as_str_list(value) -> list[str]:
    """Coerce a scalar or list into a list of trimmed strings (drops empties)."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        out.append(str(item).strip())
    return [s for s in out if s]


def _split_flow_items(inner: str) -> list[str] | None:
    """Split a flow-sequence body on its top-level commas.

    Tracks bracket/brace nesting AND quote state, so a comma inside `filter[a,b]`
    or inside a quoted string is not a separator. Returns None if the text is not
    safely splittable — unbalanced nesting, or a quote left open — in which case
    the caller must abandon the repair rather than guess.
    """
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    for ch in inner:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                return None
        if ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quote is not None or depth != 0:
        return None
    items.append("".join(buf))
    return [s for s in (i.strip() for i in items) if s]


def _is_valid_yaml_line(line: str) -> bool:
    """True if this single line parses as YAML on its own (ADR-0022).

    The repair only ever runs on a block YAML has already rejected, so the question
    a per-line guard has to answer is not "is this block valid" but "is *this* the
    line that broke it". Asking the parser is exact where a punctuation test is a
    proxy: `[a, b]` is valid, `[sortBy[0].name]` and `[scp.pc.{role}]` are not, and
    no character set has to be enumerated in advance to tell them apart.

    A line valid in isolation but invalid in context is safe to skip — skipping only
    declines to rewrite it, and some other line is what failed.
    """
    try:
        yaml.safe_load(line.strip())
    except yaml.YAMLError:
        return False
    return True


def _repair_flow_lists(block_text: str) -> str | None:
    """Rewrite single-line flow sequences that YAML rejected into block sequences.

    Narrow by design (ADR-0014): only the two list-valued contract keys, only a
    one-line flow sequence, and only when an item actually carries the bracket
    notation that makes the line invalid YAML. Every produced item must look like
    a scope or parameter path; if any does not, the repair is abandoned for the
    whole block. Items are re-emitted through `yaml.safe_dump`, so quoting is the
    serializer's problem and never a hand-rolled guess.

    Returns the repaired text, or None if nothing was safely repairable.
    """
    lines = block_text.splitlines()
    out: list[str] = []
    changed = False
    for line in lines:
        m = _FLOW_LIST_RE.match(line)
        if not m:
            out.append(line)
            continue
        indent, key, inner = m.groups()
        # A flow sequence that is already valid YAML is never rewritten. Asked directly
        # of the parser rather than guessed from punctuation (ADR-0022): the original
        # test looked for a square bracket, because the indexed-parameter notation the
        # prompt contract demonstrates is what ADR-0014 was written to repair. A brace
        # placeholder — `[scp.pc.{role}]`, the shape a model reaches for when it does
        # not know a tenant-specific value — is equally invalid YAML and carries no
        # square bracket, so the guard skipped the one line in the block that needed
        # rewriting and the repair reported nothing to do.
        if _is_valid_yaml_line(line):
            out.append(line)
            continue
        items = _split_flow_items(inner)
        if items is None or not items or not all(_REPAIR_ITEM_RE.match(i) for i in items):
            return None
        dumped = yaml.safe_dump({key: items}, sort_keys=False, default_flow_style=False)
        out.extend(f"{indent}{ln}" for ln in dumped.rstrip("\n").splitlines())
        changed = True
    return "\n".join(out) if changed else None


def parse(response_text: str) -> ParseResult:
    """Extract and validate the answer-summary block from a model response."""
    if not response_text or not response_text.strip():
        return ParseResult(failure=FormatFailure("empty response"))

    matches = _FENCE_RE.findall(response_text)
    if not matches:
        return ParseResult(
            failure=FormatFailure("no ```answer-summary``` block found in response")
        )

    block_text = matches[-1].strip()  # contract: last block is the answer
    repaired = False
    repaired_text: str | None = None
    try:
        data = yaml.safe_load(block_text)
    except yaml.YAMLError as exc:
        # ADR-0014: one narrow repair, attempted only here — never on a block that
        # already parsed. If it does not produce valid YAML, the original failure
        # stands unchanged, so the repair can only ever rescue.
        candidate = _repair_flow_lists(block_text)
        data = None
        if candidate is not None:
            try:
                data = yaml.safe_load(candidate)
            except yaml.YAMLError:
                data = None
        if data is None:
            return ParseResult(
                failure=FormatFailure(f"answer-summary block is not valid YAML: {exc}", block_text)
            )
        repaired = True
        repaired_text = candidate

    if not isinstance(data, dict):
        return ParseResult(
            failure=FormatFailure("answer-summary block is not a YAML mapping", block_text)
        )

    raw_endpoints = data.get("endpoints")
    if not isinstance(raw_endpoints, list) or not raw_endpoints:
        return ParseResult(
            failure=FormatFailure(
                "answer-summary 'endpoints' is missing or not a non-empty list", block_text
            )
        )

    endpoints: list[Endpoint] = []
    for idx, ep in enumerate(raw_endpoints):
        if not isinstance(ep, dict):
            return ParseResult(
                failure=FormatFailure(
                    f"endpoints[{idx}] is not a mapping", block_text
                )
            )
        endpoints.append(
            Endpoint(
                method=_str_or_none(ep.get("method")),
                path=_str_or_none(ep.get("path")),
                api_version=_str_or_none(ep.get("api_version")),
            )
        )

    summary = AnswerSummary(
        endpoints=endpoints,
        auth_flow=_str_or_none(data.get("auth_flow")),
        required_scopes=_as_str_list(data.get("required_scopes")),
        key_parameters=_as_str_list(data.get("key_parameters")),
    )
    return ParseResult(
        summary=summary,
        block_text=block_text,
        repaired=repaired,
        repaired_block_text=repaired_text,
    )


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def render_block(summary: AnswerSummary, *, preamble: str = "") -> str:
    """Render an AnswerSummary back into a fenced answer-summary block — a right inverse of `parse`.

    Used to ask "would this exact answer survive the contract?" without a model in the loop: the
    round-trip control (ADR-0010) renders ground truth through here and parses it back, and the
    `--mock` provider builds its responses the same way. Values are emitted by `yaml.safe_dump`,
    which quotes anything ambiguous — so prose containing `": "` survives verbatim rather than
    needing to be canonicalized away.

    Not a two-sided inverse, and the asymmetry is load-bearing: `safe_dump` emits BLOCK sequences,
    so this function can never produce the single-line flow sequence that the ADR-0014 repair
    exists to rescue. That is precisely why the round-trip control could not catch that defect —
    the harness's own renderer never speaks the dialect its parser was rejecting.
    """
    block = {
        "endpoints": [
            {"method": e.method, "path": e.path, "api_version": e.api_version}
            for e in summary.endpoints
        ],
        "auth_flow": summary.auth_flow,
        "required_scopes": list(summary.required_scopes),
        "key_parameters": list(summary.key_parameters),
    }
    body = yaml.safe_dump(block, sort_keys=False, default_flow_style=False)
    return f"{preamble}```answer-summary\n{body}```\n"
