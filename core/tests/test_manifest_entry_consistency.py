"""ADR-0056 — a manifest entry may not record a retrieval and its own failure at once.

Found by reading a published card's evidence rather than by any gate. All ten `anchors` on one pack
carried `fetch_error: HTTP Error 403: Forbidden` beside the `content_hash`, `byte_size` and
`cache_file` of a fetch that plainly succeeded. The cause is in the fetcher, not the pack: every
success field is overwritten on a re-fetch, and `fetch_error` was the one field only the FAILURE
path ever wrote — so it survived. ADR-0051's two-agent measurement fetches the same URL twice by
design, which is what made a latent bug certain.

Nothing scores or injects `fetch_error`, so no published number moves in either direction. What was
wrong is what a reviewer sees: the anchor a ground-truth citation rests on, declared unreadable in
the same breath as the proof it was read.

Two halves, and both are needed. The fetcher fix stops the state being produced; the validator
refuses it wherever it already sits — including from a hand edit, which no fetcher fix can reach.
The tests below break each rule on purpose in both directions.
"""
import shutil

import pytest
import yaml

from core import docs_fetch, validate
from core.pack import Pack

OK = "sha256:" + "a" * 64


def _entry(**over):
    base = {"url": "https://d.test/api/accounts", "role": "api-reference", "note": "n",
            "content_hash": OK, "byte_size": 4073, "cache_file": "docs-cache/t1/accounts.txt"}
    base.update(over)
    return base


def _pack_with(tmp_path, acme_pack, entry, key="anchors"):
    """A writable pack copy whose manifest holds exactly one entry, in one list."""
    dst = tmp_path / "pack"
    shutil.copytree(acme_pack.root, dst)
    pack = Pack.load(dst)
    manifest = {"budget_tokens": 15000, "tasks": {"t1": {key: [entry]}}}
    pack.docs_manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return pack


# --------------------------------------------------------------------------------------------- #
# The validator refuses the contradiction, in every list the fetcher writes.
# --------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", docs_fetch.ENTRY_KEYS)
def test_a_success_record_carrying_a_fetch_error_is_refused_in_every_list(tmp_path, acme_pack, key):
    """Parametrized over ENTRY_KEYS itself, so a fifth list cannot be added past this rule."""
    pack = _pack_with(tmp_path, acme_pack, _entry(fetch_error="HTTP Error 403: Forbidden"), key=key)
    errors = validate.validate_docs_manifest(pack)
    assert len(errors) == 1
    assert "may not be both" in errors[0]
    assert key in errors[0] and "accounts" in errors[0]


def test_the_contradiction_blocks_at_the_validate_gate_not_only_in_a_helper(tmp_path, acme_pack):
    pack = _pack_with(tmp_path, acme_pack, _entry(fetch_error="HTTP Error 403: Forbidden"))
    results = validate.validate_pack(pack)
    assert results.get("(docs-manifest)"), results
    assert any("may not be both" in e for e in results["(docs-manifest)"])


def test_a_cache_file_without_a_hash_is_refused(tmp_path, acme_pack):
    """The mirror: an entry attesting no content may not point at content."""
    pack = _pack_with(tmp_path, acme_pack, _entry(content_hash=None, byte_size=0))
    errors = validate.validate_docs_manifest(pack)
    assert len(errors) == 1 and "does not vouch for" in errors[0]


# --------------------------------------------------------------------------------------------- #
# ...and accepts every legitimate shape, or it blocks the cohort.
# --------------------------------------------------------------------------------------------- #

def test_a_clean_success_record_is_not_refused(tmp_path, acme_pack):
    assert validate.validate_docs_manifest(_pack_with(tmp_path, acme_pack, _entry())) == []


def test_an_honest_failure_record_is_not_refused(tmp_path, acme_pack):
    """A 403 with no content fields is the whole point of recording a refusal (ADR-0052)."""
    entry = _entry(content_hash=None, byte_size=0, fetch_error="HTTP Error 403: Forbidden")
    entry.pop("cache_file")
    assert validate.validate_docs_manifest(_pack_with(tmp_path, acme_pack, entry)) == []


def test_a_pack_with_no_manifest_is_not_a_problem(tmp_path, acme_pack):
    """Most packs in the cohort have no docs condition; this rule must not invent one."""
    dst = tmp_path / "pack"
    shutil.copytree(acme_pack.root, dst)
    pack = Pack.load(dst)
    pack.docs_manifest_path.unlink()
    assert validate.validate_docs_manifest(pack) == []


def test_the_real_reference_pack_still_validates(acme_pack):
    assert validate.validate_docs_manifest(acme_pack) == []


# --------------------------------------------------------------------------------------------- #
# The fetcher cannot produce the state any more. This is the half that stops it recurring.
# --------------------------------------------------------------------------------------------- #

def _doc(text):
    return docs_fetch.Document(text=text, kind="html", extracted_by=None)


def _body(name):
    return (f"<h1>{name}</h1><p>This endpoint returns the requested resource. Supported query "
            "parameters are fields, filter, sort, pageSize and pageOffset. The caller must present "
            "a bearer token. A 200 response carries the resource in the data member.</p>")


def _manifest(tmp_path, page):
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.safe_dump({"budget_tokens": 15000, "tasks": {"t1": {"pages": [page]}}},
                                sort_keys=False))
    return p


def test_a_successful_refetch_clears_the_previous_attempts_error(tmp_path, monkeypatch):
    """The exact sequence that produced the published state: fail under one agent, then succeed."""
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: _doc(_body("accounts")))
    mpath = _manifest(tmp_path, {"url": "https://d.test/api/accounts", "role": "api-reference",
                                 "note": "n", "content_hash": None, "byte_size": 0,
                                 "fetch_error": "HTTP Error 403: Forbidden"})

    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-08-04")

    page = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
    assert page["content_hash"].startswith("sha256:") and page["byte_size"] > 0
    assert "fetch_error" not in page, "the success path left the failed attempt's error behind"


def test_a_failed_refetch_drops_a_cache_file_it_no_longer_vouches_for(tmp_path, monkeypatch):
    def boom(url, timeout=30, user_agent=None):
        raise RuntimeError("HTTP Error 500: Server Error")

    monkeypatch.setattr(docs_fetch, "_fetch", boom)
    mpath = _manifest(tmp_path, {"url": "https://d.test/api/accounts", "role": "api-reference",
                                 "note": "n", "content_hash": OK, "byte_size": 4073,
                                 "cache_file": "docs-cache/t1/accounts.txt"})

    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-08-04")

    page = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
    assert page["content_hash"] is None and page["fetch_error"]
    assert "cache_file" not in page


def test_the_fetchers_output_passes_the_validator_in_both_directions(tmp_path, monkeypatch, acme_pack):
    """The two halves must agree: whatever the fetcher writes, the validator must accept.

    A fetcher fix and a validator written from the same misunderstanding would both be green and
    still disagree about what a manifest means. This is the only test that checks them against
    each other rather than each against a hand-built fixture.
    """
    calls = {"n": 0}

    def flaky(url, timeout=30, user_agent=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTP Error 403: Forbidden")
        return _doc(_body("accounts"))

    monkeypatch.setattr(docs_fetch, "_fetch", flaky)
    mpath = _manifest(tmp_path, {"url": "https://d.test/api/accounts", "role": "api-reference",
                                 "note": "n"})

    for _ in range(2):                                    # first run fails, second succeeds
        docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-08-04", sleep=lambda s: None)
        dst = tmp_path / "pack"
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(acme_pack.root, dst)
        pack = Pack.load(dst)
        pack.docs_manifest_path.write_text(mpath.read_text())
        assert validate.validate_docs_manifest(pack) == [], "the fetcher wrote what the gate refuses"
