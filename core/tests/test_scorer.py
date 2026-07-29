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


# --- dotted numeric versions (ADR-0025) ------------------------------------ #

@pytest.mark.parametrize("spelling", ["2.0", "v2.0", "V2.0", " 2.0 ", "/2.0", "api/2.0", "api/v2.0"])
def test_a_dotted_numeric_version_reads_the_same_with_or_without_the_v(spelling):
    """A vendor numbering its paths `/api/2.0/...` has no `v` anywhere, while the prompt contract's
    own example demonstrates `v1` — so a model following our contract answers `v2.0` and would lose
    the dimension on notation alone. Symmetric: it applies to ground truth and answer alike."""
    assert scorer.normalize_version(spelling) == "2.0"


def test_the_dotted_rule_does_not_merge_two_different_versions():
    """The whole point is collapsing a notation difference, never a real one."""
    assert scorer.normalize_version("2.0") != scorer.normalize_version("2.1")
    assert scorer.normalize_version("v2.1") != scorer.normalize_version("2.2")
    assert scorer.normalize_version("2.0") != scorer.normalize_version("")


@pytest.mark.parametrize("undotted", ["v1", "v3", "v2025", "beta", "oauth", "nano", "1", "2"])
def test_the_dotted_rule_requires_a_dot_and_so_cannot_touch_the_archived_cohort(undotted):
    """Folding a bare `v1` to `1` is a DIFFERENT question with a different risk profile: `v1` occurs
    694 times across the archived cohort, so that fold could move published numbers, and no measured
    vendor needs it. Requiring the dot is what makes ADR-0025 provably inert on every archive."""
    assert scorer.normalize_version(undotted) == undotted
    assert scorer.normalize_version("v1") != scorer.normalize_version("1")


def test_a_dotted_version_segment_is_stripped_from_a_path_like_any_other(   # ADR-0027
):
    """A dotted numeric version is a version segment, so `normalize_path` strips it — exactly as it
    has always stripped `v3`, `beta` and `oauth`.

    ADR-0025 originally made an exception here and ADR-0027 removed it. The exception meant a vendor
    numbering its paths `/api/2.1/...` had its version compared TWICE — once as the api_version
    dimension and again as a path segment — so one mistake cost two dimensions, while for every
    other measured vendor `/v99/accounts` and `/v3/accounts` compare equal on the path and the
    difference is caught by api_version alone. That asymmetry made one pack's headline
    incomparable to the ten beside it, which is the one thing a cross-vendor study cannot tolerate.
    """
    assert scorer.normalize_path("/api/2.0/jobs/create") == ["api", "jobs", "create"]
    assert scorer.normalize_path("/api/2.1/jobs/create") == scorer.normalize_path(
        "/api/2.2/jobs/create")
    # ...which is the same rule that has always applied to the `vN` spelling:
    assert scorer.normalize_path("/v3/accounts") == scorer.normalize_path("/v99/accounts")


def test_stripping_a_version_segment_never_reaches_an_identifier():
    """THE MUST-NOT that survives ADR-0027. The dot is what separates a version from an id. If a
    bare integer were stripped, `/jobs/123/reset` and `/jobs/456/reset` would compare equal — and
    worse, `/accounts/{id}` collapses to a `{}` sentinel, so a numeric id segment silently matching
    anything is the direction that manufactures endpoint scores. Pinned."""
    assert scorer.normalize_path("/api/2.0/jobs/123/reset") == ["api", "jobs", "123", "reset"]
    assert scorer.normalize_path("/jobs/123") != scorer.normalize_path("/jobs/456")


def test_the_version_dimension_still_has_teeth_after_the_path_stops_carrying_it():
    """The two dimensions are now genuinely independent, which is the point of ADR-0027 — NOT that
    a version mistake becomes free. The endpoint is credited for finding the right resource; the
    version dimension is where answering 2.1 against a ground truth of 2.2 is still scored 0."""
    task = _task([{"method": "POST", "path": "/api/2.2/jobs/create", "api_version": "2.2"}])

    wrong_version = scorer.score_task(task, _ans([("POST", "/api/2.1/jobs/create", "2.1")]))
    assert wrong_version.dim("endpoint").score == 1.0, "the right resource was named"
    assert wrong_version.dim("api_version").score == 0.0, "at the wrong version — still scored 0"

    notation_only = scorer.score_task(task, _ans([("POST", "/api/v2.2/jobs/create", "v2.2")]))
    assert notation_only.dim("endpoint").score == 1.0
    assert notation_only.dim("api_version").score == 1.0, "ADR-0025: `v2.2` is `2.2`"


def test_canonical_auth_flow():
    assert scorer.canonical_auth_flow("OAuth2 client-credentials grant") == "oauth2-client-credentials"
    assert scorer.canonical_auth_flow("grant_type=client_credentials") == "oauth2-client-credentials"
    assert scorer.canonical_auth_flow("OAuth2 client credentials") == "oauth2-client-credentials"  # space
    assert scorer.canonical_auth_flow("OAuth2 bearer token (see auth-token).") == "bearer-token"
    assert scorer.canonical_auth_flow("Authorization: Bearer <jwt>") == "bearer-token"
    assert scorer.canonical_auth_flow("magic") == "unknown"


# --- the authorization-code grant ADR-0030 added ---------------------------- #

def test_the_authorization_code_grant_is_a_style_of_its_own():
    cf = scorer.canonical_auth_flow
    assert cf("OAuth2 authorization code with PKCE") == "oauth2-authorization-code"
    assert cf("OAuth2 Authorization Code") == "oauth2-authorization-code"
    assert cf("OAuth 2.0 auth code grant") == "oauth2-authorization-code"
    assert cf("authorization_code grant") == "oauth2-authorization-code"      # separator-insensitive
    assert cf("PKCE is required for public clients") == "oauth2-authorization-code"


def test_the_authorization_code_grant_outranks_bearer_or_the_dimension_inverts():
    """THE COUNTEREXAMPLE THAT MADE THIS A CORRECTION RATHER THAN A NEW STYLE (ADR-0030).

    Prose describing an authorization-code grant necessarily names the bearer token the grant
    produces — you cannot document the flow without saying what you get at the end of it. With
    `bearer` ranked above, such a ground truth canonicalized to bearer-token while a model answering
    the precise, correct "OAuth2 authorization code with PKCE" canonicalized to `unknown`. The
    dimension inverted: the exact answer scored 0 and a vaguer one scored 1, on both conditions, in
    two packs — one of them already published.

    This is the same argument that puts hmac-signature first, and it is asserted here because the
    order is the ruling: reverse these two rows and the assertion below fails.
    """
    gt = ("OAuth 2.0 authorization code grant with PKCE: redirect the user to the authorization "
          "endpoint, then exchange the returned code at the token endpoint. The resulting access "
          "token is presented as `Authorization: Bearer <token>`.")
    assert scorer.canonical_auth_flow(gt) == "oauth2-authorization-code"
    assert scorer.canonical_auth_flow("OAuth2 authorization code with PKCE") == \
        scorer.canonical_auth_flow(gt), "the correct answer must match the key it describes"


def test_the_authorization_code_grant_does_not_outrank_an_explicit_client_credentials_grant():
    """The conservative half of the ordering. A ground truth that states client-credentials keeps it
    even when its prose also mentions the authorization-code grant it is distinguishing itself from,
    because the explicit statement is the stronger signal."""
    cf = scorer.canonical_auth_flow
    assert cf("OAuth 2.0 client credentials grant (machine-to-machine), not the authorization "
              "code grant") == "oauth2-client-credentials"


def test_the_authorization_code_markers_do_not_fire_on_ordinary_code_prose():
    """`code` alone would fire on every status code, response code and code_verifier in the cohort,
    so the markers are phrases. Pinned because widening them is the obvious, wrong next edit."""
    cf = scorer.canonical_auth_flow
    assert cf("POST a status code lookup; the response code is returned") == "unknown"
    assert cf("send the code_verifier with the request") == "unknown"
    assert cf("a 401 status code means the token expired") == "unknown"


# --- the three login styles ADR-0011 added ---------------------------------- #

def test_canonical_auth_flow_names_the_styles_added_by_adr_0011():
    cf = scorer.canonical_auth_flow
    assert cf("Session token from the logon call, sent in the Authorization header") == "session-token"
    assert cf("The response carries a sessionId identifying the session") == "session-token"
    assert cf("Session established beforehand by posting an authentication string") == "session-token"
    assert cf("the step before establishing a session") == "session-token"
    assert cf("HTTP Basic auth with username and password") == "basic-auth"
    assert cf("Basic-auth login (not a token-grant flow)") == "basic-auth"   # separator-insensitive
    assert cf("API key in the X-Api-Key header") == "api-key"
    assert cf("send the apikey header") == "api-key"
    # still nothing: mutual TLS is a real shape and a deliberately unlisted one
    assert cf("Mutual TLS: the caller presents a client certificate") == "unknown"


def test_precedence_is_table_order_and_is_load_bearing():
    """Which style a multi-style string REQUIRES is the whole ruling; both cases come from real packs."""
    cf = scorer.canonical_auth_flow
    # Shape 1 — a session-token product's prose DENIES OAuth. Substring matching cannot read a
    # negation, so without session-token outranking the OAuth styles this ground truth would
    # REQUIRE the answer to say the documented-wrong thing.
    denies_oauth = ("The response body IS the session token, sent verbatim in the Authorization "
                    "header. Not an OAuth2 flow: there is no client_credentials grant, no token "
                    "endpoint, and no scopes.")
    assert cf(denies_oauth) == "session-token"
    assert scorer.auth_flow_matches(denies_oauth, "session token from the logon call")
    assert not scorer.auth_flow_matches(denies_oauth, "OAuth2 bearer token (client credentials)")
    # Shape 2 — a Basic login that mints a bearer token used on every later call requires BEARER:
    # the dimension measures the per-request credential. Ranking basic-auth higher would move it.
    basic_login_bearer_calls = ("HTTP Basic-auth login with Authorization: Basic ...; the response "
                                "carries access_token and token_type=Bearer, sent as "
                                "Authorization: Bearer on every subsequent call.")
    assert cf(basic_login_bearer_calls) == "bearer-token"
    assert scorer.auth_flow_matches(basic_login_bearer_calls, "OAuth2 bearer token")
    # Shape 3 — an OAuth grant that mentions HTTP Basic client authentication still requires the grant.
    grant_via_basic = ("OAuth2 client-credentials grant; credentials sent via HTTP Basic per "
                       "client_secret_basic. The response returns a Bearer JWT.")
    assert cf(grant_via_basic) == "oauth2-client-credentials"


@pytest.mark.parametrize("answer", [
    "session bearer token",
    "Session bearer token (Authorization header)",
    "session cookie (authString POST)",
    "session-based authentication (login token)",
    "Application Server session authentication",
    "Session token from the logon call",
])
def test_real_answers_that_name_the_session_mechanism_are_credited(answer):
    """Regression on a marker list that was too narrow, caught by reading the near-misses.

    A first draft matched exact phrases ("session token", "sessionid", ...) and scored 0 for every
    string here — all of which name the mechanism correctly and differ only in wording. That made
    the dimension measure our phrasebook rather than the model. `session`/`logon` match the concept.

    The consequence is stated rather than hidden: "session bearer token" IS credited. The scored
    dimension asks whether the model names the session mechanism; whether it *also* reaches for
    bearer vocabulary is a separate, transcript-counted observation.
    """
    gt = "Session token from the logon call, sent in the Authorization header"
    assert scorer.auth_flow_matches(gt, answer)


def test_bare_login_is_not_a_session_marker():
    """`login` appears in OAuth-shaped ground truth, so making it a marker would reclassify a pack
    that legitimately requires bearer — the third-vendor safety property (ADR-0011 rule 3)."""
    basic_login = ("HTTP Basic-auth login. POST to the login path; the response carries "
                   "access_token and token_type=Bearer, sent on every subsequent call.")
    assert scorer.canonical_auth_flow(basic_login) == "bearer-token"


def test_an_unnameable_style_still_degrades_quietly_rather_than_raising():
    """The fallback survives so the scorer never raises — but `roundtrip` blocks the pack (ADR-0011)."""
    mtls = "Mutual TLS: the caller presents a client certificate"
    assert scorer.auth_flow_matches(mtls, "some scheme nobody named")   # the hole, kept explicit
    assert not scorer.auth_flow_matches(mtls, "OAuth2 bearer token")


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


# --------------------------------------------------------------------------- #
# Either-of auth scoring (ADR-0023)
# --------------------------------------------------------------------------- #

# The ground truth that produced ADR-0023. A payments flagship signs each request with an HMAC over
# a canonical string; the key it signs with travels in an `Api-Key` header, so the prose names both.
_HMAC_GT = (
    "HMAC message signature. Every call carries `Api-Key`, `Client-Request-Id`, `Timestamp` and "
    "`Auth-Token-Type: HMAC`; the `Authorization` header holds a base64 HMAC-SHA256 signature "
    "computed over apiKey + clientRequestId + timestamp + payload using the API secret."
)


def test_request_signing_outranks_the_key_it_signs_with():
    """The inversion ADR-0023 exists to fix, pinned in both directions.

    Before `hmac-signature` existed this key canonicalized to `api-key` — which is not `unknown`, so
    ADR-0011's roundtrip block never fired — and the dimension ran backwards: the answer that
    correctly described request signing scored 0 while "just send your API key" scored 1.
    """
    assert scorer.canonical_auth_flow(_HMAC_GT) == "hmac-signature"
    assert scorer.auth_flow_matches(
        _HMAC_GT, "HMAC-SHA256 request signature in the Authorization header")
    assert not scorer.auth_flow_matches(
        _HMAC_GT, "Send your API key in the Api-Key header. That's it.")


def test_bare_signed_is_not_an_hmac_marker():
    """Why the markers are narrow. Two published packs describe an OAuth client assertion as a
    "signed JWT"; a `signature`/`signed` marker would recanonicalize them and move their numbers."""
    jwt = ("OAuth 2.0 client credentials grant: POST a signed JWT client assertion to the token "
           "endpoint.")
    assert scorer.canonical_auth_flow(jwt) == "oauth2-client-credentials"


def test_access_token_ranks_last_so_it_cannot_recanonicalize_oauth_prose():
    """`access token` appears inside OAuth prose across the cohort. Ranked last, the style can only
    fire where nothing else did, which is what makes adding it score-neutral for every archive."""
    oauth = "OAuth2 client credentials; send the result as `Authorization: Bearer <access_token>`."
    assert scorer.canonical_auth_flow(oauth) == "oauth2-client-credentials"
    assert "access-token" in scorer._auth_concepts(oauth)          # recognized, but not required
    assert scorer.canonical_auth_flow("An opaque access token in the Authorization header") \
        == "access-token"


def test_a_single_style_key_scores_exactly_as_before():
    """The invariance the whole change rests on: with no alternates declared the accepted set is
    `{required}` and nothing else, so every archived pack re-scores byte-identically."""
    gt = "OAuth2 bearer token in the Authorization header"
    for answer in ("bearer token", "an API key", "HTTP Basic auth", "", None):
        assert scorer.auth_flow_matches(gt, answer) == \
            (scorer.canonical_auth_flow(gt) in scorer._auth_concepts(answer))


def test_an_alternate_widens_only_to_the_style_it_names():
    gt = "PS-Auth API key header plus an established session from the sign-in call."
    assert scorer.canonical_auth_flow(gt) == "session-token"
    assert not scorer.auth_flow_matches(gt, "the PS-Auth API key header")
    assert scorer.auth_flow_matches(gt, "the PS-Auth API key header", ["api-key"])
    # and it does not become a free pass for an unrelated style
    assert not scorer.auth_flow_matches(gt, "HTTP Basic auth", ["api-key"])


# --- the four rules that keep a set from making any answer right ------------ #

def _alt_task(**alt):
    entry = {"style": "api-key",
             "evidence": "https://docs.example-vendor.com/auth",
             "note": "The vendor's authentication page documents the key header as a valid "
                     "credential for this operation on its own."}
    entry.update(alt)
    return {"auth_flow": "PS-Auth API key header plus an established session from sign-in.",
            "auth_flow_alternates": [entry]}


def test_a_well_formed_alternate_has_no_problems():
    assert scorer.alternate_problems(_alt_task()) == []
    assert scorer.declared_alternates(_alt_task()) == ["api-key"]


def test_an_unknown_style_blocks_rather_than_widening_nothing():
    """Rule 1. A typo would otherwise read as honoured and score as if the key had never declared
    anything — the declaration would look load-bearing while doing nothing."""
    problems = scorer.alternate_problems(_alt_task(style="api-keys"))
    assert any("not a login style the scorer knows" in p for p in problems)


def test_declaring_the_style_the_prose_already_requires_blocks():
    """Rule 2. A redundant declaration must never be mistakable for evidence that two styles were
    weighed."""
    problems = scorer.alternate_problems(_alt_task(style="session-token"))
    assert any("already the style auth_flow requires" in p for p in problems)


def test_an_alternate_on_a_rehosting_host_blocks():
    """Rule 3. The claim is that the VENDOR documents this style. A copy of a document is not the
    vendor's claim (ADR-0017), and an archive capture cannot be re-verified."""
    problems = scorer.alternate_problems(
        _alt_task(evidence="https://web.archive.org/web/2022/https://docs.example-vendor.com/auth"))
    assert any("rehosts rather than publishes" in p for p in problems)
    assert scorer.alternate_problems(_alt_task(evidence="not-a-url"))


def test_an_alternate_the_prose_never_names_blocks():
    """Rule 4, the one that keeps the widening honest. If `auth_flow` does not itself say both
    styles are accepted, the acceptance lives in a field nobody reads beside prose that contradicts
    it — and the answer key stops being the record of what is correct."""
    gt = _alt_task(style="bearer-token")
    gt["auth_flow_alternates"][0]["style"] = "bearer-token"
    problems = scorer.alternate_problems(gt)
    assert any("never names 'bearer-token'" in p for p in problems)


def test_a_short_note_blocks():
    problems = scorer.alternate_problems(_alt_task(note="documented"))
    assert any("at least 40 characters" in p for p in problems)


def test_accepting_every_style_blocks():
    """Rule 5. The backstop: a dimension that accepts everything is applicable and unfalsifiable."""
    gt = {"auth_flow": "hmac message signature, session, client credentials, bearer, basic auth, "
                       "api key, access token — this key names them all",
          "auth_flow_alternates": [
              {"style": s, "evidence": "https://docs.example-vendor.com/auth",
               "note": "Every style is documented for this operation, which is the point of the test."}
              for s in scorer.KNOWN_AUTH_STYLES if s != "hmac-signature"]}
    assert any("unfalsifiable" in p for p in scorer.alternate_problems(gt))


def test_no_alternates_declared_is_never_a_problem():
    assert scorer.alternate_problems({"auth_flow": "OAuth2 bearer token"}) == []
    assert scorer.alternate_problems(None) == []
    assert scorer.alternate_problems({"auth_flow": "x", "auth_flow_alternates": []})


def test_every_known_style_has_a_mock_phrase_that_scores_itself():
    """A style added to the scorer without a mock phrase would make `run --mock` report a failure
    that says nothing about the plumbing it exists to prove."""
    from core.roundtrip import _MOCK_AUTH_PHRASE
    assert set(_MOCK_AUTH_PHRASE) == set(scorer.KNOWN_AUTH_STYLES)
    for style, phrase in _MOCK_AUTH_PHRASE.items():
        assert scorer.canonical_auth_flow(phrase) == style, (style, phrase)


# --------------------------------------------------------------------------- #
# key_parameters: a named sub-field names its parent (ADR-0024)
# --------------------------------------------------------------------------- #

def test_naming_a_sub_field_names_its_parent():
    """The fault ADR-0024 fixes, taken from a real answer on a payments flagship.

    Ground truth names the request-body containers the vendor's examples show — `amount`, `source`,
    `merchantDetails`. The model named `amount.total`, `source.sourceType`,
    `merchantDetails.merchantId`: the same containers plus which field inside each to fill. Exact
    match scored that 0 on every run while crediting nothing more accurate.
    """
    task = _task(
        [{"method": "POST", "path": "/payments/v1/charges", "api_version": "v1"}],
        params=[{"name": "amount", "in": "body", "required": True},
                {"name": "source", "in": "body", "required": True},
                {"name": "merchantDetails", "in": "body", "required": True}],
    )
    ans = _ans([("POST", "/payments/v1/charges", "v1")],
               params=["amount.total", "amount.currency", "source.sourceType",
                       "source.card.cardData", "merchantDetails.merchantId",
                       "merchantDetails.terminalId"])
    assert scorer.score_task(task, ans).dim("key_parameters").score == 1.0


def test_a_container_does_not_satisfy_a_requirement_for_a_field_inside_it():
    """MUST NOT. The asymmetry is the design: this is the direction that manufactures a score.

    Naming `amount` proves nothing about which field inside it the caller supplied, so a vague
    answer must not pass a specific requirement. Deleting the asymmetry would make this pass.
    """
    task = _task(
        [{"method": "POST", "path": "/payments/v1/charges", "api_version": "v1"}],
        params=[{"name": "amount.total", "in": "body", "required": True}],
    )
    ans = _ans([("POST", "/payments/v1/charges", "v1")], params=["amount"])
    assert scorer.score_task(task, ans).dim("key_parameters").score == 0.0


def test_the_separator_must_be_a_real_dotted_path():
    """A prefix is not a parent. `source_type` and `sourceDetails` share letters with `source` and
    are different parameters; only a literal `.` boundary counts."""
    assert scorer.names_parameter("source", {"source.sourcetype"})
    assert scorer.names_parameter("source", {"source"})
    assert not scorer.names_parameter("source", {"source_type"})
    assert not scorer.names_parameter("source", {"sourcedetails"})
    assert not scorer.names_parameter("source", {"paymentsource.card"})


def test_a_sibling_field_does_not_satisfy_a_specific_requirement():
    """Roots matching is not enough when ground truth asks for a specific leaf."""
    assert not scorer.names_parameter("merchantdetails.merchantid", {"merchantdetails.terminalid"})
    assert scorer.names_parameter("merchantdetails.merchantid", {"merchantdetails.merchantid"})


def test_flat_parameter_answers_are_unaffected():
    """Invariance: every pack whose answers name parameters flatly scores exactly as before."""
    task = _task(
        [{"method": "GET", "path": "/v3/accounts", "api_version": "v3"}],
        params=[{"name": "limit", "in": "query", "required": True}],
    )
    assert scorer.score_task(task, _ans([("GET", "/v3/accounts", "v3")],
                                        params=["limit"])).dim("key_parameters").score == 1.0
    assert scorer.score_task(task, _ans([("GET", "/v3/accounts", "v3")],
                                        params=["offset"])).dim("key_parameters").score == 0.0
