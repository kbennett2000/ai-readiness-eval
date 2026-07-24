"""Tests for the mcp consultation/skip-rate analysis (core/analyze.py).

The consulted-tool prefix is pack-supplied; core hardcodes none. Uses `mcp__acme__` here.
"""
import json

from core.analyze import consultation_rates, format_consultation

PREFIX = "mcp__acme__"


def _write_run(runs_dir, task_id, idx, tool_names):
    rec = {"task_id": task_id, "run_index": idx,
           "tool_uses": [{"name": n} for n in tool_names]}
    (runs_dir / f"{task_id}-run{idx}.json").write_text(json.dumps(rec))


def test_consultation_counts_layer_calls(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    # widget-list: 1 consulted, 2 skipped (ToolSearch alone is not consultation)
    _write_run(runs, "widget-list", 0, ["ToolSearch", f"{PREFIX}get_auth_guide"])
    _write_run(runs, "widget-list", 1, [])
    _write_run(runs, "widget-list", 2, ["ToolSearch"])
    # gadget-fetch: 2 consulted
    _write_run(runs, "gadget-fetch", 0, ["ToolSearch", f"{PREFIX}search_operations"])
    _write_run(runs, "gadget-fetch", 1, [f"{PREFIX}get_operation"])

    rates = consultation_rates(tmp_path, PREFIX)
    assert rates["widget-list"] == {"runs": 3, "consulted": 1, "skipped": 2, "skip_rate": 0.667}
    assert rates["gadget-fetch"]["skipped"] == 0
    assert rates["_overall"]["runs"] == 5 and rates["_overall"]["consulted"] == 3
    out = format_consultation(rates)
    assert "widget-list" in out and "ALL" in out
