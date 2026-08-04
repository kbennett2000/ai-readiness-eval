"""The reference pack's published numbers state their own coverage and their own reproducibility.

73 / 68 / 93 are the only numbers this repo publishes about a vendor pack. Two sentences qualify
them, and both are recomputed here rather than trusted to have been re-typed correctly:

- **coverage** (ADR-0046) — they are a mean of all six declared dimensions, and the README says so;
- **reproducibility** (ADR-0058) — they re-score from the committed transcripts with no network,
  while the documentation pages behind the `public-docs` column are attested by hash and are not in
  this repository at all.

The second one is checked in the THREE files an outside reader actually meets the numbers in, not
only on the pack card: a reproducibility claim made in writing is worth exactly what the least
careful of those files says.

If this pack ever stops exercising a dimension, or is re-fetched, or loses a page, a line goes stale
and this fails — which is the whole point: the clean case is stated, so it has to stay true to keep
being stated.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.contract import API_CONTRACT
from core.report import coverage_line, docs_provenance, reproducibility_line

PACK_DIR = Path(__file__).resolve().parents[1]
FIXTURES = PACK_DIR / "fixtures" / "imported"
README = PACK_DIR / "README.md"
REPO_ROOT = PACK_DIR.parents[1]

#: Where a reader meets these numbers, and the link spelling each file needs. The pack card sits two
#: directories below the gate it cites, so its link and its display text differ.
GATE = "core/tests/test_archive_consistency.py"
DISCLOSURE_SITES = [
    pytest.param(REPO_ROOT / "README.md",
                 {"manifest_link": "packs/sailpoint/docs-manifest.yaml"}, id="repo-README"),
    pytest.param(REPO_ROOT / "REPRODUCE.md",
                 {"manifest_link": "packs/sailpoint/docs-manifest.yaml"}, id="REPRODUCE"),
    pytest.param(README, {"gate_link": (GATE, f"../../{GATE}")}, id="pack-README"),
]


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


# --------------------------------------------------------------------------- reproducibility

def _manifest() -> dict:
    import yaml
    return yaml.safe_load((PACK_DIR / "docs-manifest.yaml").read_text())


@pytest.mark.parametrize("path,links", DISCLOSURE_SITES)
def test_every_place_a_reader_meets_the_numbers_states_the_boundary(path, links):
    """Recomputed from this pack's own manifest, so a re-fetch that changes the page count or the
    capture date fails here instead of leaving three files quietly describing a previous capture."""
    expected = reproducibility_line(docs_provenance(_manifest()), **links)
    text = path.read_text()
    # Every one of these files wraps the sentence; compare on collapsed whitespace, as the coverage
    # assertion above already does.
    assert " ".join(expected.split()) in " ".join(text.split()), (
        f"{path.name} does not carry its own reproducibility line.\nexpected: {expected}")


def test_the_boundary_is_stated_in_more_than_one_place():
    """Non-vacuity guard: an empty site list would make the sweep above a green run over nothing."""
    assert len(DISCLOSURE_SITES) >= 3


def test_the_pack_has_something_to_disclose():
    """The interesting branch of the generator is the one with retrieved pages. If this pack ever had
    none, the sweep above would still pass while asserting a much weaker sentence."""
    prov = docs_provenance(_manifest())
    assert prov["retrieved"] == 29 and prov["dates"] == ["2026-07-23"], prov
