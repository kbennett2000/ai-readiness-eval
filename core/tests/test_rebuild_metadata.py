"""A rebuild must not delete a disclosure it cannot recompute (ADR-0032, ADR-0033).

`rebuild_report` assembles metadata from a whitelist, which is the right shape — a rebuild genuinely
cannot reconstruct `cli_policy` or `tool_discipline_summary`, and ADR-0002 pins that those are
dropped. But two keys were being dropped that are not run-provenance at all:

  * `format_failure_threshold` — ADR-0032 states it is written "whether or not it fired", so that a
    grid published past a high failure rate is a decision on the permanent record.
  * `stopped_early` — the record that a grid is deliberately partial.

Neither is recomputable from the run records, so a rebuild that dropped them destroyed the only copy.
Found when a pack's two archives lost the threshold to an ADR-0024 re-score.
"""
import json

import pytest

from core.pack import Pack
from core.rebuild import rebuild_report
from core.tests.test_e2e import ACME  # the fixture pack used by the end-to-end run


def _archive(tmp_path, extra_metadata: dict):
    """A minimal but real archive: one run record plus a scores.json carrying `extra_metadata`."""
    d = tmp_path / "2026-01-01-no-context"
    (d / "runs").mkdir(parents=True)
    rec = {
        "task_id": "widget-list", "run_index": 0,
        "format_failure": True, "failure_reason": "no answer block", "dimensions": {},
        "endpoint_matches": [], "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0,
        "duration_ms": 1, "tool_uses": [], "transcript": [], "raw_response": "nothing parseable",
    }
    (d / "runs" / "widget-list-run0.json").write_text(json.dumps(rec, indent=2))
    (d / "scores.json").write_text(json.dumps(
        {"metadata": {"condition": "no-context", "model": "m", **extra_metadata},
         "aggregate": {}, "runs": [rec]}, indent=2, sort_keys=True))
    return d


@pytest.mark.parametrize("key,value", [
    ("format_failure_threshold", 0.2),
    ("format_failure_threshold", 1.0),
    ("stopped_early", "12/20 runs (60%) failed to produce a parseable answer block"),
])
def test_a_rebuild_carries_the_disclosure_forward(tmp_path, key, value):
    d = _archive(tmp_path, {key: value})
    rebuild_report(d, Pack.load(ACME))
    meta = json.loads((d / "scores.json").read_text())["metadata"]
    assert meta.get(key) == value, f"{key} was dropped by the rebuild"


def test_a_rebuild_does_not_invent_a_disclosure_that_was_never_recorded(tmp_path):
    """The converse, and the reason the carry-forward is conditional. Writing a default threshold
    into an archive that predates the breaker would assert that a value was in force when none was."""
    d = _archive(tmp_path, {})
    rebuild_report(d, Pack.load(ACME))
    meta = json.loads((d / "scores.json").read_text())["metadata"]
    assert "format_failure_threshold" not in meta
    assert "stopped_early" not in meta


def test_the_documented_provenance_drops_still_drop(tmp_path):
    """ADR-0002's pinned behaviour must not be widened by accident: a rebuild genuinely cannot
    reconstruct these, and the regression gate asserts they are absent."""
    d = _archive(tmp_path, {"cli_policy": {"x": 1}, "tool_discipline_summary": {"y": 2},
                            "reused_runs": 3})
    rebuild_report(d, Pack.load(ACME))
    meta = json.loads((d / "scores.json").read_text())["metadata"]
    for dropped in ("cli_policy", "tool_discipline_summary", "reused_runs"):
        assert dropped not in meta
