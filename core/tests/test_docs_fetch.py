"""Tests for docs fetching + manifest population (core/docs_fetch.py).

Network is mocked; verifies caching, deterministic hashing, byte_size, and that a
fetch error is recorded per page without aborting the run. The cache dir is passed in.
"""
import hashlib

import yaml

from core import docs_fetch


def _page(body: str = "reference text") -> str:
    """A page whose EXTRACTED text clears the ADR-0021 floor.

    These fixtures exercise hashing, provenance and pacing, not text length, so they are
    padded to look like the smallest real reference page rather than left as a bare `<p>`.
    Anything under MIN_TEXT_BYTES is now a recorded fetch error, which is the subject of its
    own tests below.
    """
    return (
        f"<h1>{body}</h1><p>This endpoint returns the requested resource. "
        "Supported query parameters are fields, filter, sort, pageSize and pageOffset. "
        "The caller must present a bearer token. A 200 response carries the resource in "
        "the data member; a 404 is returned when the identifier does not resolve.</p>"
    )


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
                        lambda url, timeout=30, user_agent=None: _page(f"text for {url}"))
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

    def boom(url, timeout=30, user_agent=None):
        if "accounts" in url:
            raise RuntimeError("404 not found")
        return _page("ok")

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


def test_default_user_agent_is_the_self_identifying_one(tmp_path, monkeypatch):
    """No override => the honest default agent, and no provenance key on the page."""
    seen = []
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: seen.append(user_agent) or _page())
    mpath = _write_manifest(tmp_path)

    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-23")

    assert seen == [None, None]
    page = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
    assert "fetched_with_user_agent" not in page


def test_user_agent_override_is_used_and_recorded(tmp_path, monkeypatch):
    """A pack may declare a fetch UA for a docs host that bot-gates the default (ADR-0007).

    The override must reach the transport AND be written into the manifest, so a snapshot
    taken under an override is never silently mistaken for a default-agent one.
    """
    seen = []
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: seen.append(user_agent) or _page())
    mpath = _write_manifest(tmp_path)

    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-23", user_agent="Mozilla/5.0 (test)")

    assert seen == ["Mozilla/5.0 (test)", "Mozilla/5.0 (test)"]
    for page in yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"]:
        assert page["fetched_with_user_agent"] == "Mozilla/5.0 (test)"


def test_request_carries_the_user_agent_header(monkeypatch):
    """_fetch itself must put the agent on the wire — the header, not just the parameter."""
    captured = {}

    class _Resp:
        headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

        def read(self):
            return b"<p>x</p>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        captured["ua"] = req.get_header("User-agent")
        return _Resp()

    monkeypatch.setattr(docs_fetch.urllib.request, "urlopen", fake_urlopen)

    docs_fetch._fetch("https://d/x")
    assert captured["ua"] == docs_fetch.USER_AGENT

    docs_fetch._fetch("https://d/x", user_agent="Mozilla/5.0 (test)")
    assert captured["ua"] == "Mozilla/5.0 (test)"


def test_pack_reads_public_docs_user_agent(tmp_path):
    """pack.yaml public_docs.user_agent surfaces on the Pack; absent/blank => None."""
    from core.pack import Pack

    def _mk(name, pd):
        d = tmp_path / name
        d.mkdir()
        (d / "pack.yaml").write_text(yaml.safe_dump({"vendor": {"id": name}, "public_docs": pd}))
        return Pack.load(d)

    assert _mk("a", {"user_agent": "Mozilla/5.0 (test)"}).public_docs_user_agent == "Mozilla/5.0 (test)"
    assert _mk("b", {"source_label": "docs"}).public_docs_user_agent is None
    assert _mk("c", {"user_agent": ""}).public_docs_user_agent is None


def test_empty_body_on_a_success_status_is_an_error_not_a_snapshot(monkeypatch):
    """A 2xx with a zero-length body is a throttle, not a document (ADR-0009).

    A measured vendor's support portal answers HTTP 202 with 0 bytes when it throttles an
    automated reader. Hashing that would record an empty page as a valid snapshot and
    silently gut the public-docs condition.
    """
    class _Resp:
        status = 202
        headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(docs_fetch.urllib.request, "urlopen", lambda req, timeout=30: _Resp())

    try:
        docs_fetch._fetch("https://d/x")
    except docs_fetch.EmptyDocument as exc:
        assert "202" in str(exc)
    else:
        raise AssertionError("an empty body must not be returned as page text")


def test_throttled_page_is_retried_then_recorded_as_an_error(tmp_path, monkeypatch):
    """Retry only the throttle, and record it honestly when it does not clear."""
    calls = []
    slept = []

    def always_empty(url, timeout=30, user_agent=None):
        calls.append(url)
        raise docs_fetch.EmptyDocument("HTTP 202 with an empty body")

    monkeypatch.setattr(docs_fetch, "_fetch", always_empty)
    mpath = _write_manifest(tmp_path)

    summary = docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-24",
                                   retries=3, sleep=slept.append)

    assert len(calls) == 6           # 2 pages x 3 attempts
    assert slept and all(s > 0 for s in slept)
    assert all(s[2].startswith("error") for pages in summary.values() for s in pages)
    for page in yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"]:
        assert page["content_hash"] is None
        assert page["byte_size"] == 0
        assert "202" in page["fetch_error"]


def test_a_throttle_that_clears_is_fetched_normally(tmp_path, monkeypatch):
    """A page that succeeds on retry is a normal snapshot — no error residue."""
    state = {"n": 0}

    def flaky(url, timeout=30, user_agent=None):
        state["n"] += 1
        if state["n"] == 1:
            raise docs_fetch.EmptyDocument("HTTP 202 with an empty body")
        return _page("real reference text")

    monkeypatch.setattr(docs_fetch, "_fetch", flaky)
    mpath = _write_manifest(tmp_path)

    summary = docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-24", sleep=lambda s: None)

    assert all(s[2] == "ok" for pages in summary.values() for s in pages)
    page = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
    assert page["byte_size"] > 0
    assert "fetch_error" not in page


def test_a_real_error_is_not_retried(tmp_path, monkeypatch):
    """A 404 is a fact about the page; retrying it would only slow the run down."""
    calls = []

    def not_found(url, timeout=30, user_agent=None):
        calls.append(url)
        raise RuntimeError("404 not found")

    monkeypatch.setattr(docs_fetch, "_fetch", not_found)
    mpath = _write_manifest(tmp_path)

    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-24", sleep=lambda s: None)

    assert len(calls) == 2           # 2 pages, one attempt each


def test_declared_delay_paces_pages_but_never_leads(tmp_path, monkeypatch):
    """The delay separates pages; it must not pause before the first fetch."""
    order = []
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: order.append(("fetch", url)) or _page())
    mpath = _write_manifest(tmp_path)

    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-24",
                         delay_seconds=7, sleep=lambda s: order.append(("sleep", s)))

    assert order[0][0] == "fetch"
    assert ("sleep", 7) in order
    assert [o for o in order if o[0] == "sleep"] == [("sleep", 7)]   # one gap between two pages


def test_pack_reads_public_docs_fetch_delay(tmp_path):
    """pack.yaml public_docs.fetch_delay_seconds surfaces on the Pack; absent => 0."""
    from core.pack import Pack

    def _mk(name, pd):
        d = tmp_path / name
        d.mkdir()
        (d / "pack.yaml").write_text(yaml.safe_dump({"vendor": {"id": name}, "public_docs": pd}))
        return Pack.load(d)

    assert _mk("a", {"fetch_delay_seconds": 8}).public_docs_fetch_delay_seconds == 8.0
    assert _mk("b", {"source_label": "docs"}).public_docs_fetch_delay_seconds == 0.0


def test_slug_is_filesystem_safe():
    slug = docs_fetch.slug_for("https://docs.example.invalid/api/standard-collection-parameters")
    assert "/" not in slug
    assert slug.endswith("standard-collection-parameters")


# --- ADR-0021: the floor is on extracted text, not the raw body --------------------------

# What a client-rendered reference page actually delivers: tens of kilobytes of script and
# markup wrapping a single navigation crumb. Non-empty as bytes, empty as documentation.
_CLIENT_RENDERED = (
    "<!doctype html><html><head><title>GET /activities</title></head><body>"
    "<a href='#main'>Skip to main content</a><div id='__docusaurus'></div>"
    "<script>" + "var chunk=1;" * 4000 + "</script></body></html>"
)


def test_a_page_that_renders_to_a_nav_crumb_is_an_error_not_a_snapshot(tmp_path, monkeypatch):
    """The raw body is fine and the documentation is absent — ADR-0009 cannot see this.

    A measured vendor's operation reference answers HTTP 200 with ~36 KB and extracts to
    "Skip to main content". Left alone it hashes cleanly, records a plausible byte_size and
    a unique content_hash, and feeds the public-docs condition nothing at all.
    """
    assert len(_CLIENT_RENDERED.encode()) > 40_000            # the body is emphatically not empty
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: _CLIENT_RENDERED)
    mpath = _write_manifest(tmp_path)

    summary = docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-25",
                                   sleep=lambda s: None)

    assert all(s[2].startswith("error") for pages in summary.values() for s in pages)
    for page in yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"]:
        assert page["content_hash"] is None
        assert page["byte_size"] == 0
        assert "under the 200 B floor" in page["fetch_error"]


def test_the_render_floor_is_never_retried(tmp_path, monkeypatch):
    """A throttle clears; a client-rendered page does not. Only one of them is worth waiting for.

    ADR-0009's schedule reaches a 180s gap before giving up. Spending that on a page which
    will render client-side again in three minutes is nine wasted minutes per page, so the
    check deliberately lives after `_fetch_with_retry` returns rather than inside it.
    """
    calls, slept = [], []

    def rendered(url, timeout=30, user_agent=None):
        calls.append(url)
        return _CLIENT_RENDERED

    monkeypatch.setattr(docs_fetch, "_fetch", rendered)
    mpath = _write_manifest(tmp_path)

    docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-25", sleep=slept.append)

    assert len(calls) == 2          # 2 pages, one attempt each — not 2 x DEFAULT_RETRIES
    assert slept == []              # and not one second of backoff


def test_a_declared_reason_keeps_a_short_page_and_records_why(tmp_path, monkeypatch):
    """The tolerance is opt-in and argued, like ADR-0007's user_agent and ADR-0017's prefix.

    A pack that knows its vendor's reference renders client-side may still anchor to those
    pages — one carded pack has every page unfetchable — but it has to say so in the
    manifest, where a reader of the committed record can see it.
    """
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: _CLIENT_RENDERED)
    m = yaml.safe_load(_write_manifest(tmp_path).read_text())
    reason = "operation reference renders client-side; anchored for provenance, not for text"
    m["tasks"]["t1"]["pages"][0]["short_text_ok"] = reason
    mpath = tmp_path / "manifest.yaml"
    mpath.write_text(yaml.safe_dump(m, sort_keys=False))

    summary = docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-25",
                                   sleep=lambda s: None)

    assert [s[2] for s in summary["t1"]][0] == "ok"           # declared: kept
    assert [s[2] for s in summary["t1"]][1].startswith("error")   # undeclared: still an error
    kept = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
    assert kept["short_text_ok"] == reason                    # the argument survives into the record
    assert kept["byte_size"] < docs_fetch.MIN_TEXT_BYTES      # and the number is not massaged
    assert kept["content_hash"].startswith("sha256:")


def test_an_override_with_no_argument_behind_it_is_rejected(tmp_path, monkeypatch):
    """`short_text_ok: true` is a waiver with nothing on the record; blank is the same.

    Accepting a bare boolean would turn a documented exception into a silent one, which is
    the failure mode ADR-0015 exists to catch: a tolerance nobody has to justify decays into
    a tolerance nobody remembers granting.
    """
    monkeypatch.setattr(docs_fetch, "_fetch",
                        lambda url, timeout=30, user_agent=None: _CLIENT_RENDERED)
    for bad in (True, "", "   "):
        m = yaml.safe_load(_write_manifest(tmp_path).read_text())
        m["tasks"]["t1"]["pages"][0]["short_text_ok"] = bad
        mpath = tmp_path / "manifest.yaml"
        mpath.write_text(yaml.safe_dump(m, sort_keys=False))

        summary = docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-25",
                                       sleep=lambda s: None)

        assert summary["t1"][0][2].startswith("error"), f"{bad!r} must not pass as a reason"
        page = yaml.safe_load(mpath.read_text())["tasks"]["t1"]["pages"][0]
        assert "non-empty reason" in page["fetch_error"]


def test_the_floor_is_a_floor_and_not_a_haircut(tmp_path, monkeypatch):
    """Exactly MIN_TEXT_BYTES passes; one byte less does not. Pins the boundary both ways."""
    from core.html_text import html_to_text

    def page_of(n_bytes):
        html = "<p>" + "a" * n_bytes + "</p>"
        pad = n_bytes - len(html_to_text(html).encode())
        return "<p>" + "a" * (n_bytes + pad) + "</p>"

    at_floor = page_of(docs_fetch.MIN_TEXT_BYTES)
    assert len(html_to_text(at_floor).encode()) == docs_fetch.MIN_TEXT_BYTES
    under = page_of(docs_fetch.MIN_TEXT_BYTES - 1)

    for html, expected in ((at_floor, "ok"), (under, "error")):
        monkeypatch.setattr(docs_fetch, "_fetch",
                            lambda url, timeout=30, user_agent=None, _h=html: _h)
        mpath = _write_manifest(tmp_path)
        summary = docs_fetch.fetch_all(mpath, tmp_path / "cache", today="2026-07-25",
                                       sleep=lambda s: None)
        assert summary["t1"][0][2].startswith(expected), \
            f"{len(html_to_text(html).encode())} B should be {expected}"
