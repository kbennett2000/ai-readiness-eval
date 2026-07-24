"""Tests for the side-by-side comparison report (core/report.py)."""
from core.report import (
    aggregate,
    render_comparison_md,
    render_delta_table_md,
    render_multi_comparison_md,
)
from core.scorer import DIMENSIONS


def _rec(task_id, endpoint, fmt=False):
    dims = {d: (1.0 if d == "endpoint" else None) for d in DIMENSIONS}
    dims["endpoint"] = endpoint
    return {"task_id": task_id, "format_failure": fmt,
            "dimensions": {} if fmt else dims}


def test_comparison_shows_deltas_and_rows():
    # condition A: endpoint 0.0 ; condition B: endpoint 1.0 -> +100 pts
    agg_a = aggregate([_rec("find-identity", 0.0), _rec("auth-token", 0.0)])
    agg_b = aggregate([_rec("find-identity", 1.0), _rec("auth-token", 1.0)])
    md = render_comparison_md("no-context", agg_a, {"condition": "no-context", "n": 3},
                              "public-docs", agg_b, {"condition": "public-docs", "n": 3})
    assert "no-context vs public-docs" in md
    assert "find-identity" in md and "auth-token" in md
    assert "+100 pts" in md  # endpoint dimension delta
    assert "## Per-task × per-dimension" in md


def test_comparison_counts_format_failures_per_condition():
    agg_a = aggregate([_rec("t", 1.0), _rec("t", None, fmt=True)])
    agg_b = aggregate([_rec("t", 1.0), _rec("t", 1.0)])
    md = render_comparison_md("A", agg_a, {"condition": "A"},
                              "B", agg_b, {"condition": "B"})
    assert "1/2" in md  # A had 1 format failure of 2 runs
    assert "0/2" in md  # B had none


def test_tri_comparison_columns_and_deltas():
    agg_nc = aggregate([_rec("find-identity", 0.4)])
    agg_pd = aggregate([_rec("find-identity", 0.3)])
    agg_mcp = aggregate([_rec("find-identity", 1.0)])
    entries = [
        ("no-context", agg_nc, {"condition": "no-context", "n": 5,
                                 "tool_discipline_summary": {"violations_logged": 0,
                                                             "runs_asserted": 5, "final_all_ok": True}}),
        ("public-docs", agg_pd, {"condition": "public-docs", "n": 5}),
        ("mcp", agg_mcp, {"condition": "mcp", "n": 5}),
    ]
    md = render_multi_comparison_md(entries, note="fresh N=5 tri-run")
    assert "no-context vs public-docs vs mcp" in md
    assert "fresh N=5 tri-run" in md
    # mcp (last) delta vs public-docs on the endpoint dimension: (1.0-0.3)*100 = +70
    assert "Δ(mcp−public-docs)" in md and "+70 pts" in md
    assert "Δ(mcp−no-context)" in md and "+60 pts" in md
    assert "tool discipline: 0 violation(s)" in md


def test_multi_comparison_handles_missing_task_in_one_condition():
    agg_a = aggregate([_rec("t1", 1.0)])
    agg_b = aggregate([_rec("t1", 1.0), _rec("t2", 0.5)])
    md = render_multi_comparison_md([("a", agg_a, {"condition": "a"}),
                                     ("b", agg_b, {"condition": "b"})])
    assert "t2" in md and "n/a" in md  # t2 absent from condition a -> n/a cell


def test_delta_table_matches_by_condition():
    # cycle-6 no-context endpoint 0.8; sterile no-context endpoint 0.5 -> -30 pts (crib sheet worth)
    base = [("no-context", aggregate([_rec("t", 0.8)]), {"condition": "no-context"})]
    new = [("no-context", aggregate([_rec("t", 0.5)]), {"condition": "no-context"})]
    md = render_delta_table_md(new, base)
    assert "Delta vs cycle-6" in md
    assert "-30 pts" in md  # sterile scored lower -> what CLAUDE.md was worth


def test_delta_table_marks_unmatched_condition_na():
    base = [("public-docs", aggregate([_rec("t", 0.8)]), {"condition": "public-docs"})]
    new = [("no-context", aggregate([_rec("t", 0.5)]), {"condition": "no-context"})]
    md = render_delta_table_md(new, base)
    assert "no-context" in md and "n/a" in md  # no cycle-6 no-context to match
