"""An anchor is cited, a page is injected, and the two must never be the same list (ADR-0034).

Ground truth has to be traceable to a first-party artifact, and the model has to be shown the
vendor's documentation. Those were one list, so a pack could only cite what it was willing to inject.
For a vendor whose only citable artifact is its machine-readable spec, injecting it would hand the
model the answer key's own source — and the grid would look completely normal while measuring nothing.

The load-bearing test here is the negative one: an anchor must not reach a prompt. It is asserted on
the fully built message, not on an intermediate, because that string is what the model actually sees.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from core.conditions import PublicDocsCondition
from core.docs_fetch import manifest_urls
from core.factory import check_anchoring
from core.pack import Pack

ACME = Path(__file__).resolve().parent / "fixtures" / "pack-acme"

ANCHOR_URL = "https://specs.example.invalid/gadgets-openapi.json"
ANCHOR_TEXT = "UNIQUE-ANCHOR-BODY-b3f1 openapi 3.0.1 gadgets"
PAGE_URL = "https://docs.example.invalid/gadgets"


def _pack_citing_an_anchor(tmp_path: Path, *, declare_anchor: bool = True) -> Pack:
    """A copy of the fixture pack whose `gadget-fetch` task is doc-anchored to an artifact that is
    NOT in its injected pages. `declare_anchor=False` builds the same pack with the anchor undeclared,
    which is what makes the passing case non-vacuous."""
    root = tmp_path / "pack-anchored"
    shutil.copytree(ACME, root)

    task_path = root / "tasks" / "gadget-fetch.yaml"
    task = yaml.safe_load(task_path.read_text())
    endpoint = task["ground_truth"]["endpoints"][0]
    endpoint.pop("spec_ref", None)
    endpoint["coverage"] = "doc-only"
    endpoint["doc_ref"] = {"url": ANCHOR_URL, "note": "the vendor's own machine-readable document"}
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))

    manifest_path = root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    if declare_anchor:
        manifest["tasks"]["gadget-fetch"]["anchors"] = [
            {"url": ANCHOR_URL, "note": "cited, never shown", "byte_size": len(ANCHOR_TEXT)}
        ]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    pack = Pack.load(root)
    # Cache the anchor's text, so that if anything ever DID inject it the assertion would catch real
    # content rather than a missing file.
    cache = pack.cache_path_for("gadget-fetch", ANCHOR_URL)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(ANCHOR_TEXT)
    return pack


# --- anchoring resolves against anchors ------------------------------------ #

def test_an_endpoint_cited_to_a_declared_anchor_resolves(tmp_path):
    ok, detail = check_anchoring(_pack_citing_an_anchor(tmp_path))
    assert ok, detail


def test_the_same_endpoint_with_the_anchor_undeclared_does_not_resolve(tmp_path):
    """The non-vacuity half. Without this, the test above would pass just as well if `check_anchoring`
    had stopped checking doc_refs at all."""
    ok, detail = check_anchoring(_pack_citing_an_anchor(tmp_path, declare_anchor=False))
    assert not ok
    assert ANCHOR_URL in detail and "not in docs-manifest" in detail


def test_manifest_urls_can_tell_the_two_lists_apart(tmp_path):
    pack = _pack_citing_an_anchor(tmp_path)
    manifest = pack.docs_manifest()
    assert ANCHOR_URL in manifest_urls(manifest)
    assert ANCHOR_URL not in manifest_urls(manifest, include_anchors=False)
    assert PAGE_URL in manifest_urls(manifest, include_anchors=False)


# --- an anchor is never injected ------------------------------------------- #

def test_an_anchor_never_reaches_the_prompt(tmp_path):
    """The whole point of the ruling, asserted on the message the model is actually sent."""
    pack = _pack_citing_an_anchor(tmp_path)
    task = pack.tasks_by_id()["gadget-fetch"]
    messages = PublicDocsCondition(pack).build_messages(task)
    sent = "\n".join(m["content"] for m in messages)

    assert ANCHOR_URL not in sent, "the anchor's URL reached the prompt"
    assert ANCHOR_TEXT not in sent, "the anchor's CONTENT reached the prompt"


def test_a_page_still_does_reach_the_prompt(tmp_path):
    """The converse. A condition that injected nothing at all would pass the test above perfectly."""
    pack = _pack_citing_an_anchor(tmp_path)
    task = pack.tasks_by_id()["gadget-fetch"]
    sent = PublicDocsCondition(pack).build_messages(task)[0]["content"]
    assert PAGE_URL in sent


def test_the_unbudgeted_text_also_excludes_anchors(tmp_path):
    """`full_text` is the truncation audit's baseline. If anchors leaked in here the audit would
    report a path as 'documented' on the strength of a document nobody was shown."""
    pack = _pack_citing_an_anchor(tmp_path)
    assert ANCHOR_TEXT not in PublicDocsCondition(pack).full_text("gadget-fetch")


def test_a_task_whose_only_source_is_an_anchor_injects_nothing(tmp_path):
    """The shape a vendor with unreadable documentation actually has: everything cited, nothing shown.
    It must not raise — an empty docs condition is a finding, not a broken pack."""
    pack = _pack_citing_an_anchor(tmp_path)
    manifest_path = pack.root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["tasks"]["gadget-fetch"]["pages"] = []
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    sent = PublicDocsCondition(Pack.load(pack.root)).build_messages(
        pack.tasks_by_id()["gadget-fetch"])[0]["content"]
    assert ANCHOR_TEXT not in sent and ANCHOR_URL not in sent
    assert "How do I fetch a single gadget" in sent


# --- anchors are still fetched, because an unverified citation is a claim --- #

def test_fetch_all_retrieves_anchors_as_well_as_pages(tmp_path, monkeypatch):
    from core import docs_fetch

    fetched: list[str] = []

    def _fake(url, **_kw):
        fetched.append(url)
        return f"<html><body>{'documentation body ' * 30}</body></html>"

    monkeypatch.setattr(docs_fetch, "_fetch_with_retry", _fake)
    pack = _pack_citing_an_anchor(tmp_path)
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir, today="2026-01-01")

    assert ANCHOR_URL in fetched, "an anchor was cited but never verified"
    assert PAGE_URL in fetched

    manifest = yaml.safe_load((pack.root / "docs-manifest.yaml").read_text())
    anchor = manifest["tasks"]["gadget-fetch"]["anchors"][0]
    assert anchor["byte_size"] > 0 and anchor["content_hash"].startswith("sha256:")


# --- the packs on disk are unaffected -------------------------------------- #

@pytest.mark.parametrize("pack_dir", [ACME], ids=lambda p: p.name)
def test_a_pack_that_declares_no_anchors_is_unchanged(pack_dir):
    """`anchors` is optional and absent everywhere today; adding the key must change nothing for a
    pack that does not use it."""
    pack = Pack.load(pack_dir)
    manifest = pack.docs_manifest()
    assert manifest_urls(manifest) == manifest_urls(manifest, include_anchors=False)
    assert check_anchoring(pack)[0]
