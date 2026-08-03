"""The coverage disclosure (ADR-0046): a published overall states what it is a mean OF.

ADR-0045 measured the condition and left the display half filed: 13 of 18 packs publish an
`overall_accuracy` that is a mean over fewer dimensions than their contract declares, and the only
signal on the card is an `n/a` cell in a column whose header still names the dimension. `n/a` is a
word this project uses legitimately and often, so it reads past.

These are the rules the generated line must obey, each broken on purpose. The line is generated
rather than typed because a hand-maintained derived figure goes stale silently — the failure mode
`render_group_comparison_md` was written to avoid, and the one `tests/test_cohort_claims.py` in the
packs repo exists to catch for the cohort tables.

WHAT THESE TESTS DO NOT PROVE
    That the dimensions a pack DOES exercise are exercised well. The line counts columns; an answer
    key always matches itself (ADR-0010), and a dimension carried by one weak task is counted the
    same as one carried by twelve. ADR-0046 says so in its own words.
"""
import pytest

from core.contract import CONTRACTS
from core.report import aggregate, coverage_cohort_note, coverage_line, covered_dimensions
from core.scorer import DIMENSIONS

API = CONTRACTS["api"]
DOCS = CONTRACTS["docs"]


def _agg(contract, **scores):
    """An aggregate whose dimension means are exactly `scores`; anything unnamed is n/a."""
    dims = {d: scores.get(d) for d in contract.dimensions}
    applicable = [v for v in dims.values() if v is not None]
    return {
        "task_ids": ["t"],
        "per_task": {},
        "overall_dimensions": dims,
        "overall_accuracy": (sum(applicable) / len(applicable)) if applicable else None,
        "total_runs": 1,
        "format_failures": 0,
        "format_repairs": 0,
    }


def _full(contract):
    return _agg(contract, **{d: 1.0 for d in contract.dimensions})


# --------------------------------------------------------------------------- the per-card line

def test_a_pack_covering_every_dimension_says_so_rather_than_staying_silent():
    """The clean case is STATED, not omitted (ADR-0046).

    A disclosure that appears only where something is wrong teaches a reader to infer a problem from
    its presence, and teaches the next author that the line is optional when the news is good.
    """
    line = coverage_line(_full(API), API)
    assert "**all 6** declared dimensions" in line
    for label in API.dim_labels.values():
        assert label in line
    assert "exercised by no task" not in line


def test_an_unexercised_dimension_is_named_and_the_count_drops():
    agg = _agg(API, **{d: 1.0 for d in API.dimensions if d != "required_scopes"})
    line = coverage_line(agg, API)
    assert "**5 of 6** declared dimensions" in line
    assert "**scopes** is exercised by no task" in line
    # The covered list must not advertise the dimension it just said was missing.
    assert line.split("**scopes**")[0].count("scopes") == 0


def test_a_written_reason_changes_the_sentence_and_points_at_the_file():
    agg = _agg(DOCS, catalog_number=1.0, software_version=1.0)
    declared = {"firmware_version": "No task declares a controller firmware revision."}
    with_reason = coverage_line(agg, DOCS, declared)
    without = coverage_line(agg, DOCS)
    assert "[`pack.yaml`](pack.yaml) declares the reason" in with_reason
    assert "no written reason is declared" in without
    assert with_reason != without


def test_a_blank_reason_is_not_a_reason():
    """`unexercised_dimensions: {x: ""}` must read exactly like no declaration at all.

    Same bargain as `short_text_ok` (ADR-0021): the tolerance costs a sentence a reviewer can
    disagree with, and an empty string is not one.
    """
    agg = _agg(DOCS, catalog_number=1.0, software_version=1.0)
    blank = coverage_line(agg, DOCS, {"firmware_version": "   "})
    assert blank == coverage_line(agg, DOCS)


def test_a_pack_with_some_declared_and_some_not_says_both():
    agg = _agg(API, endpoint=1.0, method=1.0, api_version=1.0, auth_flow=1.0)
    line = coverage_line(agg, API, {"required_scopes": "This vendor declares no scope anywhere."})
    assert "**4 of 6**" in line
    assert "**scopes** is exercised by no task; [`pack.yaml`](pack.yaml) declares the reason." in line
    assert "**params** is exercised by no task, and no written reason is declared" in line


def test_labels_come_from_the_contract_not_the_dimension_key():
    """A card reads `firmware`, not `firmware_version` — the label the cohort's tables already use."""
    agg = _agg(DOCS, catalog_number=1.0, software_version=1.0)
    line = coverage_line(agg, DOCS)
    assert "**firmware**" in line
    assert "firmware_version" not in line
    assert "catalog, software" in line


def test_the_stated_count_is_the_arithmetic_the_published_mean_actually_used():
    """Not a restatement of the contract — a fact about the number printed beside the line.

    Built from `aggregate()` over real run records so the count is checked against the same code
    path that computes `overall_accuracy`, rather than against a hand-built dict.
    """
    runs = [{"task_id": "t", "format_failure": False,
             "dimensions": {d: (None if d == "required_scopes" else 1.0) for d in DIMENSIONS}}]
    agg = aggregate(runs)
    covered, missing = covered_dimensions(agg, API)
    assert missing == ["required_scopes"]
    assert len(covered) == 5
    assert agg["overall_accuracy"] == 1.0  # the mean was taken over five, not six
    assert "**5 of 6**" in coverage_line(agg, API)


def test_a_line_disagreeing_with_the_published_overall_raises_rather_than_renders():
    """If the two ever disagree the line would describe a different number than the one beside it."""
    agg = _full(API)
    agg["overall_accuracy"] = None
    with pytest.raises(ValueError, match="coverage disagrees"):
        coverage_line(agg, API)

    empty = _agg(API)
    empty["overall_accuracy"] = 0.5
    with pytest.raises(ValueError, match="coverage disagrees"):
        coverage_line(empty, API)


def test_a_pack_with_no_scored_dimension_at_all_claims_no_overall():
    line = coverage_line(_agg(API), API)
    assert "publishes no overall" in line
    assert "mean of" not in line


def test_the_line_is_one_line():
    """It is pasted into a card's header block as a single line; a newline would break placement."""
    for agg, contract in ((_full(API), API), (_agg(DOCS, catalog_number=1.0), DOCS), (_agg(API), API)):
        assert "\n" not in coverage_line(agg, contract)


def test_the_adr_citation_is_a_parameter_so_each_repo_can_cite_it_its_own_way():
    """The packs repo writes `public ADR-0045`; this repo writes `ADR-0045`. Same generator."""
    assert "(ADR-0045)" in coverage_line(_full(API), API)
    assert "(public ADR-0045)" in coverage_line(_full(API), API, adr_ref="public ADR-0045")


def test_the_default_contract_is_the_api_one_exactly_as_every_other_renderer():
    assert coverage_line(_full(API), None) == coverage_line(_full(API), API)


# --------------------------------------------------------------------------- the cohort note

def test_a_cohort_where_every_pack_is_complete_says_that_plainly():
    note = coverage_cohort_note([("a", _full(API)), ("b", _full(API))], API)
    assert "mean of all 6 declared dimensions" in note
    assert "no task exercises" not in note


def test_the_cohort_note_counts_the_packs_and_names_each_shortfall():
    short = _agg(API, **{d: 1.0 for d in API.dimensions if d != "required_scopes"})
    other = _agg(API, **{d: 1.0 for d in API.dimensions if d != "auth_flow"})
    note = coverage_cohort_note(
        [("a", _full(API)), ("b", short), ("c", short), ("d", other)], API)
    assert "Of 4 measured packs against 6 declared dimensions" in note
    assert "1 scores all 6, 3 score 5 of 6" in note
    assert "**scopes** in 2 and **auth** in 1" in note


def test_a_single_pack_cohort_reads_as_one_pack_not_as_a_distribution():
    note = coverage_cohort_note([("a", _agg(DOCS, catalog_number=1.0, software_version=1.0))], DOCS)
    assert "The single measured pack scores 2 of 3" in note
    assert "no task exercises **firmware**." in note
    assert "Of 1 measured pack" not in note


def test_a_cohort_note_over_no_pack_raises_rather_than_rendering_a_sentence_about_nothing():
    """The vacuous-green shape: an empty sweep that renders cleanly is worse than one that fails."""
    with pytest.raises(ValueError, match="no measured pack"):
        coverage_cohort_note([], API)


def test_both_registered_contracts_render_a_note():
    """A cohort added later must not silently have no coverage vocabulary."""
    for contract in CONTRACTS.values():
        agg = _full(contract)
        assert coverage_cohort_note([("a", agg)], contract).startswith("> **")
        assert coverage_line(agg, contract).startswith("**Dimension coverage")
