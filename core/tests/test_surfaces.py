"""The surface classifier's rules, one test per rule (ADR-0037).

A vendor may publish several live surfaces at once. When a model answers a task about the current
one with a real endpoint from a superseded one, the six dimensions record a miss and cannot say why:
stale-but-real and fabricated score identically. This module pins the rules that tell them apart.

The fixture vendor is fictional, like `pack-acme`: a `/v3` current surface, a `/v1` deprecated one,
and a legacy `/graph` single-endpoint surface. Nothing here names a real company, which is what keeps
the `test_core_no_vendor` guard clean.
"""
import pytest

from core.surfaces import (AMBIGUOUS, CONFLICTED, NO_MATCH, UNRECOGNIZED, Surface, SurfaceSet,
                           classify_endpoint, classify_run, count_operation_mentions,
                           load_surface_set, unclassified_ground_truth)

# Both declare a host marker ON PURPOSE, so the "host never decides" test below has something it
# could decide with. Without them that test would pass against a classifier that consults the host.
CURRENT = Surface(
    id="rest-v3", label="REST API v3", measured=True, rationale="the current surface",
    version_markers=("v3",), host_markers=("v3.example.test",),
    paths=("/v3/widgets", "/v3/widgets/{id}", "/v3/widgets/{id}/action",
           "/v3/gadgets/{id}", "/v3/sprockets"))
OLD = Surface(
    id="rest-v1", label="REST API v1 (deprecated)", rationale="superseded but still served",
    version_markers=("v1",), host_markers=("v1.example.test",),
    paths=("/v1/widgets", "/v1/widgets/{id}", "/v1/widgets/{id}/stop", "/v1/gadgets/{id}"))
LEGACY = Surface(
    id="graph", label="Legacy graph API", rationale="still documented",
    paths=("/graph",), operations=("widgetCreate", "widgetStop"))

SURFACES = SurfaceSet((CURRENT, OLD, LEGACY))


# --------------------------------------------------------------------------- #
# Which surface does one endpoint belong to?
# --------------------------------------------------------------------------- #

def test_a_path_only_one_surface_publishes_needs_no_version():
    """The easy half, and the half that carries the finding: where the surfaces genuinely differ in
    path shape, the answer places itself with no version stated at all."""
    assert classify_endpoint("/v3/sprockets", None, SURFACES).bucket == "rest-v3"
    assert classify_endpoint("/v1/widgets/{id}/stop", None, SURFACES).bucket == "rest-v1"
    assert classify_endpoint("/v3/widgets/{id}/action", None, SURFACES).bucket == "rest-v3"


def test_a_shared_path_is_resolved_by_the_version_in_the_path():
    """`normalize_path` strips the version segment on purpose, so `/v1/widgets` and `/v3/widgets`
    are the SAME path to the scorer. That is exactly why the endpoint dimension cannot see this
    difference, and why the version has to be read back out of the raw path."""
    assert classify_endpoint("/v1/widgets", None, SURFACES).bucket == "rest-v1"
    assert classify_endpoint("/v3/widgets", None, SURFACES).bucket == "rest-v3"


def test_a_shared_path_is_resolved_by_the_stated_api_version():
    """The second, independent signal. A model that writes a bare path but fills in `api_version`
    has still said which surface it means."""
    assert classify_endpoint("/widgets", "v1", SURFACES).bucket == "rest-v1"
    assert classify_endpoint("/widgets", "v3", SURFACES).bucket == "rest-v3"


def test_a_shared_path_with_no_version_anywhere_is_ambiguous_not_guessed():
    """The refusal. Two surfaces publish `/widgets` and the answer says nothing that separates them,
    so there is no honest bucket to put it in. Assigning it to either one would be inventing
    evidence, and assigning it to the measured surface would manufacture the null result."""
    verdict = classify_endpoint("/widgets", None, SURFACES)
    assert verdict.bucket == AMBIGUOUS
    assert "rest-v1" in verdict.basis and "rest-v3" in verdict.basis


def test_one_surfaces_resource_with_another_surfaces_version_does_not_credit_either():
    """FOUND IN A REAL EXHIBIT, NOT IN A FIXTURE, and it inflated the measured surface.

    A vendor renamed a resource between surfaces, so only ONE inventory contains the new spelling. An
    answer that writes the new resource with the OLD version — `/v3/sprockets` where the deprecated
    surface has no sprockets at all — matches exactly one candidate, and an unconditional
    single-candidate return credits the measured surface for an address that exists on neither.

    That is the one direction of error that flatters the result, so it gets its own test. In the run
    that found it, 13 of 14 endpoints in the measured bucket were really `/v1/...` paths.
    """
    verdict = classify_endpoint("/v1/sprockets", "v1", SURFACES)
    assert verdict.bucket == CONFLICTED
    assert "rest-v3" in verdict.basis and "rest-v1" in verdict.basis


def test_a_single_candidate_that_declares_no_version_makes_no_version_claim_to_contradict():
    """The converse, and it is why the rule above is conditioned on the candidate having markers.

    The legacy surface declares no version markers — it is not making a version claim — so
    `/graph` answered with any stated version is still that surface, not a conflict. Without this
    condition every answer naming a version-less surface would become `conflicted`.
    """
    assert classify_endpoint("/graph", "v3", SURFACES).bucket == "graph"
    assert classify_endpoint("/graph", "v1", SURFACES).bucket == "graph"


def test_a_single_candidate_with_a_consistent_or_unknown_version_is_unchanged():
    assert classify_endpoint("/v3/sprockets", "v3", SURFACES).bucket == "rest-v3"
    assert classify_endpoint("/v3/sprockets", None, SURFACES).bucket == "rest-v3"
    # a version belonging to no declared surface is uninformative, not a conflict
    assert classify_endpoint("/v9/sprockets", "v9", SURFACES).bucket == "rest-v3"


def test_a_path_version_disagreeing_with_the_stated_version_is_its_own_bucket():
    """`/v1/widgets` with `api_version: v3` is not a coin flip to resolve — it is evidence about the
    exact confusion being measured, so it gets counted rather than tidied away."""
    verdict = classify_endpoint("/v1/widgets", "v3", SURFACES)
    assert verdict.bucket == CONFLICTED
    assert "rest-v1" in verdict.basis and "rest-v3" in verdict.basis


def test_an_unknown_path_is_unrecognized_never_invented():
    """`unrecognized` is a statement about our inventories; "invented" would be a statement about
    the world, and an inventory pinned on a date cannot support one."""
    verdict = classify_endpoint("/v3/flanges", "v3", SURFACES)
    assert verdict.bucket == UNRECOGNIZED
    assert "inventory" in verdict.basis


def test_the_legacy_surface_is_matched_as_a_path_with_no_protocol_special_case():
    """The legacy surface is reached like any other — its inventory contains the one path a caller
    writes. Core has no branch for any particular kind of API."""
    assert classify_endpoint("/graph", None, SURFACES).bucket == "graph"
    assert classify_endpoint("https://api.example.test/graph", None, SURFACES).bucket == "graph"


# --------------------------------------------------------------------------- #
# Normalization is borrowed, not re-implemented
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", ["/v3/widgets/{id}", "/v3/widgets/{widgetId}", "/V3/Widgets/{x}"])
def test_placeholder_names_and_case_do_not_change_the_bucket(path):
    """Rides entirely on `scorer.normalize_path`. If that rule ever moves, this fails loudly rather
    than silently re-bucketing answers."""
    assert classify_endpoint(path, None, SURFACES).bucket == "rest-v3"


@pytest.mark.parametrize("stated", ["v1", "V1", " v1 ", "<v1>"])
def test_version_spellings_are_folded_by_the_scorers_rule(stated):
    assert classify_endpoint("/widgets", stated, SURFACES).bucket == "rest-v1"


def test_a_query_string_does_not_change_the_bucket():
    assert classify_endpoint("/v3/widgets?limit=10", None, SURFACES).bucket == "rest-v3"


def test_a_stated_host_is_recorded_as_evidence_and_never_decides():
    """The prompt contract forbids a host in `path`, so a host can only appear on a contract-breaking
    answer. It is counted so the rate is published, but it must not resolve anything: here the host
    names one surface and the path names the other, and the PATH wins."""
    assert CURRENT.host_markers and OLD.host_markers, "otherwise this proves nothing"
    # The host names the deprecated surface and the path names the current one. The PATH must win.
    verdict = classify_endpoint("https://v1.example.test/v3/widgets", None, SURFACES)
    assert verdict.host_stated is True
    assert verdict.bucket == "rest-v3"
    # And a host cannot rescue an answer that says nothing else: still ambiguous, not resolved.
    assert classify_endpoint("https://v1.example.test/widgets", None, SURFACES).bucket == AMBIGUOUS
    assert classify_endpoint("/v3/widgets", None, SURFACES).host_stated is False


# --------------------------------------------------------------------------- #
# Declaration order is display order
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path,version,expected", [
    ("/v3/widgets", None, "rest-v3"), ("/v1/widgets", None, "rest-v1"),
    ("/widgets", None, AMBIGUOUS), ("/graph", None, "graph"),
    ("/v3/flanges", None, UNRECOGNIZED), ("/v1/widgets", "v3", CONFLICTED),
])
def test_declaration_order_changes_no_classification(path, version, expected):
    """The test that permanently kills order-as-tiebreak. If order broke ties, listing the measured
    surface first would classify every under-specified answer as correct — manufacturing the null —
    and listing a superseded one first would manufacture the finding."""
    forward = SurfaceSet((CURRENT, OLD, LEGACY))
    reversed_ = SurfaceSet((LEGACY, OLD, CURRENT))
    assert classify_endpoint(path, version, forward).bucket == expected
    assert classify_endpoint(path, version, reversed_).bucket == expected


# --------------------------------------------------------------------------- #
# Operation names are corroboration, never classification
# --------------------------------------------------------------------------- #

def test_operation_names_are_counted_from_prose_but_do_not_classify():
    """A model may reason in one surface's idiom and emit another surface's path. What it EMITTED is
    what an integrator would call, so the path classifies the answer; the prose is reported beside
    it. Matching short operation names against the path field instead would be a category error with
    a false-positive rate — the pathology `_AUTH_STYLES` documents at length."""
    text = "Use the widgetCreate mutation, or the REST route below."
    assert count_operation_mentions(text, SURFACES) == {"graph": 1}
    assert classify_endpoint("/v3/widgets", "v3", SURFACES).bucket == "rest-v3"


def test_an_operation_name_that_is_a_path_segment_does_not_pull_a_rest_answer_into_the_legacy_bucket():
    """The counterexample, pinned. A legacy surface declaring an operation literally named `widgets`
    must not make every correct REST answer read as legacy — which is what matching operation names
    against paths would do, silently, with no dimension moving and no test failing."""
    trap = SurfaceSet((CURRENT, OLD, Surface(
        id="graph", label="Legacy", rationale="r", paths=("/graph",),
        operations=("widgets", "gadgets"))))
    assert classify_endpoint("/v3/widgets", "v3", trap).bucket == "rest-v3"


# --------------------------------------------------------------------------- #
# Rolling up to a run
# --------------------------------------------------------------------------- #

def _task(path="/v3/widgets", method="POST"):
    return {"id": "t", "ground_truth": {"endpoints": [
        {"method": method, "path": path, "api_version": "v3"}]}}


class _Parsed:
    def __init__(self, endpoints):
        self.summary = type("S", (), {"endpoints": endpoints})()


class _Ep:
    def __init__(self, method, path, api_version=None):
        self.method, self.path, self.api_version = method, path, api_version


def test_a_run_is_labelled_by_the_endpoint_that_matched_ground_truth():
    """The pre-registered rollup rule. 58% of archived answers carry more than one endpoint, so a
    rule is required; this one puts the label where the surface question actually lives."""
    parsed = _Parsed([_Ep("POST", "/v1/auth/token"), _Ep("POST", "/v1/widgets")])
    label, verdicts = classify_run(_task(), parsed, SURFACES)
    assert label == "rest-v1"
    assert [v.bucket for v in verdicts] == [UNRECOGNIZED, "rest-v1"]


def test_a_run_matching_nothing_is_no_match_rather_than_folded_into_a_surface():
    """It already scores 0 on `endpoint`; calling it a surface answer would count a miss twice."""
    parsed = _Parsed([_Ep("GET", "/v3/flanges")])
    label, _ = classify_run(_task(), parsed, SURFACES)
    assert label == NO_MATCH


def test_a_run_with_no_endpoints_at_all_is_no_match():
    assert classify_run(_task(), _Parsed([]), SURFACES)[0] == NO_MATCH


# --------------------------------------------------------------------------- #
# The known-good control (wired into the roundtrip gate)
# --------------------------------------------------------------------------- #

def test_ground_truth_classifies_as_the_measured_surface():
    tasks = [_task("/v3/widgets"), _task("/v3/gadgets/{id}"), _task("/v3/sprockets")]
    assert unclassified_ground_truth(tasks, SURFACES) == []


def test_a_mis_transcribed_inventory_is_caught_by_the_control():
    """The failure this control exists for: an inventory that omits a path the pack measures. The
    round-trip control proper (ADR-0010) structurally cannot see it — an answer key still matches
    itself — so without this, a wrong split would be discovered only in a finished card."""
    thin = SurfaceSet((Surface(id="rest-v3", label="v3", measured=True, rationale="r",
                               version_markers=("v3",), paths=("/v3/widgets",)), OLD))
    problems = unclassified_ground_truth([_task("/v3/sprockets")], thin)
    assert len(problems) == 1
    assert "unrecognized" in problems[0] and "rest-v3" in problems[0]


def test_an_over_broad_inventory_is_caught_too():
    """The other direction: a superseded surface claiming a path the measured one omits, so the
    pack's own ground truth classifies as superseded.

    Note where the division of labour falls. When BOTH surfaces list the path, declared version
    markers resolve it and nothing is wrong; an overlap that markers CANNOT resolve is a schema
    problem caught earlier, by `validate_answer_surfaces`. What only this control can see is an
    inventory that sends the measured surface's own ground truth somewhere else."""
    greedy = SurfaceSet((
        Surface(id="rest-v3", label="v3", measured=True, rationale="r", version_markers=("v3",),
                paths=("/v3/widgets",)),
        Surface(id="rest-v1", label="v1", rationale="r", version_markers=("v1",),
                paths=("/v3/sprockets",))))
    problems = unclassified_ground_truth([_task("/v3/sprockets")], greedy)
    assert len(problems) == 1 and "rest-v1" in problems[0]


def test_the_control_is_silent_when_no_surfaces_are_declared():
    assert unclassified_ground_truth([_task()], SurfaceSet(())) == []


# --------------------------------------------------------------------------- #
# Loading a declaration
# --------------------------------------------------------------------------- #

def test_paths_may_be_declared_inline():
    declared = load_surface_set({"surfaces": [
        {"id": "a", "label": "A", "measured": True, "paths": ["/v3/x"]},
        {"id": "b", "label": "B", "paths": ["/v1/x"]}]})
    assert [s.id for s in declared.surfaces] == ["a", "b"]
    assert declared.measured.id == "a"


def test_a_long_inventory_lives_in_a_pinned_sibling_file(tmp_path):
    """The provenance fields are the point of the sibling: an inline list cannot carry the source
    URL, the fetch date and the digest that let a later cycle prove the copy is still faithful."""
    (tmp_path / "surfaces").mkdir()
    (tmp_path / "surfaces" / "v3.yaml").write_text(
        "source_url: https://example.test/openapi.json\n"
        "fetched_at: '2026-07-30'\ndigest: 'sha256:abc'\n"
        "coverage: the 3 paths that document publishes, as of the fetch date\n"
        # Block style, not flow: a `{placeholder}` segment starts a YAML mapping inside `[...]`.
        # Every real inventory is written this way for the same reason.
        "paths:\n  - /v3/widgets\n  - /v3/gadgets/{id}\n  - /v3/sprockets\n")
    declared = load_surface_set({"surfaces": [
        {"id": "v3", "label": "V3", "measured": True, "inventory": "surfaces/v3.yaml"},
        {"id": "v1", "label": "V1", "paths": ["/v1/widgets"]}]}, tmp_path)
    v3 = declared.by_id("v3")
    assert len(v3.paths) == 3 and v3.digest == "sha256:abc" and v3.fetched_at == "2026-07-30"
    assert "as of the fetch date" in declared.coverage_note()
    assert classify_endpoint("/v3/sprockets", None, declared).bucket == "v3"


def test_no_declaration_is_an_empty_set_that_classifies_nothing():
    assert not load_surface_set(None)
    assert not load_surface_set({})
