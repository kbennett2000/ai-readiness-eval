"""Fetch + cache a public-docs snapshot and populate a pack's manifest (ADR-0005 lineage).

Reads a pack's committed manifest (URLs + selection notes), downloads each page, extracts
text, writes it under the pack's gitignored docs cache, and records fetch_date +
content_hash (sha256 of the cached text) + byte_size back into the manifest. Re-running
and comparing hashes reveals drift. The page text itself is never committed. Paths are
supplied by the caller (a `Pack`); this module holds no vendor path.

Two ways a page can arrive and still not be a document, each with its own rule: a body that
is empty as bytes (`EmptyDocument`, ADR-0009, retried because a throttle can clear) and a
body that is whole but extracts to nothing (`EmptyRender`, ADR-0021, never retried because
a client-rendered page will render client-side again in sixty seconds).
"""
from __future__ import annotations

import datetime
import hashlib
import re
import time
import urllib.request
from pathlib import Path

import yaml

from .html_text import html_to_text

# Page roles, in priority order (highest first) for the context budget (ADR-0005 lineage).
ROLE_PRIORITY = ["api-reference", "topic-guide", "getting-started"]

USER_AGENT = "ai-readiness-eval-docs"

# Attempts per page when a docs host answers 2xx with an empty body (ADR-0009). The first
# attempt is not a retry, so this is 1 fetch + (DEFAULT_RETRIES - 1) backoff retries.
DEFAULT_RETRIES = 4
# Floor, in bytes of EXTRACTED text, under which a page is not a document (ADR-0021). Chosen
# as the point below which a page cannot state an endpoint, a method and a parameter — the
# minimum this project asks a reference page for. A page that genuinely sits under it is kept
# by declaring `short_text_ok: <reason>` on the manifest entry.
MIN_TEXT_BYTES = 200
# Floor for the pause between retries when a pack declares no delay of its own. Measured against
# a real throttling host: its penalty window outlasts ~90s of cumulative backoff, and every
# retry made while throttled appears to restart it. Fewer, longer waits clear it; rapid retries
# do not. The linear schedule below therefore reaches a 180s gap before giving up.
MIN_BACKOFF_SECONDS = 60


class EmptyDocument(RuntimeError):
    """A 2xx response that carried no document.

    Some docs hosts throttle automated readers with a success status and a zero-length body
    (one measured vendor's support portal answers HTTP 202 with 0 bytes). Left alone that is
    indistinguishable from a real page: the text extracts to nothing, hashes cleanly, and is
    recorded as a valid snapshot. Raising here forces it down the same path as a 404.
    """


class EmptyRender(RuntimeError):
    """A page whose body arrived intact but whose extracted text is not a document (ADR-0021).

    `EmptyDocument` tests `raw.strip()` — the body as bytes, before extraction. That catches a
    host which sends nothing and misses a host which sends everything except the documentation:
    a client-rendered reference page delivers tens of kilobytes of script, passes the raw-body
    test, and then extracts to a navigation crumb. Non-empty as bytes, empty as documentation.

    ADR-0005 already said the resulting byte_size makes such pages "visible rather than hidden",
    and it was right — a measured vendor's reference pages recorded byte_size 1 and stayed
    committed, because being visible is not the same as being checked. This is the check.

    Deliberately raised AFTER `_fetch_with_retry` returns, so it can never be retried:
    ADR-0009's backoff answers a throttle, and a page that renders client-side will render
    client-side again in sixty seconds.
    """


def load_manifest(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def slug_for(url: str) -> str:
    """A filesystem-safe slug from a URL's path (used as the cache filename)."""
    path = re.sub(r"^https?://", "", url).split("?", 1)[0].split("#", 1)[0]
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()
    return slug[-80:] or "page"


def cache_path_for(cache_dir: str | Path, task_id: str, url: str) -> Path:
    return Path(cache_dir) / task_id / f"{slug_for(url)}.txt"


def leading_comment_header(path: str | Path) -> str:
    """The hand-authored comment block at the top of a manifest, or ''.

    `yaml.safe_dump` does not round-trip comments, so every rewrite of a manifest silently deletes
    them. One pack's manifest opens with 21 lines recording, across two cycles, why its docs host is
    unreachable and what was tried — a finding, in the file the finding is about. Rewriting the file
    was quietly destroying it. Same problem `factory.save_queue` already solves for `queue.yaml`, and
    the same fix: capture the header, put it back.

    Only the LEADING block is preserved, which is where every comment in the cohort's manifests lives.
    An inline comment further down is still lost; that is a known limit rather than a silent one.
    """
    path = Path(path)
    if not path.is_file():
        return ""
    header: list[str] = []
    for line in path.read_text().splitlines(keepends=True):
        if line.strip() and not line.lstrip().startswith("#"):
            break
        header.append(line)
    return "".join(header)


def write_manifest(path: str | Path, manifest: dict, header: str | None = None) -> None:
    """Serialise a manifest, preserving its leading comment header. The only writer of these files."""
    path = Path(path)
    header = leading_comment_header(path) if header is None else header
    body = yaml.safe_dump(manifest, sort_keys=False, width=100, allow_unicode=True)
    path.write_text(header + body)


def _fetch(url: str, timeout: int = 30, user_agent: str | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent or USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        status = getattr(resp, "status", None)
        raw = resp.read()
    if not raw.strip():
        raise EmptyDocument(f"HTTP {status} with an empty body (throttled or non-document response)")
    return raw.decode(charset, errors="replace")


def _fetch_with_retry(url: str, *, user_agent: str | None, delay_seconds: float,
                      retries: int, sleep=time.sleep) -> str:
    """Fetch `url`, retrying with linear backoff when the host answers 2xx-but-empty.

    Only EmptyDocument is retried. A 404 or a connection error is a fact about the page and
    is recorded on the first attempt; a throttle is a fact about our request rate, and
    retrying is the honest response to it.
    """
    backoff = max(delay_seconds, MIN_BACKOFF_SECONDS)
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return _fetch(url, user_agent=user_agent)
        except EmptyDocument as exc:
            last = exc
            if attempt < retries - 1:
                sleep(backoff * (attempt + 1))
    raise last  # type: ignore[misc]


def _short_text_reason(page: dict) -> str | None:
    """This page's declared reason for sitting under the text floor, or None (ADR-0021).

    Present-but-empty is rejected rather than read as absent. `short_text_ok: true` is an
    override with no argument behind it, and the argument is the entire point of the field:
    a tolerance this project grants is one a pack asked for in writing, the same shape as
    `public_docs.user_agent` (ADR-0007) and `endpoint_base_prefix` (ADR-0017).
    """
    if "short_text_ok" not in page:
        return None
    reason = page["short_text_ok"]
    if not isinstance(reason, str) or not reason.strip():
        raise EmptyRender(
            f"short_text_ok must give a non-empty reason, not {reason!r} — "
            "a page kept under the text floor has to say why on the record"
        )
    return reason.strip()


# ADR-0034. A manifest task entry carries two lists, and the difference between them is the whole
# ruling: `pages` is what the model is SHOWN, `anchors` is what the answer key is CITED to. They were
# one list until a vendor turned up whose only citable first-party artifact could not be injected
# without handing the model the answer key's own source.
INJECTED_KEY = "pages"
ANCHOR_KEY = "anchors"


def _entry_lists(entry: dict) -> list[list[dict]]:
    return [entry.get(INJECTED_KEY, []) or [], entry.get(ANCHOR_KEY, []) or []]


def manifest_urls(manifest: dict, *, include_anchors: bool = True) -> set[str]:
    """Every URL the manifest names. Anchoring resolves against all of them; nothing else should.

    Lives here rather than in `factory` so the anchoring gate and the fetcher read the manifest
    through one accessor — `PublicDocsCondition` deliberately does NOT use it, and reads `pages`
    directly, so no change here can widen what reaches a prompt.
    """
    urls: set[str] = set()
    for entry in (manifest.get("tasks") or {}).values():
        lists = _entry_lists(entry) if include_anchors else [entry.get(INJECTED_KEY, []) or []]
        for pages in lists:
            urls |= {p["url"] for p in pages if p.get("url")}
    return urls


class RobotsDisallowed(RuntimeError):
    """The host instructs automated readers not to retrieve this path (ADR-0036).

    Distinct from every other failure in this module, because it is not a failure: the page is there and
    would very likely arrive intact. What is absent is permission. It is raised before any request is
    made — a Disallowed URL is never opened, so this is a refusal and not a recovery.
    """


def fetch_all(manifest_path: str | Path, cache_dir: str | Path, *, today: str | None = None,
              user_agent: str | None = None, delay_seconds: float = 0.0,
              retries: int = DEFAULT_RETRIES, sleep=time.sleep, policy_for=None) -> dict:
    """Fetch every page in the manifest, cache text, and update manifest entries in place.

    Returns a summary dict {task_id: [(url, byte_size, status)]}. Errors are recorded
    per page (status='error: ...') without aborting the rest.

    `user_agent` overrides the default self-identifying agent for vendors whose docs host
    bot-gates it (ADR-0007). The manifest records which agent retrieved each page, so a
    snapshot taken under an override is never silently indistinguishable from a default one.

    `delay_seconds` paces requests for hosts that throttle a rapid loop (ADR-0009). It
    defaults to 0, so a pack that declares nothing fetches exactly as it did before.

    `policy_for` resolves a URL to its host's robots policy (ADR-0036) and is injectable so the suite
    stays offline. Every URL is judged BEFORE it is opened; a Disallowed one is annotated and skipped,
    never requested.
    """
    from . import robots as robots_mod

    manifest_path = Path(manifest_path)
    cache_dir = Path(cache_dir)
    manifest = load_manifest(manifest_path)
    header = leading_comment_header(manifest_path)
    today = today or datetime.date.today().isoformat()
    agent = user_agent or USER_AGENT
    if policy_for is None:
        def policy_for(url):  # noqa: E306 — one fetch per host, memoised in core.robots
            return robots_mod.fetch_policy(url, user_agent=agent, today=today)
    summary: dict[str, list] = {}
    first = True
    for task_id, entry in (manifest.get("tasks") or {}).items():
        summary[task_id] = []
        # Anchors are fetched too (ADR-0034): their existence, byte size and hash are the evidence a
        # ground-truth citation rests on, and an anchor that has never been retrieved is an
        # unverified claim. What they are NOT is injected — `PublicDocsCondition` reads `pages` only.
        for page in [p for pages in _entry_lists(entry) for p in pages]:
            url = page["url"]
            dest = cache_path_for(cache_dir, task_id, url)
            # ADR-0036: permission first, and before the pacing sleep — a URL we may not open should
            # not cost the host a delay slot either.
            policy = policy_for(url)
            verdict = policy.verdict(url)
            page["robots_disallowed"] = not verdict.allowed
            page["robots_rule"] = verdict.rule
            page["robots_source"] = verdict.source
            page["robots_fetched"] = policy.fetched_on
            page["robots_agent"] = verdict.agent_group
            if not verdict.allowed:
                page["fetch_date"] = today
                page["content_hash"] = None
                page["byte_size"] = 0
                page["fetch_error"] = (
                    f"robots-disallowed — {policy.host} instructs automated readers not to retrieve "
                    f"this path ({verdict.rule or verdict.source}). Not fetched (ADR-0036).")[:200]
                # A snapshot an earlier fetch already took is deleted, not merely left unread. The
                # cache is gitignored and regenerable, so nothing is lost that permission would not
                # restore; keeping bytes we are no longer allowed to retrieve is the thing refused.
                dest.unlink(missing_ok=True)
                summary[task_id].append((url, 0, "robots-disallowed"))
                continue
            if delay_seconds and not first:
                sleep(delay_seconds)
            first = False
            try:
                html = _fetch_with_retry(url, user_agent=user_agent,
                                         delay_seconds=delay_seconds, retries=retries, sleep=sleep)
                text = html_to_text(html)
                # ADR-0021: the floor is on extracted text, and it is checked here rather than
                # inside the retry helper precisely so a client-rendered page is recorded on the
                # first attempt instead of waiting out a throttle schedule it will never clear.
                n_text = len(text.encode("utf-8"))
                if n_text < MIN_TEXT_BYTES and _short_text_reason(page) is None:
                    raise EmptyRender(
                        f"extracted text is {n_text} B, under the {MIN_TEXT_BYTES} B floor — "
                        "the body arrived but carries no documentation (rendered client-side?). "
                        "Declare short_text_ok: <reason> on this page to keep it."
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text)
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                page["fetch_date"] = today
                page["content_hash"] = f"sha256:{digest}"
                page["byte_size"] = len(text.encode("utf-8"))
                page["cache_file"] = f"{cache_dir.name}/{dest.relative_to(cache_dir)}"
                if user_agent:
                    page["fetched_with_user_agent"] = user_agent
                summary[task_id].append((url, page["byte_size"], "ok"))
            except Exception as exc:  # network / decode errors — record, don't abort
                page["fetch_date"] = today
                page["content_hash"] = None
                page["byte_size"] = 0
                page["fetch_error"] = str(exc)[:200]
                summary[task_id].append((url, 0, f"error: {str(exc)[:80]}"))
    write_manifest(manifest_path, manifest, header)
    return summary
