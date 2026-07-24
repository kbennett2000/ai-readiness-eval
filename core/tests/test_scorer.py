"""Tests for the deterministic scorer (core/scorer.py).

Covers normalization edge cases and the two documented judgment calls
(any-of scopes; required-subset params).
"""
import pytest

from core.answer_block import AnswerSummary, Endpoint
from core import scorer


# --------------------------------------------------------------------------- #
# Normalization units
# --------------------------------------------------------------------------- #

def test_normalize_path_strips_host_and_query():
    assert scorer.normalize_path("https://acme.api.identitynow.com/v3/accounts?limit=5") == ["accounts"]


def test_normalize_path_strips_leading_version():
    assert scorer.normalize_path("/v3/accounts") == ["accounts"]
    assert scorer.normalize_path("/beta/sources/{sourceId}/load-accounts") == ["sources", "{}", "load-accounts"]
    assert scorer.normalize_path("/oauth/token") == ["token"]


def test_normalize_path_strips_version_anywhere():
    # newer per-service versioning puts the version last: /search/v1 == /v3/search (resource "search")
    assert scorer.normalize_path("/search/v1") == ["search"]
    assert scorer.normalize_path("/search/v1") == scorer.normalize_path("/v3/search")
    assert scorer.normalize_path("/public-identities/v1") == scorer.normalize_path("/v3/public-identities")


def test_normalize_path_case_insensitive():
    assert scorer.normalize_path("/V3/Accounts") == scorer.normalize_path("/v3/accounts")


def test_placeholder_names_are_interchangeable():
    assert scorer.normalize_path("/v3/accounts/{id}") == scorer.normalize_path("/v3/accounts/{accountId}")


def test_normalize_method_and_version():
    assert scorer.normalize_method(" get ") == "GET"
    assert scorer.normalize_version("/Beta") == "beta"


# --- unversioned APIs (ADR-0008) ------------------------------------------- #

@pytest.mark.parametrize("answer", ["none", "None", "N/A", "na", "<none>", "(none)", "[N/A]",
                                    "no version", "unversioned", "-", "null", " none ", None, ""])
def test_saying_there_is_no_version_equals_omitting_it(answer):
    """An unversioned API is scored on whether the model knows it — not on which word it picked."""
    assert scorer.normalize_version(answer) == ""


@pytest.mark.parametrize("real", ["v3", "beta", "oauth", "v2025", "nano"])
def test_real_versions_are_untouched_by_the_sentinel_rule(real):
    """The rule must not move any versioned vendor's score — incl. versions that merely start
    like a sentinel ('nano'), and sentinels answered where a real version was required."""
    assert scorer.normalize_version(real) == real
    assert scorer.normalize_version("none") != scorer.normalize_version(real)


def test_unversioned_endpoint_credits_a_none_answer():
    """End-to-end: ground truth '/' + an answer of '<none>' scores the version dimension 1.0."""
    task = _task([{"method": "GET", "path": "/Vault/API/Safes", "api_version": "/"}])
    score = scorer.score_task(task, _ans([("GET", "/Vault/API/Safes", "<none>")]))
    assert score.dim("api_version").score == 1.0


def test_unversioned_endpoint_still_fails_an_invented_version():
    """The dimension keeps its teeth: asserting a version this API does not have is wrong."""
    task = _task([{"method": "GET", "path": "/Vault/API/Safes", "api_version": "/"}])
    score = scorer.score_task(task, _ans([("GET", "/Vault/API/Safes", "v1")]))
    assert score.dim("api_version").score == 0.0


def test_canonical_auth_flow():
    assert scorer.canonical_auth_flow("OAuth2 client-credentials grant") == "oauth2-client-credentials"
    assert scorer.canonical_auth_flow("grant_type=client_credentials") == "oauth2-client-credentials"
    assert scorer.canonical_auth_flow("OAuth2 client credentials") == "oauth2-client-credentials"  # space
    assert scorer.canonical_auth_flow("OAuth2 bearer token (see auth-token).") == "bearer-token"
    assert scorer.canonical_auth_flow("Authorization: Bearer <jwt>") == "bearer-token"
    assert scorer.canonical_auth_flow("magic") == "unknown"


def test_auth_flow_matches_concept_containment():
    gt_grant = "OAuth2 client-credentials grant; returns a JWT bearer token"
    gt_call = "OAuth2 bearer token (see auth-token)."
    # grant task: answer must name client-credentials (space or hyphen)
    assert scorer.auth_flow_matches(gt_grant, "OAuth2 client credentials")
    assert scorer.auth_flow_matches(gt_grant, "client-credentials grant")
    assert not scorer.auth_flow_matches(gt_grant, "just a bearer token")  # missed the grant
    # per-call task: bearer is required; over-specifying client-credentials still matches
    assert scorer.auth_flow_matches(gt_call, "OAuth2 bearer token")
    assert scorer.auth_flow_matches(gt_call, "OAuth2 client credentials bearer token")
    assert not scorer.auth_flow_matches(gt_call, "client credentials only")


def test_bare_scope_strips_inline_comment():
    assert scorer.bare_scope("idn:sources:manage   # createSource and importAccounts") == "idn:sources:manage"
    assert scorer.bare_scope("  sp:search:read  ") == "sp:search:read"


# --------------------------------------------------------------------------- #
# Helpers to build tiny tasks/answers
# --------------------------------------------------------------------------- #

def _task(endpoints, auth="OAuth2 bearer token (see auth-token).", scopes=None, params=None):
    return {
        "id": "t",
        "ground_truth": {
            "endpoints": endpoints,
            "auth_flow": auth,
            "required_scopes": scopes or [],
            "key_parameters": params or [],
        },
    }


def _ans(endpoints, auth="OAuth2 bearer token", scopes=None, params=None):
    return AnswerSummary(
        endpoints=[Endpoint(*e) for e in endpoints],
        auth_flow=auth,
        required_scopes=scopes or [],
        key_parameters=params or [],
    )


# --------------------------------------------------------------------------- #
# Endpoint / method / version scoring
# --------------------------------------------------------------------------- #

def test_perfect_single_endpoint():
    task = _task(
        [{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}],
        scopes=["idn:accounts:read"],
        params=[{"name": "filters", "in": "query", "required": True}],
    )
    ans = _ans([("GET", "/v3/accounts", "v3")], scopes=["idn:accounts:read"], params=["filters"])
    s = scorer.score_task(task, ans)
    assert s.dim("endpoint").score == 1.0
    assert s.dim("method").score == 1.0
    assert s.dim("api_version").score == 1.0
    assert s.dim("auth_flow").score == 1.0
    assert s.dim("required_scopes").score == 1.0
    assert s.dim("key_parameters").score == 1.0


def test_right_path_wrong_method():
    task = _task([{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}])
    ans = _ans([("POST", "/v3/accounts", "v3")])
    s = scorer.score_task(task, ans)
    assert s.dim("endpoint").score == 1.0
    assert s.dim("method").score == 0.0


def test_wrong_path_zeroes_endpoint_and_method():
    task = _task([{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}])
    ans = _ans([("GET", "/v3/wrong", "v3")])
    s = scorer.score_task(task, ans)
    assert s.dim("endpoint").score == 0.0
    # method can't be credited on an unidentified endpoint
    assert s.dim("method").score == 0.0
    assert s.dim("api_version").score == 0.0


def test_wrong_version_field():
    task = _task([{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}])
    ans = _ans([("GET", "/v3/accounts", "beta")])
    s = scorer.score_task(task, ans)
    assert s.dim("api_version").score == 0.0
    assert s.dim("endpoint").score == 1.0  # path still matched


def test_multi_endpoint_partial_coverage():
    task = _task([
        {"method": "POST", "path": "/v3/sources", "api_version": "v3"},
        {"method": "POST", "path": "/beta/sources/{sourceId}/load-accounts", "api_version": "beta"},
    ])
    # answer includes only the first endpoint
    ans = _ans([("POST", "/v3/sources", "v3")])
    s = scorer.score_task(task, ans)
    assert s.dim("endpoint").score == 0.5
    assert s.dim("method").score == 0.5


def test_multi_endpoint_full_coverage_with_extra_ignored():
    task = _task([
        {"method": "POST", "path": "/v3/sources", "api_version": "v3"},
        {"method": "POST", "path": "/beta/sources/{sourceId}/load-accounts", "api_version": "beta"},
    ])
    ans = _ans([
        ("POST", "/v3/sources", "v3"),
        ("POST", "/beta/sources/{id}/load-accounts", "beta"),
        ("GET", "/v3/unrelated", "v3"),  # extra, ignored
    ])
    s = scorer.score_task(task, ans)
    assert s.dim("endpoint").score == 1.0
    assert s.dim("method").score == 1.0
    assert s.dim("api_version").score == 1.0


def test_doc_only_endpoint_scores_like_any_other():
    # /oauth/token style: api_version 'oauth', no spec_ref needed for scoring
    task = _task([{"method": "POST", "path": "/oauth/token", "api_version": "oauth"}],
                 auth="OAuth2 client-credentials grant")
    ans = _ans([("POST", "/oauth/token", "oauth")], auth="OAuth2 client-credentials")
    s = scorer.score_task(task, ans)
    assert s.dim("endpoint").score == 1.0
    assert s.dim("api_version").score == 1.0
    assert s.dim("auth_flow").score == 1.0


# --------------------------------------------------------------------------- #
# Scope scoring (any-of overlap; ADR-0004 judgment call)
# --------------------------------------------------------------------------- #

def test_scopes_any_of_overlap_passes_on_one_match():
    # ground truth lists alternatives; naming one should pass
    task = _task([{"method": "POST", "path": "/v3/access-requests", "api_version": "v3"}],
                 scopes=["idn:access-request:manage        # ORG_ADMIN",
                         "idn:access-request-self:manage   # self"])
    ans = _ans([("POST", "/v3/access-requests", "v3")], scopes=["idn:access-request:manage"])
    s = scorer.score_task(task, ans)
    assert s.dim("required_scopes").score == 1.0


def test_scopes_no_overlap_fails():
    task = _task([{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}],
                 scopes=["idn:accounts:read"])
    ans = _ans([("GET", "/v3/accounts", "v3")], scopes=["idn:wrong:scope"])
    s = scorer.score_task(task, ans)
    assert s.dim("required_scopes").score == 0.0


def test_empty_gt_scopes_is_not_applicable():
    task = _task([{"method": "POST", "path": "/oauth/token", "api_version": "oauth"}], scopes=[])
    ans = _ans([("POST", "/oauth/token", "oauth")], scopes=[])
    s = scorer.score_task(task, ans)
    assert s.dim("required_scopes").score is None
    assert not s.dim("required_scopes").applicable


def test_scope_comment_stripped_on_both_sides():
    task = _task([{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}],
                 scopes=["idn:accounts:read   # also idn:accounts:manage"])
    # model answers with a trailing comment too (defensive)
    ans = _ans([("GET", "/v3/accounts", "v3")], scopes=["idn:accounts:read # note"])
    s = scorer.score_task(task, ans)
    assert s.dim("required_scopes").score == 1.0


# --------------------------------------------------------------------------- #
# Param scoring (required-subset containment; ADR-0004 judgment call)
# --------------------------------------------------------------------------- #

def test_params_required_subset_containment():
    task = _task(
        [{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}],
        params=[
            {"name": "filters", "in": "query", "required": True},
            {"name": "limit", "in": "query", "required": False},   # optional, ignored
            {"name": "offset", "in": "query", "required": False},
        ],
    )
    # names only the required one -> full marks; optional omission does not hurt
    ans = _ans([("GET", "/v3/accounts", "v3")], params=["filters"])
    s = scorer.score_task(task, ans)
    assert s.dim("key_parameters").score == 1.0


def test_params_missing_required_fails():
    task = _task(
        [{"method": "POST", "path": "/v3/access-requests", "api_version": "v3"}],
        params=[
            {"name": "requestType", "in": "body", "required": True},
            {"name": "requestedFor", "in": "body", "required": True},
        ],
    )
    ans = _ans([("POST", "/v3/access-requests", "v3")], params=["requestType"])
    s = scorer.score_task(task, ans)
    assert s.dim("key_parameters").score == 0.0
    assert "requestedfor" in s.dim("key_parameters").detail.lower()


def test_params_case_insensitive():
    task = _task(
        [{"method": "POST", "path": "/v3/access-requests", "api_version": "v3"}],
        params=[{"name": "requestType", "in": "body", "required": True}],
    )
    ans = _ans([("POST", "/v3/access-requests", "v3")], params=["REQUESTTYPE"])
    s = scorer.score_task(task, ans)
    assert s.dim("key_parameters").score == 1.0


def test_no_required_params_is_not_applicable():
    task = _task(
        [{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}],
        params=[{"name": "limit", "in": "query", "required": False}],
    )
    ans = _ans([("GET", "/v3/accounts", "v3")], params=[])
    s = scorer.score_task(task, ans)
    assert s.dim("key_parameters").score is None


# --------------------------------------------------------------------------- #
# Format failure
# --------------------------------------------------------------------------- #

def test_format_failure_score():
    s = scorer.format_failure_score("t", "no block")
    assert s.format_failure
    assert s.failure_reason == "no block"
    assert s.dimensions == {}
