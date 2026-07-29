"""The one imported record that ADR-0033 regenerated, pinned field by field.

`fixtures/imported/` is a byte-for-byte import from the frozen sailpoint-proof-of-concept repo, and
PROVENANCE.md said so. That claim is now narrower: ADR-0033 regenerated the scorer-derived fields of
exactly one run record, because it disagreed with the `scores.json` sitting beside it — the ADR-0014
repair had been applied to the report and never to the record.

This pins that edit precisely, so the anchor cannot drift again quietly. Two directions are asserted:

  * what changed, and to exactly what — a re-import from upstream, or a second regeneration, fires;
  * what did NOT change — the raw evidence the frozen 73/68/93 table is computed from. `rebuild_report`
    re-parses `raw_response`, so as long as that byte string is untouched the frozen numbers cannot
    move, and this is the assertion that makes "cannot" a checked property rather than an argument.
"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "imported"
CONDITION = FIXTURES / "2026-07-23-sterile-mcp"
RECORD = CONDITION / "runs" / "access-request-run3.json"

# The regenerated record's derived fields, as ADR-0033 left them. Every value here came out of the
# committed scores.json, which is why the published table is unmoved by the edit.
REGENERATED = {
    "format_failure": False,
    "failure_reason": None,
    "dimensions": {"api_version": 1.0, "auth_flow": 1.0, "endpoint": 1.0,
                   "key_parameters": 1.0, "method": 1.0, "required_scopes": 1.0},
    "endpoint_matches": [{"answer_api_version": "v3", "answer_method": "POST",
                          "answer_path": "/access-requests", "gt_api_version": "v3",
                          "gt_method": "POST", "gt_path": "/access-requests",
                          "matched": True, "method_ok": True, "version_ok": True}],
    "format_repaired": True,
}

# The transport-derived fields of the same record, pinned by value where they are short and by digest
# where they are the transcript. Nothing in ADR-0033 may touch these.
EVIDENCE = {"input_tokens": 13, "output_tokens": 1575, "cost_usd": 0.09024399999999999,
            "duration_ms": 32693}
RAW_RESPONSE_SHA256 = "a5fd6be1e8f0b0ea23c9f87e955605e210829448709505472c0bf65b3e8e2736"


@pytest.fixture(scope="module")
def record() -> dict:
    return json.loads(RECORD.read_text())


def test_the_regenerated_record_is_exactly_as_pinned(record):
    for field, want in REGENERATED.items():
        assert record[field] == want, field


def test_the_repaired_block_is_the_adr_0014_flow_sequence(record):
    """The repair's own subject: an indexed parameter inside a single-line flow sequence, which is the
    shape the prompt contract's example demonstrates and the YAML parser rejects."""
    assert "requestedItems[].type" in record["repaired_block_text"]
    assert record["repaired_block_text"].startswith("endpoints:")


def test_the_record_now_agrees_with_the_report_beside_it(record):
    published = json.loads((CONDITION / "scores.json").read_text())["runs"]
    entry = next(r for r in published
                 if r["task_id"] == "access-request" and r["run_index"] == 3)
    for field in (*REGENERATED, "repaired_block_text"):
        assert record[field] == entry[field], field


def test_the_raw_evidence_was_not_touched(record):
    """The claim that lets the frozen table stay frozen. `rebuild_report` re-parses `raw_response`, so
    an unchanged response provably reproduces an unchanged score."""
    import hashlib

    for field, want in EVIDENCE.items():
        assert record[field] == want, field
    digest = hashlib.sha256(record["raw_response"].encode()).hexdigest()
    assert digest == RAW_RESPONSE_SHA256, "the archived model response itself changed"
    assert record["tool_discipline"] == {"ok": True, "detail": "only sailpoint tools (2 call(s))",
                                         "attempts": 1}


def test_no_other_imported_record_was_regenerated():
    """The edit was one record. If a future change quietly widened it, the count moves here first."""
    from core.archive import reconcile_runs

    dirty = []
    for cond in sorted(FIXTURES.glob("*/scores.json")):
        report = reconcile_runs(cond.parent, write=False)
        assert report.ok, "; ".join(report.problems)
        dirty += list(report.changed)
    assert dirty == [], f"imported record(s) out of step with their report: {dirty}"


def test_the_provenance_note_records_the_regeneration():
    """A provenance claim is a published claim. If the import is no longer byte-identical to upstream,
    the file that asserts it must say so — and this fires if someone edits that disclosure away."""
    text = (FIXTURES / "PROVENANCE.md").read_text()
    assert "ADR-0033" in text
    assert "access-request-run3" in text
    assert "no longer byte-identical" in text
