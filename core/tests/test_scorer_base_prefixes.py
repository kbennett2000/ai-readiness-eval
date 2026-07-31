"""ADR-0039 — a pack may declare MORE THAN ONE endpoint-base prefix.

ADR-0017 gave a pack one prefix, because the vendor that forced it disagreed with itself in one
place. A later vendor disagrees with itself in two places at once, in its own machine-readable
documents rather than merely between a spec and a guide:

  * two of its OpenAPI documents describe the same domain on the same host, one writing a leading
    platform segment into every path key and the other omitting it;
  * a third document absorbs a different segment into `servers[].url`, so the address its own
    reference page DISPLAYS carries a prefix its `paths` key does not.

One declared prefix cannot reconcile both, and choosing either one leaves half the pack mis-scored
in the direction ADR-0013 exists to prevent — a dimension reported low while the model wrote the
address the vendor's own page shows.

The fixtures below are neutral: the vendor is a measured prospect and cannot be named here.
"""
from core import scorer
from core.answer_block import Endpoint

# Two independent bases, exactly as the forcing vendor declares them.
HUB = ["hubprefix"]
SVC = ["svc"]
BOTH = [HUB, SVC]


def _ep(path, method="GET", version="v1"):
    return Endpoint(method=method, path=path, api_version=version)


def _gt(path, method="GET", version="v1"):
    return {"method": method, "path": path, "api_version": version}


# --------------------------------------------------------------------------------------------- #
# Back-compatibility. These are the properties that keep six packs' archived scores identical.
# --------------------------------------------------------------------------------------------- #

def test_a_single_flat_prefix_still_means_one_prefix():
    """The pre-ADR-0039 call shape must behave exactly as it did, or archived scores move."""
    assert scorer.as_prefix_list(HUB) == [["hubprefix"]]
    assert scorer._strip_base_prefix(["hubprefix", "users"], HUB) == ["users"]


def test_no_declaration_is_still_inert():
    for empty in (None, [], ()):
        assert scorer.as_prefix_list(empty) == []
        assert scorer._strip_base_prefix(["hubprefix", "users"], empty) == ["hubprefix", "users"]
    recs = scorer._match_endpoints([_gt("/users")], [_ep("/hubprefix/users")])
    assert recs[0]["matched"] is False


# --------------------------------------------------------------------------------------------- #
# The widening itself.
# --------------------------------------------------------------------------------------------- #

def test_either_declared_prefix_is_absorbed():
    assert scorer._strip_base_prefix(["hubprefix", "users"], BOTH) == ["users"]
    assert scorer._strip_base_prefix(["svc", "v2", "users"], BOTH) == ["v2", "users"]


def test_both_sides_of_one_comparison_may_carry_DIFFERENT_declared_prefixes():
    """The case that forced this: ground truth from one document, answer from another."""
    recs = scorer._match_endpoints([_gt("/hubprefix/corehr/companies/{id}")],
                                   [_ep("/corehr/companies/{id}")], BOTH)
    assert recs[0]["matched"] is True
    recs = scorer._match_endpoints([_gt("/v2/companies/{id}/employees")],
                                   [_ep("/svc/v2/companies/{id}/employees")], BOTH)
    assert recs[0]["matched"] is True


def test_declaration_order_is_the_packs_own_tie_break():
    """First match wins, so a pack that declares an ambiguous pair chose which one applies."""
    segments = ["svc", "hubprefix", "users"]
    assert scorer._strip_base_prefix(segments, [SVC, HUB]) == ["hubprefix", "users"]
    assert scorer._strip_base_prefix(segments, [HUB, SVC]) == ["hubprefix", "users"]


# --------------------------------------------------------------------------------------------- #
# THE MUST-NOT-INFLATE PROPERTIES. Each was verified by breaking it on purpose.
# --------------------------------------------------------------------------------------------- #

def test_stripping_happens_at_most_once():
    """Two short declared prefixes must not eat a real resource segment between them.

    `/svc/hubprefix/users` is ONE base plus a resource called `hubprefix`. Repeated stripping would
    reduce it to `/users` and let it match an unrelated endpoint — the tolerance would then be as
    wide as the number of prefixes declared rather than as wide as one base URL.
    """
    assert scorer._strip_base_prefix(["svc", "hubprefix", "users"], BOTH) == ["hubprefix", "users"]
    recs = scorer._match_endpoints([_gt("/users")], [_ep("/svc/hubprefix/users")], BOTH)
    assert recs[0]["matched"] is False


def test_an_undeclared_leading_segment_is_still_a_miss():
    """The ADR-0014 counterexample, re-pinned for the multi-prefix path.

    A tolerance that allowed "the answer ends with the ground truth" would let `/admin/users` match
    `/users` and manufacture a score upward. Only declared prefixes are absorbed, however many.
    """
    recs = scorer._match_endpoints([_gt("/users/{id}")], [_ep("/admin/users/{id}")], BOTH)
    assert recs[0]["matched"] is False


def test_a_declared_prefix_is_only_stripped_at_the_front():
    assert scorer._strip_base_prefix(["api", "hubprefix", "users"], BOTH) == \
        ["api", "hubprefix", "users"]


def test_two_surfaces_sharing_a_declared_prefix_do_not_collide():
    """Absorbing a base must not make two genuinely different resources the same resource."""
    a = scorer._strip_base_prefix(scorer.normalize_path("/hubprefix/corehr/v1/companies/{c}/employees"), BOTH)
    b = scorer._strip_base_prefix(scorer.normalize_path("/svc/v2/companies/{c}/employees"), BOTH)
    assert a != b


def test_empty_inner_prefixes_are_dropped_rather_than_matching_everything():
    """A `[]` entry would match the front of ANY path and absorb nothing while claiming to."""
    assert scorer.as_prefix_list([[], HUB]) == [["hubprefix"]]
    assert scorer._strip_base_prefix(["users"], [[], HUB]) == ["users"]
