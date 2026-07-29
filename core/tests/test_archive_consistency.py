"""Every archived run record agrees with the report built from it (ADR-0033).

This is the standing sweep, and it exists because the drift it checks for was invisible for the whole
life of the project. `rebuild-report` recomputed every per-run score into `scores.json` and stopped one
file short of `runs/*.json`, so **all 24 archived conditions that had ever been rebuilt disagreed with
their own published totals** — 638 run records, 929 fields — while every test passed. Nothing compared
the two, so nothing noticed.

It is not a tidiness check. `cmd_run` resumes a grid by appending an archived record verbatim
(`records.append(prev)`), so a stale record is re-published into a NEW scores.json, and the ADR-0032
breaker reads the same stale `format_failure` flags.

There is no exemption list, deliberately. The public repo's own frozen reference fixture was one of
the stale directories, and an exemption for it would have hidden exactly the case worth seeing.
"""
import json
import os
from pathlib import Path

import pytest

from core.archive import reconcile_runs

REPO_ROOT = Path(__file__).resolve().parents[2]


def _archived_conditions() -> list[Path]:
    """Every result directory on disk that has both a report and the runs it was built from.

    Two globs, matching `test_run_guard.py`: packs keep live grids under `results/` and imported
    fixtures under `fixtures/imported/`. Issue #52 counted only the first and so reported 3 of 29
    where the real figure was 4 of 32 — the missed directory being this repo's own frozen anchor.
    """
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external:
        roots.append(Path(external))
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("*/results/*/scores.json", "*/fixtures/imported/*/scores.json"):
            found += [p.parent for p in sorted(root.glob(pattern)) if (p.parent / "runs").is_dir()]
    return found


ARCHIVED = _archived_conditions()


def test_the_sweep_below_is_not_vacuous():
    """A glob that silently matches nothing would make every assertion below a no-op — and with
    AIRE_PACKS_DIR unset it very nearly does, finding only the in-repo fixtures."""
    assert ARCHIVED, "no archived conditions found — the sweep below would prove nothing"
    total = sum(len(list((d / "runs").glob("*.json"))) for d in ARCHIVED)
    assert total > 100, f"only {total} archived runs found; the sweep is too thin to be evidence"


@pytest.mark.skipif(not ARCHIVED, reason="no archived conditions on disk")
@pytest.mark.parametrize("results_dir", ARCHIVED, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_run_record_agrees_with_its_own_report(results_dir):
    report = reconcile_runs(results_dir, write=False)
    assert report.ok, "; ".join(report.problems)
    assert not report.changed, (
        f"{len(report.changed)} of {report.checked} run record(s) disagree with scores.json "
        f"({report.total_fields} field(s)): "
        + "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(report.changed.items())[:5])
        + " — run `python -m core reconcile-runs <dir>`")


@pytest.mark.skipif(not ARCHIVED, reason="no archived conditions on disk")
@pytest.mark.parametrize("results_dir", ARCHIVED, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_the_check_above_actually_read_the_records(results_dir):
    """Guards the sweep from the other direction. `reconcile_runs` reports `ok` with nothing changed
    both when every record agrees and when it read no records at all, and those are opposite facts."""
    report = reconcile_runs(results_dir, write=False)
    on_disk = len(list((results_dir / "runs").glob("*.json")))
    assert report.checked == on_disk > 0, (
        f"{report.checked} record(s) compared but {on_disk} on disk")
