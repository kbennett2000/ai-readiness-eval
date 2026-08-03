"""The RFC 9309 matcher, rule by rule (ADR-0036).

Every case here is a claim about what this project is permitted to fetch, so each is asserted against a
hand-written robots body rather than a live host — the suite is offline by construction and the only
network path is the `annotate-robots` command.

The two cases that forced the module exist at the top: `Disallow: /*/api-next` and `Disallow: /wfm$`.
`urllib.robotparser` gets both wrong in opposite directions, which is why it is not used.
"""
import ast
import pathlib

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


def test_this_module_does_not_delegate_to_the_standard_library():
    """Non-vacuity for the whole module, stated as a property of this code rather than of CPython's.

    This test used to assert the opposite of a fact: that `urllib.robotparser` mis-reads
    `Disallow: /*/api-next`, which was the stated reason for writing this module (ADR-0036). Its
    docstring promised that if the stdlib ever became correct, it would fire and the argument could
    be re-examined rather than inherited. **It fired, on 2026-08-01, in CI.** CPython rewrote
    `urllib.robotparser` to RFC 9309 between 3.14.4 and 3.14.6, and on 3.14.6 it agrees with this
    module on every case in `BODY_WILDCARDS`, including both forms that motivated it.

    So the old assertion has to go: it is now false on a new interpreter and true on an old one,
    which makes it a test of the runner rather than of this repository. What replaces it is the
    claim that was always the real one — this module decides for itself. See ADR-0043 for why it
    stays now that the stdlib has caught up: an answer that changed between two patch releases of
    one minor version is an answer whose value depends on which machine asked, and a fetch-permission
    decision that varies by interpreter is not one this project can publish or reproduce.
    """
    tree = ast.parse(pathlib.Path(robots.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = sorted(n for n in imported if "robotparser" in n)
    assert not offenders, (
        f"core/robots.py imports {offenders}. Every case in this file would then be testing "
        f"CPython's parser, which changed its answers inside a single minor version — see ADR-0043."
    )


def test_our_answers_do_not_move_when_the_standard_library_does():
    """The converse, and the actual argument for keeping the module.

    Runs the same body through both and asserts only OURS. Whatever the interpreter's parser says —
    it said one thing on 3.14.4 and another on 3.14.6 — the pinned table above is what this project
    acts on. A failure here means our matcher moved, which is the only movement that matters.
    """
    import urllib.robotparser

    policy = _policy(BODY_WILDCARDS)
    for path, expected in [
        ("https://h.invalid/hcm/api-next/v2/branches", False),
        ("https://h.invalid/wfm", False),
        ("https://h.invalid/wfmx/reference", True),
    ]:
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(BODY_WILDCARDS.splitlines())
        rp.can_fetch(robots.USER_AGENT, path)      # exercised, deliberately not asserted
        assert policy.allows(path) is expected, (
            f"our matcher moved on {path} — it, not the stdlib, is what ADR-0036 publishes"
        )


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


# --- Crawl-delay is a directive in this file too (ADR-0048) ----------------- #

def test_a_declared_crawl_delay_reaches_the_policy():
    """The whole of the defect: this value was parsed by nothing and reached nobody."""
    p = _policy("User-agent: *\nDisallow: /x/\nCrawl-delay: 10\n")
    assert p.crawl_delay == 10.0


def test_a_host_that_declares_no_delay_reports_none_rather_than_zero():
    """None is 'never raised'; 0.0 is 'considered and declined'. A caller must be able to tell."""
    assert _policy("User-agent: *\nDisallow: /x/\n").crawl_delay is None
    assert _policy("User-agent: *\nDisallow: /x/\nCrawl-delay: 0\n").crawl_delay == 0.0


def test_the_delay_is_read_from_the_group_that_governs_us():
    body = ("User-agent: *\nDisallow: /everyone-else/\nCrawl-delay: 30\n\n"
            "User-agent: ai-readiness-eval-docs\nDisallow: /us/\nCrawl-delay: 2\n")
    assert _policy(body).crawl_delay == 2.0
    # ...and the wildcard delay is what an agent falling back to `*` gets, not ours.
    assert _policy(body, agent="some-other-crawler").crawl_delay == 30.0


def test_a_delay_in_a_group_that_does_not_govern_us_does_not_leak():
    body = ("User-agent: ai-readiness-eval-docs\nDisallow: /us/\n\n"
            "User-agent: Chrome\nDisallow: /b/\nCrawl-delay: 45\n")
    assert _policy(body).crawl_delay is None
    assert _policy(body, agent=BROWSER_UA).crawl_delay == 45.0


def test_the_wildcard_delay_does_not_reach_a_group_that_names_us_and_states_none():
    """A named group REPLACES the wildcard group — this module already asserts that for rules, and the
    delay follows the same semantics or the policy is half one group and half another, which is a thing
    no host wrote. A host that names us and gives us no rate has given us no rate.

    Written after a deliberate `delays.get(chosen) or delays.get("*")` fallback survived the first
    version of these tests: every case there gave OUR group a delay, so the leak had nowhere to show.
    """
    body = ("User-agent: *\nDisallow: /everyone-else/\nCrawl-delay: 30\n\n"
            "User-agent: ai-readiness-eval-docs\nDisallow: /us/\n")
    p = _policy(body)
    assert p.agent_group == "ai-readiness-eval-docs"
    assert p.crawl_delay is None


def test_a_crawl_delay_line_does_not_re_cut_the_rules_groups():
    """Only allow/disallow open a rules group; a rate directive is not a rule and does not close the
    agent list. The case below is where the two readings diverge, and it is a fetch PERMISSION that
    turns on it: with `crawl-delay` ending the agent list, our named group holds no rule at all, the
    policy reads as an absent robots.txt, and this host's `Disallow: /` never reaches us.

    That is the whole reason the flag is left alone. A rate-limit directive must not be able to hand
    this project a green light on a host that wrote `Disallow: /` three lines further down.
    """
    body = ("User-agent: ai-readiness-eval-docs\nCrawl-delay: 5\n"
            "User-agent: *\nDisallow: /\n")
    p = _policy(body)
    assert p.allows("https://h.invalid/anything") is False, (
        "a Crawl-delay line split the group and turned a site-wide Disallow into permission")


def test_a_delay_after_a_rule_still_ends_its_group_at_the_next_agent_line():
    body = ("User-agent: alpha\nDisallow: /alpha/\nCrawl-delay: 5\n"
            "User-agent: ai-readiness-eval-docs\nDisallow: /ours/\n")
    p = _policy(body)
    assert p.agent_group == "ai-readiness-eval-docs"
    assert p.allows("https://h.invalid/alpha/x") is True
    assert p.allows("https://h.invalid/ours/x") is False
    assert p.crawl_delay is None, "a delay declared for another agent was applied to us"


def test_a_group_stating_the_delay_twice_gets_the_slower_of_them():
    """Malformed, and no convention rules on it. The tie breaks towards the host: waiting longer than
    asked can only be more polite, and the other direction cannot say that."""
    assert _policy("User-agent: *\nDisallow: /x/\nCrawl-delay: 2\nCrawl-delay: 9\n").crawl_delay == 9.0
    assert _policy("User-agent: *\nDisallow: /x/\nCrawl-delay: 9\nCrawl-delay: 2\n").crawl_delay == 9.0


@pytest.mark.parametrize("value", ["soon", "", "-5", "10s", "nan", "inf"])
def test_an_unusable_delay_is_absent_rather_than_zero(value):
    """0.0 would read downstream as 'the host permits an unpaced burst' — a permission a typo did not
    grant. An unparseable value is an absence of instruction, and falls back to the caller's default."""
    p = _policy(f"User-agent: *\nDisallow: /x/\nCrawl-delay: {value}\n")
    assert p.crawl_delay is None


def test_a_delay_survives_a_body_that_states_no_fetch_rule():
    """A host may state a rate and no Allow/Disallow. `source` records that no permission rule was
    applied; the rate is still an instruction and still travels."""
    p = _policy("User-agent: *\nCrawl-delay: 7\n")
    assert p.source == robots.SOURCE_ABSENT
    assert p.crawl_delay == 7.0


@pytest.mark.parametrize("status", [404, 500, robots.STATUS_NO_HOST, robots.STATUS_NETWORK_FAILURE])
def test_a_host_that_stated_nothing_declares_no_delay(status):
    """No body, no directive. A default invented here would be a rate this host never asked for."""
    assert _policy("", status=status).crawl_delay is None


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
