"""The DOCS-cohort answer block: prompt contract, parser, renderer (ADR-0044).

The sibling of `core/prompt.py` + `core/answer_block.py`, for a cohort whose ground truth is
discrete engineering values published as manuals rather than as a machine-readable API description.
Not one of the six API dimensions applies — there is no endpoint, method, API version, auth flow,
scope or request parameter anywhere on such a surface — so this cohort gets its own contract rather
than a re-interpretation of one written for something else.

TWO THINGS THIS CONTRACT DOES DIFFERENTLY, BOTH DELIBERATE AND BOTH RECORDED IN ADR-0044.

1. **The example teaches a BLOCK sequence.** ADR-0014 repaired answers that were unparseable
   because the API contract's own example demonstrates a single-line flow sequence, and a model
   following it with a real parameter name produced invalid YAML. That ADR states the permanent fix
   is to change the example and that it cannot be applied retroactively, because the archive would
   stop being an answer to the prompt that produced it. This cohort has no archive yet, so it starts
   with the fixed example and needs no repair path at all.

2. **Scalars are read as WRITTEN, never as YAML resolves them.** `yaml.safe_load` types
   `firmware_version: 35.010` as a float and hands back `35.01` — the trailing digit is gone before
   any comparison happens, and a version dimension that silently rewrites the value it is scoring is
   the ADR-0013 fault class in miniature. `yaml.compose` returns the node tree with each scalar's
   ORIGINAL text and its resolved tag, so this parser reads the literal the model wrote and consults
   the tag only to tell a genuine null from the four-character string "null".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from .answer_block import FormatFailure, ParseResult

# Shared with the API contract on purpose: one fence language across the project means a model's
# habit, a reviewer's eye and every archive-reading tool keep working across cohorts.
ANSWER_BLOCK_LANG = "answer-summary"

_FENCE_RE = re.compile(
    r"```[ \t]*answer-summary[ \t]*\r?\n(.*?)\r?\n[ \t]*```",
    re.DOTALL | re.IGNORECASE,
)

_NULL_TAG = "tag:yaml.org,2002:null"

#: The keys this contract defines. A block carrying none of them did not honour the contract.
KEYS = ("catalog_numbers", "firmware_version", "software_version", "publication")

DOCS_ANSWER_BLOCK_SUFFIX = """\

---

After your normal answer (explanation and reasoning), end your response with a single fenced code \
block tagged `answer-summary` containing YAML with exactly these keys:

  catalog_numbers:      # list of the catalog / part numbers your answer names ([] if none)
  firmware_version:     # the device firmware revision your answer requires (null if not applicable)
  software_version:     # the programming-software version your answer requires (null if not
                        # applicable)
  publication:          # the vendor publication number your answer is based on (null if none)

Write each version exactly as the vendor writes it, as a quoted string, and give one value per key.

Example:

```answer-summary
catalog_numbers:
  - ABC-1234X
firmware_version: "12.003"
software_version: "30"
publication: ABC-XX001
```

Output the `answer-summary` block exactly once, as the very last thing in your response.
"""


def build_prompt(task_prompt: str) -> str:
    """Return the task prompt with the docs-cohort answer contract appended."""
    return task_prompt.rstrip() + "\n" + DOCS_ANSWER_BLOCK_SUFFIX


@dataclass
class DocsAnswer:
    """One parsed docs-cohort answer. Every field is the literal text the model wrote."""

    catalog_numbers: list[str]
    firmware_version: str | None
    software_version: str | None
    publication: str | None


def _scalar(node) -> str | None:
    """A scalar node's ORIGINAL text, or None when the model genuinely wrote a null.

    The tag is consulted only to separate a real null (`null`, `~`, or an empty value) from the
    string "null" a model might legitimately write; everything else is returned exactly as typed,
    which is the whole reason this module composes instead of loading.
    """
    if not isinstance(node, yaml.ScalarNode):
        return None
    if node.tag == _NULL_TAG:
        return None
    text = str(node.value).strip()
    return text or None


def _sequence(node) -> list[str]:
    """A sequence node as literal strings. A lone scalar is accepted as a one-item list."""
    if isinstance(node, yaml.ScalarNode):
        one = _scalar(node)
        return [one] if one else []
    if not isinstance(node, yaml.SequenceNode):
        return []
    out = [_scalar(item) for item in node.value]
    return [s for s in out if s]


def parse(response_text: str) -> ParseResult:
    """Extract and validate the docs answer-summary block from a model response.

    Shares `ParseResult` / `FormatFailure` with the API contract so every caller that distinguishes
    an unparseable answer from a wrong one — the runner, `rebuild-report`, the report aggregator —
    works unchanged across cohorts.

    A block carrying NONE of this contract's keys is a format failure: the model did not answer in
    the shape it was asked for. A block carrying the keys with empty or null values is NOT a format
    failure — it is an answer that did not know, and it is scored as one. Keeping those apart is the
    same rule the API contract applies to a missing `endpoints` list, and it is what stops a
    don't-know from being laundered into an instrument fault.
    """
    if not response_text or not response_text.strip():
        return ParseResult(failure=FormatFailure("empty response"))

    matches = _FENCE_RE.findall(response_text)
    if not matches:
        return ParseResult(
            failure=FormatFailure("no ```answer-summary``` block found in response")
        )

    block_text = matches[-1].strip()  # contract: last block is the answer
    try:
        root = yaml.compose(block_text)
    except yaml.YAMLError as exc:
        return ParseResult(
            failure=FormatFailure(f"answer-summary block is not valid YAML: {exc}", block_text)
        )

    if not isinstance(root, yaml.MappingNode):
        return ParseResult(
            failure=FormatFailure("answer-summary block is not a YAML mapping", block_text)
        )

    fields: dict[str, object] = {}
    for key_node, value_node in root.value:
        key = _scalar(key_node)
        if key in KEYS:
            fields[key] = value_node

    if not fields:
        return ParseResult(
            failure=FormatFailure(
                "answer-summary block carries none of the contract's keys "
                f"({', '.join(KEYS)})", block_text
            )
        )

    summary = DocsAnswer(
        catalog_numbers=_sequence(fields.get("catalog_numbers")),
        firmware_version=_scalar(fields.get("firmware_version")),
        software_version=_scalar(fields.get("software_version")),
        publication=_scalar(fields.get("publication")),
    )
    return ParseResult(summary=summary, block_text=block_text)


def render_block(summary: DocsAnswer, *, preamble: str = "") -> str:
    """Render a DocsAnswer back into a fenced answer-summary block — a right inverse of `parse`.

    Used by the round-trip control (ADR-0010) and the `--mock` provider. `safe_dump` quotes any
    string that would otherwise resolve to a number, so a version survives the boundary as the text
    it was written as — which is the property `parse` composes rather than loads to preserve.
    """
    block = {
        "catalog_numbers": list(summary.catalog_numbers),
        "firmware_version": summary.firmware_version,
        "software_version": summary.software_version,
        "publication": summary.publication,
    }
    body = yaml.safe_dump(block, sort_keys=False, default_flow_style=False, allow_unicode=True)
    return f"{preamble}```answer-summary\n{body}```\n"
