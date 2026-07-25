"""ADR-0017 — the opt-in endpoint-base tolerance.

The vendor that forced this rule is a measured prospect and cannot be named in this repo, so the
fixtures use a neutral base. The shape is exact: the vendor's documentation states the base URL as
`https://<host>/VendorBase/api/public/v3`, while the vendor's own OpenAPI fragments put `/vendorbase`
in `servers[].url` and start their `paths` key at `/api/public/v3`. Both address the same operation.

A cold model recalls the prose and writes DOC_STYLE; a model reading the fragments writes SPEC_STYLE.
No single literal ground truth accepts both, which is why the tolerance lives in the scorer.
"""
from core import scorer
from core.answer_block import Endpoint

DOC_STYLE = "/VendorBase/api/public/v3/Auth/SignIn"     # the address the documentation teaches
SPEC_STYLE = "/api/public/v3/Auth/SignIn"               # where the spec fragment starts its path
PREFIX = ["vendorbase"]


def _ep(path, method="GET", version="v3"):
    return Endpoint(method=method, path=path, api_version=version)


def _gt(path, method="GET", version="v3"):
    return {"method": method, "path": path, "api_version": version}


def test_base_prefix_is_inert_when_a_pack_does_not_opt_in():
    """The default must reproduce pre-ADR-0017 behaviour exactly, or every archived score moves."""
    recs = scorer._match_endpoints([_gt(SPEC_STYLE)], [_ep(DOC_STYLE)])
    assert recs[0]["matched"] is False


def test_base_prefix_absorbs_the_declared_prefix_on_the_answer():
    recs = scorer._match_endpoints([_gt(SPEC_STYLE)], [_ep(DOC_STYLE)], PREFIX)
    assert recs[0]["matched"] is True
    assert recs[0]["method_ok"] and recs[0]["version_ok"]


def test_base_prefix_is_symmetric():
    """Ground truth may be the side carrying the prefix; the rule must not care which."""
    recs = scorer._match_endpoints([_gt(DOC_STYLE)], [_ep(SPEC_STYLE)], PREFIX)
    assert recs[0]["matched"] is True


def test_base_prefix_only_strips_a_leading_occurrence():
    """It is a base prefix, not a substring: the same word deeper in a path is real content."""
    assert scorer._strip_base_prefix(["api", "vendorbase", "users"], PREFIX) == \
        ["api", "vendorbase", "users"]


def test_base_prefix_cannot_match_two_different_resources():
    """THE MUST-NOT-INFLATE COUNTEREXAMPLE.

    A tolerance that merely allowed "the answer ends with the ground truth" would let `/admin/users`
    match `/users` and manufacture a score upward — the failure ADR-0014 pinned a test against. Only
    the prefix a pack DECLARED is absorbed, so an undeclared leading segment is still a miss.
    """
    recs = scorer._match_endpoints([_gt("/users/{id}")], [_ep("/admin/users/{id}")], PREFIX)
    assert recs[0]["matched"] is False


def test_a_declared_prefix_does_not_rescue_a_genuinely_wrong_path():
    """Absorbing the base must not turn a wrong resource into a right one."""
    recs = scorer._match_endpoints([_gt("/api/public/v3/Requests")],
                                   [_ep("/VendorBase/api/public/v3/Sessions")], PREFIX)
    assert recs[0]["matched"] is False


def test_declaring_no_prefix_and_an_empty_prefix_agree():
    for prefix in (None, []):
        recs = scorer._match_endpoints([_gt(SPEC_STYLE)], [_ep(DOC_STYLE)], prefix)
        assert recs[0]["matched"] is False
