"""The ground-truth round-trip control (ADR-0010): can a task score its own answer key?

Two paths per task — the answer built directly from ground truth, and the same answer serialized to
an answer block and parsed back. Both must score 1.0 on every applicable dimension. These tests also
pin what the control does NOT claim: it cannot detect a wrong answer key, only an unscoreable one.
"""
import pytest

from core import scorer
from core.answer_block import parse, render_block
from core.roundtrip import (
    answer_from_ground_truth,
    check_pack,
    check_task,
    format_report,
    summarize_failures,
)


def _task(**overrides) -> dict:
    """A minimal schema-shaped task; overrides are merged into ground_truth."""
    gt = {
        "endpoints": [{"method": "GET", "path": "/v3/widgets", "api_version": "v3",
                       "operation_id": "listWidgets"}],
        "auth_flow": "OAuth2 bearer token",
        "required_scopes": ["widgets:read"],
        "key_parameters": [{"name": "limit", "in": "query", "required": True}],
        "success_shape": "200 OK",
        "common_failure_modes": ["wrong scope"],
    }
    gt.update(overrides)
    return {"id": "sample", "category": "foundational", "job_category": "search-filter",
            "prompt": "How?", "ground_truth": gt}


# --------------------------------------------------------------------------- #
# The control on a healthy pack
# --------------------------------------------------------------------------- #

def test_every_fixture_task_scores_its_own_ground_truth(acme_pack):
    controls = check_pack(acme_pack)
    assert controls
    assert all(c.ok for c in controls), [c.problems for c in controls if not c.ok]
    _text, total = format_report(controls)
    assert total == 0


def test_both_paths_are_scored(acme_pack):
    for control in check_pack(acme_pack):
        assert control.direct is not None
        assert control.parsed is not None, f"{control.task_id}: text path never produced a score"
        assert control.block_text.startswith("```answer-summary")


def test_na_dimensions_are_reported_not_failed(acme_pack):
    by_id = {c.task_id: c for c in check_pack(acme_pack)}
    # No scopes in ground truth -> required_scopes is n/a by design, and that is not a failure.
    assert by_id["gadget-fetch"].ok
    assert "required_scopes" in by_id["gadget-fetch"].na_dimensions
    # Nothing marked `required: true` -> key_parameters is n/a, reported as a non-blocking note.
    assert by_id["widget-list"].ok
    assert "key_parameters" in by_id["widget-list"].na_dimensions
    assert any("required: true" in note for note in by_id["widget-list"].notes)


# --------------------------------------------------------------------------- #
# The text path: the answer key must survive the answer-block contract
# --------------------------------------------------------------------------- #

def test_rendered_ground_truth_round_trips_through_parse(acme_pack):
    for task in acme_pack.load_tasks():
        answer = answer_from_ground_truth(task)
        result = parse(render_block(answer))
        assert not result.is_failure, f"{task['id']}: {result.failure and result.failure.reason}"
        assert [e.path for e in result.summary.endpoints] == [e.path for e in answer.endpoints]
        assert result.summary.auth_flow == answer.auth_flow


def test_auth_prose_with_a_colon_survives_serialization_verbatim():
    """The anti-laundering regression.

    Ground-truth auth prose routinely contains `": "`, which is why the mock provider substitutes a
    canonical phrase. The control must NOT do that — canonicalizing would test a string the control
    invented rather than the answer key the pack documents. `yaml.safe_dump` quotes it correctly.
    """
    prose = "OAuth2 client-credentials: POST /oauth/token, then Authorization: Bearer <jwt>"
    task = _task(auth_flow=prose)
    assert answer_from_ground_truth(task).auth_flow == prose        # verbatim, not canonicalized

    control = check_task(task)
    assert control.ok, control.problems
    assert parse(control.block_text).summary.auth_flow == prose
    assert control.parsed.dim("auth_flow").score == 1.0


def test_mock_canonicalization_is_opt_in():
    task = _task(auth_flow="obtain a token via the client credentials grant")
    assert answer_from_ground_truth(task, canonical_auth=True).auth_flow == "OAuth2 client-credentials"


def test_scopes_keep_their_inline_comments_and_still_score():
    task = _task(required_scopes=["widgets:read   # also accepted: widgets:admin"])
    control = check_task(task)
    assert control.ok, control.problems
    assert control.direct.dim("required_scopes").score == 1.0


# --------------------------------------------------------------------------- #
# What the control catches
# --------------------------------------------------------------------------- #

def test_an_unrecognized_auth_shape_is_flagged_as_close_to_free():
    """A dimension can be applicable and still measure almost nothing.

    The scorer recognizes bearer and client-credentials. Ground truth naming neither scores 1.0
    against any answer that also names neither — so a pack whose vendor uses, say, an API key gets a
    free 100% on auth unless someone teaches the scorer that shape. The control reports it rather
    than blocking: the fix belongs in the scorer, not in the pack.
    """
    control = check_task(_task(auth_flow="API key in the X-Api-Key header"))
    assert control.ok                                        # non-blocking
    assert any("close to free" in note for note in control.notes)
    assert control.direct.dim("auth_flow").score == 1.0      # ...and this is the point


def test_a_recognized_auth_shape_draws_no_note():
    assert not any("close to free" in n for n in check_task(_task()).notes)


def test_an_asymmetric_scoring_rule_is_caught(monkeypatch):
    """The tripwire this gate exists for.

    A rule that credits only a canonical answer phrase, while ground truth is documented as prose,
    makes the auth dimension unwinnable for every pack — the dimension would read 0.00 everywhere
    and look like a finding about vendors. The control fails immediately, before any spend.
    """
    monkeypatch.setattr(scorer, "auth_flow_matches",
                        lambda gt, ans: (ans or "").strip() == "OAuth2 client-credentials")
    control = check_task(_task(auth_flow="Bearer token in the Authorization header"))
    assert not control.ok
    assert any("auth_flow scored 0.00" in p for p in control.problems)


def test_ground_truth_that_cannot_be_parsed_back_is_a_problem():
    """A task with no endpoints renders a block the contract rejects, and leaves endpoint/method/
    api_version unscored. The schema forbids it, but the control must not depend on that."""
    control = check_task(_task(endpoints=[], required_scopes=[], key_parameters=[]))
    assert not control.ok
    assert any("does not parse" in p for p in control.problems)
    assert {"endpoint", "method", "api_version"} <= set(control.na_dimensions)


# --------------------------------------------------------------------------- #
# The gate must never crash the dispatcher
# --------------------------------------------------------------------------- #

def test_a_task_with_no_ground_truth_is_reported_not_raised():
    control = check_task({"id": "broken"})
    assert not control.ok
    assert control.problems == ["task has no ground_truth mapping"]


def test_a_malformed_ground_truth_is_reported_not_raised():
    """`run_pipeline`'s gate loop has no exception handling, so a raising gate would crash the
    unattended dispatcher instead of blocking the target with a written reason. `check_pack` is
    that boundary — it converts any per-task explosion into a written problem."""
    class Boom(dict):
        def get(self, *a, **k):
            raise TypeError("hostile task")

    class HostilePack:
        def load_tasks(self):
            return [{"id": "boom", "ground_truth": Boom()}]

    controls = check_pack(HostilePack())
    assert not controls[0].ok
    assert controls[0].task_id == "boom"
    assert any("TypeError" in p and "hostile task" in p for p in controls[0].problems)


def test_check_pack_reports_unreadable_tasks():
    class BrokenPack:
        def load_tasks(self):
            raise OSError("tasks/ is gone")

    controls = check_pack(BrokenPack())
    assert len(controls) == 1
    assert not controls[0].ok
    assert "tasks could not be loaded" in controls[0].problems[0]


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def test_format_report_counts_problems_and_names_tasks():
    controls = [check_task(_task()), check_task({"id": "broken"})]
    text, total = format_report(controls)
    assert total == 1
    assert "FAIL broken" in text
    assert "ok   sample" in text
    assert "✗ 1 problem(s)" in text


def test_summarize_failures_is_short_enough_for_a_queue_field():
    controls = [check_task({"id": f"t{i}"}) for i in range(6)]
    line = summarize_failures(controls)
    assert "\n" not in line
    assert "(+3 more)" in line
    assert summarize_failures([check_task(_task())]) == ""
