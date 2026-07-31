"""ADR-0041 — a pack may declare, in writing, that its own auth key cannot be corroborated.

ADR-0011 refuses to score `auth_flow` when the SCORER cannot positively test the style. This is the
same rule one level up: it refuses to score when the PACK cannot positively establish which style is
true. The forcing case is a vendor whose only readable statement about its login style is a
machine-generated `securityDefinitions` block carrying a placeholder URL and no token URL, whose
documentation is closed to automated readers, and whose one auth-adjacent document ships placeholder
Latin where the grant type should be. Scoring that would publish a model's answer as wrong on the
authority of a key the pack's own author does not trust.

The vendor is a measured prospect and cannot be named here, so the fixtures are neutral.

Every assertion was verified by breaking it on purpose.
"""
import pytest

from core import scorer
from core.answer_block import AnswerSummary, Endpoint


def _gt(**over):
    gt = {
        "endpoints": [{"method": "GET", "path": "/widgets/{id}", "api_version": "v1"}],
        "auth_flow": "OAuth 2.0 implicit grant; the document publishes no token URL",
        "required_scopes": ["Widgets"],
        "key_parameters": [{"name": "id", "in": "path", "required": True}],
    }
    gt.update(over)
    return gt


def _answer(auth="OAuth2 client credentials"):
    return AnswerSummary(
        endpoints=[Endpoint(method="GET", path="/widgets/{id}", api_version="v1")],
        auth_flow=auth, required_scopes=["Widgets"], key_parameters=["id"],
    )


REASON = ("the sole first-party statement is a generated securityDefinitions block with a "
          "placeholder authorizationUrl and no tokenUrl, and the documentation that would "
          "corroborate it is closed to automated readers")


# --------------------------------------------------------------------------------------------- #
# Inertness. This is what lets the field exist without moving a single archived number.
# --------------------------------------------------------------------------------------------- #

def test_a_task_that_does_not_declare_it_is_completely_unaffected():
    for absent in ({}, {"auth_flow_not_corroborable": None}, {"auth_flow_not_corroborable": False}):
        gt = _gt(**absent)
        assert scorer.uncorroborated_auth_reason(gt) is None
        s = scorer.score_task({"id": "t", "ground_truth": gt}, _answer("OAuth2 implicit grant"))
        assert s.dimensions["auth_flow"].score == 1.0


def test_the_dimension_still_scores_zero_for_a_mismatch_when_undeclared():
    """The behaviour every published pack relies on: a wrong style is still wrong."""
    s = scorer.score_task({"id": "t", "ground_truth": _gt()}, _answer("OAuth2 client credentials"))
    assert s.dimensions["auth_flow"].score == 0.0


# --------------------------------------------------------------------------------------------- #
# The declaration itself.
# --------------------------------------------------------------------------------------------- #

def test_a_declared_reason_makes_the_dimension_n_a():
    gt = _gt(auth_flow_not_corroborable=REASON)
    s = scorer.score_task({"id": "t", "ground_truth": gt}, _answer("OAuth2 client credentials"))
    assert s.dimensions["auth_flow"].score is None
    assert "n/a" in s.dimensions["auth_flow"].detail


def test_the_reason_travels_into_the_detail_so_a_reader_can_disagree_with_it():
    gt = _gt(auth_flow_not_corroborable=REASON)
    s = scorer.score_task({"id": "t", "ground_truth": gt}, _answer())
    assert "placeholder authorizationUrl" in s.dimensions["auth_flow"].detail


def test_it_is_n_a_even_when_the_answer_would_have_MATCHED():
    """n/a means unmeasurable, not "wrong". It must not quietly become a free point either.

    This is the direction that would flatter a result: declaring the field on a task whose answers
    happen to match would convert 1.0 into n/a and REMOVE a correct cell from the mean. Both
    directions are the same rule — the dimension is not measured, whichever way it would have gone.
    """
    gt = _gt(auth_flow_not_corroborable=REASON)
    s = scorer.score_task({"id": "t", "ground_truth": gt}, _answer("OAuth 2.0 implicit grant"))
    assert s.dimensions["auth_flow"].score is None


def test_no_other_dimension_is_touched():
    gt = _gt(auth_flow_not_corroborable=REASON)
    s = scorer.score_task({"id": "t", "ground_truth": gt}, _answer())
    assert s.dimensions["endpoint"].score == 1.0
    assert s.dimensions["method"].score == 1.0
    assert s.dimensions["api_version"].score == 1.0
    assert s.dimensions["required_scopes"].score == 1.0
    assert s.dimensions["key_parameters"].score == 1.0


# --------------------------------------------------------------------------------------------- #
# THE MUST-NOT-ABUSE PROPERTIES. Each was verified by breaking it.
# --------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", [True, "", "   ", 1, [], {}])
def test_a_reason_that_is_not_written_out_is_refused(bad):
    """A bare `true` is exactly the silent opt-out this field must never become (cf. ADR-0021)."""
    with pytest.raises(ValueError, match="non-empty reason"):
        scorer.uncorroborated_auth_reason({"auth_flow_not_corroborable": bad})


def test_declaring_it_does_not_excuse_prose_the_scorer_cannot_NAME():
    """It decides whether a nameable style is SCORED. It never makes an unnameable style acceptable.

    Without this, the field would be a way around ADR-0011: a pack with vague auth prose could
    declare itself uncorroborable and sail past the round-trip gate. `roundtrip` reads the prose
    independently, so the two checks cannot be collapsed.
    """
    from core.roundtrip import check_task
    task = {"id": "t", "prompt": "p",
            "ground_truth": _gt(auth_flow="send credentials as documented",
                                auth_flow_not_corroborable=REASON)}
    control = check_task(task)
    assert not control.ok
    assert any("names no login style the scorer recognizes" in p for p in control.problems)
