"""The reproducibility disclosure (ADR-0058): a published number states what can be re-checked.

Every number this project publishes has two sides pinned by different means. The spec side is pinned
to a public commit a third party can re-resolve; the documentation side is pinned by a capture date,
a byte size and a SHA-256, and by nothing else, because the cached bytes are the vendor's copyrighted
documentation and are gitignored. Both halves are true, and neither was stated where a reader meets
the number — the boundary lived in issue #102 and in ADR-0057's Consequences, which no vendor's
engineer reads.

The sentence is GENERATED rather than typed for the reason ADR-0046 gives about the coverage line: it
carries a count and a date that move whenever a pack is re-fetched, and a hand-maintained derived
figure goes stale silently. These tests break each rule of the generator on purpose.

WHAT THESE TESTS DO NOT PROVE
    That the recorded capture date is TRUE. Nothing in this repository can corroborate it — the bytes
    that would are gitignored — which is the standing hazard
    `a-capture-date-is-attested-never-corroborated` (ADR-0057) and is exactly what the second
    sentence tells a reader.
"""
import os
import pathlib

import pytest

from core.pack import Pack
from core.report import docs_provenance, reproducibility_line

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

OK = "sha256:" + "a" * 64


def _manifest(*pages) -> dict:
    """A manifest carrying `pages` under one task, in the real nesting the fetcher writes."""
    return {"tasks": {"t1": {"pages": list(pages)}}}


def _page(**over) -> dict:
    base = {"url": "https://d.test/api/accounts", "role": "api-reference", "note": "n",
            "fetch_date": "2026-07-23", "content_hash": OK, "byte_size": 4073}
    base.update(over)
    return base


# --------------------------------------------------------------------------- what counts as retrieved

def test_a_retrieved_page_is_one_with_a_content_hash():
    prov = docs_provenance(_manifest(_page(), _page(url="https://d.test/b")))
    assert prov == {"entries": 2, "retrieved": 2, "dates": ["2026-07-23"]}


def test_a_recorded_failure_is_not_counted_as_a_captured_page():
    """A `fetch_error` entry injected nothing, so claiming it as a captured page would overstate what
    the docs condition read — in the direction that flatters, which is the direction to refuse."""
    prov = docs_provenance(_manifest(
        _page(),
        {"url": "https://d.test/gone", "role": "api-reference", "note": "n",
         "fetch_date": "2026-07-23", "content_hash": None, "byte_size": 0,
         "fetch_error": "HTTP 404"},
    ))
    assert prov["entries"] == 2 and prov["retrieved"] == 1


def test_a_never_attempted_entry_is_not_counted_either():
    """The shape of a manifest authored before its first fetch (ADR-0057)."""
    prov = docs_provenance(_manifest({"url": "https://d.test/x", "role": "api-reference", "note": "n"}))
    assert prov["entries"] == 1 and prov["retrieved"] == 0 and prov["dates"] == []


@pytest.mark.parametrize("key", ["pages", "anchors", "spec_documents", "gated_pages"])
def test_every_entry_list_is_swept(key):
    """All four `ENTRY_KEYS` are fetched and cached, so all four are attested-but-absent bytes. A
    fifth list added later must not slip past the count."""
    prov = docs_provenance({"tasks": {"t1": {key: [_page()]}}})
    assert prov["retrieved"] == 1


def test_a_date_on_an_unretrieved_entry_is_not_cited():
    """The dates come off the RETRIEVED set. Reading them off every entry would let the sentence cite
    the capture date of a page that was never captured."""
    prov = docs_provenance(_manifest(
        {"url": "https://d.test/x", "role": "api-reference", "note": "n",
         "fetch_date": "2019-01-01", "content_hash": None, "byte_size": 0,
         "fetch_error": "HTTP 500"}))
    assert prov["dates"] == []


# --------------------------------------------------------------------------- the sentence

def test_the_line_states_both_halves_of_the_boundary():
    line = reproducibility_line(docs_provenance(_manifest(_page(), _page(url="https://d.test/b"))))
    assert "re-scores from the committed transcripts with no network access" in line
    assert "2 documentation pages this pack retrieved were captured 2026-07-23" in line
    assert "cannot be re-obtained from a clean checkout" in line


def test_one_capture_date_is_stated_as_a_date_and_several_as_a_range():
    one = reproducibility_line(docs_provenance(_manifest(_page())))
    assert "was captured 2026-07-23" in one and "between" not in one

    many = reproducibility_line(docs_provenance(_manifest(
        _page(), _page(url="https://d.test/b", fetch_date="2026-07-30"),
        _page(url="https://d.test/c", fetch_date="2026-07-25"))))
    assert "were captured between 2026-07-23 and 2026-07-30" in many


def test_a_manifest_with_nothing_retrieved_claims_no_capture():
    """The branch that matters most. A manifest authored before its first fetch, or a pack whose every
    page was refused, must not be described as having captured anything — inventing a capture is the
    failure the whole line exists to prevent."""
    line = reproducibility_line(docs_provenance(_manifest(
        {"url": "https://d.test/x", "role": "api-reference", "note": "n"})))
    assert "records no retrieved page" in line
    assert "captured" not in line
    # The first half is still true and is still stated: what re-derives does not depend on the cache.
    assert "re-scores from the committed transcripts" in line


def test_the_line_is_one_line_so_it_can_be_pasted_anywhere():
    for prov in (docs_provenance(_manifest(_page())), docs_provenance(_manifest())):
        assert "\n" not in reproducibility_line(prov)


def test_the_adr_citation_and_both_links_are_parameters():
    """Two repos cite this repo's ADRs differently (ADR-0046), and one sentence has to be valid from
    the repo root, from inside a pack, and from a card — the paths point different ways from each."""
    prov = docs_provenance(_manifest(_page()))
    assert "(public ADR-0058)" in reproducibility_line(prov, adr_ref="public ADR-0058")
    assert "(packs/x/docs-manifest.yaml)" in reproducibility_line(
        prov, manifest_link="packs/x/docs-manifest.yaml")
    # A (display, href) pair when the two must differ, e.g. a gate two directories up.
    line = reproducibility_line(prov, gate_link=("core/tests/t.py", "../../core/tests/t.py"))
    assert "[`core/tests/t.py`](../../core/tests/t.py)" in line


def test_the_page_count_is_singular_when_there_is_one():
    line = reproducibility_line(docs_provenance(_manifest(_page())))
    assert "The 1 documentation page this pack retrieved was captured" in line


# --------------------------------------------------------------------------- every pack on disk

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
def test_every_pack_on_disk_can_state_its_own_provenance(pack_dir):
    """Swept over every pack rather than the one a cycle happens to be authoring, for the reason
    ADR-0010 gives about the round-trip control: a gate that runs only on dispatch has never run on
    most of the cohort.

    The count is recomputed here independently of `docs_provenance` — a generator checked only
    against itself is checked against nothing.
    """
    pack = Pack.load(pack_dir)
    manifest = pack.docs_manifest()
    prov = docs_provenance(manifest)

    expected = sum(1 for task in (manifest.get("tasks") or {}).values()
                   for key in ("pages", "anchors", "spec_documents", "gated_pages")
                   for page in (task.get(key) or []) if page.get("content_hash"))
    assert prov["retrieved"] == expected, f"{pack_dir.name}: retrieved count disagrees"

    line = reproducibility_line(prov)
    assert line.startswith("**Reproducibility (")
    assert "\n" not in line
    if prov["retrieved"]:
        assert str(prov["retrieved"]) in line
        # ADR-0057 refuses a recorded outcome with no date at the `validate` gate, so a retrieved
        # page on disk always has one. If that ever stops being true the sentence must not invent one.
        assert prov["dates"], f"{pack_dir.name}: retrieved pages carry no capture date"
