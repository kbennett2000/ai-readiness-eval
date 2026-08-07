"""A robots.txt that does not address us is not an absent robots.txt (ADR-0060).

The sixth provenance state, asserted against the body that forced it. Every case here is a claim
about what this project WROTE DOWN rather than about what it fetched: the new state permits exactly
what `no-robots-txt` permits, and a test below pins that so no later edit can turn a recording change
into a prohibition.

**The fixture is the real body.** `NO_GROUP_BODY` is transcribed verbatim from the recon record of
the measured documentation host that raised public issue #107 — 386 bytes, HTTP 200, served as a
real `text/plain` robots file, naming ten crawler groups and granting each of them `Allow: /`, with
**no `*` group anywhere in it**. Exactly one line is changed: the trailing `Sitemap:` line, which is
the only line in the file that names the host, and therefore the only line this public repository may
not carry. Its SHA-256 and the unmodified text live in that pack's `specs.yaml` recon record.

A synthetic fixture would have been weaker in a specific way. The shape that produces this state is
not one anybody would invent — a file that is *more* permissive than most, addressing more readers
by name than most, and saying nothing at all about the reader that actually arrives.
"""
import pytest

from core import robots

# The ten groups, in file order, verbatim. The `Sitemap:` line names the host and is the one
# substitution; `h.invalid` is the reserved name the rest of this suite uses.
NO_GROUP_BODY = """User-agent: GPTBot
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Claude-Web
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Amazonbot
Allow: /

User-agent: Bingbot
Allow: /

User-agent: Bytespider
Allow: /

User-agent: Google-Extended
Allow: /

Sitemap: https://h.invalid/sitemap.xml
"""

# The other measured 200-that-is-not-a-robots-file: a host answering /robots.txt with its site-wide
# JavaScript shell. Zero groups, so it stays ABSENT — a page with no rules in it stated no rule.
JS_SHELL = "<!doctype html><html><body><div id=root></div><script src=/app.js></script></body></html>"

PATHS = ["https://h.invalid/", "https://h.invalid/reference/api", "https://h.invalid/a/b/c?q=1",
         "https://h.invalid/sitemap.xml", "https://h.invalid/anything$weird"]


def _policy(body: str, agent: str = robots.USER_AGENT, status: int = 200) -> robots.RobotsPolicy:
    return robots.policy_from_response("h.invalid", status, body, user_agent=agent, today="2026-01-01")


# --- the three checks `assert_guard_ran.SUITE_REQUIRED` requires by name ----- #

def test_a_served_robots_txt_naming_no_group_for_us_is_not_recorded_as_absent():
    """THE FIRE. The state exists because this exact record was being published as `no-robots-txt`.

    "No robots.txt" is a claim that the host never stated a policy. This host stated one, at length,
    and declined to mention us — which is ADR-0052's distinction reached by a different route. A
    refusal has a status code and is visible; this leaves no trace but an empty directive list, which
    is what an absent file leaves too.
    """
    p = _policy(NO_GROUP_BODY)
    assert p.source == robots.SOURCE_NO_GROUP
    assert p.source != robots.SOURCE_ABSENT, \
        "the whole point is that this is no longer recorded as an absence"
    # ...and the annotation must not simultaneously claim the wildcard group applied. There is no
    # wildcard group in this file; saying otherwise is the record contradicting itself in one row.
    assert p.agent_group == robots.AGENT_GROUP_NONE
    assert p.agent_group, "the annotation sweep requires a truthy agent group on every page"


def test_a_genuinely_absent_robots_txt_is_still_recorded_as_absent():
    """THE THEFT CHECK. A new state earns its place by taking cases from nowhere.

    Each input below is a world in which the host really did state nothing: it answered not-found,
    or it answered with a body that declares no group at all. Two of the four are measured — the
    404 family across the cohort, and the JS shell ADR-0036 argued about.
    """
    for status, body, why in [(404, "", "not found"),
                              (410, "", "gone"),
                              (200, "", "an empty 200 body"),
                              (200, "   \n\n  ", "a whitespace-only body"),
                              (200, JS_SHELL, "a site shell, which declares no group")]:
        p = _policy(body, status=status)
        assert p.source == robots.SOURCE_ABSENT, \
            f"{why} must stay `no-robots-txt`, not become {p.source!r}"
        assert p.agent_group == "*", f"{why} should still read as the wildcard fallback"


def test_a_matching_group_is_unaffected():
    """THE OTHER THEFT CHECK. A group that DOES govern us keeps producing rules and citing them."""
    wildcard = _policy("User-agent: *\nDisallow: /x/\n")
    assert wildcard.source == robots.SOURCE_RULES
    assert wildcard.agent_group == "*"
    assert wildcard.allows("https://h.invalid/x/y") is False
    assert wildcard.verdict("https://h.invalid/x/y").rule == "Disallow: /x/"

    named = _policy(f"User-agent: {robots.USER_AGENT}\nDisallow: /ours/\n")
    assert named.source == robots.SOURCE_RULES
    assert named.agent_group == robots.USER_AGENT
    assert named.allows("https://h.invalid/ours/x") is False


# --- requirement 1: a record fix, never a permission change ------------------ #

@pytest.mark.parametrize("url", PATHS)
def test_the_new_state_permits_exactly_what_absence_permits(url):
    """The permission half, asserted rather than assumed.

    `verdict()` special-cases only `SOURCE_UNREACHABLE`, so a state with no directives allows
    everything — but "so it must be fine" is the reasoning ADR-0052 also had available and wrote a
    test for anyway. If this ADR ever changed what a host is allowed to fetch, it would be the wrong
    thing built, and this is what says so.
    """
    served = _policy(NO_GROUP_BODY).verdict(url)
    absent = _policy("", status=404).verdict(url)
    assert served.allowed is absent.allowed is True
    assert served.rule is absent.rule is None
    # The two states differ in exactly one field, which is the entire change.
    assert served.source != absent.source


def test_no_directive_in_the_file_can_reach_us():
    """Stronger than the parametrized case: the fixture grants `Allow: /` ten times over, and not
    one of those grants is ours to cite. A rule appearing here would mean a group had been matched."""
    p = _policy(NO_GROUP_BODY)
    assert p.directives == []
    assert all(p.verdict(u).rule is None for u in PATHS)


def test_the_new_state_declares_no_crawl_delay():
    """A rate a host asked of a crawler it named is not a rate it asked of us (ADR-0048). Pinned
    here because the delay is read off the governing group, and in this state there is none."""
    body = NO_GROUP_BODY.replace("User-agent: Bingbot\nAllow: /",
                                 "User-agent: Bingbot\nAllow: /\nCrawl-delay: 30")
    p = _policy(body)
    assert p.source == robots.SOURCE_NO_GROUP
    assert p.crawl_delay is None, "a delay declared for a named crawler must not leak to us"


# --- requirement 6: ADR-0007 stands ----------------------------------------- #

def test_a_named_crawlers_grant_is_not_ours():
    """The file grants `ClaudeBot` `Allow: /`. We are not ClaudeBot and do not become it.

    This is the temptation the state creates: a host that says no group applies to us is a host one
    header away from saying `Allow: /`. Public ADR-0007 settles it — the policy a retrieval is judged
    against has to be the policy for the agent it presented itself as — and borrowing a named
    crawler's grant would make the conduct record describe a request nobody made. Asserted as a test
    on the exact body that offers the grant, rather than left as a sentence in an ADR.
    """
    assert "ClaudeBot" in NO_GROUP_BODY and "Allow: /" in NO_GROUP_BODY
    p = _policy(NO_GROUP_BODY)
    assert p.agent_group != "claudebot"
    assert p.source == robots.SOURCE_NO_GROUP, \
        "our agent must be judged as unaddressed, not as a crawler the host did name"
    assert robots.USER_AGENT == "ai-readiness-eval-docs", \
        "the fetch agent is fixed and self-identifying; a named-crawler string is not an option"


def test_the_same_file_governs_a_reader_it_does_name():
    """The state is a fact about a CONVERSATION, not about the host — ADR-0052's argument, and the
    proof is that one body yields two states depending only on who asked."""
    ours = _policy(NO_GROUP_BODY)
    theirs = _policy(NO_GROUP_BODY, agent="Mozilla/5.0 (compatible; Bingbot/2.0)")
    assert ours.source == robots.SOURCE_NO_GROUP and ours.agent_group == robots.AGENT_GROUP_NONE
    assert theirs.source == robots.SOURCE_RULES and theirs.agent_group == "bingbot"
    assert theirs.allows("https://h.invalid/anything") is True


# --- non-vacuity: each of the three above, broken on purpose ---------------- #

def test_the_fire_needs_the_declared_groups_and_nothing_else():
    """Break the fixture instead of the code: strip the `User-agent:` lines and the same file, with
    the same length and the same `Allow: /` lines, records as ABSENT again. That is the evidence the
    fire is caused by the declared groups rather than by anything else in the body."""
    stripped = "\n".join(ln for ln in NO_GROUP_BODY.splitlines()
                         if not ln.lower().startswith("user-agent:"))
    assert "Allow: /" in stripped
    assert _policy(stripped).source == robots.SOURCE_ABSENT


def test_a_wildcard_group_stating_no_rule_is_still_an_absence():
    """The case deliberately NOT split, and the boundary that makes the new state a state rather
    than a catch-all: this host addressed us. It put us in a group and then asked nothing of us,
    which is a different fact from never mentioning us. ADR-0048's delay case rides on this."""
    p = _policy("User-agent: *\nCrawl-delay: 7\n")
    assert p.source == robots.SOURCE_ABSENT
    assert p.crawl_delay == 7.0, "the delay still travels — it is an instruction addressed to us"


def test_a_group_naming_us_and_stating_no_rule_is_also_an_absence():
    p = _policy(f"User-agent: {robots.USER_AGENT}\nCrawl-delay: 3\n")
    assert p.source == robots.SOURCE_ABSENT
    assert p.agent_group == robots.USER_AGENT and p.crawl_delay == 3.0


def test_a_file_with_a_wildcard_group_beside_named_ones_still_governs_us():
    """One `User-agent: *` line anywhere in the fixture puts it back under the old ruling."""
    p = _policy(NO_GROUP_BODY + "\nUser-agent: *\nDisallow: /private/\n")
    assert p.source == robots.SOURCE_RULES
    assert p.allows("https://h.invalid/private/x") is False


def test_parse_keeps_its_three_value_contract():
    """`_Parsed` exists so that widening what a parse knows did not mean editing every caller."""
    directives, agent_group, delay = robots.parse(NO_GROUP_BODY)
    assert (directives, agent_group, delay) == ([], "*", None)
    # The two facts `parse` cannot return, which is why `policy_from_response` uses the wider view.
    parsed = robots._parse_groups(NO_GROUP_BODY)
    assert len(parsed.group_names) == 10 and parsed.governed is False
    assert parsed.group_names[0] == "gptbot" and parsed.group_names[-1] == "google-extended"


def test_the_state_string_and_the_agent_sentinel_are_their_own():
    """These strings are written into pack manifests and cited on cards, so a collision would make
    two different findings indistinguishable in the record a reviewer reads."""
    states = [v for name, v in vars(robots).items()
              if name.startswith("SOURCE_") and isinstance(v, str)]
    assert robots.SOURCE_NO_GROUP in states and len(states) == len(set(states))
    assert robots.AGENT_GROUP_NONE not in states
    assert robots.SOURCE_NO_GROUP.startswith("robots.txt"), \
        "the prefix is what tells a reader at a glance that a file WAS served"
