"""robots.txt as a fetch permission, not a crawl suggestion (ADR-0036).

Every URL this project retrieves is a page some vendor serves. Until now nothing asked whether the
vendor's host permitted an automated reader to retrieve it: `docs_fetch` opened a URL because a manifest
named it. Thirteen packs and 242 manifest URLs were fetched on that basis.

This module answers the question, and `docs_fetch` refuses rather than fetches when the answer is no. A
Disallowed documentation set is then a **measured finding** — recorded, quoted, and reported on the
card — instead of an obstacle to route around.

WHY NOT `urllib.robotparser` — and the answer changed under us, which is now the better reason
(ADR-0043). When this module was written, the standard library's `RuleLine.applies_to` was
`path.startswith(pattern)` with no wildcard or anchor handling at all, and it mis-read both forms that
mattered against the host that forced the ruling: `Disallow: /*/api-next` matched nothing (no path
starts with a literal `/*/`) and `Disallow: /wfm$` matched everything under `/wfm$...` and nothing
else — exactly the wrong set, twice.

**That is no longer true.** CPython rewrote the module to RFC 9309 between 3.14.4 and 3.14.6, and it
now agrees with this one on every case in `core/tests/test_robots.py`. The non-vacuity test written to
notice exactly that fired in CI on 2026-08-01, on a runner two patch releases ahead of the authoring
machine.

The module stays, for a reason the original argument did not have available: **the standard library's
answer to a robots question moved inside a single minor version.** A fetch-permission decision is a
conduct claim about what this project was allowed to retrieve, and it has to be reproducible from the
record years later, on whatever interpreter is to hand. One that silently depends on the runner's patch
level cannot be that. `SOURCE_*`, the status-code rulings below, and the fixed `USER_AGENT` are also
not things `can_fetch` returns.

WHAT IS DELIBERATE, because each of these is a judgement and not a lookup:

  * **Unreadable is not permission.** A 4xx makes the file "unavailable" and the host unrestricted
    (RFC 9309 §2.3.1.3) — that is the standard's call and four hosts in the cohort rely on it. But a 5xx,
    a timeout or a connection error makes it "unreachable" (§2.3.1.4) and the whole host is treated as
    disallowed. A fetcher that reads a timeout as a green light has no policy at all, only a preference.
  * **...and a REFUSAL is not an absence, even though it permits the same things** (ADR-0052). A 401 or
    a 403 on /robots.txt is a 4xx, so RFC 9309's unrestricted reading still applies and no URL becomes
    forbidden by this distinction. What changes is what gets WRITTEN DOWN. A host that answers "not
    found" never had a policy; a host that answers "forbidden" declined to show us the one it has, and
    RFC 9309 §2.3.1.3 says so itself in a note. Collapsing them made `source: no-robots-txt` — a phrase
    a manifest publishes and a card cites — a true statement about the first and a false one about the
    second. Found the expensive way: a recon's own generated audit table recorded PERMITTED, from
    `no-robots-txt`, for a host that had just answered 403 to every request including that one.
  * **...but a host that does not resolve is a fourth thing, not a fifth kind of refusal.** See
    `SOURCE_NO_HOST`. Folding NXDOMAIN into "unreachable" made the first cohort-wide run report eleven
    violations against a pack whose docs host had simply ceased to exist, which is a conduct accusation
    the evidence does not support.
  * **A body that carries no GROUPS is an absent robots.txt.** One measured host answers
    /robots.txt with its site-wide JavaScript shell. Parsing yields zero groups, which is treated as
    "no file" rather than sniffed for HTML — the question is whether the host stated a rule, and a page
    with no rules in it did not.
  * **...but a body that declares groups and names none of ours is a SIXTH thing** (ADR-0060). See
    `SOURCE_NO_GROUP`. A host may serve a real robots.txt that addresses ten crawlers by name and
    declares no `*` group; `parse` then returns zero directives for us and the old code fell straight
    through to "no robots.txt", publishing that the host never stated a policy about a host that had
    stated one deliberately and at length. Like the refusal above, it permits exactly what an absence
    permits and says something different about the world — and, like the refusal, it is a fact about a
    CONVERSATION rather than about the host, because the same file addresses other readers by name.
  * **The group is chosen by the agent actually used.** A pack may override the fetch agent
    (`public_docs.user_agent`, ADR-0007); one does, to a browser string. The policy it is judged against
    has to be the policy for the agent it presents itself as, or the annotation would describe a request
    nobody made.
  * **`Crawl-delay` is a directive in this file too, and it is now kept** (ADR-0048). It is not part of
    RFC 9309 and Google ignores it; this project does not, because the question here is not what a search
    crawler may skip but what a vendor asked an automated reader to do. Obeying the `Disallow` in a file
    while discarding the rate limit three lines below it was never a considered position — it was what
    happened when the parser kept two field names and dropped every other. See `parse`.
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
SOURCE_ABSENT = "no-robots-txt"             # 404-family, or a body declaring no group → unrestricted
# 401/403. Permits exactly what SOURCE_ABSENT permits (RFC 9309 §2.3.1.3: a 4xx leaves the host
# unrestricted), and says something different about the world, which is the entire point (ADR-0052).
# "No robots.txt" claims the host never stated a policy. This host has one and refused to show it —
# and, since the refusal is a decision about the requesting agent rather than about the file, the same
# host may serve the file to a different reader. Recording that as absence is not a small inaccuracy:
# it is the one place where this project's conduct record could say "nothing was asked of us" about a
# server that had just said no.
SOURCE_REFUSED = "robots.txt-refused"
SOURCE_UNREACHABLE = "robots.txt-unreachable"  # 5xx / network failure → the host is fully disallowed
# DNS does not resolve. Distinct from UNREACHABLE, and the distinction is not pedantry: a host that
# answers nothing is a server refusing to state its policy, and the conservative reading is to stay
# out. A host that does not RESOLVE is not a server at all — it never issued an instruction, so
# recording one would be inventing it, and reporting the pack as having named a "disallowed" page
# would put a conduct claim on a card that the evidence does not support. Found the useful way: one
# cohort docs host went NXDOMAIN some time after that pack was measured, and collapsing the two
# branches reported eleven fabricated violations against it.
SOURCE_NO_HOST = "host-does-not-resolve"
# The host served a real robots.txt, it parsed, and not one of the groups in it governs the agent we
# presented (ADR-0060). Permits exactly what SOURCE_ABSENT permits — zero directives apply, so nothing
# is Disallowed — and, again, says something different about the world. "No robots.txt" claims the host
# never stated a policy; this host stated one and did not address us. The distinction is ADR-0052's,
# reached by a different route: a refusal has a status code and is therefore visible, while this state
# was invisible because the only trace it leaves is an empty directive list, which an absent file leaves
# too. The measured case names ten crawler groups, grants each `Allow: /`, and declares no `*` group.
SOURCE_NO_GROUP = "robots.txt-no-group-for-agent"

# What `agent_group` says when no group governed. NOT "*": in this state there is no `*` group, so
# recording one would make the annotation assert both that no group addressed us and that the wildcard
# group applied. Truthy, so the annotation sweep's "which agent decided it" assertion still holds.
AGENT_GROUP_NONE = "(none)"

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
    """One host's rules, as they apply to one user agent.

    `crawl_delay` is the seconds the governing group asked a reader to wait between requests, or None
    where the host asked for nothing. None and 0.0 are different answers and are kept apart: 0.0 is a
    host that considered the question and declared no delay, None is a host that never raised it. A
    caller that collapses them cannot tell "unpaced by permission" from "unpaced by default".
    """
    host: str
    directives: list[tuple[str, str]] = field(default_factory=list)  # [("disallow", "/wfm/"), ...]
    agent_group: str = "*"
    source: str = SOURCE_ABSENT
    fetched_on: str | None = None
    body: str = ""
    crawl_delay: float | None = None

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


def _crawl_delay(value: str) -> float | None:
    """One `Crawl-delay` value, or None where the host did not state a usable number.

    A malformed or negative value is None rather than 0.0 on purpose: 0.0 would read downstream as "the
    host permits an unpaced burst", which is a permission this file never granted. The unparseable case
    is an absence of instruction, and the conservative reading of an absence here is to fall back to the
    caller's own default rather than to invent a green light out of a typo.
    """
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds != seconds or seconds in (float("inf"), float("-inf")) or seconds < 0:
        return None
    return seconds


@dataclass(frozen=True)
class _Parsed:
    """Everything one parse of a robots.txt body knows, including the two facts `parse` cannot return.

    `parse` has a three-value contract that a dozen callers and twenty tests depend on, and widening it
    would mean editing all of them to carry a fact only `policy_from_response` uses. So the parse
    happens here and `parse` is the narrow view of it.

    `group_names` and `governed` are what separate "this host served no robots.txt" from "this host
    served one and did not address us" (ADR-0060). `directives` is empty in BOTH cases, which is
    exactly why the distinction was invisible before there was somewhere to put it.
    """
    directives: list[tuple[str, str]]
    agent_group: str                 # the group that governed, or the "*" fallback
    crawl_delay: float | None
    group_names: tuple[str, ...]     # every User-agent group the file declared, in file order
    governed: bool                   # one of them actually applies to the agent we sent


def parse(text: str,
          user_agent: str = USER_AGENT) -> tuple[list[tuple[str, str]], str, float | None]:
    """Parse a robots.txt body and return (directives, agent_group, crawl_delay) for `user_agent`.

    Group selection follows the deployed convention rather than a strict token equality: a group name
    matches when it is a case-insensitive substring of the agent string, longest name wins, and `*` is
    the fallback. Strict equality would put a browser-string override (ADR-0007) into the `*` group even
    where a host names that browser explicitly.

    `Crawl-delay` is read per group and returned for the group that governs (ADR-0048), so a delay a host
    declares for `*` never leaks into a group that names us, and vice versa. Two rules about it are
    deliberate:

      * **A `crawl-delay` line neither opens nor closes a rules group.** Only `allow`/`disallow` set
        `in_rules`, exactly as before. A host writing `User-agent` / `Disallow` / `Crawl-delay` /
        `User-agent` states two groups; treating the delay as a rule would re-cut them into one and
        silently reassign the second agent's directives.
      * **A group that states the delay twice gets the SLOWEST of them.** Duplicates are malformed and
        no convention rules on them, so the tie is broken towards the host: obeying the longer wait can
        only ever be more polite than what was asked, and the other direction cannot say that.
    """
    p = _parse_groups(text, user_agent)
    return p.directives, p.agent_group, p.crawl_delay


def _parse_groups(text: str, user_agent: str = USER_AGENT) -> _Parsed:
    """The parse itself. `parse` above is the three-value view of it and carries the argument."""
    groups: dict[str, list[tuple[str, str]]] = {}
    delays: dict[str, float] = {}
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
        elif field_name == "crawl-delay" and current:
            seconds = _crawl_delay(value)
            if seconds is not None:
                for agent in current:
                    delays[agent] = max(delays.get(agent, seconds), seconds)

    agent_l = user_agent.lower()
    best = None
    for name in groups:
        if name == "*" or not name:
            continue
        if name in agent_l and (best is None or len(name) > len(best)):
            best = name
    chosen = best if best is not None else "*"
    # A group governs us if one NAMED us, or if the file declared the wildcard fallback. Where neither
    # is true `chosen` is still "*" — the directive lookup has to fall back to something — and the
    # honest reading of that is not "the wildcard group applied" but "no group did" (ADR-0060).
    return _Parsed(groups.get(chosen, []), chosen, delays.get(chosen),
                   tuple(groups), best is not None or "*" in groups)


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
    if status in (401, 403):
        # Unrestricted, like any other 4xx — and recorded as a refusal, not an absence (ADR-0052).
        return RobotsPolicy(host, [], "*", SOURCE_REFUSED, today, "")
    if status >= 400:
        return RobotsPolicy(host, [], "*", SOURCE_ABSENT, today, "")
    parsed = _parse_groups(body, user_agent)
    directives, agent_group, delay = parsed.directives, parsed.agent_group, parsed.crawl_delay
    if not directives and not body.strip():
        return RobotsPolicy(host, [], agent_group, SOURCE_ABSENT, today, "")
    if parsed.group_names and not parsed.governed:
        # A real robots.txt that does not address the agent we sent (ADR-0060). `directives` is empty
        # here BY CONSTRUCTION and not by coincidence — `_parse_groups` returns `groups.get("*", [])`
        # when nothing named us, and `"*"` is absent in precisely this branch — so this ordering
        # depends on no property of the body. `delay` is None for the same reason: a rate a host
        # declared for a crawler it named is not a rate it asked of us.
        return RobotsPolicy(host, [], AGENT_GROUP_NONE, SOURCE_NO_GROUP, today, body, delay)
    if not directives:
        # A 200 that is not a robots file (one cohort host serves its JS shell here). No rule was
        # stated, so no rule is applied — but the body is kept so the record shows what arrived.
        # A delay found here still travels: a host may state a rate and no fetch rule, and that is an
        # instruction about conduct even though `source` records that no permission rule was applied.
        return RobotsPolicy(host, [], agent_group, SOURCE_ABSENT, today, body, delay)
    return RobotsPolicy(host, directives, agent_group, SOURCE_RULES, today, body, delay)


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

    from .docs_fetch import _entry_lists, leading_comment_header, load_manifest, write_manifest

    policy_for = policy_for or (lambda url: fetch_policy(url, user_agent=user_agent, today=today))
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    header = leading_comment_header(manifest_path)
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
        write_manifest(manifest_path, manifest, header)
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
