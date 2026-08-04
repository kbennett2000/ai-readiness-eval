"""Every card the template generates carries both disclosures, above its first table row.

`render_card_scaffold` is the only report-card template in this project, and until this file it had
no test at all. It also emitted NEITHER disclosure: ADR-0046 requires every card to state what its
overall is a mean of, and the template that generates cards left the sentence to whoever remembered
to paste it — which is the decay mode ADR-0046 exists to name, pointed at ADR-0046's own rule.

Position is load-bearing and is asserted, not assumed. ADR-0046's card gate requires the coverage
line BEFORE the card's first table row, because a disclosure a reader passes on the way to the number
is a disclosure they can read past. The same holds for the reproducibility line (ADR-0058), which
tells a reader which half of the card they can re-check for themselves.

WHAT THESE TESTS DO NOT PROVE
    That any card ALREADY published carries either line. Cards live in a separate repository, and
    nothing here can reach them — the standing limit ADR-0046 records as
    `two-cohort-numbers-look-alike-on-a-page`. This gate covers cards generated from now on.
"""
import json
import pathlib

import pytest

from core.factory import render_card_scaffold
from core.pack import Pack
from core.report import aggregate, coverage_line, docs_provenance, reproducibility_line

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ACME = REPO_ROOT / "core" / "tests" / "fixtures" / "pack-acme"
REFERENCE = REPO_ROOT / "packs" / "sailpoint"
REFERENCE_FIXTURES = REFERENCE / "fixtures" / "imported"


def _graded(pack: Pack, fixtures: pathlib.Path | None):
    """(condition, aggregate, metadata) per committed condition; a synthetic one when a pack has no
    committed scores, since the template must work for a pack being carded for the first time."""
    out = []
    for scores_path in sorted((fixtures or pathlib.Path("/nonexistent")).glob("*/scores.json")):
        scores = json.loads(scores_path.read_text())
        out.append((scores["metadata"].get("condition", scores_path.parent.name),
                    aggregate(scores["runs"]), scores["metadata"]))
    if out:
        return out
    dims = list(pack.contract.dimensions)
    agg = {"task_ids": ["t"], "per_task": {}, "overall_dimensions": {d: 1.0 for d in dims},
           "overall_accuracy": 1.0, "total_runs": 1, "format_failures": 0, "format_repairs": 0}
    return [("no-context", agg, {"model": "m", "provider": "mock", "n": 1})]


CARDS = [
    pytest.param(ACME, None, id="acme-never-fetched"),
    pytest.param(REFERENCE, REFERENCE_FIXTURES, id="reference-pack"),
]


def test_both_packs_exist_so_this_sweep_is_not_vacuous():
    assert ACME.is_dir() and REFERENCE.is_dir()


@pytest.mark.parametrize("pack_dir,fixtures", CARDS)
def test_the_card_carries_both_disclosures_verbatim(pack_dir, fixtures):
    pack = Pack.load(pack_dir)
    graded = _graded(pack, fixtures)
    card = render_card_scaffold(pack, graded, {})

    expected_coverage = coverage_line(graded[0][1], pack.contract, pack.unexercised_dimensions)
    expected_repro = reproducibility_line(docs_provenance(pack.docs_manifest()))
    assert expected_coverage in card, f"{pack_dir.name}: card lost its coverage line (ADR-0046)"
    assert expected_repro in card, f"{pack_dir.name}: card lost its reproducibility line (ADR-0058)"


@pytest.mark.parametrize("pack_dir,fixtures", CARDS)
def test_both_disclosures_sit_above_the_first_table_row(pack_dir, fixtures):
    """A disclosure below the headline table is one a reader reaches after the number it qualifies."""
    pack = Pack.load(pack_dir)
    card = render_card_scaffold(pack, _graded(pack, fixtures), {})
    lines = card.splitlines()

    first_row = next(i for i, line in enumerate(lines) if line.startswith("|"))
    coverage_at = next(i for i, line in enumerate(lines) if line.startswith("**Dimension coverage"))
    repro_at = next(i for i, line in enumerate(lines) if line.startswith("**Reproducibility"))
    assert coverage_at < first_row and repro_at < first_row, (
        f"{pack_dir.name}: a disclosure appears after the headline table")


def test_a_never_fetched_pack_claims_no_capture_on_its_card():
    """Pinned to the real acme fixture, which is deliberately a manifest authored before its first
    fetch. A future cycle that fetches it has to notice it is removing this branch's only live
    evidence — the same lever ADR-0057 used for the undated-entry rule."""
    pack = Pack.load(ACME)
    card = render_card_scaffold(pack, _graded(pack, None), {})
    assert "records no retrieved page" in card
    assert "captured" not in card


def test_a_card_whose_conditions_disagree_about_coverage_refuses_to_render():
    """One line cannot honestly describe two arms that differ (ADR-0046), so the template raises and
    the `card` stage blocks the target with the reason rather than silently picking one."""
    pack = Pack.load(REFERENCE)
    dims = list(pack.contract.dimensions)
    full = {d: 1.0 for d in dims}
    short = dict(full, **{dims[-1]: None})

    def _agg(overall):
        applicable = [v for v in overall.values() if v is not None]
        return {"task_ids": ["t"], "per_task": {}, "overall_dimensions": overall,
                "overall_accuracy": sum(applicable) / len(applicable), "total_runs": 1,
                "format_failures": 0, "format_repairs": 0}

    graded = [("a", _agg(full), {}), ("b", _agg(short), {})]
    with pytest.raises(ValueError, match="disagree about dimension coverage"):
        render_card_scaffold(pack, graded, {})
