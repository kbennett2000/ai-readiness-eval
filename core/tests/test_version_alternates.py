"""ADR-0059 — a version tolerance must cite the vendor, and it is declared per task.

`api_version` was the one scored API dimension with no way to accept a second value, and it is the
one a vendor routinely publishes two right answers for: a current GA release beside a current pre-GA
release, both on the reference root, neither deprecated. `auth_flow_alternates` (ADR-0023) and
`endpoint_base_prefix` (ADR-0055) both solved the same problem the same way — a tolerance that can
only move a dimension UP must cite the first-party artifact that justifies it — and this file holds
the third instance of that rule.

Every rule is broken on purpose, in BOTH directions: a malformed declaration must block, and a
well-formed one must not. Three tests carry the properties that make the whole thing honest, and
`tools/assert_guard_ran.py` requires those three BY NAME, because a green run is not evidence a test
executed:

    test_a_cited_alternate_fires
    test_an_uncited_alternate_is_refused
    test_a_task_declaring_nothing_scores_exactly_as_before

Each of the three is then broken deliberately, in the section that follows it, so that none of them
can pass for a reason other than the one it claims.

WHAT THESE TESTS DO NOT PROVE
    That the cited page says what the note says. The gate checks that a first-party URL is present
    and is not a rehosting host; whether the vendor really publishes that version as current is a
    human reading (ADR-0055 recorded the same hole for both sibling fields, filed as #97). Nor can
    the round-trip control help: an answer key matches itself whatever set of versions it accepts
    (ADR-0010).
"""
import copy

import pytest

from core import roundtrip_api, scorer
from core.answer_block import AnswerSummary, Endpoint

VALID_NOTE = ("The vendor's reference root lists this version beside the GA one under "
              "\"Recommended Versions\", with neither marked deprecated.")
VALID = {"version": "v4", "evidence": "https://developer.example.test/reference/",
         "note": VALID_NOTE}


def task(*alternates, api_version="v3", path="/v3/widgets"):
    """One task whose key names `api_version`, declaring `alternates` if any are given."""
    gt = {
        "endpoints": [{"method": "GET", "path": path, "api_version": api_version,
                       "operation_id": "listWidgets",
                       "spec_ref": {"file": "widgets/v3/paths/widgets.yaml",
                                    "operation_id": "listWidgets"}}],
        "auth_flow": "OAuth2 bearer token",
        "required_scopes": [],
        "key_parameters": [{"name": "limit", "in": "query", "required": True}],
        "success_shape": "200 OK",
        "common_failure_modes": ["Using the wrong version."],
    }
    if alternates:
        gt["api_version_alternates"] = list(alternates)
    return {"id": "widget-list", "category": "foundational", "job_category": "find-principal",
            "prompt": "How do I list widgets?", "ground_truth": gt}


def answer(api_version, path="/v3/widgets", method="GET"):
    return AnswerSummary(
        endpoints=[Endpoint(method=method, path=path, api_version=api_version)],
        auth_flow="OAuth2 bearer token", required_scopes=[], key_parameters=["limit"],
    )


def problems(*alternates, **kw):
    return scorer.version_alternate_problems(task(*alternates, **kw)["ground_truth"])


def version_score(t, ans):
    return scorer.score_task(t, ans).dim("api_version").score


# =============================================================================================== #
# 1. The tolerance FIRES when it is cited.
# =============================================================================================== #

def test_a_cited_alternate_fires():
    """A version the key does not name, declared with its citation, scores 1.0.

    Required by name in `tools/assert_guard_ran.SUITE_REQUIRED`.
    """
    assert version_score(task(VALID), answer("v4")) == 1.0


def test_the_key_own_version_still_scores_one_when_an_alternate_is_declared():
    """The widening is additive. A declaration must never cost the answer the key names."""
    assert version_score(task(VALID), answer("v3")) == 1.0


def test_a_version_that_is_neither_the_key_nor_an_alternate_still_scores_zero():
    """The dimension must stay falsifiable — this is what separates a tolerance from a free pass."""
    assert version_score(task(VALID), answer("v2")) == 0.0


def test_a_credited_alternate_is_recorded_on_the_endpoint_match():
    """ADR-0058: a widened cell says which half of it a reader can re-check.

    Written only when the credit came from the alternate, so an archived record cannot gain a key.
    """
    score = scorer.score_task(task(VALID), answer("v4"))
    assert score.endpoint_matches[0]["version_via_alternate"] == "v4"


def test_the_dimension_detail_names_the_accepted_set():
    """A widened cell that reads identically to an un-widened one gives a reviewer nothing to
    disagree with — the reason the auth detail already names its own accepted set."""
    detail = scorer.score_task(task(VALID), answer("v4")).dim("api_version").detail
    assert "also accepting v4" in detail and "ADR-0059" in detail


# --------------------------------------------------------------------------------------------- #
# …and the deliberate break: the fire above must be caused by the DECLARATION and nothing else.
# --------------------------------------------------------------------------------------------- #

def test_the_fire_test_would_fail_without_the_declaration():
    """Remove the declaration, change nothing else: the same answer must score 0.0.

    Without this, `test_a_cited_alternate_fires` could be passing because `v4` matched some other
    way — the exact vacuity `test_prospect_regex_actually_matches_every_token` was written to record
    for a different guard.
    """
    assert version_score(task(), answer("v4")) == 0.0
    assert "version_via_alternate" not in scorer.score_task(task(), answer("v4")).endpoint_matches[0]


def test_the_credit_cannot_reach_an_endpoint_whose_path_did_not_match():
    """The must-not-inflate property. `api_version` is credited only where the PATH matched, and the
    path is where a service segment lives, so a version tolerance can never credit a wrong resource.
    """
    score = scorer.score_task(task(VALID), answer("v4", path="/v4/gadgets"))
    assert score.dim("endpoint").score == 0.0
    assert score.dim("api_version").score == 0.0
    assert not score.endpoint_matches[0]["matched"]


def test_an_alternate_cannot_widen_the_method_or_the_endpoint_dimension():
    """The tolerance is scoped to one dimension, and that is asserted rather than assumed."""
    score = scorer.score_task(task(VALID), answer("v4", method="POST"))
    assert score.dim("api_version").score == 1.0
    assert score.dim("method").score == 0.0


# =============================================================================================== #
# 2. The tolerance is REFUSED when it is not cited.
# =============================================================================================== #

def test_an_uncited_alternate_is_refused():
    """It blocks at the gate that runs before a grid burns, not merely in a helper nobody calls.

    Required by name in `tools/assert_guard_ran.SUITE_REQUIRED`.
    """
    gt = task({"version": "v4"})["ground_truth"]
    out = roundtrip_api.roundtrip_problems({"ground_truth": gt})
    assert any("needs an `evidence:` URL" in p for p in out), out
    assert any("needs a `note:`" in p for p in out), out


# --------------------------------------------------------------------------------------------- #
# …and the deliberate break: the refusal must be SPECIFIC to the missing citation.
# --------------------------------------------------------------------------------------------- #

def test_the_refusal_is_specific_and_not_a_blanket_block():
    """Add the citation, change nothing else: the gate must go silent.

    A gate that refuses the cited case too would be refusing the feature, and would pass
    `test_an_uncited_alternate_is_refused` for a reason that has nothing to do with citation.
    """
    gt = task(VALID)["ground_truth"]
    assert roundtrip_api.roundtrip_problems({"ground_truth": gt}) == []
    assert scorer.version_alternate_problems(gt) == []


def test_a_task_that_declares_nothing_draws_no_problem():
    """The default. Most tasks declare no tolerance and must stay untouched by this rule."""
    assert scorer.version_alternate_problems(task()["ground_truth"]) == []
    assert scorer.version_alternate_problems({}) == []
    assert scorer.version_alternate_problems(None) == []


# =============================================================================================== #
# 3. A task that declares NOTHING is unchanged.
# =============================================================================================== #

def test_a_task_declaring_nothing_scores_exactly_as_before():
    """Every scored field of an undeclared task is what it was before ADR-0059, key for key.

    Compared against the pre-change expression directly — `normalize_version(ans) == gt_version` —
    rather than against a remembered number, so this stays true if the surrounding scorer changes.

    Required by name in `tools/assert_guard_ran.SUITE_REQUIRED`.
    """
    for ans_version in ("v3", "v4", "v2", "none", "", "3.0"):
        t = task()
        score = scorer.score_task(t, answer(ans_version))
        expected = (scorer.normalize_version(ans_version)
                    == scorer.normalize_version(t["ground_truth"]["endpoints"][0]["api_version"]))
        rec = score.endpoint_matches[0]
        assert rec["version_ok"] is expected, ans_version
        assert "version_via_alternate" not in rec, (
            f"an undeclared task gained a conditional field on {ans_version!r}; every archived run "
            f"record would change shape")
        assert score.dim("api_version").detail == f"{int(expected)}/1 api_versions correct"


def test_the_declaration_is_the_only_thing_that_can_widen_it(acme_pack):
    """Over the real fixture pack, whose tasks declare nothing: scoring is identical whether the
    alternates are read from ground truth or forced empty. The pack-wide form of the same claim."""
    for t in acme_pack.load_tasks():
        gt_eps = t["ground_truth"]["endpoints"]
        ans = [Endpoint(method="GET", path=e["path"], api_version="v99") for e in gt_eps]
        with_decl = scorer._match_endpoints(gt_eps, ans, None,
                                            scorer.declared_version_alternates(t["ground_truth"]))
        without = scorer._match_endpoints(gt_eps, ans, None, ())
        assert with_decl == without, t["id"]


# --------------------------------------------------------------------------------------------- #
# …and the deliberate break: the neutrality assertion above must have teeth.
# --------------------------------------------------------------------------------------------- #

def test_the_neutrality_check_would_notice_a_leak():
    """Declare an alternate on the same task and the comparison MUST come apart.

    A neutrality test that compares two things which cannot differ proves nothing. This is the
    canary for `test_a_task_declaring_nothing_scores_exactly_as_before` and for the archive sweep in
    `test_version_alternates_archive.py`, which makes exactly this comparison over every archived
    run on disk.
    """
    t = task(VALID)
    gt_eps = t["ground_truth"]["endpoints"]
    ans = [Endpoint(method="GET", path="/v3/widgets", api_version="v4")]
    with_decl = scorer._match_endpoints(gt_eps, ans, None,
                                        scorer.declared_version_alternates(t["ground_truth"]))
    without = scorer._match_endpoints(gt_eps, ans, None, ())
    assert with_decl != without, "the sweep's comparison cannot detect a widening"
    assert with_decl[0]["version_ok"] and not without[0]["version_ok"]


# =============================================================================================== #
# The six rules, each broken on purpose.
# =============================================================================================== #

@pytest.mark.parametrize("sentinel", ["none", "N/A", "null", "nil", "unversioned", "-", "--",
                                      "<none>", "  "])
def test_rule_1_an_alternate_that_normalizes_to_the_no_version_sentinel_blocks(sentinel):
    """The widest this dimension can be made, and it reads in the file like a version.

    `normalize_version` collapses every spelling of "there isn't one" to "" (ADR-0008), so such an
    alternate would credit EVERY answer naming no version against a key that names one.
    """
    out = problems(dict(VALID, version=sentinel))
    assert any("no-version sentinel" in p or "needs a `version:` string" in p for p in out), out


def test_rule_1_is_not_vacuous_a_real_version_does_not_trip_it():
    assert not any("no-version sentinel" in p for p in problems(VALID))


def test_rule_2_an_alternate_equal_to_the_keys_own_version_blocks():
    out = problems(dict(VALID, version="v3"))
    assert any("already the version this task's ground truth declares" in p for p in out), out


def test_rule_2_compares_normalized_not_literal():
    """`26.2` and `v26.2` are one version (ADR-0025/0027). A redundant declaration spelled the other
    way would otherwise read as a widening and score as if absent."""
    out = problems(dict(VALID, version="26.2"), api_version="v26.2")
    assert any("already the version" in p for p in out), out


def test_rule_3_evidence_on_a_rehosting_host_blocks():
    out = problems(dict(VALID, evidence="https://web.archive.org/web/2020/https://v.test/x"))
    assert any("rehosts rather than publishes" in p for p in out), out


def test_rule_3_evidence_that_is_not_a_url_blocks():
    out = problems(dict(VALID, evidence="developer.example.test/reference"))
    assert any("needs an `evidence:` URL" in p for p in out), out


def test_rule_3_a_missing_evidence_key_blocks_even_when_a_note_is_present():
    out = problems({"version": "v4", "note": VALID_NOTE})
    assert any("needs an `evidence:` URL" in p for p in out), out


@pytest.mark.parametrize("note", ["", "   ", "too short to be a reason", None])
def test_rule_4_a_note_under_forty_characters_blocks(note):
    out = problems(dict(VALID, note=note))
    assert any("at least 40 characters" in p for p in out), out


def test_rule_4_a_missing_note_blocks_even_when_evidence_is_present():
    """`evidence:` alone cannot buy silence on the note, nor `note:` alone on the evidence URL —
    each half is judged on itself, so one entry draws the specific complaint rather than a generic
    one."""
    out = problems({"version": "v4", "evidence": VALID["evidence"]})
    assert any("at least 40 characters" in p for p in out), out


def test_rule_5_a_duplicate_alternate_blocks():
    out = problems(VALID, dict(VALID, evidence="https://developer.example.test/elsewhere"))
    assert any("declared more than once" in p for p in out), out


def test_rule_5_catches_a_duplicate_spelled_differently():
    """`v4.0` and `4.0` are the same tolerance; the duplicate rule must see through the notation."""
    out = problems(dict(VALID, version="v4.0"),
                   dict(VALID, version="4.0", evidence="https://developer.example.test/elsewhere"))
    assert any("declared more than once" in p for p in out), out


def test_rule_6_a_bare_string_blocks():
    """The uncited shape. Unlike ADR-0055's equivalent it arrives blocking, because nothing declares
    the key and there is no transitional cohort to grandfather."""
    out = problems("v4")
    assert len(out) == 1 and "bare string" in out[0], out


def test_rule_6_a_bare_list_blocks_every_entry_not_just_the_first():
    out = problems("v4", "v5")
    assert len(out) == 2
    assert "[0]" in out[0] and "[1]" in out[1]


def test_a_cited_entry_is_never_caught_by_the_bare_rule():
    """The rule must be reachable ONLY by an entry citing nothing, or it blocks every real pack."""
    assert problems(VALID) == []
    assert len(problems(VALID, "v5")) == 1


# --------------------------------------------------------------------------------------------- #
# Shape refusals.
# --------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw", [[], "v4", {"version": "v4"}, 42])
def test_a_declaration_that_is_not_a_non_empty_list_blocks(raw):
    """An empty declaration is not a declaration of nothing; it is a declaration nobody finished."""
    out = scorer.version_alternate_problems({"endpoints": [], "api_version_alternates": raw})
    assert out and "non-empty list" in out[0], out


def test_an_entry_of_the_wrong_type_blocks_rather_than_raising():
    """The gate loop has no exception handling around it; a crash would skip the block entirely."""
    out = problems(42)
    assert any("not a mapping" in p for p in out), out


def test_a_missing_version_key_blocks():
    out = problems({"evidence": VALID["evidence"], "note": VALID_NOTE})
    assert any("needs a `version:` string" in p for p in out), out


def test_several_well_formed_entries_block_nothing():
    second = dict(VALID, version="v5", evidence="https://developer.example.test/other")
    assert problems(VALID, second) == []


def test_declared_version_alternates_reads_only_well_formed_entries():
    """A malformed entry must not be silently dropped INTO the scorer as if it were valid, nor
    crash the reader — it is the gate's job to block it, and the gate runs first."""
    gt = {"api_version_alternates": [VALID, "v5", 42, {"evidence": "x"}]}
    assert scorer.declared_version_alternates(gt) == ["v4"]
    assert scorer.declared_version_alternates({}) == []
    assert scorer.declared_version_alternates({"api_version_alternates": "v4"}) == []


# =============================================================================================== #
# It blocks at the gate every pack on disk goes through, and the schema admits only the cited shape.
# =============================================================================================== #

def test_the_schema_refuses_a_bare_string_alternate():
    from jsonschema import Draft202012Validator

    from core.validate import build_schema
    t = copy.deepcopy(task())
    t["ground_truth"]["api_version_alternates"] = ["v4"]
    errors = [e for e in Draft202012Validator(build_schema()).iter_errors(t)
              if "api_version_alternates" in list(e.absolute_path) or "alternates" in str(e.message)]
    assert errors,"the schema accepted a bare-string alternate"


def test_the_schema_refuses_an_alternate_missing_its_citation():
    from jsonschema import Draft202012Validator

    from core.validate import build_schema
    t = copy.deepcopy(task({"version": "v4"}))
    errors = [e for e in Draft202012Validator(build_schema()).iter_errors(t)
              if "api_version_alternates" in list(e.absolute_path) or "alternates" in str(e.message)]
    assert errors,"the schema accepted an alternate with no evidence or note"


def test_the_schema_accepts_the_cited_shape():
    from jsonschema import Draft202012Validator

    from core.validate import build_schema
    assert list(Draft202012Validator(build_schema()).iter_errors(task(VALID))) == []


def test_the_docs_schema_refuses_the_key_outright():
    """The docs cohort has no `api_version` dimension, so the key would be scored by nothing and
    read by nobody — the state `additionalProperties: false` exists to prevent (ADR-0044)."""
    from jsonschema import Draft202012Validator

    from core.validate import build_docs_schema
    t = {"id": "d", "category": "foundational", "job_category": "select-hardware",
         "prompt": "p",
         "ground_truth": {"publication": {"number": "1", "revision": "A",
                                          "url": "https://example.test/x"},
                          "catalog_numbers": ["1"],
                          "success_shape": "s", "common_failure_modes": ["f"],
                          "api_version_alternates": [VALID]}}
    messages = [e.message for e in Draft202012Validator(build_docs_schema()).iter_errors(t)]
    assert any("api_version_alternates" in m and "Additional properties" in m for m in messages), \
        messages
