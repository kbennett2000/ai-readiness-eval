"""robots.txt as a fetch permission, not a crawl suggestion (ADR-0036).

Every URL this project retrieves is a page some vendor serves. Until now nothing asked whether the
vendor's host permitted an automated reader to retrieve it: `docs_fetch` opened a URL because a manifest
named it. Thirteen packs and 242 manifest URLs were fetched on that basis.

This module answers the question, and `docs_fetch` refuses rather than fetches when the answer is no. A
Disallowed documentation set is then a **measured finding** — recorded, quoted, and reported on the
card — instead of an obstacle to route around.

WHY NOT `urllib.robotparser`. The standard library's `RuleLine.applies_to` is `path.startswith(pattern)`
with no wildcard or anchor handling at all. Against the host that forced this ruling it silently
mis-reads both of the forms that matter — `Disallow: /*/api-next` never matches anything (no path starts
with a literal `/*/`), and `Disallow: /wfm$` matches every path under `/wfm$...` and nothing else, i.e.
exactly the wrong set both times. A parser that is wrong about the only two directives at issue cannot
be the basis for a conduct claim, so RFC 9309 is implemented here directly.

WHAT IS DELIBERATE, because each of these is a judgement and not a lookup:

  * **Unreadable is not permission.** A 4xx makes the file "unavailable" and the host unrestricted
    (RFC 9309 §2.3.1.3) — that is the standard's call and four hosts in the cohort rely on it. But a 5xx,
    a timeout or a connection error makes it "unreachable" (§2.3.1.4) and the whole host is treated as
    disallowed. A fetcher that reads a timeout as a green light has no policy at all, only a preference.
  * **...but a host that does not resolve is a fourth thing, not a fifth kind of refusal.** See
    `SOURCE_NO_HOST`. Folding NXDOMAIN into "unreachable" made the first cohort-wide run report eleven
    violations against a pack whose docs host had simply ceased to exist, which is a conduct accusation
    the evidence does not support.
  * **A body that carries no directives is an absent robots.txt.** One measured host answers
    /robots.txt with its site-wide JavaScript shell. Parsing yields zero groups, which is treated as
    "no file" rather than sniffed for HTML — the question is whether the host stated a rule, and a page
    with no rules in it did not.
  * **The group is chosen by the agent actually used.** A pack may override the fetch agent
    (`public_docs.user_agent`, ADR-0007); one does, to a browser string. The policy it is judged against
    has to be the policy for the agent it presents itself as, or the annotation would describe a request
    nobody made.
"""
from __future__ import annotations

import datetime
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "ai-readiness-eval-docs"

# Why a source is what it is, in one line each — these strings are written into pack manifests, so they
# are part of the record a reviewer reads and not just an internal enum.
SOURCE_RULES = "robots.txt"                 # the host served directives and they were applied
SOURCE_ABSENT = "no-robots-txt"             # 4xx, or a body with no directives in it → unrestricted
SOURCE_UNREACHABLE = "robots.txt-unreachable"  # 5xx / network failure → the host is fully disallowed
# DNS does not resolve. Distinct from UNREACHABLE, and the distinction is not pedantry: a host that
# answers nothing is a server refusing to state its policy, and the conservative reading is to stay
# out. A host that does not RESOLVE is not a server at all — it never issued an instruction, so
# recording one would be inventing it, and reporting the pack as having named a "disallowed" page
# would put a conduct claim on a card that the evidence does not support. Found the useful way: one
# cohort docs host went NXDOMAIN some time after that pack was measured, and collapsing the two
# branches reported eleven fabricated violations against it.
SOURCE_NO_HOST = "host-does-not-resolve"

# Sentinel statuses for `policy_from_response`, which is where the whole status ruling lives.
STATUS_NETWORK_FAILURE = 0
STATUS_NO_HOST = -1


@dataclass(frozen=True)
class Verdict:
    """One URL, judged. `rule` is the matching directive verbatim, so a manifest can quote it."""
    allowed: bool
    rule: str | None
    agent_group: str
    source: str


@dataclass
class RobotsPolicy:
    """One host's rules, as they apply to one user agent."""
    host: str
    directives: list[tuple[str, str]] = field(default_factory=list)  # [("disallow", "/wfm/"), ...]
    agent_group: str = "*"
    source: str = SOURCE_ABSENT
    fetched_on: str | None = None
    body: str = ""

    def verdict(self, url: str) -> Verdict:
        if self.source == SOURCE_UNREACHABLE:
            return Verdict(False, None, self.agent_group, self.source)
        path = _path_of(url)
        best_len, best = -1, None
        for kind, pattern in self.directives:
            if not pattern:
                # "Disallow:" with an empty value means allow everything; an empty Allow says nothing.
                continue
            n = _match_length(pattern, path)
            if n is None:
                continue
            # Longest matching pattern wins; Allow wins an exact-length tie (RFC 9309 §2.2.2).
            if n > best_len or (n == best_len and kind == "allow"):
                best_len, best = n, (kind, pattern)
        if best is None:
            return Verdict(True, None, self.agent_group, self.source)
        kind, pattern = best
        return Verdict(kind == "allow", f"{kind.capitalize()}: {pattern}", self.agent_group, self.source)

    def allows(self, url: str) -> bool:
        return self.verdict(url).allowed


def _path_of(url: str) -> str:
    """The path a rule is matched against: path plus query, compared as written.

    Percent-encoding is compared literally rather than normalized. Normalizing would be defensible, but
    it would also mean the string a directive is tested against is not the string the manifest records,
    and every rule here is meant to be re-checkable by hand from what is committed.
    """
    parts = urllib.parse.urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def _match_length(pattern: str, path: str) -> int | None:
    """Specificity of `pattern` against `path`, or None if it does not match.

    `*` matches any run of characters; a trailing `$` anchors the end of the path. Specificity is the
    length of the pattern with wildcards and the anchor removed — so `/wfm/` (5) beats `/` (1), and a
    path-prefix rule beats a catch-all no matter how the catch-all is written.
    """
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    if not re.match("^" + regex + ("$" if anchored else ""), path):
        return None
    return len(body.replace("*", ""))


def parse(text: str, user_agent: str = USER_AGENT) -> tuple[list[tuple[str, str]], str]:
    """Parse a robots.txt body and return (directives, agent_group) for `user_agent`.

    Group selection follows the deployed convention rather than a strict token equality: a group name
    matches when it is a case-insensitive substring of the agent string, longest name wins, and `*` is
    the fallback. Strict equality would put a browser-string override (ADR-0007) into the `*` group even
    where a host names that browser explicitly.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    current: list[str] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name, value = field_name.strip().lower(), value.strip()
        if field_name == "user-agent":
            if in_rules:  # a new agent line after rules starts a new group
                current, in_rules = [], False
            current.append(value.lower())
            for agent in current:
                groups.setdefault(agent, [])
        elif field_name in ("allow", "disallow") and current:
            in_rules = True
            for agent in current:
                groups[agent].append((field_name, value))

    agent_l = user_agent.lower()
    best = None
    for name in groups:
        if name == "*" or not name:
            continue
        if name in agent_l and (best is None or len(name) > len(best)):
            best = name
    chosen = best if best is not None else "*"
    return groups.get(chosen, []), chosen


def robots_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, "/robots.txt", "", ""))


def _http_get(url: str, user_agent: str, timeout: int = 25) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return getattr(resp, "status", 200) or 200, resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except urllib.error.URLError as exc:
        # A name that does not resolve is not a server declining to answer.
        if isinstance(exc.reason, socket.gaierror):
            return STATUS_NO_HOST, ""
        return STATUS_NETWORK_FAILURE, ""
    except socket.gaierror:
        return STATUS_NO_HOST, ""
    except Exception:
        return STATUS_NETWORK_FAILURE, ""  # §2.3.1.4 "unreachable"


def policy_from_response(host: str, status: int, body: str, *, user_agent: str = USER_AGENT,
                         today: str | None = None) -> RobotsPolicy:
    """Build a policy from one robots.txt response. The status ruling lives here, in one place."""
    today = today or datetime.date.today().isoformat()
    if status == STATUS_NO_HOST:
        return RobotsPolicy(host, [], "*", SOURCE_NO_HOST, today, "")
    if status == STATUS_NETWORK_FAILURE or status >= 500:
        return RobotsPolicy(host, [], "*", SOURCE_UNREACHABLE, today, "")
    if status >= 400:
        return RobotsPolicy(host, [], "*", SOURCE_ABSENT, today, "")
    directives, agent_group = parse(body, user_agent)
    if not directives and not body.strip():
        return RobotsPolicy(host, [], agent_group, SOURCE_ABSENT, today, "")
    if not directives:
        # A 200 that is not a robots file (one cohort host serves its JS shell here). No rule was
        # stated, so no rule is applied — but the body is kept so the record shows what arrived.
        return RobotsPolicy(host, [], agent_group, SOURCE_ABSENT, today, body)
    return RobotsPolicy(host, directives, agent_group, SOURCE_RULES, today, body)


_CACHE: dict[tuple[str, str], RobotsPolicy] = {}


def clear_cache() -> None:
    _CACHE.clear()


# --------------------------------------------------------------------------- #
# Manifest annotation — the disclosure becomes checked evidence
# --------------------------------------------------------------------------- #

# Written onto every manifest page and anchor. `robots_disallowed` is the claim; the other four are what
# makes it re-checkable by hand: which directive decided it, why the host had (or lacked) one, when it
# was read, and which agent group it was read as.
ANNOTATION_FIELDS = ("robots_disallowed", "robots_rule", "robots_source", "robots_fetched",
                     "robots_agent")


@dataclass
class ManifestAudit:
    """One manifest, judged. `disallowed` is the conduct answer; `drift` is what --check reports."""
    manifest_path: object
    label: str = ""
    checked: int = 0
    hosts: set = field(default_factory=set)
    disallowed: list[tuple[str, str, str]] = field(default_factory=list)  # (task, url, rule)
    unreachable: list[str] = field(default_factory=list)
    no_host: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    written: bool = False

    @property
    def ok(self) -> bool:
        return not self.disallowed and not self.unreachable


def annotate_manifest(manifest_path, *, user_agent: str = USER_AGENT, today: str | None = None,
                      write: bool = True, policy_for=None) -> ManifestAudit:
    """Read every URL a manifest names, judge it against its host, and record the verdict in place.

    Judges `anchors` as well as `pages` (ADR-0034): an anchor is fetched to verify the citation it
    carries, so it is a retrieval like any other and the host's instruction applies to it identically.

    Writes only the five `robots_*` keys. It never touches `url`, `content_hash`, `byte_size` or
    `cache_file`, so annotating a pack cannot change one byte of what any condition injects — which is
    what makes it safe to run across an already-published cohort.
    """
    from pathlib import Path

    import yaml

    from .docs_fetch import _entry_lists, load_manifest

    policy_for = policy_for or (lambda url: fetch_policy(url, user_agent=user_agent, today=today))
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    audit = ManifestAudit(manifest_path=manifest_path, label=manifest_path.parent.name)

    for task_id, entry in (manifest.get("tasks") or {}).items():
        for page in [p for pages in _entry_lists(entry) for p in pages]:
            url = page.get("url")
            if not url:
                continue
            policy = policy_for(url)
            v = policy.verdict(url)
            audit.checked += 1
            audit.hosts.add(urllib.parse.urlsplit(url).netloc)
            if v.source == SOURCE_UNREACHABLE:
                audit.unreachable.append(url)
            elif v.source == SOURCE_NO_HOST:
                audit.no_host.append(url)
            if not v.allowed:
                audit.disallowed.append((task_id, url, v.rule or v.source))
            was = page.get("robots_disallowed")
            if was is not None and bool(was) != (not v.allowed):
                audit.drift.append(
                    f"{task_id}: {url} was recorded {'disallowed' if was else 'allowed'} "
                    f"and the host now says {'disallowed' if not v.allowed else 'allowed'}")
            if write:
                page["robots_disallowed"] = not v.allowed
                page["robots_rule"] = v.rule
                page["robots_source"] = v.source
                page["robots_fetched"] = policy.fetched_on
                page["robots_agent"] = v.agent_group

    if write:
        manifest_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, width=100, allow_unicode=True))
        audit.written = True
    return audit


def format_report(audits: list[ManifestAudit]) -> tuple[str, int]:
    """Render the audit on the shared `(text, total)` contract. `total` is the disallowed count —
    the number that has to be zero for this project's retrieval to have been compliant."""
    lines: list[str] = []
    total = 0
    for a in sorted(audits, key=lambda x: x.label):
        flag = "ok " if a.ok else "!! "
        lines.append(f"  {flag}{a.label:<16} {a.checked:>4} URL(s), {len(a.hosts)} host(s)")
        for task_id, url, rule in a.disallowed:
            total += 1
            lines.append(f"      DISALLOWED  {task_id}: {url}")
            lines.append(f"                  matched {rule}")
        for url in a.unreachable:
            lines.append(f"      UNREACHABLE robots.txt for {url} — host treated as disallowed")
        if a.no_host:
            hosts = sorted({urllib.parse.urlsplit(u).netloc for u in a.no_host})
            lines.append(f"      NO HOST     {len(a.no_host)} URL(s) on {', '.join(hosts)} — DNS does "
                         "not resolve; no instruction exists and nothing is fetchable")
        for d in a.drift:
            lines.append(f"      DRIFT       {d}")
    checked = sum(a.checked for a in audits)
    hosts = len({h for a in audits for h in a.hosts})
    lines.append("")
    if total:
        lines.append(f"{total} of {checked} URL(s) across {hosts} host(s) are robots-Disallowed. "
                     "The harness must not fetch them (ADR-0036).")
    else:
        lines.append(f"{checked} URL(s) across {hosts} host(s): none is robots-Disallowed.")
    return "\n".join(lines), total


def fetch_policy(url: str, *, user_agent: str = USER_AGENT, today: str | None = None,
                 get=_http_get) -> RobotsPolicy:
    """The policy for `url`'s host, fetched at most once per (host, agent) per process.

    `get` is injectable so the entire test suite stays offline; the only online path in this project is
    the `annotate-robots` command an operator runs.
    """
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    key = (host, user_agent)
    if key not in _CACHE:
        status, body = get(robots_url(url), user_agent)
        _CACHE[key] = policy_from_response(host, status, body, user_agent=user_agent, today=today)
    return _CACHE[key]
