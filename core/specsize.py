"""Measure the pinned OpenAPI spec repo's size (Task 1, cycle 4).

Concrete evidence for why "just paste the whole spec into the model" is infeasible
and a context layer must exist. Downloads the repo tarball at the pinned SHA, sums
the bytes of the OpenAPI spec files, finds the largest single file, and estimates
tokens (bytes / 4). Real numbers, not hand-waving.
"""
from __future__ import annotations

import io
import tarfile
import urllib.request
from pathlib import Path

import yaml

_SPEC_EXTS = (".yaml", ".yml", ".json")
_CHARS_PER_TOKEN = 4          # rough Claude/GPT-family estimate for English + YAML
_CONTEXT_WINDOW_TOKENS = 200_000  # a generous current large-context budget, for scale

USER_AGENT = "ai-readiness-eval"


def _pin(specs_file: str | Path) -> tuple[str, str]:
    cfg = yaml.safe_load(Path(specs_file).read_text())
    return cfg["spec_repo"], cfg["spec_sha"]


def _tarball_url(repo: str, sha: str) -> str:
    return f"https://codeload.github.com/{repo}/tar.gz/{sha}"


def measure(specs_file: str | Path, spec_prefix: str = "", *,
            repo: str | None = None, sha: str | None = None, timeout: int = 120) -> dict:
    """Measure a pinned OpenAPI spec repo's size. `spec_prefix` scopes which subtree counts as
    "the spec" (e.g. a vendor's versioned API tree), excluding sibling collections; "" = whole repo."""
    if repo is None or sha is None:
        repo, sha = _pin(specs_file)
    url = _tarball_url(repo, sha)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    total_bytes = 0
    file_count = 0
    largest = ("", 0)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[-1]  # strip the top-level "<repo>-<sha>/" dir
            if not name.startswith(spec_prefix) or not name.lower().endswith(_SPEC_EXTS):
                continue
            file_count += 1
            total_bytes += member.size
            if member.size > largest[1]:
                largest = (name, member.size)
    total_tokens = total_bytes // _CHARS_PER_TOKEN
    largest_tokens = largest[1] // _CHARS_PER_TOKEN
    return {
        "repo": repo,
        "spec_sha": sha,
        "scope": spec_prefix or "(whole repo)",
        "spec_file_count": file_count,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1_048_576, 2),
        "est_total_tokens": total_tokens,
        "largest_file": largest[0],
        "largest_file_bytes": largest[1],
        "largest_file_est_tokens": largest_tokens,
        "context_window_tokens": _CONTEXT_WINDOW_TOKENS,
        "total_vs_window_x": round(total_tokens / _CONTEXT_WINDOW_TOKENS, 1),
        "largest_vs_window_x": round(largest_tokens / _CONTEXT_WINDOW_TOKENS, 1),
    }


def format_report(m: dict) -> str:
    return (
        f"Spec repo:            {m['repo']} @ {m['spec_sha'][:12]}\n"
        f"Scope:                {m['scope']} (the OpenAPI spec subtree measured)\n"
        f"OpenAPI spec files:   {m['spec_file_count']:,}\n"
        f"Total size:           {m['total_bytes']:,} bytes ({m['total_mb']} MB)\n"
        f"Est. total tokens:    ~{m['est_total_tokens']:,} (bytes/4) "
        f"= ~{m['total_vs_window_x']}x a {m['context_window_tokens']:,}-token window\n"
        f"Largest single file:  {m['largest_file']}\n"
        f"                      {m['largest_file_bytes']:,} bytes "
        f"(~{m['largest_file_est_tokens']:,} tokens = ~{m['largest_vs_window_x']}x one window)"
    )
