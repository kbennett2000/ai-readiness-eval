"""Parse the ```answer-summary``` block out of a model response.

This is one of the two auditable cores (ADR-0004). It is strict-but-forgiving:
it finds the LAST fenced `answer-summary` block (the contract says "output it
once, last"; taking the last one tolerates the model echoing the example), parses
it as YAML, and validates the shape. Anything that is missing, unparseable, or
structurally wrong yields a FormatFailure — a distinct outcome from a wrong-but-
well-formed answer, never silently scored.
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

# Keys the scorer consumes.
_ENDPOINT_KEYS = ("method", "path", "api_version")


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
    try:
        data = yaml.safe_load(block_text)
    except yaml.YAMLError as exc:
        return ParseResult(
            failure=FormatFailure(f"answer-summary block is not valid YAML: {exc}", block_text)
        )

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
    return ParseResult(summary=summary, block_text=block_text)


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def render_block(summary: AnswerSummary, *, preamble: str = "") -> str:
    """Render an AnswerSummary back into a fenced answer-summary block — the inverse of `parse`.

    Used to ask "would this exact answer survive the contract?" without a model in the loop: the
    round-trip control (ADR-0010) renders ground truth through here and parses it back, and the
    `--mock` provider builds its responses the same way. Values are emitted by `yaml.safe_dump`,
    which quotes anything ambiguous — so prose containing `": "` survives verbatim rather than
    needing to be canonicalized away.
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
