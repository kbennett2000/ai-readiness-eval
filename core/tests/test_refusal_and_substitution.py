"""Two things a fetch pipeline could not previously say (ADR-0052, ADR-0053).

**A refusal is not an absence.** A 401/403 on `/robots.txt` is a 4xx, so RFC 9309 leaves the host
unrestricted and nothing this project may retrieve changes. What changes is the sentence written into
the record. `no-robots-txt` claims a host never stated a policy; a host answering 403 has one and
declined to show this reader. A recon's own generated audit table published PERMITTED, sourced from
`no-robots-txt`, for a host that had just answered 403 to every request including that one.

**A substitute page is not a document.** A host can answer a path that does not exist with HTTP 200
and a real page. Every gate already in the pipeline passes it: 200, non-empty (ADR-0009), far above
the text floor (ADR-0021), robots-permitted. So a manifest can import one substitute under ten URLs
and inject one page ten times while believing it injected ten, and no transcript can show it.

Both rules are checked here by BREAKING them, and both were measured over every pack on disk before
being written: neither moves a published number.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from core import robots
from core.docs_fetch import GATED_KEY, MIN_TEXT_BYTES
from core.factory import _check_robots_refusals, _refused_robots_hosts, check_substitution
from core.pack import Pack

ACME = Path(__file__).resolve().parent / "fixtures" / "pack-acme"


def _pack(tmp_path: Path, *, pages: list[dict] | None = None, specs_extra: dict | None = None,
          name: str = "p") -> Pack:
    root = tmp_path / name
    shutil.copytree(ACME, root)
    if pages is not None:
        manifest_path = root / "docs-manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["tasks"]["gadget-fetch"]["pages"] = pages
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    if specs_extra:
        specs_path = root / "specs.yaml"
        specs = yaml.safe_load(specs_path.read_text()) or {}
        specs.update(specs_extra)
        specs_path.write_text(yaml.safe_dump(specs, sort_keys=False))
    return Pack.load(root)


def _page(url: str, *, digest: str, size: int, source: str | None = None) -> dict:
    page = {"url": url, "role": "api-reference", "content_hash": digest, "byte_size": size}
    if source:
        page["robots_source"] = source
    return page


# --- ADR-0052: a refusal is not an absence ---------------------------------- #

def test_the_refused_state_is_its_own_string():
    """These strings are written into pack manifests, so they are part of the record a reviewer
    reads. Two states that mean different things may not share one."""
    assert robots.SOURCE_REFUSED != robots.SOURCE_ABSENT
    assert robots.SOURCE_REFUSED not in (robots.SOURCE_UNREACHABLE, robots.SOURCE_NO_HOST,
                                         robots.SOURCE_RULES)


def test_a_refusal_still_permits_every_url():
    """The split must not smuggle in a new prohibition. RFC 9309 §2.3.1.3 governs a 4xx, and this
    ADR changes what is recorded, never what is allowed."""
    p = robots.policy_from_response("h.invalid", 403, "")
    assert p.source == robots.SOURCE_REFUSED
    assert p.allows("https://h.invalid/anything") is True
    assert p.verdict("https://h.invalid/anything").rule is None


def test_a_pack_with_no_refused_host_is_unaffected(tmp_path):
    pack = _pack(tmp_path)
    assert _refused_robots_hosts(pack) == {}
    ok, why = _check_robots_refusals(pack, {})
    assert ok and "no host refused" in why


def test_an_undeclared_refusal_is_refused(tmp_path):
    pack = _pack(tmp_path, pages=[_page("https://gated.invalid/a", digest="sha256:aa", size=900,
                                        source=robots.SOURCE_REFUSED)])
    ok, why = _check_robots_refusals(pack, {})
    assert not ok
    assert "gated.invalid" in why and "recording a refusal as an absence" in why


def test_a_declared_refusal_passes(tmp_path):
    pack = _pack(tmp_path, pages=[_page("https://gated.invalid/a", digest="sha256:aa", size=900,
                                        source=robots.SOURCE_REFUSED)])
    ok, why = _check_robots_refusals(pack, {"robots_refusals": {
        "gated.invalid": "the host filters on the User-Agent string; a conventional "
                         "self-identifying agent was served the file and it declares no rules"}})
    assert ok and "1 host(s) refused" in why


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_a_blank_declaration_does_not_satisfy_the_gate(tmp_path, reason):
    """A written reason, never a boolean (ADR-0031, ADR-0045). The sentence is the thing a reviewer
    can disagree with."""
    pack = _pack(tmp_path / str(reason), pages=[
        _page("https://gated.invalid/a", digest="sha256:aa", size=900,
              source=robots.SOURCE_REFUSED)])
    ok, _ = _check_robots_refusals(pack, {"robots_refusals": {"gated.invalid": reason}})
    assert not ok


def test_a_declaration_for_a_host_that_did_not_refuse_is_refused(tmp_path):
    pack = _pack(tmp_path)
    ok, why = _check_robots_refusals(pack, {"robots_refusals": {"never.invalid": "not true"}})
    assert not ok and "did not refuse" in why


def test_a_non_mapping_declaration_is_refused(tmp_path):
    pack = _pack(tmp_path, pages=[_page("https://gated.invalid/a", digest="sha256:aa", size=900,
                                        source=robots.SOURCE_REFUSED)])
    ok, why = _check_robots_refusals(pack, {"robots_refusals": ["gated.invalid"]})
    assert not ok and "must be a mapping" in why


def test_the_refusal_is_detected_in_every_manifest_list(tmp_path):
    """Anchors and gated pages are fetched too, so a refusal recorded on one of them is as real as
    one recorded on an injected page."""
    root = tmp_path / "lists"
    shutil.copytree(ACME, root)
    manifest_path = root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["tasks"]["gadget-fetch"][GATED_KEY] = [
        _page("https://gated.invalid/g", digest="sha256:gg", size=900,
              source=robots.SOURCE_REFUSED)]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    pack = Pack.load(root)
    assert "gated.invalid" in _refused_robots_hosts(pack)


# --- ADR-0053: a substitute page is not a document -------------------------- #

def test_two_urls_returning_the_same_substantial_page_are_refused(tmp_path):
    pack = _pack(tmp_path, pages=[
        _page("https://docs.invalid/one", digest="sha256:same", size=4207),
        _page("https://docs.invalid/two", digest="sha256:same", size=4207),
    ])
    ok, why = check_substitution(pack)
    assert not ok
    assert "substitute page" in why and "soft 404" in why


def test_one_url_cited_by_several_tasks_is_not_a_substitution(tmp_path):
    """The normal, correct case: a shared concept page belongs in every task that needs it."""
    root = tmp_path / "shared"
    shutil.copytree(ACME, root)
    manifest_path = root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    shared = _page("https://docs.invalid/concepts", digest="sha256:shared", size=4207)
    for entry in manifest["tasks"].values():
        entry["pages"] = [dict(shared)]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    ok, why = check_substitution(Pack.load(root))
    assert ok, why


def test_a_repeated_body_below_the_text_floor_is_left_to_adr_0021(tmp_path):
    """Two published packs carry exactly this shape — many distinct URLs whose client-rendered
    bodies extract to the same handful of bytes — and each page declares a written `short_text_ok`.
    Re-litigating that here would fail work that was disclosed correctly."""
    pack = _pack(tmp_path, pages=[
        _page("https://docs.invalid/one", digest="sha256:shell", size=MIN_TEXT_BYTES - 1),
        _page("https://docs.invalid/two", digest="sha256:shell", size=MIN_TEXT_BYTES - 1),
    ])
    ok, why = check_substitution(pack)
    assert ok, why


def test_the_floor_is_inclusive(tmp_path):
    """A page exactly at the floor is a document, so a collision at the floor is a substitution."""
    pack = _pack(tmp_path, pages=[
        _page("https://docs.invalid/one", digest="sha256:same", size=MIN_TEXT_BYTES),
        _page("https://docs.invalid/two", digest="sha256:same", size=MIN_TEXT_BYTES),
    ])
    ok, _ = check_substitution(pack)
    assert not ok


def test_distinct_documents_pass_and_the_message_counts_them(tmp_path):
    pack = _pack(tmp_path, pages=[
        _page("https://docs.invalid/one", digest="sha256:a", size=4207),
        _page("https://docs.invalid/two", digest="sha256:b", size=4207),
    ])
    ok, why = check_substitution(pack)
    assert ok and "2 distinct document(s)" in why


def test_an_unfetched_manifest_has_nothing_to_compare(tmp_path):
    """A pack before its first `fetch-docs` must not fail a gate about what it fetched."""
    pack = _pack(tmp_path, pages=[{"url": "https://docs.invalid/one", "role": "api-reference"}])
    ok, why = check_substitution(pack)
    assert ok and "nothing to compare" in why


def test_the_gate_reads_every_list_not_only_pages(tmp_path):
    """An anchor and an injected page that returned the same body is the same defect: the answer key
    and the context would both be pointing at a substitute."""
    root = tmp_path / "lists"
    shutil.copytree(ACME, root)
    manifest_path = root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    entry = manifest["tasks"]["gadget-fetch"]
    entry["pages"] = [_page("https://docs.invalid/page", digest="sha256:same", size=4207)]
    entry["anchors"] = [_page("https://docs.invalid/anchor", digest="sha256:same", size=4207)]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    ok, why = check_substitution(Pack.load(root))
    assert not ok, why
