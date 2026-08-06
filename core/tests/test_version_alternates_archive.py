"""ADR-0059 — the version tolerance moves no archived cell it was not declared for.

A version tolerance can only ever move `api_version` UP, so the claim that it changes nothing has to
be checked against every number that already exists rather than asserted about the code. That is the
same obligation ADR-0055 met for the endpoint-base tolerance, applied to a wider surface: every
archived run in every pack on disk, re-scored from its committed `raw_response`.

THE COMPARISON, AND WHY IT IS THIS ONE
    Each archived run is scored twice — once with the declarations its task carries, once with the
    alternates forced empty — and the two must agree wherever nothing is declared. The obvious
    alternative, recomputed-equals-committed-`scores.json`, is a different and stronger claim that
    does NOT hold today and does not hold because of anything here: on the tree this landed against,
    11 of 2,403 archived runs already disagreed with their own report, all in one pack's
    `mock-preflight` directory (`provider: mock`), because twelve of that pack's tasks adopted
    ADR-0041's `auth_flow_not_corroborable` after that mock was archived. Asserting the absolute
    would therefore have needed an exemption list, and an exemption list is how a sweep stops seeing
    the thing it was written for — `test_archive_consistency.py` carries none for exactly that
    reason, in a case where the exempted directory would have been this repository's own anchor.

    So the cycle that landed the mechanism proved neutrality the other way, as a diff of the same
    recomputation before and after: 2,403 runs re-scored on the merge base, 2,403 on the branch,
    zero cells different, and the 11 pre-existing disagreements identical in both. This test is the
    standing form of that proof, in the shape a test can hold.

THERE IS NO EXEMPTION LIST, AND NO SELF-EXEMPTION
    Packs are enumerated from disk by glob, in this repository and in `AIRE_PACKS_DIR`, so a pack
    added later is covered without anyone remembering to add it — the rule the coverage work landed
    on and the one `test_pack_roundtrip.py` already applies.

WHAT THIS CANNOT DO
    While no pack declares an alternate, this proves the new path is UNREACHED rather than that it
    is harmless where it is reached — which is exactly what a mechanism landing against zero
    declarations can prove, and it is why `test_the_comparison_can_detect_a_widening` below is not
    optional. The standing value arrives with the first declaration: whichever pack declares one is
    told precisely which archived cells its tolerance moves, run by run, instead of discovering it
    in a rebuilt report.
"""
import json
import os
from pathlib import Path

import pytest

from core.answer_block import Endpoint
from core.contract import contract_for
from core.pack import Pack
from core.scorer import _match_endpoints, declared_version_alternates

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pack_dirs() -> list[Path]:
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external:
        roots.append(Path(external))
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += [p.parent for p in sorted(root.glob("*/pack.yaml"))]
    return found


def _archived_conditions(pack_dir: Path) -> list[Path]:
    """Both globs, matching `test_archive_consistency.py`: live grids under `results/` and imported
    fixtures under `fixtures/imported/`. Counting only the first missed this repo's frozen anchor."""
    return [p.parent
            for pattern in ("results/*/scores.json", "fixtures/imported/*/scores.json")
            for p in sorted(pack_dir.glob(pattern))
            if (p.parent / "runs").is_dir()]


PACK_DIRS = _pack_dirs()


def _recompute(pack_dir: Path) -> tuple[int, list[str]]:
    """Re-score every archived run in one pack twice and report (runs compared, disagreements).

    The answer is re-PARSED from the committed `raw_response` rather than read out of the record's
    `endpoint_matches`, so the comparison starts from the archived evidence and not from the
    scorer's own earlier opinion of it. Costs about two seconds over the whole cohort.
    """
    pack = Pack.load(pack_dir)
    contract = contract_for(pack)
    if contract.name != "api":
        return 0, []           # only the API cohort has an `api_version` dimension to widen
    tasks = pack.tasks_by_id()
    prefixes = pack.base_prefix_segments
    compared = 0
    moved: list[str] = []
    for d in _archived_conditions(pack_dir):
        for f in sorted((d / "runs").glob("*.json")):
            rec = json.loads(f.read_text())
            task = tasks.get(rec.get("task_id"))
            if task is None:
                continue
            parsed = contract.parse(rec.get("raw_response", ""))
            if parsed.is_failure:
                continue       # a format failure scores no dimension, so there is none to widen
            gt_eps = task["ground_truth"]["endpoints"]
            answer_eps = parsed.summary.endpoints
            compared += 1
            with_declaration = _match_endpoints(
                gt_eps, answer_eps, prefixes, declared_version_alternates(task["ground_truth"]))
            without = _match_endpoints(gt_eps, answer_eps, prefixes, ())
            if with_declaration != without:
                moved.append(f"{pack_dir.name}/{d.name}/{f.stem}")
    return compared, moved


RESULTS = {p.name: _recompute(p) for p in PACK_DIRS}


# --------------------------------------------------------------------------- the sweep is real ---


def test_the_sweep_is_not_vacuous():
    """A glob that silently matched nothing would make every assertion below a no-op — and with
    AIRE_PACKS_DIR unset it very nearly does, finding only the in-repo fixtures."""
    assert PACK_DIRS, "pack discovery found nothing; the sweep below would prove nothing"
    total = sum(compared for compared, _ in RESULTS.values())
    assert total > 100, f"only {total} archived runs re-scored; the sweep is too thin to be evidence"


def test_the_comparison_can_detect_a_widening():
    """The canary that makes the sweep mean something.

    With no pack declaring an alternate, both arms of every comparison below run identical code, and
    a comparison that cannot come apart reports agreement whatever the scorer does. So the same
    comparison is made once on a task that DOES declare one, and it must come apart there.
    """
    gt_eps = [{"method": "GET", "path": "/v3/widgets", "api_version": "v3",
               "operation_id": "listWidgets"}]
    answer_eps = [Endpoint(method="GET", path="/v3/widgets", api_version="v4")]
    assert _match_endpoints(gt_eps, answer_eps, None, ["v4"]) != \
        _match_endpoints(gt_eps, answer_eps, None, ())


# ------------------------------------------------------------------------------- the assertion ---


@pytest.mark.skipif(not PACK_DIRS, reason="no packs on disk to sweep")
@pytest.mark.parametrize("pack_name", sorted(RESULTS))
def test_no_archived_run_is_scored_differently_by_the_version_tolerance(pack_name):
    compared, moved = RESULTS[pack_name]
    assert not moved, (
        f"{len(moved)} of {compared} archived run(s) in {pack_name} score differently with the "
        f"declared version alternates than without them: " + ", ".join(moved[:5])
    )


@pytest.mark.skipif(not PACK_DIRS, reason="no packs on disk to sweep")
def test_the_sweep_actually_re_scored_something_in_more_than_one_pack():
    """Guards the sweep from the other direction, as `test_archive_consistency.py` does: a run that
    compared zero records reports agreement and disagreement identically."""
    with_runs = [name for name, (compared, _) in RESULTS.items() if compared]
    assert len(with_runs) > 1, f"only {with_runs} had any archived run to re-score"
