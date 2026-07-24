"""Tests for the category rollup + cross-vendor comparison renderer (ADR-0004).

The reference pack's 1:1 task↔category map (ADR-0003) is the known-good check: rolling its per-task
aggregate up to per-category numbers must reproduce each task's numbers under its category label.
"""
import json
from pathlib import Path
from statistics import mean

from core.category import rollup_by_category, render_cross_vendor_category_md
from core.pack import Pack
from core.scorer import DIMENSIONS
from core.taxonomy import CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[2]
SAILPOINT = REPO_ROOT / "packs" / "sailpoint"
NC_SCORES = SAILPOINT / "fixtures" / "imported" / "2026-07-23-sterile-no-context" / "scores.json"


def _sailpoint_rollup():
    agg = json.loads(NC_SCORES.read_text())["aggregate"]
    pack = Pack.load(SAILPOINT)
    task_to_cat = {tid: t["job_category"] for tid, t in pack.tasks_by_id().items()}
    return agg, task_to_cat, rollup_by_category(agg, task_to_cat, pack.na_categories)


def test_rollup_covers_all_canonical_categories():
    _, _, roll = _sailpoint_rollup()
    assert set(roll.keys()) == set(CATEGORIES)
    # The reference pack declares no N/A categories, so every category has exactly one task.
    assert all(not roll[c]["na"] for c in CATEGORIES)
    assert all(len(roll[c]["tasks"]) == 1 for c in CATEGORIES)


def test_one_to_one_rollup_reproduces_per_task_numbers():
    agg, task_to_cat, roll = _sailpoint_rollup()
    cat_to_task = {cat: tid for tid, cat in task_to_cat.items()}
    for cat in CATEGORIES:
        tid = cat_to_task[cat]
        task_dims = agg["per_task"][tid]["dimensions"]
        for d in DIMENSIONS:
            assert roll[cat]["dimensions"][d] == task_dims[d], f"{cat}/{d}"
        applicable = [v for v in task_dims.values() if v is not None]
        assert roll[cat]["overall"] == (mean(applicable) if applicable else None)


def test_multi_task_category_is_mean_of_task_means():
    # Two tasks mapped to one category -> that category's dimension is the mean of the two task means.
    agg = {
        "per_task": {
            "t1": {"dimensions": {d: 1.0 for d in DIMENSIONS}},
            "t2": {"dimensions": {d: 0.0 for d in DIMENSIONS}},
        }
    }
    roll = rollup_by_category(agg, {"t1": "find-principal", "t2": "find-principal"})
    assert roll["find-principal"]["dimensions"]["endpoint"] == 0.5
    assert roll["find-principal"]["overall"] == 0.5
    assert sorted(roll["find-principal"]["tasks"]) == ["t1", "t2"]


def test_none_dimension_excluded_from_category_mean():
    agg = {
        "per_task": {
            "t1": {"dimensions": {**{d: 1.0 for d in DIMENSIONS}, "required_scopes": None}},
            "t2": {"dimensions": {**{d: 0.0 for d in DIMENSIONS}, "required_scopes": 0.4}},
        }
    }
    roll = rollup_by_category(agg, {"t1": "grant-access", "t2": "grant-access"})
    # required_scopes: only t2 contributes -> 0.4, not (None+0.4) averaged.
    assert roll["grant-access"]["dimensions"]["required_scopes"] == 0.4


def test_na_category_renders_and_carries_reason():
    agg = {"per_task": {"t1": {"dimensions": {d: 1.0 for d in DIMENSIONS}}}}
    roll = rollup_by_category(
        agg, {"t1": "find-principal"},
        na_categories={"connect-source": "agent-based, not an API operation"},
    )
    assert roll["connect-source"]["na"] is True
    assert roll["connect-source"]["overall"] is None
    assert roll["connect-source"]["na_reason"] == "agent-based, not an API operation"
    assert roll["find-principal"]["na"] is False


def test_renderer_emits_all_categories_and_labels():
    _, _, roll = _sailpoint_rollup()
    other = rollup_by_category(
        {"per_task": {"x": {"dimensions": {d: 0.5 for d in DIMENSIONS}}}},
        {"x": "authenticate"},
        na_categories={"connect-source": "n/a here"},
    )
    md = render_cross_vendor_category_md([("Reference", roll), ("Other", other)])
    for cat in CATEGORIES:
        assert f"| {cat} |" in md
    assert "| category | Reference | Other |" in md
    # The N/A category renders n/a for the source that declares it.
    connect_row = [ln for ln in md.splitlines() if ln.startswith("| connect-source |")][0]
    assert connect_row.count("n/a") >= 1


def test_renderer_single_dimension_mode():
    _, _, roll = _sailpoint_rollup()
    md = render_cross_vendor_category_md([("Reference", roll)], dimension="auth_flow")
    assert "auth_flow" in md.splitlines()[0]
