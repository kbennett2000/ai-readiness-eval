"""Every pack on disk must score its own ground truth — enforced by the suite, not only by the
factory (ADR-0010).

The factory runs the `roundtrip` gate when it drives a target. That leaves a pack nobody has
dispatched yet unchecked, and a pack edited after it was carded unchecked again. This test closes
both gaps: it discovers packs by glob, so a pack added later is covered without anyone remembering
to write a test for it.

External packs live outside this repo (the core is vendor-agnostic), so `AIRE_PACKS_DIR` is swept
too — the same env var the CLI resolves bare pack names against.
"""
import os
from pathlib import Path

import pytest

from core.pack import Pack
from core.roundtrip import check_pack, format_report

REPO_ROOT = Path(__file__).resolve().parents[2]


def _discover() -> list[Path]:
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external:
        roots.append(Path(external))
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += [p.parent for p in sorted(root.glob("*/pack.yaml"))]
    return found


PACK_DIRS = _discover()


@pytest.mark.skipif(not PACK_DIRS, reason="no packs on disk to check")
@pytest.mark.parametrize("pack_dir", PACK_DIRS, ids=lambda p: p.name)
def test_pack_scores_its_own_ground_truth(pack_dir):
    controls = check_pack(Pack.load(pack_dir))
    assert controls, f"{pack_dir.name} has no tasks"
    text, total = format_report(controls)
    assert total == 0, f"{pack_dir.name} cannot score its own answer key:\n{text}"


def test_at_least_the_reference_pack_is_discovered():
    """A glob that silently matches nothing would make the check above vacuously green."""
    assert PACK_DIRS, "pack discovery found nothing — the enforcement above would be a no-op"
