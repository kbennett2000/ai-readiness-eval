"""Fetch + cache a public-docs snapshot and populate a pack's manifest (ADR-0005 lineage).

Reads a pack's committed manifest (URLs + selection notes), downloads each page, extracts
text, writes it under the pack's gitignored docs cache, and records fetch_date +
content_hash (sha256 of the cached text) + byte_size back into the manifest. Re-running
and comparing hashes reveals drift. The page text itself is never committed. Paths are
supplied by the caller (a `Pack`); this module holds no vendor path.
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
# Floor for the pause between retries when a pack declares no delay of its own. Measured against
# a real throttling host: its penalty window outlasts ~90s of cumulative backoff, and every
# retry made while throttled appears to restart it. Fewer, longer waits clear it; rapid retries
# do not. The linear schedule below therefore reaches a 180s gap before giving up.
MIN_BACKOFF_SECONDS = 60


class EmptyDocument(RuntimeError):
    """A 2xx response that carried no document.

    Some docs hosts throttle automated readers with a success status and a zero-length body
    (One Identity's support portal answers HTTP 202 with 0 bytes). Left alone that is
    indistinguishable from a real page: the text extracts to nothing, hashes cleanly, and is
    recorded as a valid snapshot. Raising here forces it down the same path as a 404.
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


def fetch_all(manifest_path: str | Path, cache_dir: str | Path, *, today: str | None = None,
              user_agent: str | None = None, delay_seconds: float = 0.0,
              retries: int = DEFAULT_RETRIES, sleep=time.sleep) -> dict:
    """Fetch every page in the manifest, cache text, and update manifest entries in place.

    Returns a summary dict {task_id: [(url, byte_size, status)]}. Errors are recorded
    per page (status='error: ...') without aborting the rest.

    `user_agent` overrides the default self-identifying agent for vendors whose docs host
    bot-gates it (ADR-0007). The manifest records which agent retrieved each page, so a
    snapshot taken under an override is never silently indistinguishable from a default one.

    `delay_seconds` paces requests for hosts that throttle a rapid loop (ADR-0009). It
    defaults to 0, so a pack that declares nothing fetches exactly as it did before.
    """
    manifest_path = Path(manifest_path)
    cache_dir = Path(cache_dir)
    manifest = load_manifest(manifest_path)
    today = today or datetime.date.today().isoformat()
    summary: dict[str, list] = {}
    first = True
    for task_id, entry in (manifest.get("tasks") or {}).items():
        summary[task_id] = []
        for page in entry.get("pages", []):
            url = page["url"]
            dest = cache_path_for(cache_dir, task_id, url)
            if delay_seconds and not first:
                sleep(delay_seconds)
            first = False
            try:
                html = _fetch_with_retry(url, user_agent=user_agent,
                                         delay_seconds=delay_seconds, retries=retries, sleep=sleep)
                text = html_to_text(html)
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
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, width=100, allow_unicode=True))
    return summary
