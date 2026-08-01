"""The docs condition must not measure our own truncation (ADR-0029).

`public-docs` enforces a token budget by dropping low-priority pages and then cropping the tail of the
last page it keeps. When the cropped page is the one carrying the operation a task asks about, the
resulting score measures OUR budget rather than the vendor's documentation — and nothing downstream can
tell the difference, because a truncated-away endpoint and an undocumented endpoint produce the same
transcript. That is the ADR-0013 fault class: a dimension read 13.7% while the model was right in 98%
of runs, and the whole gap was an instrument artifact nobody could see in the numbers.

This sweeps every pack on disk rather than only the pack a cycle happens to be authoring, for the
reason ADR-0010 gives about the round-trip control: a gate that runs only on dispatch is a gate that
has never run on most of the cohort. The reference pack's recon state (ADR-0029) is exactly what
happens when that lesson is not applied.
"""
import os
import pathlib

import pytest

from core.conditions import audit_docs_truncation
from core.pack import Pack

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pack_dirs() -> list[pathlib.Path]:
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external and pathlib.Path(external).is_dir():
        roots.append(pathlib.Path(external))
    return [d for root in roots if root.is_dir()
            for d in sorted(root.iterdir()) if (d / "pack.yaml").exists()]


PACK_DIRS = _pack_dirs()


def test_the_sweep_enumerates_packs():
    """Non-vacuity guard (standing rule): a parametrized sweep over an empty list is a green run that
    checked nothing, and reads identically to a real pass in the summary line."""
    assert PACK_DIRS, "no packs discovered — this sweep would pass vacuously"


@pytest.mark.parametrize("pack_dir", PACK_DIRS, ids=lambda p: p.name)
def test_the_budget_never_deletes_a_documented_ground_truth_path(pack_dir):
    """The defect is RELATIVE: present in the full cached page, absent from the injected text.

    A path absent from both is not a failure and must never become one — a vendor whose documentation
    omits an endpoint is a finding this method exists to publish, and gating on it would forbid the
    result the cohort most wants to report. Only the budget deleting an answer the page actually
    carried is a defect, because only that one is ours.
    """
    losses = [r for r in audit_docs_truncation(Pack.load(pack_dir)) if r["truncated"]]
    assert not losses, (
        f"{pack_dir.name}: the context budget removed {len(losses)} ground-truth path(s) that the "
        f"cached page does contain — raise budget_tokens or split the page: "
        + ", ".join(f"{r['task_id']}:{r['path']}" for r in losses[:5])
    )


def test_the_matcher_finds_paths_that_are_really_there():
    """THE TEST THAT KEEPS THE SWEEP HONEST.

    Every assertion above is a negative — "no losses" — so a matcher that silently matched nothing
    would make the entire file pass while checking nothing at all. That is the exact shape of the
    vacuous-green failure this project keeps re-learning, so it is closed by a positive claim: across
    the cohort, some ground-truth paths ARE found in their cached pages. If this ever reaches zero the
    matcher has broken, whatever the rest of the file says.

    Two ways to reach zero, and they are NOT the same finding. The matcher can be broken, or there
    can be no cached page to look in — `docs-cache/` is gitignored, so on a clean checkout or a CI
    runner every audit raises and the count is zero for a reason that says nothing about the matcher.
    The first armed CI run failed here for the second reason and reported the first, which is how a
    control that cannot tell "absent" from "broken" spends someone's afternoon. Counted separately.
    """
    documented = 0
    audited, uncached = [], []
    for pack_dir in PACK_DIRS:
        try:
            records = audit_docs_truncation(Pack.load(pack_dir))
        except Exception:                       # a pack that cannot be loaded at all
            uncached.append(pack_dir.name)
            continue
        # The signal is `searchable` — cached text at least as long as the shortest spelling being
        # looked for — and not the absence of an `error`, nor a non-zero byte count. Both weaker
        # forms were tried and both still reported "the matcher is broken" against a runner that
        # simply had no cache: a pack whose pages all failed to fetch raises nothing and returns
        # an empty string, and one whose docs host serves a JavaScript shell extracts to a SINGLE
        # BYTE, which is non-zero and searches for nothing (ADR-0043).
        searchable = [r for r in records if r.get("searchable")]
        (audited if searchable else uncached).append(pack_dir.name)
        documented += sum(1 for r in searchable if r["documented"])
    if not audited:
        pytest.skip(
            f"no pack on disk has a fetched docs cache ({len(uncached)} checked), so this control "
            f"cannot run here — `docs-cache/` is gitignored. It says nothing about the matcher, and "
            f"the sweep it keeps honest is equally unexercised: see the hazard entry "
            f"`the-truncation-sweep-is-unexercised-without-a-docs-cache`."
        )
    assert documented > 0, (
        f"no ground-truth path was found in any cached page across {len(audited)} pack(s) that DO "
        f"have a cache ({', '.join(audited)}) — the matcher is broken"
    )
