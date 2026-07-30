"""Every URL any pack names has been checked against its host's instruction (ADR-0036).

The conduct claim this project now makes is that it has never retrieved a page a vendor's robots.txt
told automated readers not to retrieve. That claim was true when it was first checked — 242 URLs across
15 hosts, none disallowed — but it was true as an *audit result*, which is a thing someone ran once. This
is the standing form: the annotation is committed beside each URL, and the sweep fails if a pack ever
names a page its host disallows.

**Offline by construction.** It reads committed annotations and never opens a socket, so the suite stays
deterministic and runnable without a network. Refreshing the annotations against the live hosts is a
separate, explicitly online step — `python -m core annotate-robots --check` — run by a cycle, not by
pytest. The split matters: a test that fetched would make every run depend on thirteen vendors' uptime,
and a green suite would then mean "the hosts were up", not "we were permitted".
"""
import os
from pathlib import Path

import pytest
import yaml

from core.docs_fetch import _entry_lists
from core.robots import ANNOTATION_FIELDS

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifests() -> list[Path]:
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external:
        roots.append(Path(external))
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += sorted(root.glob("*/docs-manifest.yaml"))
    return found


MANIFESTS = _manifests()


def _urls(manifest_path: Path) -> list[tuple[str, str, dict]]:
    """(task_id, url, page) for every page AND anchor. Anchors are included because ADR-0034 has them
    fetched to verify the citation they carry — a retrieval is a retrieval."""
    data = yaml.safe_load(manifest_path.read_text()) or {}
    out = []
    for task_id, entry in (data.get("tasks") or {}).items():
        for page in [p for pages in _entry_lists(entry) for p in pages]:
            if page.get("url"):
                out.append((task_id, page["url"], page))
    return out


ALL = [(m, t, u, p) for m in MANIFESTS for (t, u, p) in _urls(m)]


def test_the_sweep_below_is_not_vacuous():
    """With AIRE_PACKS_DIR unset this finds only the in-repo reference pack, and every assertion
    below would pass by finding almost nothing to assert about."""
    assert MANIFESTS, "no docs manifests found — the sweep below would prove nothing"
    assert len(ALL) > 100, (
        f"only {len(ALL)} manifest URL(s) across {len(MANIFESTS)} manifest(s); the sweep is too thin "
        "to be evidence. Is AIRE_PACKS_DIR exported?")
    hosts = {u.split("/")[2] for _, _, u, _ in ALL}
    assert len(hosts) > 5, f"only {len(hosts)} distinct host(s) — the sweep is not cohort-wide"


@pytest.mark.skipif(not ALL, reason="no manifest URLs on disk")
@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: p.parent.name)
def test_no_pack_names_a_url_its_host_disallows(manifest):
    """The conduct assertion. A pack must not name a page it may not fetch — the Disallow gets
    recorded as a finding in `specs.yaml` and on the card instead."""
    offending = [f"{t}: {u}  ({p.get('robots_rule')})"
                 for (t, u, p) in _urls(manifest) if p.get("robots_disallowed")]
    assert not offending, (
        f"{manifest.parent.name} names {len(offending)} robots-Disallowed URL(s):\n  "
        + "\n  ".join(offending))


@pytest.mark.skipif(not ALL, reason="no manifest URLs on disk")
@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: p.parent.name)
def test_every_url_carries_a_complete_annotation(manifest):
    """Absent is not the same as allowed. An unannotated URL is one nobody asked about, and it must
    read as an open question rather than quietly as a pass."""
    missing = []
    for task_id, url, page in _urls(manifest):
        absent = [f for f in ANNOTATION_FIELDS if f not in page]
        if absent:
            missing.append(f"{task_id}: {url} is missing {', '.join(absent)}")
    assert not missing, (
        f"{manifest.parent.name} has {len(missing)} unchecked URL(s) — run "
        f"`python -m core annotate-robots`:\n  " + "\n  ".join(missing[:10]))


@pytest.mark.skipif(not ALL, reason="no manifest URLs on disk")
def test_the_annotation_records_which_agent_and_which_source_decided_it():
    """`robots_disallowed: false` alone is a verdict with no working shown. The other fields are what
    let a reviewer re-derive it: which agent group applied, and whether the host stated a rule at all."""
    from core.robots import (SOURCE_ABSENT, SOURCE_NO_HOST, SOURCE_RULES,
                             SOURCE_UNREACHABLE)

    known = {SOURCE_RULES, SOURCE_ABSENT, SOURCE_UNREACHABLE, SOURCE_NO_HOST}
    for _m, task_id, url, page in ALL:
        assert page["robots_source"] in known, \
            f"{task_id}: {url} records an unknown robots_source {page['robots_source']!r}"
        assert page["robots_agent"], f"{task_id}: {url} does not say which agent group applied"
        # A host that stated no rule cannot have produced a matching directive, and vice versa.
        if page["robots_source"] in (SOURCE_ABSENT, SOURCE_NO_HOST):
            assert page["robots_rule"] is None, \
                f"{task_id}: {url} cites a directive from a host that served none"


@pytest.mark.skipif(not ALL, reason="no manifest URLs on disk")
def test_annotating_never_changed_what_a_condition_injects():
    """The safety argument for running this across an already-published cohort: the annotation adds
    provenance and touches nothing the injected bytes are derived from. A page recorded as fetched
    still has its hash, its size and its cache file."""
    for _m, task_id, url, page in ALL:
        if page.get("byte_size"):
            assert page.get("content_hash"), f"{task_id}: {url} has a size but lost its hash"
            assert page.get("cache_file"), f"{task_id}: {url} has a size but lost its cache_file"
