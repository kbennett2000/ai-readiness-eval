"""The rule that actually binds: a Disallowed URL is never opened (ADR-0036).

Annotating a manifest is a disclosure. Refusing the request is the conduct. This file asserts the
conduct, on the path that does the fetching, and it asserts it as a NEGATIVE — the fetcher is never
called — because "we recorded that we were not allowed to" and "we did not do it" are different claims
and only the second one is the ruling.

Every case pairs with its converse. A fetcher that fetched nothing at all, or a condition that injected
nothing at all, would satisfy the negative half perfectly.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from core import docs_fetch, robots
from core.conditions import PublicDocsCondition
from core.pack import Pack

ACME = Path(__file__).resolve().parent / "fixtures" / "pack-acme"

ALLOWED_URL = "https://docs.example.invalid/widgets"
DISALLOWED_URL = "https://docs.example.invalid/auth"
BODY = "documentation body " * 40


def _policy_for(url: str) -> robots.RobotsPolicy:
    """Everything on the host is allowed except /auth — one rule, so the difference between the two
    URLs is the policy and nothing else."""
    return robots.policy_from_response(
        "docs.example.invalid", 200, "User-agent: *\nAllow: /\nDisallow: /auth\n",
        today="2026-01-01")


@pytest.fixture()
def pack(tmp_path) -> Pack:
    root = tmp_path / "pack-acme"
    shutil.copytree(ACME, root)
    return Pack.load(root)


@pytest.fixture()
def fetched(monkeypatch) -> list:
    """Records every URL the network layer was asked for. Empty is the assertion, not the absence."""
    calls: list[str] = []

    def fake(url, **_kw):
        calls.append(url)
        return f"<html><body>{BODY}</body></html>"

    monkeypatch.setattr(docs_fetch, "_fetch_with_retry", fake)
    return calls


# --- the refusal ------------------------------------------------------------ #

def test_a_disallowed_url_is_never_requested(pack, fetched):
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir,
                         today="2026-01-01", policy_for=_policy_for)
    assert DISALLOWED_URL not in fetched, "the harness opened a URL its host disallowed"


def test_an_allowed_url_on_the_same_host_still_is(pack, fetched):
    """The converse. Without it, a fetch_all that had simply stopped working would pass above."""
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir,
                         today="2026-01-01", policy_for=_policy_for)
    assert ALLOWED_URL in fetched


def test_no_cache_file_is_written_for_a_disallowed_url(pack, fetched):
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir,
                         today="2026-01-01", policy_for=_policy_for)
    assert not docs_fetch.cache_path_for(pack.docs_cache_dir, "widget-list", DISALLOWED_URL).exists()
    assert docs_fetch.cache_path_for(pack.docs_cache_dir, "widget-list", ALLOWED_URL).exists()


def test_the_refusal_is_recorded_on_the_page_it_refused(pack, fetched):
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir,
                         today="2026-01-01", policy_for=_policy_for)
    manifest = yaml.safe_load((pack.root / "docs-manifest.yaml").read_text())
    pages = {p["url"]: p for p in manifest["tasks"]["widget-list"]["pages"]}

    refused = pages[DISALLOWED_URL]
    assert refused["robots_disallowed"] is True
    assert refused["robots_rule"] == "Disallow: /auth"
    assert refused["robots_source"] == robots.SOURCE_RULES
    assert refused["byte_size"] == 0 and refused["content_hash"] is None
    assert "robots-disallowed" in refused["fetch_error"]

    kept = pages[ALLOWED_URL]
    assert kept["robots_disallowed"] is False
    # An allowed page records the directive that permitted it, not a blank. The host said `Allow: /`
    # and the record says so, which is what makes the verdict re-checkable rather than asserted.
    assert kept["robots_rule"] == "Allow: /"
    assert kept["byte_size"] > 0


def test_a_disallowed_page_never_reaches_a_built_prompt(pack, fetched):
    """Asserted on the message the model is actually sent, like ADR-0034's anchor test."""
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir,
                         today="2026-01-01", policy_for=_policy_for)
    reloaded = Pack.load(pack.root)
    task = reloaded.tasks_by_id()["widget-list"]
    sent = "\n".join(m["content"] for m in PublicDocsCondition(reloaded).build_messages(task))

    assert DISALLOWED_URL not in sent, "a URL we may not fetch was named to the model"
    assert ALLOWED_URL in sent, "the allowed page did not reach the prompt either"


def test_an_unreachable_robots_txt_stops_the_whole_host(pack, fetched):
    """§2.3.1.4. This is the branch where refusing is expensive, which is why it is pinned."""
    def unreachable(_url):
        return robots.policy_from_response("docs.example.invalid", 503, "", today="2026-01-01")

    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir,
                         today="2026-01-01", policy_for=unreachable)
    assert fetched == [], "a host whose robots.txt could not be read was fetched anyway"


def test_the_pacing_delay_is_not_spent_on_a_url_we_will_not_open(pack, fetched):
    """A refused URL costs the host nothing — not a request, and not a delay slot either."""
    slept: list[float] = []
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir,
                         today="2026-01-01", policy_for=_policy_for,
                         delay_seconds=5, sleep=slept.append)
    # 4 manifest URLs, 1 refused, and the first fetched page is not paced → 2 sleeps, not 3.
    assert len(slept) == 2


# --- a rewrite must not delete the record it is written into ---------------- #

HEADER = ("# FINDING (cycle 3): this docs host does not resolve from any environment tested.\n"
          "# CYCLE-4 CLOSEOUT: re-attempted from additional vantage points and CONFIRMED.\n")


def _with_header(pack: Pack) -> Path:
    path = pack.root / "docs-manifest.yaml"
    path.write_text(HEADER + path.read_text())
    return path


def test_fetching_preserves_a_manifests_comment_header(pack, fetched):
    """`yaml.safe_dump` does not round-trip comments, so every rewrite was silently deleting them.
    One pack's manifest opens with 21 lines recording, across two cycles, why its docs host is
    unreachable — a finding, living in the file the finding is about."""
    path = _with_header(pack)
    docs_fetch.fetch_all(path, pack.docs_cache_dir, today="2026-01-01", policy_for=_policy_for)
    assert path.read_text().startswith(HEADER)
    assert yaml.safe_load(path.read_text())["tasks"], "the header survived but the document did not"


def test_annotating_preserves_a_manifests_comment_header(pack):
    from core.robots import annotate_manifest

    path = _with_header(pack)
    annotate_manifest(path, today="2026-01-01", policy_for=lambda u: _policy_for(u))
    assert path.read_text().startswith(HEADER)
    assert yaml.safe_load(path.read_text())["tasks"]


def test_a_manifest_with_no_header_gains_none(pack, fetched):
    """The converse: preservation must not invent a leading blank or a stray line."""
    path = pack.root / "docs-manifest.yaml"
    before = path.read_text()
    docs_fetch.fetch_all(path, pack.docs_cache_dir, today="2026-01-01", policy_for=_policy_for)
    assert not path.read_text().startswith("\n")
    assert before.splitlines()[0].split(":")[0] == path.read_text().splitlines()[0].split(":")[0]


# --- the default path consults the real policy module ----------------------- #

def test_fetch_all_consults_robots_when_no_policy_is_injected(pack, fetched, monkeypatch):
    """`policy_for` is a test seam. If the default ever stopped calling `robots.fetch_policy`, every
    test above would still pass while the shipped code fetched blind."""
    asked: list[str] = []

    def fake_policy(url, **_kw):
        asked.append(url)
        return robots.policy_from_response("docs.example.invalid", 404, "", today="2026-01-01")

    monkeypatch.setattr(robots, "fetch_policy", fake_policy)
    docs_fetch.fetch_all(pack.root / "docs-manifest.yaml", pack.docs_cache_dir, today="2026-01-01")
    assert len(asked) == 4, "fetch_all did not ask for a policy for every URL"
