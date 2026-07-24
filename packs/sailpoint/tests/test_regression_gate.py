"""The regression gate (ADR-0002) — the point of cycle 1.

Re-scoring the imported SailPoint archives through the extracted, vendor-agnostic core MUST reproduce
the frozen repo's canonical tables EXACTLY: overall 73 / 68 / 93 and every per-task, per-dimension
cell. The only permitted byte-differences are the documented run-provenance metadata class (AUDIT.md
§2). If any score-bearing cell moves, that is an extraction bug — this test fails loudly.

Run just this gate:

    pytest packs/sailpoint/tests/test_regression_gate.py
    # or, by marker, across the repo:
    pytest -m regression
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.pack import Pack
from core.rebuild import rebuild_report
from core.report import aggregate, render_multi_comparison_md

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_DIR = REPO_ROOT / "packs" / "sailpoint"
FIXTURES = PACK_DIR / "fixtures" / "imported"

# The frozen headline, per condition.
EXPECTED_OVERALL = {"no-context": 73, "public-docs": 68, "mcp": 93}
CONDITIONS = ["no-context", "public-docs", "mcp"]

# The documented run-provenance metadata class: the ONLY metadata allowed to differ on a rebuild.
METADATA_DROPPED_ON_REBUILD = {"cli_policy", "tool_discipline_summary", "reused_runs"}
METADATA_ADDED_ON_REBUILD = {"rebuilt_from_runs"}


def _fixture_dir(cond: str) -> Path:
    return FIXTURES / f"2026-07-23-sterile-{cond}"


@pytest.fixture(scope="module")
def pack() -> Pack:
    return Pack.load(PACK_DIR)


@pytest.fixture(scope="module")
def rebuilt(pack, tmp_path_factory) -> dict:
    """Re-score each imported archive into an isolated temp copy; return {cond: rebuilt scores.json}."""
    out: dict[str, dict] = {}
    for cond in CONDITIONS:
        src = _fixture_dir(cond)
        dst = tmp_path_factory.mktemp(cond) / src.name
        shutil.copytree(src, dst)
        rebuild_report(dst, pack)
        out[cond] = json.loads((dst / "scores.json").read_text())
    return out


@pytest.mark.regression
@pytest.mark.parametrize("cond", CONDITIONS)
def test_overall_headline_reproduces(rebuilt, cond):
    """Overall accuracy re-scores to the frozen headline (73 / 68 / 93)."""
    overall = rebuilt[cond]["aggregate"]["overall_accuracy"]
    assert round(overall * 100) == EXPECTED_OVERALL[cond], (
        f"{cond}: overall re-scored to {overall*100:.1f}%, expected {EXPECTED_OVERALL[cond]}% — "
        "an extraction bug moved a cell."
    )


@pytest.mark.regression
@pytest.mark.parametrize("cond", CONDITIONS)
def test_aggregate_is_byte_identical(rebuilt, cond):
    """Every per-task and per-dimension aggregate cell recomputes exactly (deep value equality)."""
    committed = json.loads((_fixture_dir(cond) / "scores.json").read_text())
    assert rebuilt[cond]["aggregate"] == committed["aggregate"], (
        f"{cond}: recomputed aggregate differs from the committed fixture."
    )


@pytest.mark.regression
@pytest.mark.parametrize("cond", CONDITIONS)
def test_per_run_scores_are_byte_identical(rebuilt, cond):
    """Every per-run dimensions/endpoint_matches/format_failure recomputes exactly."""
    committed = json.loads((_fixture_dir(cond) / "scores.json").read_text())
    assert rebuilt[cond]["runs"] == committed["runs"], (
        f"{cond}: at least one per-run record differs from the committed fixture."
    )


@pytest.mark.regression
@pytest.mark.parametrize("cond", CONDITIONS)
def test_metadata_diff_is_only_the_provenance_class(rebuilt, cond):
    """The only metadata differences are the documented run-provenance class — no score field moves."""
    committed = json.loads((_fixture_dir(cond) / "scores.json").read_text())["metadata"]
    rebuilt_meta = rebuilt[cond]["metadata"]
    dropped = set(committed) - set(rebuilt_meta)
    added = set(rebuilt_meta) - set(committed)
    changed = {k for k in set(committed) & set(rebuilt_meta) if committed[k] != rebuilt_meta[k]}
    assert dropped <= METADATA_DROPPED_ON_REBUILD, f"{cond}: unexpected dropped metadata {dropped}"
    assert added <= METADATA_ADDED_ON_REBUILD, f"{cond}: unexpected added metadata {added}"
    assert not changed, f"{cond}: score-bearing metadata changed on rebuild: {sorted(changed)}"


@pytest.mark.regression
@pytest.mark.parametrize("cond", CONDITIONS)
def test_summary_diff_is_only_the_tool_discipline_note(rebuilt, pack, cond, tmp_path):
    """summary.md reproduces except the single tool-discipline note line (dropped on rebuild)."""
    src = _fixture_dir(cond)
    committed_summary = (src / "summary.md").read_text()
    dst = tmp_path / src.name
    shutil.copytree(src, dst)
    rebuild_report(dst, pack)
    rebuilt_summary = (dst / "summary.md").read_text()

    committed_lines = committed_summary.splitlines()
    rebuilt_lines = rebuilt_summary.splitlines()
    only_committed = [l for l in committed_lines if l not in rebuilt_lines]
    only_rebuilt = [l for l in rebuilt_lines if l not in committed_lines]
    assert only_rebuilt == [], f"{cond}: rebuild introduced summary lines: {only_rebuilt}"
    assert len(only_committed) == 1 and "tool discipline" in only_committed[0], (
        f"{cond}: summary.md diff is not limited to the tool-discipline note: {only_committed}"
    )


def _score_sections(md: str) -> dict[str, str]:
    """Split a comparison markdown into its `## ` sections, keyed by header line."""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


@pytest.mark.regression
def test_comparison_score_tables_reproduce(rebuilt):
    """The regenerated cross-condition comparison reproduces the canonical score tables exactly.

    Compares the three score-bearing sections (overall-by-dimension + both per-task tables). The
    committed file's `> Note:` annotation, the per-condition tool-discipline suffixes, and the trailing
    cycle-6 delta table are run-provenance annotations (the delta table needs the superseded baseline
    dirs, intentionally not imported) — not score cells — and are out of scope for this equality.
    """
    entries = [(c, aggregate(rebuilt[c]["runs"]), rebuilt[c]["metadata"]) for c in CONDITIONS]
    regen = render_multi_comparison_md(entries)
    committed = (FIXTURES / "comparison-sterile-2026-07-23.md").read_text()

    regen_sec = _score_sections(regen)
    committed_sec = _score_sections(committed)
    for header in ("Overall accuracy by dimension",
                   "Per-task accuracy (mean of applicable dimensions)"):
        assert regen_sec[header] == committed_sec[header], (
            f"comparison section '{header}' did not reproduce exactly."
        )
    # The per-task × per-dimension header includes the condition list; match by prefix.
    def _ptxpd(sec: dict) -> str:
        key = next(k for k in sec if k.startswith("Per-task × per-dimension"))
        return sec[key]
    assert _ptxpd(regen_sec) == _ptxpd(committed_sec), (
        "comparison per-task × per-dimension table did not reproduce exactly."
    )
    # And the headline overall row literally reads 73% / 68% / 93%.
    assert "| **overall** | 73% | 68% | 93% |" in regen_sec["Overall accuracy by dimension"]
