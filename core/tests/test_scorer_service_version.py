"""A service-qualified version is the same version (ADR-0020).

The prompt contract offers `<service>/v1` as a legal `api_version` answer in its own right, and
`normalize_version` did not accept the form the contract advertised. On an API documented as versioned
per service, a model that had read the documentation answered `ledger/v1` where ground truth said `v1`
and the dimension read 1%.

These tests pin the collapse, its symmetry, its limits, and the thing the first attempt got wrong: the
exhibit must keep what the model actually wrote.
"""
import pytest

from core.answer_block import AnswerSummary, Endpoint
from core.scorer import normalize_version, score_task


# --------------------------------------------------------------------------- #
# The collapse.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("written,expected", [
    ("ledger/v1", "v1"),
    ("report/v1", "v1"),
    ("oauth2/v1", "v1"),
    ("async/v1", "v1"),
    ("search/v3", "v3"),
    ("things/beta", "beta"),
    ("Record/V1", "v1"),        # case-folded like every other spelling
    ("/ledger/v1", "v1"),       # a leading slash was already stripped
])
def test_a_service_qualified_version_collapses_to_the_version(written, expected):
    assert normalize_version(written) == expected


@pytest.mark.parametrize("written", ["v1", "v3", "beta", "oauth", "v2025"])
def test_a_bare_version_is_untouched(written):
    """The overwhelmingly common case must not move, or every carded vendor re-scores."""
    assert normalize_version(written) == written


@pytest.mark.parametrize("written", ["a/b/v1", "services/rest/ledger/v1"])
def test_more_than_one_leading_segment_is_left_alone(written):
    """Only a single service qualifier is collapsed. A whole base path is not a version, and
    silently reducing one would hide a pack writing the wrong thing in this field."""
    assert normalize_version(written) == written.lower()


@pytest.mark.parametrize("written", ["record/things", "v1/record", "customer/107"])
def test_a_pair_whose_tail_is_not_a_version_is_left_alone(written):
    assert normalize_version(written) == written.lower()


def test_the_sentinels_still_win():
    """A service-qualified sentinel is still "no version" — the ADR-0008 rule is not bypassed."""
    assert normalize_version("<none>") == ""
    assert normalize_version("none") == ""


# --------------------------------------------------------------------------- #
# Symmetry, and what it still refuses to credit.
# --------------------------------------------------------------------------- #

def _task(gt_version: str, path: str = "/ledger/v1/customer"):
    return {
        "id": "t", "category": "foundational", "job_category": "authenticate",
        "prompt": "p",
        "ground_truth": {
            "endpoints": [{"method": "GET", "path": path, "api_version": gt_version,
                           "operation_id": "op"}],
            "auth_flow": "OAuth2 bearer token",
            "required_scopes": [],
            "key_parameters": [{"name": "id", "in": "path", "required": True}],
            "success_shape": "200",
            "common_failure_modes": ["x"],
        },
    }


def _answer(version: str, path: str = "/ledger/v1/customer"):
    return AnswerSummary(
        endpoints=[Endpoint(method="GET", path=path, api_version=version)],
        auth_flow="OAuth2 bearer token", required_scopes=[], key_parameters=["id"],
    )


@pytest.mark.parametrize("gt,ans", [
    ("v1", "ledger/v1"),   # the case that produced this ADR
    ("ledger/v1", "v1"),   # and its mirror — a pack may write either
    ("ledger/v1", "report/v1"),  # both collapse; see the test below for why this is safe
])
def test_the_collapse_is_symmetric(gt, ans):
    score = score_task(_task(gt), _answer(ans))
    assert score.dim("api_version").score == 1.0


def test_a_genuinely_different_version_still_scores_zero():
    """The dimension keeps its teeth: this is not "any version matches any version"."""
    assert score_task(_task("v3"), _answer("ledger/v1")).dim("api_version").score == 0.0


def test_the_wrong_service_is_caught_by_the_endpoint_dimension_not_this_one():
    """Why collapsing `report/v1` and `ledger/v1` together cannot credit the wrong service:
    api_version is scored only on an endpoint whose PATH matched, and the service lives in the
    path. An answer aimed at the wrong service fails earlier and never reaches this rule."""
    score = score_task(_task("v1", "/ledger/v1/customer"),
                       _answer("report/v1", "/report/v1/ledgerquery"))
    assert score.dim("endpoint").score == 0.0
    assert score.dim("api_version").score == 0.0


# --------------------------------------------------------------------------- #
# The exhibit.
# --------------------------------------------------------------------------- #

def test_the_exhibit_records_what_the_model_wrote_not_the_normalized_form():
    """The first attempt at ADR-0020 normalized this field too, which rewrote ten archived
    `search/v1` strings to `v1` in a frozen fixture without moving a single score. The
    byte-identical regression assertion caught it. Losing the raw answer would destroy the
    evidence needed to tell a wrong version from a differently-spelled right one."""
    score = score_task(_task("v1"), _answer("ledger/v1"))
    match = score.endpoint_matches[0]
    assert match["answer_api_version"] == "ledger/v1"
    assert match["version_ok"] is True
