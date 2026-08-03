"""The reference pack's README states which dimensions its published overalls cover (ADR-0046).

73 / 68 / 93 are the only numbers this repo publishes about a vendor pack, and they are a mean of
all six declared dimensions. The README says so, and this gate recomputes the sentence from the
frozen fixtures rather than trusting that someone re-typed it correctly — the same bargain every
card in the packs repo now makes.

If this pack ever stops exercising a dimension, the README line goes stale and this fails, which is
the whole point: the clean case is stated, so it has to stay true to keep being stated.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.contract import API_CONTRACT
from core.report import coverage_line

PACK_DIR = Path(__file__).resolve().parents[1]
FIXTURES = PACK_DIR / "fixtures" / "imported"
README = PACK_DIR / "README.md"


def _aggregates():
    out = {}
    for scores in sorted(FIXTURES.glob("*/scores.json")):
        out[scores.parent.name] = json.loads(scores.read_text())["aggregate"]
    return out


def test_the_readme_carries_the_recomputed_coverage_line():
    aggs = _aggregates()
    assert aggs, "no imported fixture found — an empty sweep is not a passing gate"

    lines = {name: coverage_line(agg, API_CONTRACT) for name, agg in aggs.items()}
    assert len(set(lines.values())) == 1, (
        f"conditions disagree about coverage, so one README line cannot be honest: {lines}"
    )

    expected = next(iter(lines.values()))
    text = README.read_text()
    # The README wraps the sentence across two lines; compare on collapsed whitespace.
    assert " ".join(expected.split()) in " ".join(text.split()), (
        f"README.md does not carry its own coverage line.\nexpected: {expected}"
    )


def test_the_reference_pack_is_complete_so_the_line_states_the_clean_case():
    for name, agg in _aggregates().items():
        assert "**all 6** declared dimensions" in coverage_line(agg, API_CONTRACT), name
