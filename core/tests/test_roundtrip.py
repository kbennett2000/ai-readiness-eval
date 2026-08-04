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
    # `check_pack` also returns PACK-level controls — `(answer-surfaces)` (ADR-0037) and
    # `(dimension-coverage)` (ADR-0045) — which answer a question about the suite rather than about
    # one task, and so have no scored answer of their own. They are named, not filtered by shape, so
    # a task that genuinely lost its score cannot slip through this exemption.
    pack_level = {"(dimension-coverage)", "(answer-surfaces)", "(suite)",
                  "(endpoint-base-evidence)"}
    controls = [c for c in check_pack(acme_pack) if c.task_id not in pack_level]
    assert controls, "every control was pack-level, so this asserted nothing about a task"
    for control in controls:
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

def test_a_login_style_the_scorer_cannot_name_blocks_the_pack():
    """The scoring hole ADR-0011 closes, now enforced rather than warned about.

    Ground truth naming no listed style scores 1.0 against any answer that also names none — the
    dimension reads as applicable while testing nothing. Mutual TLS is a real auth shape and a
    genuinely unlisted one, so this is the case a future pack actually hits. The control blocks it,
    and the message points at the fix: teach `scorer._AUTH_STYLES`, do not rewrite the pack.
    """
    control = check_task(_task(auth_flow="Mutual TLS: the caller presents a client certificate"))
    assert not control.ok
    assert any("names no login style the scorer recognizes" in p for p in control.problems)
    assert any("scorer._AUTH_STYLES" in p for p in control.problems)
    # ...and the reason it must block: the dimension still scores a perfect mark.
    assert control.direct.dim("auth_flow").score == 1.0


@pytest.mark.parametrize("auth_flow", [
    "API key in the X-Api-Key header",
    "Session token from the logon call, sent in the Authorization header",
    "HTTP Basic-auth login (not a token-grant flow)",
    # ADR-0040. A vendor whose published specification declares `flow: implicit` blocked all twelve
    # of its tasks here until `oauth2-implicit` was taught, which is the gate doing its job — and
    # this row is what pins that it now passes.
    "OAuth 2.0 implicit grant against the tenant authorization host; no token URL is published",
])
def test_the_styles_taught_this_cycle_no_longer_block(auth_flow):
    """Every login style taught to close a scoring hole must pass the gate it would have failed."""
    control = check_task(_task(auth_flow=auth_flow))
    assert control.ok, control.problems


def test_a_recognized_auth_shape_draws_no_problem():
    assert check_task(_task()).ok


def test_an_asymmetric_scoring_rule_is_caught(monkeypatch):
    """The tripwire this gate exists for.

    A rule that credits only a canonical answer phrase, while ground truth is documented as prose,
    makes the auth dimension unwinnable for every pack — the dimension would read 0.00 everywhere
    and look like a finding about vendors. The control fails immediately, before any spend.
    """
    monkeypatch.setattr(scorer, "auth_flow_matches",
                        lambda gt, ans, alternates=(): (ans or "").strip() == "OAuth2 client-credentials")
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


# --------------------------------------------------------------------------- #
# Either-of auth: a bad declaration blocks here, before any grid (ADR-0023)
# --------------------------------------------------------------------------- #

_GOOD_ALT = {"style": "api-key",
             "evidence": "https://docs.example-vendor.com/auth",
             "note": "The vendor's authentication page documents the key header as a valid "
                     "credential for this operation on its own."}


def _alt_task(**alt):
    entry = dict(_GOOD_ALT)
    entry.update(alt)
    return _task(auth_flow="PS-Auth API key header plus an established session from sign-in.",
                 auth_flow_alternates=[entry])


def test_a_well_formed_alternate_passes_the_control():
    control = check_task(_alt_task())
    assert control.ok, control.problems


@pytest.mark.parametrize("bad,expected", [
    ({"style": "api-keys"}, "not a login style the scorer knows"),
    ({"style": "session-token"}, "already the style auth_flow requires"),
    ({"evidence": "https://web.archive.org/web/2022/https://docs.example-vendor.com/auth"},
     "rehosts rather than publishes"),
    ({"note": "short"}, "at least 40 characters"),
])
def test_a_bad_alternate_blocks_the_pack_before_any_grid(bad, expected):
    """Each rule is blocking, not a note. A bad declaration never fails loudly at scoring time — it
    silently changes what counts as a correct answer, which is the failure mode that has to be
    caught before money is spent rather than after a card is published."""
    control = check_task(_alt_task(**bad))
    assert not control.ok
    assert any(expected in p for p in control.problems), control.problems


def test_an_alternate_the_prose_never_names_blocks_the_pack():
    control = check_task(_task(
        auth_flow="OAuth2 bearer token in the Authorization header.",
        auth_flow_alternates=[dict(_GOOD_ALT, style="api-key")]))
    assert not control.ok
    assert any("never names 'api-key'" in p for p in control.problems), control.problems


def test_a_task_declaring_no_alternates_is_unaffected():
    """The invariance restated at the gate: every existing pack declares nothing, so nothing about
    the control's verdict on them can change."""
    assert check_task(_task()).ok
