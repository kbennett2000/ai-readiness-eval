"""Tests for docs fetching + manifest population (core/docs_fetch.py).

Network is mocked; verifies caching, deterministic hashing, byte_size, and that a
fetch error is recorded per page without aborting the run. The cache dir is passed in.
"""
import hashlib

import yaml

from core import docs_fetch


def _write_manifest(tmp_path):
    m = {
        "budget_tokens": 15000,
        "tasks": {
            "t1": {"pages": [
                {"url": "https://d/api/authentication", "role": "getting-started", "note": "n"},
                {"url": "https://d/api/accounts", "role": "api-reference", "note": "n"},
            ]},
        },
    }
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.safe_dump(m, sort_keys=False))
    return p


def test_fetch_populates_hash_and_size(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30: f"<p>text for {url}</p>")
    mpath = _write_manifest(tmp_path)

    summary = docs_fetch.fetch_all(mpath, cache_dir, today="2026-07-23")

    assert all(s[2] == "ok" for pages in summary.values() for s in pages)
    m = yaml.safe_load(mpath.read_text())
    page = m["tasks"]["t1"]["pages"][0]
    assert page["fetch_date"] == "2026-07-23"
    assert page["content_hash"].startswith("sha256:")
    assert page["byte_size"] > 0
    # hash matches the cached text exactly
    cache_file = cache_dir / "t1" / (docs_fetch.slug_for(page["url"]) + ".txt")
    text = cache_file.read_text()
    assert page["content_hash"] == "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    assert page["byte_size"] == len(text.encode())


def test_fetch_error_recorded_not_fatal(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"

    def boom(url, timeout=30):
        if "accounts" in url:
            raise RuntimeError("404 not found")
        return "<p>ok</p>"

    monkeypatch.setattr(docs_fetch, "_fetch", boom)
    mpath = _write_manifest(tmp_path)

    summary = docs_fetch.fetch_all(mpath, cache_dir, today="2026-07-23")
    statuses = [s[2] for s in summary["t1"]]
    assert any(st == "ok" for st in statuses)
    assert any(st.startswith("error") for st in statuses)
    m = yaml.safe_load(mpath.read_text())
    bad = m["tasks"]["t1"]["pages"][1]
    assert bad["content_hash"] is None
    assert "fetch_error" in bad


def test_slug_is_filesystem_safe():
    slug = docs_fetch.slug_for("https://docs.example.invalid/api/standard-collection-parameters")
    assert "/" not in slug
    assert slug.endswith("standard-collection-parameters")
