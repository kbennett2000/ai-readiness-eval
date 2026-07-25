"""End-to-end tests with a mocked model — no live API calls.

Exercises the full path: response text -> parse -> score -> record -> report, and the real CLI
`run --mock` over the synthetic pack's tasks. Asserts summary.md/scores.json render and that format
failures are counted as their own category.
"""
import json
from pathlib import Path

from core import answer_block, report
from core.__main__ import main
from core.pack import Pack
from core.scorer import DIMENSIONS, format_failure_score, score_task

ACME = str(Path(__file__).resolve().parent / "fixtures" / "pack-acme")


PERFECT = """\
```answer-summary
endpoints:
  - method: GET
    path: /v3/widgets
    api_version: v3
auth_flow: OAuth2 bearer token
required_scopes: [widgets:read]
key_parameters: [filters]
```
"""

WRONG_PATH = """\
```answer-summary
endpoints:
  - method: GET
    path: /v3/gizmos
    api_version: v3
auth_flow: OAuth2 bearer token
required_scopes: [widgets:read]
key_parameters: [filters]
```
"""

NO_BLOCK = "You'd call the widgets endpoint, but here's no structured block."


def _task():
    return {
        "id": "widget-list",
        "ground_truth": {
            "endpoints": [{"method": "GET", "path": "/v3/widgets", "api_version": "v3"}],
            "auth_flow": "OAuth2 bearer token",
            "required_scopes": ["widgets:read"],
            "key_parameters": [{"name": "filters", "in": "query", "required": True}],
        },
    }


def _record_from(task, run_index, text):
    parsed = answer_block.parse(text)
    if parsed.is_failure:
        s = format_failure_score(task["id"], parsed.failure.reason)
    else:
        s = score_task(task, parsed.summary)
    dims = {d: (s.dim(d).score if s.dim(d) else None) for d in DIMENSIONS}
    rec = {
        "task_id": task["id"],
        "run_index": run_index,
        "format_failure": s.format_failure,
        "failure_reason": s.failure_reason,
        "dimensions": dims,
        "endpoint_matches": s.endpoint_matches,
        "raw_response": text,
    }
    if parsed.repaired:  # mirrors the runner (ADR-0014)
        rec["format_repaired"] = True
    return rec


def test_three_run_mix_reports_correctly(tmp_path):
    task = _task()
    records = [
        _record_from(task, 0, PERFECT),
        _record_from(task, 1, WRONG_PATH),
        _record_from(task, 2, NO_BLOCK),
    ]
    agg = report.write_reports(tmp_path, records, {"condition": "no-context", "model": "mock",
                                                   "date": "2026-07-21", "spec_sha": "abc",
                                                   "temperature": 0.0, "n": 3})
    # one of three runs was a format failure
    assert agg["format_failures"] == 1
    assert agg["total_runs"] == 3
    # endpoint dimension: perfect=1.0, wrong=0.0 (format-failure run excluded) -> mean 0.5
    assert agg["per_task"]["widget-list"]["dimensions"]["endpoint"] == 0.5
    # files exist and parse
    assert (tmp_path / "summary.md").exists()
    scores = json.loads((tmp_path / "scores.json").read_text())
    assert scores["aggregate"]["format_failures"] == 1
    summary = (tmp_path / "summary.md").read_text()
    assert "1 of 3 runs" in summary
    assert "widget-list" in summary


def test_format_failures_excluded_from_means_not_zeroed(tmp_path):
    task = _task()
    # two perfect, one format failure -> endpoint mean should be 1.0, not 0.66
    records = [
        _record_from(task, 0, PERFECT),
        _record_from(task, 1, PERFECT),
        _record_from(task, 2, NO_BLOCK),
    ]
    agg = report.aggregate(records)
    assert agg["per_task"]["widget-list"]["dimensions"]["endpoint"] == 1.0
    assert agg["format_failures"] == 1


def test_cli_run_mock_over_real_tasks(tmp_path):
    out = tmp_path / "mockrun"
    rc = main(["--pack", ACME, "run", "--condition", "no-context", "--mock",
               "--n", "1", "--out", str(out)])
    assert rc == 0
    assert (out / "summary.md").exists()
    scores = json.loads((out / "scores.json").read_text())
    # _build_mock_responses deliberately breaks the last task -> at least one fmt failure
    assert scores["aggregate"]["format_failures"] >= 1
    # every task got a raw archive
    n_tasks = len(Pack.load(ACME).load_tasks())
    archived = list((out / "runs").glob("*.json"))
    assert len(archived) == n_tasks
    # metadata carries model/date/spec_sha
    md = scores["metadata"]
    assert md["condition"] == "no-context"
    assert md["spec_sha"]
    assert md["mock"] is True


def test_api_provider_blocked_without_key(tmp_path, monkeypatch):
    # --provider api with no API key -> BLOCKED exit code, no crash, no CLI call.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("core.__main__.get_config", lambda: (None, "claude-sonnet-4-6"))
    rc = main(["--pack", ACME, "run", "--condition", "no-context", "--provider", "api",
               "--n", "1", "--out", str(tmp_path / "x")])
    assert rc == 3


# --- ADR-0014: the repair counter is reported, never absorbed ---------------

REPAIRED = """\
```answer-summary
endpoints:
  - method: GET
    path: /v3/widgets
    api_version: v3
auth_flow: OAuth2 bearer token
required_scopes: [widgets:read]
key_parameters: [filters, sortBy[0].name]
```
"""


def test_format_repairs_are_counted_and_always_reported(tmp_path):
    task = _task()
    records = [
        _record_from(task, 0, PERFECT),
        _record_from(task, 1, REPAIRED),
    ]
    # The repair fires through the real parse path, not a hand-set flag.
    assert records[1]["format_repaired"] is True
    assert "format_repaired" not in records[0]

    agg = report.aggregate(records)
    assert agg["format_repairs"] == 1
    assert agg["per_task"]["widget-list"]["format_repairs"] == 1
    # A repaired run is SCORED, not counted a failure.
    assert agg["format_failures"] == 0
    assert agg["total_runs"] == 2

    out = tmp_path / "rep"
    report.write_reports(out, records, {"condition": "no-context"})
    summary = (out / "summary.md").read_text()
    assert "**format repairs (ADR-0014):** 1" in summary


def test_the_repair_counter_is_present_even_when_zero():
    """A reader must be able to tell 'nothing needed repair' from 'this report
    predates the counter'."""
    agg = report.aggregate([_record_from(_task(), 0, PERFECT)])
    assert agg["format_repairs"] == 0
    assert agg["per_task"]["widget-list"]["format_repairs"] == 0
