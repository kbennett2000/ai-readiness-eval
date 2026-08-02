"""The docs-cohort answer contract (ADR-0044).

Every rule below was verified by breaking it on purpose before it was written down. The ones that
matter most are the REFUSALS — the normalization folds this contract will not do, and the gate
outcomes it will not soften — because a scorer's failure mode is not "wrong answer marked wrong", it
is a fold that quietly credits an answer nobody would credit by hand.

Nothing here names a real vendor: the fixture pack is synthetic, exactly as `pack-acme` is for the
API cohort, so `test_core_no_vendor` stays clean.
"""
import copy
from pathlib import Path

import pytest
import yaml

from core import docs_answer, docs_scorer, factory
from core.contract import API_CONTRACT, CONTRACTS, DOCS_CONTRACT, contract_for
from core.pack import Pack

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DOCS_PACK = FIXTURES / "pack-docs-neutral"
API_PACK = FIXTURES / "pack-acme"


def _answer(**over) -> docs_answer.DocsAnswer:
    base = {"catalog_numbers": [], "firmware_version": None,
            "software_version": None, "publication": None}
    base.update(over)
    return docs_answer.DocsAnswer(**base)


def _block(body: str) -> str:
    return f"Here is the answer.\n\n```answer-summary\n{body}\n```\n"


# --------------------------------------------------------------------------- #
# The registry: which contract a pack is measured under
# --------------------------------------------------------------------------- #

def test_a_pack_declaring_nothing_is_measured_under_the_api_contract():
    """The default is the whole no-regression argument: every pack written before ADR-0044 declares
    no cohort, so it must land on the contract it was authored, gated and published under."""
    assert Pack.load(API_PACK).cohort == "api"
    assert contract_for(Pack.load(API_PACK)) is API_CONTRACT


def test_a_docs_pack_is_measured_under_the_docs_contract():
    assert contract_for(Pack.load(DOCS_PACK)) is DOCS_CONTRACT


def test_an_unknown_cohort_raises_instead_of_falling_back(tmp_path):
    """A typo must not be scored. Falling back to the API contract would give a docs pack six
    dimensions its ground truth cannot supply — every one n/a, the run green, nothing measured."""
    d = tmp_path / "typo"
    d.mkdir()
    (d / "pack.yaml").write_text(yaml.safe_dump({"vendor": {"id": "x"}, "cohort": "dcos"}))
    with pytest.raises(KeyError) as exc:
        contract_for(Pack.load(d))
    assert "dcos" in str(exc.value) and "api" in str(exc.value)


def test_the_two_dimension_sets_are_disjoint():
    """A shared name would let a docs cell be read into an API column — in a rollup, in a card, or
    in the cohort table — and every value in both columns is a bare percentage that looks fine."""
    assert not set(API_CONTRACT.dimensions) & set(DOCS_CONTRACT.dimensions)


def test_every_registered_contract_is_internally_consistent():
    for name, contract in CONTRACTS.items():
        assert contract.name == name
        assert contract.dimensions, f"{name} scores nothing"
        assert set(contract.dim_labels) == set(contract.dimensions), \
            f"{name} labels and dimensions disagree — a renderer would KeyError on a real run"
        assert contract.categories, f"{name} has no task taxonomy"


# --------------------------------------------------------------------------- #
# The prompt: built without the excerpt promise, from day one
# --------------------------------------------------------------------------- #

def test_the_docs_context_carries_no_excerpt_promise():
    """Public #67: the API preamble claims excerpts were supplied whether or not any were. The docs
    cohort has no archive to invalidate, so it starts on the far side of that defect."""
    assert DOCS_CONTRACT.context_preamble("any label") == ""


def test_the_api_context_preamble_is_unchanged_to_the_byte():
    """The other half of the same decision. Changing this sentence changes what every archived API
    run was asked, so five published numbers would stand as measurements of a prompt that no longer
    exists. It is pinned here so the docs work cannot drift into it."""
    assert API_CONTRACT.context_preamble("VENDOR docs") == (
        "You have been given excerpts from VENDOR docs below. Use them to answer accurately.\n")


def test_the_injected_docs_context_starts_with_the_page_itself():
    from core.conditions import PublicDocsCondition

    context = PublicDocsCondition(Pack.load(DOCS_PACK)).build_context("pick-controller")
    assert "You have been given excerpts" not in context
    assert context.lstrip().startswith("=====")


def test_the_contract_example_is_valid_yaml_and_teaches_block_style():
    """ADR-0014 exists because the API contract's example demonstrates a flow sequence, and a model
    following it with a real parameter name emitted invalid YAML. That ADR names the permanent fix —
    change the example — and records that it cannot be applied retroactively. This cohort has it."""
    suffix = docs_answer.DOCS_ANSWER_BLOCK_SUFFIX
    body = suffix.split("```answer-summary\n", 1)[1].split("```", 1)[0]
    assert "catalog_numbers:\n  - " in body, "the example must teach a block sequence"
    assert "[" not in body.split("publication")[0], "no flow sequence in the example"
    parsed = docs_answer.parse(_block(body.rstrip()))
    assert not parsed.is_failure, parsed.failure and parsed.failure.reason


def test_the_prompt_appends_the_contract_and_keeps_the_question():
    built = DOCS_CONTRACT.build_prompt("Which part meets the requirement?")
    assert built.startswith("Which part meets the requirement?")
    assert "answer-summary" in built


# --------------------------------------------------------------------------- #
# The parser: literal text, not what YAML resolves it to
# --------------------------------------------------------------------------- #

def test_a_version_is_read_as_written_and_not_as_a_float():
    """THE TRAP THIS PARSER COMPOSES RATHER THAN LOADS TO AVOID.

    `yaml.safe_load` types an unquoted `12.010` as a float and hands back `12.01`: the trailing digit
    is gone before anything compares it, and the version dimension would be scoring a value it had
    silently rewritten. Verified against the standard loader in the same test, so this cannot pass by
    describing a problem that no longer exists.
    """
    assert yaml.safe_load("firmware_version: 12.010")["firmware_version"] == 12.01

    result = docs_answer.parse(_block("firmware_version: 12.010"))
    assert not result.is_failure
    assert result.summary.firmware_version == "12.010"


def test_a_genuine_null_and_the_string_null_are_different_answers():
    """One is "not applicable to this question"; the other is a model writing a word. A parser that
    could not tell them apart would report a don't-know as a four-character answer."""
    assert docs_answer.parse(_block("firmware_version: null")).summary.firmware_version is None
    assert docs_answer.parse(_block("firmware_version: ~")).summary.firmware_version is None
    assert docs_answer.parse(_block('firmware_version: "null"')).summary.firmware_version == "null"


def test_a_block_with_none_of_the_contract_keys_is_a_format_failure():
    result = docs_answer.parse(_block("endpoints:\n  - method: GET"))
    assert result.is_failure and "none of the contract's keys" in result.failure.reason


def test_a_block_with_keys_but_empty_values_is_an_answer_not_a_format_failure():
    """The split that keeps a don't-know from being laundered into an instrument fault. The model
    honoured the shape and had nothing to put in it; that is a score of zero, not an unparseable
    response, and the two are counted separately everywhere downstream."""
    result = docs_answer.parse(_block("catalog_numbers: []\nfirmware_version: null"))
    assert not result.is_failure
    assert result.summary.catalog_numbers == [] and result.summary.firmware_version is None


def test_the_last_block_wins_and_unknown_keys_are_ignored():
    text = (_block("catalog_numbers:\n  - WRONG-1") +
            _block("catalog_numbers:\n  - RIGHT-1\nnotes: chatter\n"))
    result = docs_answer.parse(text)
    assert result.summary.catalog_numbers == ["RIGHT-1"]


def test_a_missing_or_unparseable_block_is_a_format_failure():
    assert docs_answer.parse("no block at all").is_failure
    assert docs_answer.parse("").is_failure
    assert docs_answer.parse(_block("catalog_numbers: [unclosed")).is_failure


def test_render_and_parse_round_trip_a_version_that_looks_like_a_number():
    answer = _answer(catalog_numbers=["XR-8300"], firmware_version="12.003",
                     software_version="30", publication="XR-TD001")
    back = docs_answer.parse(docs_answer.render_block(answer)).summary
    assert back == answer


# --------------------------------------------------------------------------- #
# Normalization: the folds this scorer refuses
# --------------------------------------------------------------------------- #

def test_catalog_normalization_collapses_only_what_carries_no_information():
    assert docs_scorer.normalize_catalog("  xr-8300 ") == "XR-8300"
    assert docs_scorer.normalize_catalog("XR  8300") == "XR 8300"


@pytest.mark.parametrize("variant", ["XR-8300-K", "XR-8300-XT", "XR-8300-NSE"])
def test_a_variant_suffix_is_never_folded_away(variant):
    """MUST-NOT-FOLD. A conformal-coated or extended-temperature part is a different orderable part
    with a different rating, and a buyer handed the wrong one has a wrong answer. This dimension is
    containment-scored, so a fold here could only ever ADD a match — the direction that manufactures
    a score."""
    assert docs_scorer.normalize_catalog(variant) != docs_scorer.normalize_catalog("XR-8300")


def test_a_leading_zero_in_a_version_segment_carries_no_meaning():
    assert docs_scorer.version_tuples("12.003") == docs_scorer.version_tuples("12.3")
    assert docs_scorer.version_tuples("v30") == [(30,)]


def test_a_more_precise_answer_satisfies_a_major_only_requirement():
    assert docs_scorer.version_satisfies("30", "30.01")
    assert docs_scorer.version_satisfies("30", "30")


def test_a_vaguer_answer_does_not_satisfy_a_precise_requirement():
    """MUST-NOT-CREDIT, and the asymmetry is the whole design (the ADR-0024 shape). When a vendor
    states three components the later ones are the point of stating them: an integrator who installs
    12.000 has not met a 12.003 requirement, and crediting the vague answer manufactures a score."""
    assert not docs_scorer.version_satisfies("12.003", "12")
    assert not docs_scorer.version_satisfies("12.003", "12.002")


def test_a_requirement_nothing_states_is_never_satisfied():
    assert not docs_scorer.version_satisfies(None, "30")
    assert not docs_scorer.version_satisfies("30", None)


def test_a_hedged_version_field_is_counted_rather_than_trusted():
    """`version_satisfies` is any-of, the same judgment call `required_scopes` makes, so listing many
    versions can only ever help. That is visible rather than punished: the count lands in the exhibit
    and on the card, where a reader can discount it."""
    assert docs_scorer.version_satisfies("30", "28, 29, 30 or later")
    assert docs_scorer.hedge_count("28, 29, 30 or later") == 3
    assert docs_scorer.hedge_count("30") == 1
    assert docs_scorer.hedge_count(None) == 0


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def _task(name: str) -> dict:
    return yaml.safe_load((DOCS_PACK / "tasks" / f"{name}.yaml").read_text())


def test_a_class_the_task_does_not_ask_about_is_n_a_and_never_zero():
    """A catalog-selection task saying nothing about firmware is not wrong about firmware. n/a is
    excluded from the means, exactly as the API scorer treats a task with no required scopes."""
    score = docs_scorer.score_task(_task("pick-controller"), _answer(catalog_numbers=["XR-8300"]))
    assert score.dim("catalog_number").score == 1.0
    assert score.dim("firmware_version").score is None
    assert score.dim("software_version").score is None


def test_the_catalog_dimension_is_any_of_overlap():
    task = _task("pick-controller")
    assert docs_scorer.score_task(
        task, _answer(catalog_numbers=["XR-8200", "XR-8300"])).dim("catalog_number").score == 1.0
    assert docs_scorer.score_task(
        task, _answer(catalog_numbers=["XR-8200"])).dim("catalog_number").score == 0.0


def test_the_pairing_is_recorded_and_is_not_a_dimension():
    """Compatibility is two published values, and pairing them is what an integrator actually needs.
    It is still not a fourth dimension: `overall_accuracy` is the mean of applicable dimensions, so
    adding it would let compatibility drive three quarters of the headline."""
    task = _task("check-pairing")
    both = docs_scorer.score_task(task, _answer(firmware_version="12.003", software_version="30"))
    assert both.exhibit["pairing_ok"] is True
    assert "pairing" not in " ".join(both.dimensions)

    half = docs_scorer.score_task(task, _answer(firmware_version="12.003", software_version="28"))
    assert half.exhibit["pairing_ok"] is False
    assert half.dim("firmware_version").score == 1.0
    assert half.dim("software_version").score == 0.0


def test_the_pairing_is_n_a_when_the_task_asks_for_only_one_half():
    """So a card can never average a pairing over tasks that had no pairing to get right."""
    score = docs_scorer.score_task(_task("pick-controller"), _answer(catalog_numbers=["XR-8300"]))
    assert score.exhibit["pairing_ok"] is None


def test_the_cited_publication_is_recorded_and_scores_nothing():
    """It is the mechanical signal a pack needs to ask whether a model answered about one product
    line with a document about a neighbouring one. Core records it; which numbers are a near
    neighbour is a vendor fact and stays in the pack."""
    score = docs_scorer.score_task(
        _task("pick-controller"), _answer(catalog_numbers=["XR-8300"], publication="ZZ-OTHER99"))
    assert score.exhibit["publication"] == "ZZ-OTHER99"
    assert score.dim("catalog_number").score == 1.0


# --------------------------------------------------------------------------- #
# The round-trip control
# --------------------------------------------------------------------------- #

def test_every_docs_task_scores_its_own_ground_truth():
    from core.roundtrip import check_pack

    controls = check_pack(Pack.load(DOCS_PACK))
    assert controls and all(c.ok for c in controls), \
        [p for c in controls for p in c.problems]


def test_a_task_declaring_no_scorable_value_is_blocked_not_passed():
    """The docs analogue of ADR-0011's unnameable login style: every dimension would report n/a, the
    task would pass the control by measuring nothing, and a grid would burn on it."""
    from core.roundtrip import check_task

    task = _task("pick-controller")
    del task["ground_truth"]["catalog_numbers"]
    control = check_task(task, None, DOCS_CONTRACT)
    assert not control.ok
    assert any("measure nothing" in p for p in control.problems)


def test_a_half_declared_pairing_draws_a_note_and_still_passes():
    from core.roundtrip import check_task

    control = check_task(_task("pick-controller"), None, DOCS_CONTRACT)
    assert control.ok
    assert not control.notes  # this task declares neither half, so there is nothing to note

    task = _task("check-pairing")
    del task["ground_truth"]["software_version"]
    half = check_task(task, None, DOCS_CONTRACT)
    assert half.ok and any("pairing is n/a" in n for n in half.notes)


# --------------------------------------------------------------------------- #
# The truncation gate
# --------------------------------------------------------------------------- #

def _pack_copy(tmp_path: Path, **pack_yaml_over) -> Pack:
    dest = tmp_path / "pack"
    import shutil
    shutil.copytree(DOCS_PACK, dest)
    cfg = yaml.safe_load((dest / "pack.yaml").read_text())
    for key, value in pack_yaml_over.items():
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value
    (dest / "pack.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return Pack.load(dest)


def test_the_gate_passes_when_every_value_survives_the_budget():
    ok, detail = factory.check_truncation(Pack.load(DOCS_PACK))
    assert ok and "survive" in detail


def test_a_budget_that_crops_the_answer_blocks_the_docs_cohort(tmp_path):
    """The ADR-0013 fault class, caught before the money is spent. On this surface the ground-truth
    VALUE is the answer, so a value the budget cropped away does not make the question harder — it
    makes it unanswerable, and every point of the measured gap would be an artifact of a number we
    chose."""
    pack = _pack_copy(tmp_path, public_docs={"source_label": "lib", "budget_tokens": 1})
    manifest = yaml.safe_load((pack.root / "docs-manifest.yaml").read_text())
    manifest["budget_tokens"] = 1
    (pack.root / "docs-manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))

    ok, detail = factory.check_truncation(pack)
    assert not ok
    assert "removed" in detail and "budget_tokens" in detail


def test_nothing_to_search_blocks_the_docs_cohort_rather_than_passing(tmp_path):
    """ADR-0043 pointed in the direction a GATE must fail. A control that cannot tell *absent* from
    *broken* has to refuse: passing here would certify a window nobody looked through."""
    import shutil

    pack = _pack_copy(tmp_path)
    shutil.rmtree(pack.docs_cache_dir)
    ok, detail = factory.check_truncation(pack)
    assert not ok
    assert "fetch-docs" in detail


def test_the_api_cohort_is_advisory_and_no_existing_pack_is_newly_blocked():
    """Every API pack on disk was authored under the old behaviour. A gate that newly blocked them
    would be a rule applied retroactively to published work."""
    ok, _detail = factory.check_truncation(Pack.load(API_PACK))
    assert ok


def test_the_audit_searches_for_values_on_a_docs_pack_and_paths_on_an_api_pack():
    from core.conditions import audit_docs_truncation

    docs_items = {r["item"] for r in audit_docs_truncation(Pack.load(DOCS_PACK))}
    assert "catalog:XR-8300" in docs_items and "firmware_version:12.003" in docs_items

    api_items = {r["item"] for r in audit_docs_truncation(Pack.load(API_PACK))}
    assert any(str(i).startswith("/") for i in api_items), "the API cohort still audits paths"


# --------------------------------------------------------------------------- #
# The schema
# --------------------------------------------------------------------------- #

def _docs_errors(task: dict) -> list[str]:
    from jsonschema import Draft7Validator

    from core.validate import build_docs_schema

    return [e.message for e in Draft7Validator(build_docs_schema()).iter_errors(task)]


def test_the_docs_schema_accepts_the_fixture_tasks():
    for name in ("pick-controller", "check-pairing"):
        assert _docs_errors(_task(name)) == []


def test_the_docs_schema_refuses_an_endpoint():
    """A separate schema rather than a loosened one. Admitting both shapes would have meant dropping
    `additionalProperties: false`, and a docs task could then declare `endpoints:` — scored by
    nothing, read by nobody, indistinguishable from a task that meant it."""
    task = copy.deepcopy(_task("pick-controller"))
    task["ground_truth"]["endpoints"] = [{"method": "GET", "path": "/v1/x"}]
    assert _docs_errors(task)


def test_the_docs_schema_requires_a_publication_with_a_revision():
    """This cohort's form of the anchoring rule: ground truth rests on a first-party document,
    identified precisely enough that a reader can fetch the same one."""
    task = copy.deepcopy(_task("pick-controller"))
    del task["ground_truth"]["publication"]["revision"]
    assert _docs_errors(task)

    task = copy.deepcopy(_task("pick-controller"))
    del task["ground_truth"]["publication"]
    assert _docs_errors(task)


def test_the_docs_schema_refuses_a_version_written_as_a_number():
    """The schema half of the float trap. Written bare, `12.003` is a YAML float and the answer key
    itself would arrive already rewritten — so it is refused at authoring time, not compensated for
    at scoring time."""
    task = copy.deepcopy(_task("check-pairing"))
    task["ground_truth"]["firmware_version"] = 12.003
    assert _docs_errors(task)


def test_a_docs_task_may_not_use_the_api_taxonomy():
    from core.taxonomy import CATEGORIES, DOCS_CATEGORIES

    assert not set(CATEGORIES) & set(DOCS_CATEGORIES)
    task = copy.deepcopy(_task("pick-controller"))
    task["job_category"] = "grant-access"
    assert _docs_errors(task)


# --------------------------------------------------------------------------- #
# Cross-cohort comparison
# --------------------------------------------------------------------------- #

def test_a_cross_cohort_table_is_refused_rather_than_captioned():
    """Rendering it with a caveat would leave the numbers on the page for someone to quote without
    the caveat. The private repo's cohort-partitioned card gate is the prose half of this rule."""
    from core.category import cross_cohort_conflict, render_cross_vendor_category_md

    assert cross_cohort_conflict(["api", "api"]) == ""
    assert "more than one cohort" in cross_cohort_conflict(["api", "docs"])
    with pytest.raises(ValueError):
        render_cross_vendor_category_md([("A", {}), ("B", {})], cohorts=["api", "docs"])


def test_a_single_cohort_table_still_renders():
    from core.category import render_cross_vendor_category_md

    text = render_cross_vendor_category_md([("A", {}), ("B", {})], cohorts=["docs", "docs"],
                                           contract=DOCS_CONTRACT)
    assert "select-hardware" in text and "grant-access" not in text
