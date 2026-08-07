"""Every provenance string the cohort has committed still means what the classifier says it means.

ADR-0060 adds a sixth robots state, and the only way a new state can do damage is by taking cases
from an old one. 140 committed annotations across 8 packs read `no-robots-txt`; if the new branch
claimed the 404 family, or the empty body, or the site shell, every one of those strings would
quietly start describing a different world than the one it was written for — and nothing else in the
suite would notice, because a manifest is static YAML and a code change cannot move it.

**What this sweep can and cannot be.** The obvious assertion — *no archived manifest records the new
state* — is true on the day the state is added and cannot fail, so it proves nothing on its own. It
is kept below with a canary, and the teeth are somewhere else: a WITNESS sweep.

    For every pack, for every `robots_source` string its manifests actually record, feed
    `policy_from_response` the inputs that string stands for, and assert it still maps every one of
    them back to that string.

Break the classifier in either direction and this fails naming real packs, because the packs and the
strings both come off disk. That is the point — a sweep whose break values do not exist in the
archive stays green while the archive rots.

**The limit is the finding, not a caveat.** We cannot tell which witness produced any given entry.
The robots.txt bytes and the HTTP status are not in the record — `ANNOTATION_FIELDS` is five keys and
neither is among them, `RobotsPolicy.body` never leaves the process, and `robots_agent` is `'*'` on
every annotation in the cohort — so no archived pack can be reclassified into the new state offline,
and re-fetching would record today's policy against an archive's date. Filed as a public issue in its
general form: a provenance field that cannot be re-derived from the archive. See ADR-0060.
"""
import os
from pathlib import Path

import pytest
import yaml

from core.docs_fetch import _entry_lists
from core.robots import (SOURCE_ABSENT, SOURCE_NO_GROUP, SOURCE_NO_HOST, SOURCE_REFUSED,
                         SOURCE_RULES, SOURCE_UNREACHABLE, STATUS_NETWORK_FAILURE, STATUS_NO_HOST,
                         policy_from_response)
from core.tests.test_robots_no_group import JS_SHELL, NO_GROUP_BODY

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The worlds each committed string stands for. A state with no witness is itself a failure below —
#: that is what stops a seventh state from being added without anything asserting what it means.
WITNESSES: dict[str, list[tuple[int, str]]] = {
    SOURCE_ABSENT:      [(404, ""), (410, ""), (200, ""), (200, JS_SHELL)],
    SOURCE_RULES:       [(200, "User-agent: *\nDisallow: /x/\n"),
                         (200, "User-agent: ai-readiness-eval-docs\nDisallow: /ours/\n")],
    SOURCE_REFUSED:     [(401, ""), (403, "")],
    SOURCE_UNREACHABLE: [(500, ""), (503, ""), (STATUS_NETWORK_FAILURE, "")],
    SOURCE_NO_HOST:     [(STATUS_NO_HOST, "")],
    SOURCE_NO_GROUP:    [(200, NO_GROUP_BODY)],
}


def _manifests() -> list[Path]:
    """Enumerated from disk, both roots, no exemption list — the `test_robots_annotations` pattern."""
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external:
        roots.append(Path(external))
    return [m for root in roots if root.is_dir() for m in sorted(root.glob("*/docs-manifest.yaml"))]


def _recorded_sources(manifest_path: Path) -> dict[str, int]:
    """{robots_source: how many entries record it} across every list a manifest carries."""
    data = yaml.safe_load(manifest_path.read_text()) or {}
    counts: dict[str, int] = {}
    for entry in (data.get("tasks") or {}).values():
        for page in [p for pages in _entry_lists(entry) for p in pages]:
            source = page.get("robots_source")
            if source:
                counts[source] = counts.get(source, 0) + 1
    return counts


MANIFESTS = _manifests()
RECORDED = {m: _recorded_sources(m) for m in MANIFESTS}
ALL_SOURCES = {s for counts in RECORDED.values() for s in counts}
TOTAL_ENTRIES = sum(n for counts in RECORDED.values() for n in counts.values())


def witness_problems(counts: dict[str, int]) -> list[str]:
    """Pure over one pack's recorded strings, so the canary below can feed it a synthetic set."""
    problems: list[str] = []
    for source in sorted(counts):
        witnesses = WITNESSES.get(source)
        if not witnesses:
            problems.append(
                f"{counts[source]} entr(ies) record {source!r} and this sweep has no witness for it — "
                "add one to WITNESSES so the string's meaning is asserted rather than assumed")
            continue
        for status, body in witnesses:
            got = policy_from_response("h.invalid", status, body, today="2026-01-01").source
            if got != source:
                problems.append(
                    f"{counts[source]} entr(ies) record {source!r}, but status={status} with a "
                    f"{len(body)}-byte body now classifies as {got!r} — those committed annotations "
                    "no longer mean what the classifier says they mean")
    return problems


# --- anti-vacuity ----------------------------------------------------------- #

def test_the_sweep_is_not_vacuous():
    """With AIRE_PACKS_DIR unset this finds only the in-repo reference pack and asserts almost
    nothing. The counts are the evidence the sweep ran over the cohort."""
    assert MANIFESTS, "no docs manifests found — the sweep below would prove nothing"
    assert TOTAL_ENTRIES > 100, (
        f"only {TOTAL_ENTRIES} annotated entr(ies) across {len(MANIFESTS)} manifest(s). "
        "Is AIRE_PACKS_DIR exported?")
    assert len(ALL_SOURCES) >= 3, (
        f"only {sorted(ALL_SOURCES)} recorded — a sweep over one string cannot notice a state "
        "stealing cases from another")


def test_every_state_the_module_defines_has_a_witness():
    """Not just the ones on disk. A state nothing records yet is the one most likely to be
    mis-specified, because nothing is exercising it."""
    from core import robots
    defined = {v for name, v in vars(robots).items()
               if name.startswith("SOURCE_") and isinstance(v, str)}
    assert defined <= set(WITNESSES), f"no witness for {sorted(defined - set(WITNESSES))}"


def test_the_witness_check_can_actually_fail():
    """The canary. Two arms running identical code agree whatever the code does, so the comparison
    has to be shown capable of coming apart before its agreement means anything."""
    assert witness_problems({SOURCE_ABSENT: 140}) == []
    # A string nothing can produce: recorded, unwitnessed, and therefore reported.
    assert witness_problems({"robots.txt-invented": 1})
    # And a real string whose witness has been pointed at the wrong world.
    saved = WITNESSES[SOURCE_ABSENT]
    try:
        WITNESSES[SOURCE_ABSENT] = [(200, NO_GROUP_BODY)]
        assert witness_problems({SOURCE_ABSENT: 140})
    finally:
        WITNESSES[SOURCE_ABSENT] = saved


# --- the sweep -------------------------------------------------------------- #

@pytest.mark.skipif(not MANIFESTS, reason="no docs manifests on disk")
@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: p.parent.name)
def test_every_committed_provenance_string_still_means_what_it_meant(manifest):
    """Parametrized per pack so a break names the packs it would mis-describe, and how many entries."""
    problems = witness_problems(RECORDED[manifest])
    assert not problems, (
        f"{manifest.parent.name}/docs-manifest.yaml:\n  " + "\n  ".join(problems))


@pytest.mark.skipif(not MANIFESTS, reason="no docs manifests on disk")
def test_no_archived_manifest_records_the_new_state():
    """True on arrival and unable to fail today — recorded as such rather than presented as a result.

    The bytes are not in the record, so no archived annotation can be reclassified into the new state
    without re-fetching, and this cycle reclassifies nothing. What this assertion is FOR is the day
    one does: the first pack to record `robots.txt-no-group-for-agent` fails here, and whoever added
    it has to say so in the PR rather than have it appear.
    """
    carrying = {m.parent.name: counts[SOURCE_NO_GROUP]
                for m, counts in RECORDED.items() if SOURCE_NO_GROUP in counts}
    assert not carrying, (
        f"{carrying} now record the new state. That is not a failure — it is the disclosure this "
        "test exists to force. Update it, and say in the PR which annotations moved and why.")
