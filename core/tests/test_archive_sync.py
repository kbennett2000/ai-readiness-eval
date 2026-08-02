"""The run-record sync: what it writes, and what it refuses to write (ADR-0033).

The whole safety argument for this module is that it never rewrites raw evidence — it copies scorer
output out of a report and into the records that report was built from. So the tests that matter most
are the refusals: a transport-derived field that disagrees must abort the directory untouched, because
that disagreement means something has gone wrong that a sync cannot fix.
"""
import json
from pathlib import Path

import pytest

from core.archive import DERIVED_FIELDS, TRANSPORT_FIELDS, format_report, reconcile_runs


def _rec(task_id="alpha", run_index=0, **over) -> dict:
    rec = {
        "task_id": task_id,
        "run_index": run_index,
        "format_failure": False,
        "failure_reason": None,
        "dimensions": {"endpoint": 1.0, "method": 1.0, "api_version": 1.0,
                       "auth_flow": 1.0, "required_scopes": 1.0, "key_parameters": 1.0},
        "endpoint_matches": [{"matched": True}],
        "input_tokens": 10,
        "output_tokens": 20,
        "cost_usd": 0.01,
        "duration_ms": 1234,
        "tool_uses": [],
        "transcript": [{"role": "assistant", "text": "hi"}],
        "raw_response": "the model said this",
        "tool_discipline": {"ok": True, "detail": "none", "attempts": 1},
    }
    rec.update(over)
    return rec


def _dir(tmp_path: Path, runs: list[dict], published: list[dict] | None = None) -> Path:
    d = tmp_path / "2026-01-01-no-context"
    (d / "runs").mkdir(parents=True)
    for r in runs:
        (d / "runs" / f"{r['task_id']}-run{r['run_index']}.json").write_text(json.dumps(r, indent=2))
    (d / "scores.json").write_text(json.dumps(
        {"metadata": {}, "aggregate": {}, "runs": published if published is not None else runs},
        indent=2, sort_keys=True))
    return d


# --- the happy path -------------------------------------------------------- #

def test_a_directory_that_already_agrees_is_not_written(tmp_path):
    d = _dir(tmp_path, [_rec()])
    before = (d / "runs" / "alpha-run0.json").read_bytes()
    res = reconcile_runs(d)
    assert res.ok and not res.changed and not res.written and res.checked == 1
    assert (d / "runs" / "alpha-run0.json").read_bytes() == before


def test_a_stale_derived_field_is_synced_from_the_report(tmp_path):
    stale = _rec(dimensions={"endpoint": 0.0, "method": 1.0, "api_version": 1.0,
                             "auth_flow": 1.0, "required_scopes": 1.0, "key_parameters": 1.0})
    d = _dir(tmp_path, [stale], published=[_rec()])
    res = reconcile_runs(d)
    assert res.ok and res.written
    assert res.changed == {"alpha-run0": ["dimensions"]}
    written = json.loads((d / "runs" / "alpha-run0.json").read_text())
    assert written["dimensions"]["endpoint"] == 1.0


def test_a_conditional_field_present_only_in_the_report_is_added(tmp_path):
    """The ADR-0014 repair shape: the report says repaired, the record has never heard of it."""
    d = _dir(tmp_path, [_rec()],
             published=[_rec(format_repaired=True, repaired_block_text="endpoints:\n  - x")])
    res = reconcile_runs(d)
    assert res.changed == {"alpha-run0": ["format_repaired", "repaired_block_text"]}
    written = json.loads((d / "runs" / "alpha-run0.json").read_text())
    assert written["format_repaired"] is True


def test_a_conditional_field_the_report_dropped_is_removed_not_left_behind(tmp_path):
    """A repair that no longer fires must clear the flag. Leaving it is a stale `true` that nothing
    could ever clear — the failure `rebuild.py` already guards against inside scores.json."""
    d = _dir(tmp_path, [_rec(format_repaired=True, repaired_block_text="old")], published=[_rec()])
    res = reconcile_runs(d)
    assert res.changed == {"alpha-run0": ["format_repaired", "repaired_block_text"]}
    written = json.loads((d / "runs" / "alpha-run0.json").read_text())
    assert "format_repaired" not in written and "repaired_block_text" not in written


def test_the_sync_is_idempotent(tmp_path):
    d = _dir(tmp_path, [_rec(format_failure=True)], published=[_rec()])
    assert reconcile_runs(d).changed
    assert reconcile_runs(d).changed == {}


def test_scores_json_is_never_written(tmp_path):
    """The structural guarantee that no published number can move. If this file is opened for
    writing at all, the guarantee is a claim rather than a property."""
    d = _dir(tmp_path, [_rec(format_failure=True)], published=[_rec()])
    before = (d / "scores.json").read_bytes()
    reconcile_runs(d)
    assert (d / "scores.json").read_bytes() == before


def test_check_mode_reports_without_writing(tmp_path):
    d = _dir(tmp_path, [_rec(format_failure=True)], published=[_rec()])
    before = (d / "runs" / "alpha-run0.json").read_bytes()
    res = reconcile_runs(d, write=False)
    assert res.changed and not res.written
    assert (d / "runs" / "alpha-run0.json").read_bytes() == before


# --- the refusals ---------------------------------------------------------- #

@pytest.mark.parametrize("field", TRANSPORT_FIELDS)
def test_a_disagreeing_transport_field_aborts_the_directory_untouched(tmp_path, field):
    """The load-bearing refusal, tested over EVERY transport field rather than a representative one.

    A run record whose raw evidence differs from the report's copy is not a stale score — it is two
    records of different events. Syncing would overwrite a real score with one computed from a
    different response, which is the exact class of harm this module exists to avoid.
    """
    altered = {"raw_response": "a DIFFERENT response", "transcript": [{"role": "user"}],
               "tool_uses": ["surprise"], "tool_discipline": {"ok": False}, "input_tokens": 999,
               "output_tokens": 999, "cost_usd": 9.99, "duration_ms": 1, "mock": True}[field]
    # Stale in a derived field too, so an abort is distinguishable from "nothing to do".
    d = _dir(tmp_path, [_rec(format_failure=True, **{field: altered})], published=[_rec()])
    before = (d / "runs" / "alpha-run0.json").read_bytes()

    res = reconcile_runs(d)
    assert not res.ok, f"{field} disagreed and the sync did not refuse"
    assert field in res.problems[0] and "left untouched" in res.problems[0]
    assert (d / "runs" / "alpha-run0.json").read_bytes() == before


def test_the_transport_guard_is_not_vacuous(tmp_path):
    """The parametrization above substitutes a value into each field; if any substitution were a
    no-op the test would pass while proving nothing. This is the same value-set, asserted different."""
    base = _rec()
    altered = {"raw_response": "a DIFFERENT response", "transcript": [{"role": "user"}],
               "tool_uses": ["surprise"], "tool_discipline": {"ok": False}, "input_tokens": 999,
               "output_tokens": 999, "cost_usd": 9.99, "duration_ms": 1, "mock": True}
    assert set(altered) == set(TRANSPORT_FIELDS)
    for field, value in altered.items():
        assert base.get(field) != value, f"substituting {field} changes nothing"


def test_a_run_file_with_no_entry_in_the_report_aborts(tmp_path):
    d = _dir(tmp_path, [_rec(), _rec(run_index=1)], published=[_rec()])
    res = reconcile_runs(d)
    assert not res.ok and "run file(s) but" in res.problems[0]


def test_a_report_entry_with_no_run_file_aborts(tmp_path):
    d = _dir(tmp_path, [_rec()], published=[_rec(), _rec(run_index=1)])
    res = reconcile_runs(d)
    assert not res.ok and "run file(s) but" in res.problems[0]


def test_a_report_with_two_entries_for_one_run_aborts(tmp_path):
    d = _dir(tmp_path, [_rec(), _rec(run_index=1)], published=[_rec(), _rec()])
    res = reconcile_runs(d)
    assert not res.ok and "two entries" in res.problems[0]


def test_a_missing_scores_json_is_reported_not_raised(tmp_path):
    d = tmp_path / "2026-01-01-no-context"
    (d / "runs").mkdir(parents=True)
    assert not reconcile_runs(d).ok


def test_unreadable_json_is_reported_not_raised(tmp_path):
    d = _dir(tmp_path, [_rec()])
    (d / "scores.json").write_text("{not json")
    res = reconcile_runs(d)
    assert not res.ok and "unreadable" in res.problems[0]


def test_a_report_with_no_runs_array_is_reported(tmp_path):
    d = _dir(tmp_path, [_rec()])
    (d / "scores.json").write_text(json.dumps({"metadata": {}, "aggregate": {}}))
    res = reconcile_runs(d)
    assert not res.ok and "no `runs` array" in res.problems[0]


# --- the field lists themselves -------------------------------------------- #

def test_the_two_field_lists_do_not_overlap(tmp_path):
    """A field in both lists would be checked as evidence and written as a score — the contradiction
    that would let the sync overwrite the very thing it promises never to touch."""
    assert not set(DERIVED_FIELDS) & set(TRANSPORT_FIELDS)


def test_every_field_a_live_run_writes_is_classified():
    """`_record` in core/__main__.py is where a run record's shape is decided. A field added there
    and to neither list would be silently unprotected AND never synced."""
    from core.__main__ import _record

    class _Resp:
        text, input_tokens, output_tokens = "x", 1, 2
        cost_usd, duration_ms, tool_uses, transcript = 0.0, 0, [], []

    class _Score:
        format_failure, failure_reason, endpoint_matches = False, None, []
        # ADR-0044. Non-empty on purpose: the field is written CONDITIONALLY, so a stub that left it
        # empty would exercise the branch where it never appears and this guard would pass without
        # ever seeing it — which is the whole failure mode the guard exists to catch.
        exhibit = {"publication": "ABC-XX001"}

        def dim(self, _d):
            return None

    class _Parsed:
        repaired, repaired_block_text = True, "block"

    rec = _record("alpha", 0, _Score(), _Resp(), tool_discipline={"ok": True},
                  parsed=_Parsed(), mock=True)
    identity = {"task_id", "run_index"}
    unclassified = set(rec) - set(DERIVED_FIELDS) - set(TRANSPORT_FIELDS) - identity
    assert not unclassified, f"unclassified run-record field(s): {sorted(unclassified)}"


def test_the_report_names_the_directory_and_counts_problems(tmp_path):
    good = _dir(tmp_path / "a", [_rec()])
    bad = _dir(tmp_path / "b", [_rec()], published=[_rec(raw_response="different")])
    text, problems = format_report([reconcile_runs(good), reconcile_runs(bad)])
    assert problems == 1
    assert "already agree" in text and "BLOCKED" in text
