"""The RFC 9309 matcher, rule by rule (ADR-0036).

Every case here is a claim about what this project is permitted to fetch, so each is asserted against a
hand-written robots body rather than a live host — the suite is offline by construction and the only
network path is the `annotate-robots` command.

The two cases that forced the module exist at the top: `Disallow: /*/api-next` and `Disallow: /wfm$`.
`urllib.robotparser` gets both wrong in opposite directions, which is why it is not used.
"""
import pytest

from core import robots

BODY_WILDCARDS = """
User-agent: *
Allow: /
Disallow: /*/api-next
Disallow: /wfm$
Disallow: /wfm/
"""


def _policy(body: str, agent: str = robots.USER_AGENT, status: int = 200) -> robots.RobotsPolicy:
    return robots.policy_from_response("h.invalid", status, body, user_agent=agent, today="2026-01-01")


# --- the two forms the standard library gets wrong -------------------------- #

@pytest.mark.parametrize("path,allowed", [
    ("https://h.invalid/wfm/api-next/v2/branches/x/apis/people.json", False),  # both rules bite
    ("https://h.invalid/hcm/api-next/v2/branches", False),                     # the wildcard alone
    ("https://h.invalid/wfm", False),                                          # the $-anchored form
    ("https://h.invalid/wfm/reference/welcome", False),                        # the prefix form
    ("https://h.invalid/wfmx/reference", True),      # $-anchor must NOT swallow a longer segment
    ("https://h.invalid/api-next/v2", True),         # the wildcard needs a segment before it
    ("https://h.invalid/general/docs", True),        # not named in this body
])
def test_wildcard_and_anchor_forms(path, allowed):
    assert _policy(BODY_WILDCARDS).allows(path) is allowed


def test_the_standard_library_would_disagree_which_is_why_this_module_exists():
    """Non-vacuity for the whole module. If `urllib.robotparser` ever became correct, this fires and
    the argument in the docstring can be re-examined rather than inherited."""
    import urllib.robotparser

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(BODY_WILDCARDS.splitlines())
    stdlib = rp.can_fetch(robots.USER_AGENT, "https://h.invalid/hcm/api-next/v2/branches")
    ours = _policy(BODY_WILDCARDS).allows("https://h.invalid/hcm/api-next/v2/branches")
    assert stdlib is True and ours is False, "the stdlib parser no longer mis-reads a wildcard rule"


# --- precedence ------------------------------------------------------------- #

def test_longest_matching_pattern_wins_over_a_catch_all():
    body = "User-agent: *\nDisallow: /\nAllow: /docs/public/\n"
    p = _policy(body)
    assert p.allows("https://h.invalid/docs/public/page") is True
    assert p.allows("https://h.invalid/docs/private/page") is False


def test_allow_wins_an_exact_length_tie():
    body = "User-agent: *\nDisallow: /docs/\nAllow: /docs/\n"
    assert _policy(body).allows("https://h.invalid/docs/x") is True


def test_order_in_the_file_does_not_decide_it():
    """Precedence is by specificity, not by position — the same two rules in either order agree."""
    a = "User-agent: *\nDisallow: /\nAllow: /ok/\n"
    b = "User-agent: *\nAllow: /ok/\nDisallow: /\n"
    for body in (a, b):
        assert _policy(body).allows("https://h.invalid/ok/x") is True
        assert _policy(body).allows("https://h.invalid/no/x") is False


def test_a_query_string_is_part_of_the_path_a_rule_sees():
    body = "User-agent: *\nDisallow: /*?\n"
    p = _policy(body)
    assert p.allows("https://h.invalid/listing") is True
    assert p.allows("https://h.invalid/listing?page=2") is False


def test_an_empty_disallow_means_allow_everything():
    """The inversion that matters: `Disallow:` with no value grants the whole site. Read as a bare
    prefix it would match every path and lock a host out completely."""
    assert _policy("User-agent: *\nDisallow:\n").allows("https://h.invalid/anything") is True


def test_a_body_with_no_directives_is_an_absent_robots_file():
    """One cohort host answers /robots.txt with its site-wide JavaScript shell."""
    p = _policy("<html><body>Not a robots file</body></html>")
    assert p.source == robots.SOURCE_ABSENT
    assert p.allows("https://h.invalid/anything") is True


# --- agent groups ----------------------------------------------------------- #

BODY_GROUPS = """
User-agent: *
Disallow: /everyone-else/

User-agent: Chrome
Disallow: /browsers/

User-agent: ai-readiness-eval-docs
Disallow: /us/
"""

BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36")


def test_our_own_agent_gets_its_own_group():
    p = _policy(BODY_GROUPS)
    assert p.agent_group == "ai-readiness-eval-docs"
    assert p.allows("https://h.invalid/us/x") is False
    # A named group REPLACES the wildcard group; it does not stack with it.
    assert p.allows("https://h.invalid/everyone-else/x") is True


def test_a_browser_override_is_judged_as_the_browser_it_claims_to_be():
    """ADR-0007 lets a pack present a browser string to a bot-gated host. The policy it is judged
    against has to be the policy for the agent it actually sent."""
    p = _policy(BODY_GROUPS, agent=BROWSER_UA)
    assert p.agent_group == "chrome"
    assert p.allows("https://h.invalid/browsers/x") is False
    assert p.allows("https://h.invalid/us/x") is True


def test_an_unnamed_agent_falls_back_to_the_wildcard_group():
    p = _policy(BODY_GROUPS, agent="some-other-crawler")
    assert p.agent_group == "*"
    assert p.allows("https://h.invalid/everyone-else/x") is False


def test_the_longest_matching_group_name_wins():
    body = "User-agent: eval\nDisallow: /a/\n\nUser-agent: ai-readiness-eval-docs\nDisallow: /b/\n"
    p = _policy(body)
    assert p.agent_group == "ai-readiness-eval-docs"
    assert p.allows("https://h.invalid/a/x") is True and p.allows("https://h.invalid/b/x") is False


def test_consecutive_agent_lines_share_one_group():
    body = "User-agent: alpha\nUser-agent: ai-readiness-eval-docs\nDisallow: /shared/\n"
    assert _policy(body).allows("https://h.invalid/shared/x") is False


def test_a_new_agent_line_after_rules_starts_a_new_group():
    body = ("User-agent: alpha\nDisallow: /alpha/\n"
            "User-agent: ai-readiness-eval-docs\nDisallow: /ours/\n")
    p = _policy(body)
    assert p.allows("https://h.invalid/alpha/x") is True
    assert p.allows("https://h.invalid/ours/x") is False


def test_comments_and_blank_lines_are_ignored():
    body = "# a comment\n\nUser-agent: *   # trailing\nDisallow: /x/  # why\n"
    assert _policy(body).allows("https://h.invalid/x/y") is False


# --- status handling: the judgement, not the lookup ------------------------- #

@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_a_4xx_leaves_the_host_unrestricted(status):
    """RFC 9309 §2.3.1.3. Four hosts in the cohort rely on this branch."""
    p = _policy("", status=status)
    assert p.source == robots.SOURCE_ABSENT
    assert p.allows("https://h.invalid/anything") is True


@pytest.mark.parametrize("status", [0, 500, 502, 503])
def test_unreachable_means_the_whole_host_is_disallowed(status):
    """§2.3.1.4. A fetcher that reads a timeout as permission has a preference, not a policy."""
    p = _policy("", status=status)
    assert p.source == robots.SOURCE_UNREACHABLE
    assert p.allows("https://h.invalid/anything") is False
    assert p.verdict("https://h.invalid/anything").rule is None


def test_a_host_that_does_not_resolve_is_not_a_host_that_refused():
    """The distinction that stopped eleven fabricated violations. NXDOMAIN is not a server declining
    to state a policy; it is the absence of a server, so there is no instruction to obey and no
    conduct claim to make either way."""
    p = _policy("", status=robots.STATUS_NO_HOST)
    assert p.source == robots.SOURCE_NO_HOST
    assert p.source != robots.SOURCE_UNREACHABLE
    assert p.allows("https://gone.invalid/anything") is True
    assert p.verdict("https://gone.invalid/anything").rule is None


@pytest.mark.parametrize("reason,expected", [
    (__import__("socket").gaierror(-5, "No address associated with hostname"),
     robots.STATUS_NO_HOST),
    (ConnectionRefusedError(111, "Connection refused"), robots.STATUS_NETWORK_FAILURE),
    (TimeoutError("timed out"), robots.STATUS_NETWORK_FAILURE),
])
def test_a_dns_failure_and_a_connection_failure_are_told_apart_at_the_transport(
        monkeypatch, reason, expected):
    """The two branches diverge on `socket.gaierror`, so the split is asserted where it is actually
    decided — in `_http_get`'s exception handling — and not only on the sentinel it produces."""
    import urllib.error
    import urllib.request

    def boom(*_a, **_k):
        raise urllib.error.URLError(reason)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    status, body = robots._http_get("https://h.invalid/robots.txt", robots.USER_AGENT)
    assert (status, body) == (expected, "")


def test_an_unreachable_host_is_disallowed_even_where_a_cached_body_would_allow():
    """Guards against a future refactor that consults directives before the source."""
    p = robots.RobotsPolicy("h.invalid", [("allow", "/")], "*", robots.SOURCE_UNREACHABLE, None, "")
    assert p.allows("https://h.invalid/anything") is False


# --- the verdict is quotable ------------------------------------------------ #

def test_the_verdict_names_the_directive_that_decided_it_verbatim():
    v = _policy(BODY_WILDCARDS).verdict("https://h.invalid/wfm/reference/welcome")
    assert v.allowed is False
    assert v.rule == "Disallow: /wfm/"
    assert v.source == robots.SOURCE_RULES


def test_an_allowed_url_with_no_matching_rule_reports_no_directive():
    v = _policy("User-agent: *\nDisallow: /x/\n").verdict("https://h.invalid/y")
    assert v.allowed is True and v.rule is None


# --- fetching is once per host, and injectable ------------------------------ #

def test_a_hosts_robots_txt_is_fetched_once_per_agent():
    robots.clear_cache()
    calls = []

    def fake(url, agent):
        calls.append((url, agent))
        return 200, "User-agent: *\nDisallow: /x/\n"

    for path in ("/a", "/b", "/x/c"):
        robots.fetch_policy(f"https://one.invalid{path}", get=fake, today="2026-01-01")
    robots.fetch_policy("https://two.invalid/a", get=fake, today="2026-01-01")
    assert [u for u, _ in calls] == ["https://one.invalid/robots.txt", "https://two.invalid/robots.txt"]
    robots.clear_cache()


def test_the_robots_url_is_derived_from_the_page_url():
    assert robots.robots_url("https://h.invalid/deep/path?q=1") == "https://h.invalid/robots.txt"
