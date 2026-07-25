"""A mock answer may never stand in for a measured one.

`run --mock` writes its per-condition runs into the same date-stamped results directory a real grid
uses — only the mock *preflight* gets a directory of its own. The runner is resumable, so before this
guard the documented dry-run sequence (`factory next --provider mock`, then
`factory next --model <id>` on the same day) resumed straight off the mock answers and reported them
as measured, under a metadata block naming the real model.

These tests pin both halves: the stamp that makes a mock archive recognizable, and the refusal that
uses it. The refusal is unit-tested through `may_reuse_archived_run` rather than by driving a real
grid, because a real grid needs a live model; what an end-to-end test can prove without one — that a
mock run stamps every archive, and that a second mock run still resumes normally — is proved below.
"""
import json
from pathlib import Path

import pytest

from core.__main__ import main, may_reuse_archived_run

ACME = str(Path(__file__).resolve().parent / "fixtures" / "pack-acme")


# --------------------------------------------------------------------------- #
# The decision.
# --------------------------------------------------------------------------- #

def test_a_mock_archive_is_refused_by_a_real_run():
    reusable, why = may_reuse_archived_run({"mock": True}, is_mock=False)
    assert reusable is False
    assert "mock" in why


def test_a_real_archive_is_refused_by_a_mock_run():
    """The converse matters too: a mock dry-run that silently reused real answers would report a
    plumbing proof it never actually performed."""
    reusable, why = may_reuse_archived_run({}, is_mock=True)
    assert reusable is False
    assert "real" in why


@pytest.mark.parametrize("prev,is_mock", [
    ({}, False),                 # every archive written before the stamp existed
    ({"mock": True}, True),      # mock resuming its own dry-run
])
def test_matching_provenance_is_reused(prev, is_mock):
    reusable, why = may_reuse_archived_run(prev, is_mock=is_mock)
    assert reusable is True
    assert why == ""


def test_absence_of_the_stamp_means_real_so_no_committed_archive_is_invalidated():
    """The stamp is written only on mock runs. If absence meant "unknown" instead of "real", every
    archived result in every pack would be re-run on the next resume — at full model cost — and the
    frozen regression fixtures would stop reproducing."""
    assert may_reuse_archived_run({"tool_discipline": {"ok": True}}, is_mock=False)[0] is True


def test_discipline_failure_still_forces_a_re_run():
    """The pre-existing half of the rule, kept explicit so a future edit cannot drop it while
    keeping the provenance check."""
    prev = {"tool_discipline": {"ok": False}}
    reusable, why = may_reuse_archived_run(prev, is_mock=False)
    assert reusable is False
    assert "discipline" in why


def test_a_disciplined_mock_archive_is_still_refused_by_a_real_run():
    """Provenance is checked independently of discipline — a mock run passes the discipline
    assertion trivially, so a rule that checked only discipline would let it through."""
    prev = {"mock": True, "tool_discipline": {"ok": True}}
    assert may_reuse_archived_run(prev, is_mock=False)[0] is False


# --------------------------------------------------------------------------- #
# The stamp, end to end.
# --------------------------------------------------------------------------- #

def test_a_mock_run_stamps_every_archived_run(tmp_path):
    out = tmp_path / "mockrun"
    assert main(["--pack", ACME, "run", "--condition", "no-context", "--mock",
                 "--n", "1", "--out", str(out)]) == 0
    archived = sorted((out / "runs").glob("*.json"))
    assert archived, "mock run wrote no archives"
    for path in archived:
        assert json.loads(path.read_text()).get("mock") is True, f"{path.name} carries no mock stamp"


def test_a_second_mock_run_still_resumes(tmp_path, capsys):
    """Matching provenance must not break resumability — the guard refuses mismatches, not repeats."""
    out = tmp_path / "mockrun"
    main(["--pack", ACME, "run", "--condition", "no-context", "--mock", "--n", "1", "--out", str(out)])
    capsys.readouterr()
    main(["--pack", ACME, "run", "--condition", "no-context", "--mock", "--n", "1", "--out", str(out)])
    printed = capsys.readouterr().out
    assert "reused (archived)" in printed
    assert "re-running" not in printed
    assert json.loads((out / "scores.json").read_text())["metadata"]["reused_runs"] > 0
