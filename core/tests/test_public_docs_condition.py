"""Tests for the public-docs condition (core/conditions.py).

Uses a temp cache + in-memory manifest via the synthetic pack; no network. Verifies context assembly,
the answer contract, budget truncation (priority order), and missing-cache errors. The docs source
label is pack-supplied.
"""
import pytest

from core.conditions import PublicDocsCondition


@pytest.fixture
def pack(acme_pack, tmp_path, monkeypatch):
    """Acme pack with its docs cache redirected to a temp dir."""
    monkeypatch.setattr(acme_pack, "docs_cache_dir", tmp_path / "cache")
    return acme_pack


@pytest.fixture
def cache(pack):
    """Return a writer that stores text where the pack expects the cache file."""
    def write(task_id, url, text):
        p = pack.cache_path_for(task_id, url)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return write


LABEL = "Acme's official documentation"


def _manifest(pages, budget=15000):
    return {"budget_tokens": budget, "tasks": {"t": {"pages": pages}}}


def _task():
    return {"id": "t", "prompt": "How do I do the thing?"}


def test_context_includes_labels_and_text(pack, cache):
    cache("t", "https://d/api/authentication", "AUTH GUIDE TEXT")
    cache("t", "https://d/api/accounts", "ACCOUNTS REF TEXT")
    cond = PublicDocsCondition(pack, _manifest([
        {"url": "https://d/api/authentication", "role": "getting-started"},
        {"url": "https://d/api/accounts", "role": "api-reference"},
    ]))
    ctx = cond.build_context("t")
    assert "AUTH GUIDE TEXT" in ctx
    assert "ACCOUNTS REF TEXT" in ctx
    assert f"{LABEL}: https://d/api/accounts" in ctx


def test_build_messages_appends_answer_contract(pack, cache):
    cache("t", "https://d/api/authentication", "AUTH")
    cond = PublicDocsCondition(pack, _manifest([
        {"url": "https://d/api/authentication", "role": "getting-started"},
    ]))
    msgs = cond.build_messages(_task())
    content = msgs[0]["content"]
    assert "answer-summary" in content          # the scoring contract
    assert "How do I do the thing?" in content   # the task prompt
    assert "AUTH" in content                      # the injected docs


def test_missing_cache_raises(pack, cache):
    cond = PublicDocsCondition(pack, _manifest([
        {"url": "https://d/api/authentication", "role": "getting-started"},
    ]))
    with pytest.raises(FileNotFoundError):
        cond.build_context("t")  # nothing written to cache


def test_unfetchable_page_injects_nothing_not_error(pack, cache):
    # A page the manifest records as unfetchable (dead portal / empty SPA) has no cache file, but
    # must NOT crash the condition — it injects nothing, modelling what a real fetch retrieves.
    cond = PublicDocsCondition(pack, _manifest([
        {"url": "https://d/dead-portal", "role": "api-reference",
         "fetch_error": "urlopen error: No address associated with hostname", "byte_size": 0},
    ]))
    ctx = cond.build_context("t")  # does not raise
    assert "dead-portal" not in ctx          # the unfetchable page contributes no text
    assert pack.public_docs_source_label in ctx  # the wrapper/label is still present


def test_mix_of_fetchable_and_unfetchable_pages(pack, cache):
    # One real page + one unfetchable page: the real content is injected, the dead page is skipped.
    cache("t", "https://d/api/authentication", "REAL AUTH SPEC")
    cond = PublicDocsCondition(pack, _manifest([
        {"url": "https://d/api/authentication", "role": "getting-started", "byte_size": 14},
        {"url": "https://d/dead-portal", "role": "api-reference", "fetch_error": "dns fail", "byte_size": 0},
    ]))
    ctx = cond.build_context("t")
    assert "REAL AUTH SPEC" in ctx
    assert "dead-portal" not in ctx


def test_budget_drops_lowest_priority_first(pack, cache):
    # api-reference (highest priority) must survive; getting-started dropped when over budget
    cache("t", "https://d/api/authentication", "G" * 4000)   # getting-started
    cache("t", "https://d/api/accounts", "R" * 400)          # api-reference
    # budget ~120 tokens => ~480 chars: only the small api-reference fits (+ header)
    cond = PublicDocsCondition(pack, _manifest([
        {"url": "https://d/api/authentication", "role": "getting-started"},
        {"url": "https://d/api/accounts", "role": "api-reference"},
    ], budget=120))
    ctx = cond.build_context("t")
    assert "RRRR" in ctx                     # api-reference kept
    assert "GGGG" not in ctx                 # getting-started dropped (lowest priority)


def test_budget_truncates_tail_of_last_page(pack, cache):
    cache("t", "https://d/api/accounts", "R" * 100000)
    cond = PublicDocsCondition(pack, _manifest([
        {"url": "https://d/api/accounts", "role": "api-reference"},
    ], budget=200))  # ~800 chars
    ctx = cond.build_context("t")
    assert "truncated to fit context budget" in ctx
    assert len(ctx) < 2000
