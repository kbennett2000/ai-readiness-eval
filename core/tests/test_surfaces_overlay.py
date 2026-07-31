"""The surface overlay's safety properties, and the validator (ADR-0037).

The classifier in `test_surfaces.py` decides which surface an answer came from. This module pins the
things that make it safe to add to a project whose whole product is numbers:

* declaring surfaces moves NO score, in two independent forms;
* the overlay writes nothing;
* its arithmetic reconciles with the exhibit printed beside it on the same card;
* an inventory that cannot discriminate is refused at `validate`, not discovered in a card.
"""
import ast
import json
import shutil
from pathlib import Path

import pytest
import yaml

from core import surfaces as surfaces_mod
from core.analyze import iter_parsed_runs, unmatched_endpoints
from core.pack import Pack
from core.surfaces import (AMBIGUOUS, NO_MATCH, RESIDUAL_BUCKETS, UNRECOGNIZED, Surface, SurfaceSet,
                           classify_results_dir, format_report)
from core.validate import validate_answer_surfaces

CORE = Path(__file__).resolve().parents[1]
ACME = CORE / "tests" / "fixtures" / "pack-acme"

# The fixture vendor's surfaces: the acme pack's ground truth is all `/v3`, so `/v1` is the
# superseded surface it could have been answered with.
DECLARATION = {
    "ambiguous_ceiling": 0.10,
    "surfaces": [
        {"id": "rest-v3", "label": "REST API v3", "measured": True,
         "rationale": "the current surface, and what every task asks about",
         "version_markers": ["v3"],
         "paths": ["/v3/widgets", "/v3/gadgets/{id}"]},
        {"id": "rest-v1", "label": "REST API v1 (deprecated)",
         "rationale": "superseded, still served",
         "version_markers": ["v1"],
         "paths": ["/v1/widgets", "/v1/gadgets/{id}"]},
    ],
}


def _answer(path, version, method="GET"):
    return ("```answer-summary\n"
            f"endpoints:\n  - method: {method}\n    path: {path}\n    api_version: {version}\n"
            "auth_flow: OAuth2 bearer token\nrequired_scopes: []\nkey_parameters: [id]\n```")


def _results_dir(tmp_path, answers):
    runs = tmp_path / "runs"
    runs.mkdir(parents=True)
    for i, (task_id, text) in enumerate(answers):
        (runs / f"{task_id}-run{i}.json").write_text(json.dumps(
            {"task_id": task_id, "run_index": i, "raw_response": text}))
    return tmp_path


@pytest.fixture
def acme_with_surfaces(tmp_path):
    """A copy of the fixture pack that declares surfaces. The shipped fixture stays undeclared, so
    the two can be compared."""
    dest = tmp_path / "pack-acme"
    shutil.copytree(ACME, dest)
    cfg = yaml.safe_load((dest / "pack.yaml").read_text())
    cfg["answer_surfaces"] = DECLARATION
    (dest / "pack.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return Pack.load(dest)


# --------------------------------------------------------------------------- #
# The must-not-regress property, in two forms
# --------------------------------------------------------------------------- #

def test_declaring_surfaces_moves_no_score(acme_with_surfaces):
    """Form 1: the same answers score identically with and without a declaration.

    This is the licence for the whole feature. The overlay can only ever redistribute outcomes the
    scorer already recorded, among buckets a pack already declared — there is no arrangement of
    inventories that manufactures a point.
    """
    from core.scorer import score_task
    from core.answer_block import parse

    plain = Pack.load(ACME)
    answers = {"widget-list": _answer("/v3/widgets", "v3"),
               "widget-create": _answer("/v3/widgets", "v3", "POST"),
               "gadget-fetch": _answer("/v1/gadgets/{id}", "v1")}
    for task_id, text in answers.items():
        without = score_task(plain.tasks_by_id()[task_id], parse(text).summary,
                             plain.base_prefix_segments)
        with_ = score_task(acme_with_surfaces.tasks_by_id()[task_id], parse(text).summary,
                           acme_with_surfaces.base_prefix_segments)
        assert without.dimensions == with_.dimensions, task_id


def test_the_scoring_path_cannot_see_surfaces():
    """Form 2: structural. Form 1 tests one input; this makes the violation impossible.

    `core.surfaces` imports FROM the scorer, never the other way round. If that edge ever reversed,
    a classification rule could reach a published number without any test noticing.
    """
    for module in ("scorer.py", "report.py", "category.py", "rebuild.py"):
        tree = ast.parse((CORE / module).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("surfaces"):
                pytest.fail(f"core/{module} imports core.surfaces — the scoring path must not")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.endswith("surfaces"), f"core/{module} imports surfaces"


def test_the_frozen_reference_pack_declares_no_surfaces_so_its_numbers_cannot_move():
    """The 73/68/93 anchor is only an anchor while nothing new touches it."""
    assert not Pack.load(CORE.parent / "packs" / "sailpoint").answer_surfaces


def test_the_overlay_writes_nothing(tmp_path, acme_with_surfaces):
    d = _results_dir(tmp_path / "r", [("widget-list", _answer("/v3/widgets", "v3"))])
    before = {p: p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}
    classify_results_dir(d, acme_with_surfaces.tasks_by_id(), acme_with_surfaces.answer_surfaces)
    after = {p: p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}
    assert before == after


# --------------------------------------------------------------------------- #
# Arithmetic that reconciles with what is printed beside it
# --------------------------------------------------------------------------- #

def test_buckets_sum_to_the_endpoints_actually_read(tmp_path, acme_with_surfaces):
    d = _results_dir(tmp_path / "r", [
        ("widget-list", _answer("/v3/widgets", "v3")),
        ("widget-list", _answer("/v1/widgets", "v1")),
        ("gadget-fetch", _answer("/widgets", None)),
        ("gadget-fetch", _answer("/v3/flanges", "v3")),
    ])
    report = classify_results_dir(d, acme_with_surfaces.tasks_by_id(),
                                  acme_with_surfaces.answer_surfaces)
    assert sum(report.endpoints.values()) == report.total_endpoints == 4
    assert sum(report.runs.values()) == report.total_runs == 4
    assert report.endpoints["rest-v3"] == 1 and report.endpoints["rest-v1"] == 1
    assert report.endpoints[AMBIGUOUS] == 1 and report.endpoints[UNRECOGNIZED] == 1


def test_the_overlay_reads_the_same_runs_as_the_unmatched_exhibit(tmp_path, acme_with_surfaces):
    """The two exhibits print side by side on one card, so a reader must be able to reconcile them.
    Both go through `iter_parsed_runs` — this asserts the shared loop is actually shared."""
    d = _results_dir(tmp_path / "r", [
        ("widget-list", _answer("/v3/widgets", "v3")),
        ("widget-list", "no answer block here at all"),          # format failure: skipped by both
        ("gadget-fetch", _answer("/v3/flanges", "v3")),          # unmatched AND unrecognized
    ])
    tasks = acme_with_surfaces.tasks_by_id()
    report = classify_results_dir(d, tasks, acme_with_surfaces.answer_surfaces)
    unmatched = sum(sum(c.values()) for c in unmatched_endpoints(d, tasks).values())

    assert report.total_runs == 2, "the format failure must be skipped by the overlay too"
    assert len(list(iter_parsed_runs(d, tasks))) == 2
    # `/v1/widgets` would be unmatched-but-recognized; here the only unmatched endpoint is also the
    # only unrecognized one, so the two exhibits agree on it exactly.
    assert unmatched == report.endpoints[UNRECOGNIZED] == 1


def test_a_run_answering_a_superseded_surface_is_counted_as_stale_not_fabricated(
        tmp_path, acme_with_surfaces):
    """The finding this whole module exists to make expressible: a real endpoint from a superseded
    surface is a different error from an invented one, and lands in a different bucket."""
    d = _results_dir(tmp_path / "r", [("gadget-fetch", _answer("/v1/gadgets/{id}", "v1"))])
    report = classify_results_dir(d, acme_with_surfaces.tasks_by_id(),
                                  acme_with_surfaces.answer_surfaces)
    assert report.runs["rest-v1"] == 1
    assert report.endpoints[UNRECOGNIZED] == 0


def test_every_bucket_is_reachable(tmp_path, acme_with_surfaces):
    """Non-vacuity. A classifier where some bucket can never fire, or one bucket absorbs everything,
    would pass every test above while reporting nothing."""
    d = _results_dir(tmp_path / "r", [
        ("widget-list", _answer("/v3/widgets", "v3")),      # measured
        ("widget-list", _answer("/v1/widgets", "v1")),      # superseded
        ("widget-list", _answer("/widgets", None)),         # ambiguous
        ("widget-list", _answer("/v1/widgets", "v3")),      # conflicted
        ("widget-list", _answer("/v3/flanges", "v3")),      # unrecognized
    ])
    report = classify_results_dir(d, acme_with_surfaces.tasks_by_id(),
                                  acme_with_surfaces.answer_surfaces)
    for bucket in ("rest-v3", "rest-v1", *RESIDUAL_BUCKETS):
        assert report.endpoints[bucket] >= 1, f"bucket {bucket} never fired"
    assert max(report.endpoints.values()) < report.total_endpoints, "one bucket absorbed everything"


def test_the_report_refuses_to_print_a_split_above_the_declared_ambiguous_ceiling(
        tmp_path, acme_with_surfaces):
    """A number printed with a caveat gets quoted without the caveat, so past the ceiling the table
    is replaced by the reason rather than footnoted."""
    d = _results_dir(tmp_path / "r", [("widget-list", _answer("/widgets", None))] * 3)
    report = classify_results_dir(d, acme_with_surfaces.tasks_by_id(),
                                  acme_with_surfaces.answer_surfaces)
    text, n_residual = format_report(report, acme_with_surfaces.answer_surfaces)
    assert report.ambiguous_rate == 1.0 and n_residual == 3
    assert "NOT REPORTABLE" in text


def test_the_host_rate_is_published_rather_than_assumed(tmp_path, acme_with_surfaces):
    """No rule here uses the host, and the way to keep that honest is to print how often one appeared
    instead of asserting in prose that it never does."""
    d = _results_dir(tmp_path / "r", [
        ("widget-list", _answer("https://api.example.test/v3/widgets", "v3")),
        ("widget-list", _answer("/v3/widgets", "v3"))])
    report = classify_results_dir(d, acme_with_surfaces.tasks_by_id(),
                                  acme_with_surfaces.answer_surfaces)
    assert report.host_stated == 1
    text, _ = format_report(report, acme_with_surfaces.answer_surfaces)
    assert "1** of 2" in text or "**1** of 2" in text


# --------------------------------------------------------------------------- #
# The validator
# --------------------------------------------------------------------------- #

def _set(*surfaces):
    return SurfaceSet(tuple(surfaces))


def test_a_single_surface_is_refused():
    errors = validate_answer_surfaces(_set(Surface(
        id="only", label="Only", measured=True, rationale="r", paths=("/v3/x",))))
    assert any("fewer than 2" in e for e in errors)


def test_exactly_one_surface_must_be_measured():
    two_measured = _set(
        Surface(id="a", label="A", measured=True, rationale="r", paths=("/v3/x",),
                version_markers=("v3",)),
        Surface(id="b", label="B", measured=True, rationale="r", paths=("/v1/x",),
                version_markers=("v1",)))
    assert any("exactly one" in e for e in validate_answer_surfaces(two_measured))

    none_measured = _set(
        Surface(id="a", label="A", rationale="r", paths=("/v3/x",), version_markers=("v3",)),
        Surface(id="b", label="B", rationale="r", paths=("/v1/x",), version_markers=("v1",)))
    assert any("exactly one" in e for e in validate_answer_surfaces(none_measured))


def test_an_empty_inventory_is_refused():
    """Without it every answer falls to `unrecognized` without ever being wrong — the split would
    report the inventory's own emptiness and read as a finding about the model."""
    errors = validate_answer_surfaces(_set(
        Surface(id="a", label="A", measured=True, rationale="r", paths=("/v3/x",)),
        Surface(id="b", label="B", rationale="r", paths=())))
    assert any("empty path inventory" in e for e in errors)


def test_each_surface_needs_a_written_rationale():
    errors = validate_answer_surfaces(_set(
        Surface(id="a", label="A", measured=True, rationale="r", paths=("/v3/x",),
                version_markers=("v3",)),
        Surface(id="b", label="B", paths=("/v1/x",), version_markers=("v1",))))
    assert any("no rationale" in e for e in errors)


def test_an_unresolvable_overlap_is_refused_at_validate_not_discovered_at_classify_time():
    """Two surfaces publishing one path is normal and expected. Publishing it with nothing to tell
    them apart is a schema error: every such answer would silently land in `ambiguous`, and a pack
    would ship a split whose biggest bucket is its own under-specification."""
    no_markers = _set(
        Surface(id="a", label="A", measured=True, rationale="r", paths=("/v3/x",),
                version_markers=("v3",)),
        Surface(id="b", label="B", rationale="r", paths=("/v1/x",)))
    assert any("no version_markers" in e for e in validate_answer_surfaces(no_markers))

    shared_marker = _set(
        Surface(id="a", label="A", measured=True, rationale="r", paths=("/v3/x",),
                version_markers=("v3", "beta")),
        Surface(id="b", label="B", rationale="r", paths=("/v1/x",), version_markers=("beta",)))
    assert any("share version marker" in e for e in validate_answer_surfaces(shared_marker))


def test_a_duplicate_surface_id_is_refused():
    """Two surfaces sharing an id would make every bucket lookup and every card label ambiguous."""
    errors = validate_answer_surfaces(_set(
        Surface(id="a", label="A", measured=True, rationale="r", paths=("/v3/x",),
                version_markers=("v3",)),
        Surface(id="a", label="A again", rationale="r", paths=("/v1/x",), version_markers=("v1",))))
    assert any("more than once" in e for e in errors)


def test_a_valid_declaration_passes_and_the_fixture_pack_is_one(acme_with_surfaces):
    assert validate_answer_surfaces(acme_with_surfaces.answer_surfaces) == []


def test_a_pack_declaring_nothing_is_not_validated_against_these_rules():
    assert validate_answer_surfaces(SurfaceSet(())) == []
    assert validate_answer_surfaces(None) == []


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #

def test_a_mis_transcribed_inventory_blocks_the_roundtrip_gate(acme_with_surfaces, tmp_path):
    """The control has to BLOCK, not warn: a wrong inventory produces a confident wrong split, and
    the only cheap moment to catch it is before a grid burns."""
    from core.roundtrip import check_pack

    assert all(c.ok for c in check_pack(acme_with_surfaces))

    cfg = yaml.safe_load((acme_with_surfaces.root / "pack.yaml").read_text())
    cfg["answer_surfaces"]["surfaces"][0]["paths"] = ["/v3/widgets"]   # drops /v3/gadgets/{id}
    (acme_with_surfaces.root / "pack.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))

    controls = check_pack(Pack.load(acme_with_surfaces.root))
    failed = [c for c in controls if not c.ok]
    assert failed and any(c.task_id == "(answer-surfaces)" for c in failed)
    assert any("gadget" in p for c in failed for p in c.problems)


def test_the_uncurated_caveat_is_carried_wherever_the_exhibit_is_printed():
    """The correction this cycle also ships: these endpoints are UNMATCHED, which is all the code can
    establish. Calling them invented is a claim about the world that nothing here checks — and real,
    documented endpoints have already been printed under that word on a card."""
    from core import analyze, factory
    assert "UNCURATED" in analyze.UNCURATED_CAVEAT
    src = (CORE / "factory.py").read_text()
    assert "## Invented endpoints" not in src
    assert "outside ground truth" in src
    assert "UNCURATED_CAVEAT" in src
