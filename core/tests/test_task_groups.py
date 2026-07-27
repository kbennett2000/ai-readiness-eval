"""Pack-declared task groups: the rollup, the renderer and the validator rules (ADR-0026).

A pack may declare named task groups as a REPORTING AXIS — the motivating case is surface age, where
the question is whether accuracy tracks how long an API surface has existed. The grouping lives in
`pack.yaml` rather than in a task file because the task schema is closed, because the same tasks can
be grouped more than one way, and because a grouping is an argument a card makes rather than a fact a
task carries.

The arithmetic is deliberately the SAME function the job-category rollup uses. `rollup_by_category`
is now a thin wrapper over `rollup_by_group`, so "the mean of a group" can never be computed two
different ways in one report.
"""
import json
from pathlib import Path

import pytest

from core.category import rollup_by_category, rollup_by_group
from core.pack import Pack
from core.report import render_group_comparison_md
from core.scorer import DIMENSIONS
from core.validate import validate_task_groups

REPO_ROOT = Path(__file__).resolve().parents[2]
SAILPOINT = REPO_ROOT / "packs" / "sailpoint"
NC_SCORES = SAILPOINT / "fixtures" / "imported" / "2026-07-23-sterile-no-context" / "scores.json"
PD_SCORES = SAILPOINT / "fixtures" / "imported" / "2026-07-23-sterile-public-docs" / "scores.json"


def _agg(path):
    return json.loads(path.read_text())["aggregate"]


def _split_reference_pack():
    """Split the reference pack's tasks in half — any partition exercises the same machinery."""
    ids = sorted(_agg(NC_SCORES)["per_task"])
    half = len(ids) // 2
    groups = {
        "first": {"label": "First half", "rationale": "An arbitrary partition, for the test.",
                  "tasks": ids[:half]},
        "second": {"label": "Second half", "rationale": "The complement of the first.",
                   "tasks": ids[half:]},
    }
    mapping = {t: k for k, b in groups.items() for t in b["tasks"]}
    return ids, groups, mapping


# --- the rollup ------------------------------------------------------------ #

def test_rollup_by_group_partitions_the_tasks():
    ids, groups, mapping = _split_reference_pack()
    roll = rollup_by_group(_agg(NC_SCORES), mapping, list(groups))
    assert list(roll) == ["first", "second"], "groups render in declared order, not sorted"
    assert roll["first"]["tasks"] + roll["second"]["tasks"] == ids
    assert set(roll["first"]["dimensions"]) == set(DIMENSIONS)


def test_a_one_task_group_reproduces_that_task_exactly():
    """The known-good check: a group of one must be that task's own numbers, unaveraged."""
    agg = _agg(NC_SCORES)
    tid = sorted(agg["per_task"])[0]
    roll = rollup_by_group(agg, {tid: "solo"}, ["solo"])
    assert roll["solo"]["dimensions"] == {
        d: agg["per_task"][tid]["dimensions"].get(d) for d in DIMENSIONS}


def test_an_na_group_reports_its_reason_and_no_number():
    _, groups, mapping = _split_reference_pack()
    roll = rollup_by_group(_agg(NC_SCORES), mapping, list(groups),
                           na_groups={"second": "declared absent for this product"})
    assert roll["second"]["na"] is True
    assert roll["second"]["overall"] is None
    assert roll["second"]["na_reason"] == "declared absent for this product"
    assert roll["first"]["overall"] is not None, "the other group is unaffected"


def test_the_category_rollup_is_unchanged_by_the_extraction():
    """`rollup_by_category` became a wrapper; it must still produce byte-identical output."""
    agg = _agg(NC_SCORES)
    pack = Pack.load(SAILPOINT)
    task_to_cat = {tid: t["job_category"] for tid, t in pack.tasks_by_id().items()}
    from core.taxonomy import CATEGORIES
    assert rollup_by_category(agg, task_to_cat, pack.na_categories) == rollup_by_group(
        agg, task_to_cat, CATEGORIES, pack.na_categories)


# --- the renderer ---------------------------------------------------------- #

def test_group_comparison_renders_every_group_and_its_rationale():
    _, groups, mapping = _split_reference_pack()
    md = render_group_comparison_md(
        "no-context", rollup_by_group(_agg(NC_SCORES), mapping, list(groups)),
        "public-docs", rollup_by_group(_agg(PD_SCORES), mapping, list(groups)),
        groups)
    for block in groups.values():
        assert block["label"] in md
        assert block["rationale"] in md, "the rationale is the evidence a reviewer disagrees with"
    for d in DIMENSIONS:
        assert md.count("| overall |") + md.count("| **overall** |") >= 1
    assert "delta" in md


def test_the_rendered_group_number_is_the_one_the_rollup_computed():
    """The renderer must not re-derive anything — cycle 19's finding was hand-maintained numbers."""
    _, groups, mapping = _split_reference_pack()
    roll = rollup_by_group(_agg(NC_SCORES), mapping, list(groups))
    md = render_group_comparison_md("a", roll, "b", roll, groups)
    assert f"{roll['first']['overall'] * 100:.0f}%" in md


# --- the validator rules, each verified by breaking it --------------------- #

TASKS = ["alpha", "beta", "gamma"]
GOOD = {
    "old": {"label": "Old", "rationale": "shipped first", "tasks": ["alpha", "beta"]},
    "new": {"label": "New", "rationale": "shipped later", "tasks": ["gamma"]},
}


def test_a_well_formed_grouping_passes():
    assert validate_task_groups(GOOD, TASKS) == []


def test_no_declared_groups_is_not_an_error():
    """Groups are optional, so every existing pack keeps validating unchanged."""
    assert validate_task_groups(None, TASKS) == []
    assert validate_task_groups({}, TASKS) == []


def test_an_unknown_task_id_is_an_error():
    bad = {**GOOD, "new": {**GOOD["new"], "tasks": ["gamma", "nope"]}}
    assert any("unknown task 'nope'" in e for e in validate_task_groups(bad, TASKS))


def test_a_task_in_two_groups_is_an_error():
    """Double-counting would publish a group mean no reader could reconstruct."""
    bad = {**GOOD, "new": {**GOOD["new"], "tasks": ["beta", "gamma"]}}
    assert any("'beta' is in more than one group" in e for e in validate_task_groups(bad, TASKS))


def test_an_ungrouped_task_is_an_error():
    """Silently dropping a task is the direction that flatters — it lets a bad task vanish."""
    bad = {"old": {**GOOD["old"], "tasks": ["alpha"]}, "new": GOOD["new"]}
    errs = validate_task_groups(bad, TASKS)
    assert any("ungrouped: beta" in e for e in errs)


def test_an_empty_group_is_an_error():
    bad = {**GOOD, "empty": {"label": "Empty", "rationale": "why", "tasks": []}}
    assert any("lists no tasks" in e for e in validate_task_groups(bad, TASKS))


@pytest.mark.parametrize("rationale", [None, "", "   "])
def test_a_group_with_no_rationale_is_an_error(rationale):
    """Nothing in this repo can check that 'long-stable' is TRUE of a surface. The rationale is the
    only thing a reviewer can disagree with, so its absence blocks rather than draws a note."""
    bad = {**GOOD, "new": {**GOOD["new"], "rationale": rationale}}
    assert any("has no rationale" in e for e in validate_task_groups(bad, TASKS))


def test_pack_task_to_group_is_empty_when_nothing_is_declared():
    """Every already-published pack declares no groups, so this must be inert for all of them."""
    assert Pack.load(SAILPOINT).task_groups is None
    assert Pack.load(SAILPOINT).task_to_group() == {}
