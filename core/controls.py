"""Recon controls: the two objections a thin fetch result always draws, answered before it is reported.

A recon that reports "this host serves us almost nothing" invites two immediate and entirely
reasonable objections, and a record that leaves either unanswered is not evidence:

  * **"Your fetcher is broken."** — refuted by `reachability_control`, which retrieves an unrelated
    host through the same fetcher, same user agent, same session, and reports what came back.
  * **"You mis-detected a soft 404 as a page."** — refuted by `soft_404_baseline`, which asks the host
    what it does with a path that cannot exist.

Both were run by hand on two prior targets and recorded as prose. Nothing made them mandatory and
nothing checked them, which is how a check becomes a habit and then a memory (ADR-0015). They are code
here for one specific reason, recorded in ADR-0047: without the baseline, a well-known-path sweep of a
host that answers HTTP 200 for everything reports that the vendor publishes a specification at four
well-known paths, and that claim is FALSE. It was nearly published once.

So `well_known_spec_probe` takes `baseline` as a **required keyword argument**, and refuses to return
a `spec` verdict unless the baseline was established and the response differs from it. The wrong claim
is not discouraged here; there is no code path that emits it.

PACING (ADR-0048). These probes are seventeen requests to one host, and the first target measured with
them declared `Crawl-delay: 10` in the group we fall under. That recon was paced by wrapping the
injected `get` in a sleep, by hand, in a scratch script — the "run it and remember to" shape this module
exists to end, reintroduced one function further out. The delay is now read from the host's own
robots.txt, which is already fetched before the first request, and applied here. Nothing about it is
remembered by a cycle.

This module holds no vendor string and adds no retrieval policy of its own: robots is
`core.robots` (ADR-0036), extraction is `core.html_text` / `core.docs_fetch`, and the floor is
`core.docs_fetch.MIN_TEXT_BYTES` (ADR-0021).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import robots as robots_mod
from .docs_fetch import MAX_REPLACEMENT_RATIO, MIN_TEXT_BYTES, _decompress, pdf_to_text
from .html_text import html_to_text

USER_AGENT = robots_mod.USER_AGENT

# The paths a machine-readable API description is conventionally served at. This is the UNION of the
# sets two prior recons each invented for themselves, declared once so the next one extends a list
# instead of writing a third. Order is stable so a re-run diffs cleanly against a committed record.
WELL_KNOWN_SPEC_PATHS: tuple[str, ...] = (
    "/openapi.json",
    "/openapi.yaml",
    "/swagger.json",
    "/swagger/v1/swagger.json",
    "/swagger/docs/v1",
    "/api/swagger.json",
    "/api-docs",
    "/v2/api-docs",
    "/v3/api-docs",
    "/.well-known/openapi",
    "/.well-known/openapi.json",
    "/.well-known/ai-plugin.json",
    "/.well-known/mcp.json",
    "/graphql",
    "/api",
)

# Paths used to ask a host what it does with something that cannot exist. Two, not one, because a host
# may 404 a bare segment and shell a deeper one; and FIXED rather than random, so a committed record
# can be re-checked by hand years later against the same URLs.
NONSENSE_PATHS: tuple[str, ...] = (
    "/aire-control-no-such-path",
    "/aire-control/no-such-path/either.json",
)

# What a well-known path turned out to be.
SPEC = "spec"                              # parsed, carries a spec marker, and differs from the shell
SPEC_UNVERIFIED = "spec-unverified"        # looks like a spec, but no baseline was established
NOT_A_SPEC = "not-a-spec"                  # a real, distinct response with no spec marker in it
SHELL_INDISTINGUISHABLE = "shell-indistinguishable"   # 2xx, and identical to what a bad path returns
HONEST_404 = "honest-404"
DISALLOWED = "disallowed"                  # robots refused it; it was NOT requested
UNREACHABLE = "unreachable"                # network/DNS failure, or a 5xx

VERDICTS = (SPEC, SPEC_UNVERIFIED, NOT_A_SPEC, SHELL_INDISTINGUISHABLE, HONEST_404, DISALLOWED,
            UNREACHABLE)

# A parsed document is a specification if it is a mapping carrying one of these top-level keys. Kept
# deliberately short: these are the two the probed paths advertise, and a longer list would start
# crediting documents nobody probed for.
SPEC_MARKERS = ("openapi", "swagger")

# Where the pace came from. Written into the committed record, because "we waited" and "we waited
# because the host asked us to" are different claims and only one of them is checkable.
DELAY_ROBOTS = "robots"            # the host's own Crawl-delay, in the group that governs this agent
DELAY_EXPLICIT = "explicit"        # the caller passed a number and overrode whatever the host said
DELAY_NONE = "none-declared"       # the host raised no rate at all, and the caller named none either

# How long a paced run may spend waiting before it refuses to start. A host is free to declare
# `Crawl-delay: 3600`, and seventeen probes at that rate is seventeen hours — in an unattended cycle
# that is a hang, and the tempting repair is to quietly pace faster than asked. This project does not
# get to do that: a directive is obeyed on its terms or the run is refused with the arithmetic stated.
MAX_TOTAL_WAIT_SECONDS = 600.0


@dataclass(frozen=True)
class Response:
    """One retrieval, with the status and the byte count kept — which is why this is not `_fetch`.

    `core.docs_fetch._fetch` raises on a 404 and discards the status on success, because a documentation
    fetcher only ever wants the text of a page it already believes in. A control wants exactly the cases
    that fetcher throws away: what status came back, how many bytes, and whether the body is the same
    body some other URL returned.
    """

    url: str
    status: int | None
    raw_bytes: int
    text: str
    content_type: str = ""
    error: str | None = None
    # The decoded body BEFORE extraction. Spec detection must not read `text`: extraction is built for
    # prose and would collapse a JSON document's whitespace and unescape its entities before any parser
    # saw it. Kept beside the extracted text rather than instead of it, because the two controls need
    # different things from the same response.
    raw_text: str = ""

    @property
    def text_bytes(self) -> int:
        return len(self.text.encode("utf-8"))

    @property
    def signature(self) -> str:
        """A hash of the EXTRACTED text, not the raw body.

        Raw bytes are the wrong thing to compare: a client-rendered shell commonly carries a per-request
        nonce or a build hash in a script tag, so two byte-different responses can be the same page.
        Extraction has already dropped the scripts, so this compares what a reader would receive.
        """
        return hashlib.sha256(re.sub(r"\s+", " ", self.text).strip().encode("utf-8")).hexdigest()[:16]

    @property
    def below_text_floor(self) -> bool:
        return self.text_bytes < MIN_TEXT_BYTES


@dataclass(frozen=True)
class Baseline:
    """What a host does with a path that cannot exist."""

    base_url: str
    probes: tuple[Response, ...] = ()

    @property
    def established(self) -> bool:
        """True when every probe answered and they AGREE with each other.

        Disagreement is not averaged over. A host that 404s one bad path and shells another has no
        single baseline behaviour, so nothing downstream may claim a response "differs from the shell"
        — there is no one shell to differ from.
        """
        if not self.probes or any(p.error for p in self.probes):
            return False
        return len({(p.status, p.signature) for p in self.probes}) == 1

    @property
    def status(self) -> int | None:
        return self.probes[0].status if self.probes else None

    @property
    def signature(self) -> str | None:
        return self.probes[0].signature if self.established else None

    @property
    def honest_404(self) -> bool:
        return self.established and self.status == 404

    @property
    def soft_404(self) -> bool:
        """The host answers a nonexistent path with success. Every 2xx it serves is now uninformative."""
        return self.established and self.status is not None and 200 <= self.status < 300

    @property
    def text_bytes(self) -> int | None:
        return self.probes[0].text_bytes if self.established else None


@dataclass(frozen=True)
class Finding:
    """One well-known path, judged against the baseline."""

    path: str
    url: str
    verdict: str
    status: int | None = None
    raw_bytes: int = 0
    text_bytes: int = 0
    detail: str = ""
    robots_rule: str | None = None


@dataclass(frozen=True)
class ControlReport:
    """Everything a recon record needs to state, in one object the CLI renders to YAML."""

    baseline: Baseline
    reachability: Response | None = None
    findings: tuple[Finding, ...] = ()
    user_agent: str = USER_AGENT
    notes: list[str] = field(default_factory=list)
    pacer: "Pacer | None" = None

    @property
    def specs_found(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.verdict == SPEC)


# --- pacing ----------------------------------------------------------------------------------- #

class PacingRefused(RuntimeError):
    """A paced run would wait longer than its budget. Raised BEFORE any request is issued."""


@dataclass
class Pacer:
    """Waits between requests to one host, at the rate that host asked for.

    `sleep` is injectable for the same reason `get` is: the suite is entirely offline, and conduct is
    asserted against the CALL LOG rather than against a verdict. The hazard entry this closes argued
    that a test asserting `run_controls` sleeps would pin an implementation rather than the conduct —
    which is true of a test that patches `time.sleep`, and not of one handed a recording function.

    The wait is owed BETWEEN requests, so the first costs nothing. A request that is never issued —
    a robots-refused path — costs nothing either, because `before_request` is called at the point of
    retrieval and a refusal never reaches it. Pacing a refusal would be theatre.
    """

    seconds: float = 0.0
    source: str = DELAY_NONE
    sleep: object = time.sleep
    budget_seconds: float = MAX_TOTAL_WAIT_SECONDS
    issued: int = 0
    waited: float = 0.0

    def projected(self, requests: int) -> float:
        """Seconds this pacer would spend waiting for `requests` further retrievals."""
        if self.seconds <= 0:
            return 0.0
        owed = requests if self.issued else max(0, requests - 1)
        return self.seconds * owed

    def check_budget(self, requests: int) -> None:
        projected = self.waited + self.projected(requests)
        if projected > self.budget_seconds:
            raise PacingRefused(
                f"{requests} request(s) at the declared {self.seconds}s ({self.source}) would wait "
                f"{projected:.0f}s, over the {self.budget_seconds:.0f}s budget. Raise "
                f"`max_total_wait` deliberately, probe fewer paths, or record the host as unprobed — "
                f"pacing faster than a host asked is not one of the options.")

    def before_request(self) -> None:
        if self.issued and self.seconds > 0:
            if self.waited + self.seconds > self.budget_seconds:
                self.check_budget(1)
            self.sleep(self.seconds)
            self.waited += self.seconds
        self.issued += 1


def make_pacer(policy=None, *, delay_seconds: float | None = None, sleep=time.sleep,
               max_total_wait: float = MAX_TOTAL_WAIT_SECONDS, already_issued: int = 0) -> Pacer:
    """Build the pacer for one host: the caller's delay if given, else the host's own, else none.

    `already_issued` is how the robots.txt retrieval is accounted for. It is a request to the same host,
    made moments earlier by `fetch_policy`, so the first content probe genuinely owes a wait — and a
    pacer that started at zero would fire it back-to-back with the very file that asked for the delay.
    """
    if delay_seconds is not None:
        seconds, source = float(delay_seconds), DELAY_EXPLICIT
    elif policy is not None and getattr(policy, "crawl_delay", None) is not None:
        seconds, source = float(policy.crawl_delay), DELAY_ROBOTS
    else:
        seconds, source = 0.0, DELAY_NONE
    return Pacer(seconds=seconds, source=source, sleep=sleep, budget_seconds=max_total_wait,
                 issued=already_issued)


# --- retrieval -------------------------------------------------------------------------------- #

def _http_probe(url: str, user_agent: str = USER_AGENT, timeout: int = 30):
    """`(status, raw, content_type)`, with an HTTP error status returned rather than raised.

    Injectable everywhere below, so the suite is entirely offline. A 404 is a fact about the path and
    the single most important one a control reports, so it must arrive as data.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (getattr(resp, "status", None),
                    _decompress(resp.read(), resp.headers.get("Content-Encoding")),
                    (resp.headers.get_content_type() or "").lower())
    except urllib.error.HTTPError as exc:
        return (exc.code, _decompress(exc.read(), exc.headers.get("Content-Encoding")),
                (exc.headers.get_content_type() or "").lower())


def _probe(url: str, *, user_agent: str = USER_AGENT, get=_http_probe, pacer: Pacer | None = None
           ) -> Response:
    if pacer is not None:
        pacer.before_request()
    try:
        status, raw, content_type = get(url, user_agent)
    except Exception as exc:  # DNS, TLS, timeout, connection reset
        return Response(url=url, status=None, raw_bytes=0, text="", error=f"{type(exc).__name__}: {exc}")
    raw = raw or b""
    if content_type == "application/pdf" or raw[:5] == b"%PDF-":
        return Response(url=url, status=status, raw_bytes=len(raw), text=pdf_to_text(raw),
                        content_type=content_type, raw_text="")
    decoded = raw.decode("utf-8", errors="replace")
    # A body this module could not decode is an ERROR, not a thin page. Reported rather than raised,
    # because a control's job is to describe what happened; but never reported as text, because the
    # failure ADDS bytes and would otherwise clear the ADR-0021 floor as "substantial documentation".
    if decoded and decoded.count("�") / len(decoded) > MAX_REPLACEMENT_RATIO:
        return Response(url=url, status=status, raw_bytes=len(raw), text="",
                        content_type=content_type, raw_text="",
                        error=f"undecodable: {len(raw)} B is mostly replacement characters "
                              f"(compressed or mis-declared, not text)")
    return Response(url=url, status=status, raw_bytes=len(raw), text=html_to_text(decoded),
                    content_type=content_type, raw_text=decoded)


def _join(base_url: str, path: str) -> str:
    parts = urllib.parse.urlsplit(base_url)
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))


# --- the three controls ----------------------------------------------------------------------- #

def soft_404_baseline(base_url: str, *, paths: tuple[str, ...] = NONSENSE_PATHS,
                      user_agent: str = USER_AGENT, get=_http_probe, policy=None,
                      robots_get=None, pacer: Pacer | None = None,
                      delay_seconds: float | None = None, sleep=time.sleep,
                      max_total_wait: float = MAX_TOTAL_WAIT_SECONDS) -> Baseline:
    """Ask `base_url`'s host what it returns for a path that cannot exist.

    Robots applies here too, and the first draft of this module forgot that — `well_known_spec_probe`
    checked and this did not, so a `Disallow: /` host would have received two unauthorised requests
    from the control that runs FIRST. Caught before it ran, and recorded because the asymmetry is the
    easy mistake: the sweep is obviously a retrieval, and the baseline reads like setup.

    A refused baseline is not established, so every downstream verdict caps at `spec-unverified`. That
    is the correct outcome: on a host that forbids reading, this project knows nothing about what its
    paths return, and must not imply otherwise.
    """
    own_policy = policy is None
    if own_policy:
        kwargs = {"user_agent": user_agent}
        if robots_get is not None:
            kwargs["get"] = robots_get
        policy = robots_mod.fetch_policy(base_url, **kwargs)
    if pacer is None:
        pacer = make_pacer(policy, delay_seconds=delay_seconds, sleep=sleep,
                           max_total_wait=max_total_wait, already_issued=1 if own_policy else 0)
    pacer.check_budget(len(paths))

    probes = []
    for p in paths:
        url = _join(base_url, p)
        verdict = policy.verdict(url)
        if not verdict.allowed:
            probes.append(Response(url=url, status=None, raw_bytes=0, text="",
                                   error=f"robots-Disallowed ({verdict.rule}); not requested"))
            continue
        probes.append(_probe(url, user_agent=user_agent, get=get, pacer=pacer))
    return Baseline(base_url=base_url, probes=tuple(probes))


def reachability_control(url: str, *, user_agent: str = USER_AGENT, get=_http_probe, policy=None,
                         robots_get=None) -> Response:
    """Retrieve an unrelated host through the same fetcher, so "your fetcher is broken" is answerable.

    The caller chooses the URL, and the choice is part of the record: the useful control is a host that
    is expected to serve substantial server-rendered text, so a thin result HERE means the instrument,
    and a thin result THERE means the target.

    ROBOTS APPLIES, and this is the THIRD function in this module to need that said. ADR-0047 records
    the baseline probe missing it while the sweep had it; this one missed it while both others had it,
    and was caught the same way — by reading the code before running it against a real host. The
    asymmetry keeps recurring for a reason worth naming: a control reads like instrumentation rather
    than retrieval, and instrumentation feels exempt. It is not. This issues a request to somebody's
    server, and being an unrelated third party is not consent.

    Deliberately unpaced by the target's pacer: this is a single request to a DIFFERENT host, and one
    host's declared rate is not an instruction the next host issued. A caller probing an unrelated host
    repeatedly owes it its own pacer.
    """
    if policy is None:
        kwargs = {"user_agent": user_agent}
        if robots_get is not None:
            kwargs["get"] = robots_get
        policy = robots_mod.fetch_policy(url, **kwargs)
    verdict = policy.verdict(url)
    if not verdict.allowed:
        return Response(url=url, status=None, raw_bytes=0, text="",
                        error=f"robots-Disallowed ({verdict.rule}); not requested")
    return _probe(url, user_agent=user_agent, get=get)


def _looks_like_a_spec(raw_text: str) -> tuple[bool, str]:
    """`(is_spec, detail)` — parsed as JSON or YAML, a mapping, and carrying a spec marker."""
    doc = None
    stripped = raw_text.strip()
    if not stripped:
        return False, "empty body"
    try:
        doc = json.loads(stripped)
    except ValueError:
        try:
            import yaml
            doc = yaml.safe_load(stripped)
        except Exception:
            return False, "body is neither JSON nor YAML"
    if not isinstance(doc, dict):
        return False, f"parsed as {type(doc).__name__}, not a mapping"
    present = [m for m in SPEC_MARKERS if m in doc]
    if not present:
        return False, f"a mapping with no {'/'.join(SPEC_MARKERS)} key"
    return True, f"declares {present[0]}: {doc[present[0]]!r}"


def well_known_spec_probe(base_url: str, *, baseline: Baseline,
                          paths: tuple[str, ...] = WELL_KNOWN_SPEC_PATHS,
                          policy=None, user_agent: str = USER_AGENT,
                          get=_http_probe, robots_get=None, pacer: Pacer | None = None,
                          delay_seconds: float | None = None, sleep=time.sleep,
                          max_total_wait: float = MAX_TOTAL_WAIT_SECONDS) -> list[Finding]:
    """Probe the well-known specification paths on `base_url`'s host.

    `baseline` is required, and that is the whole design. A host answering HTTP 200 for every path
    returns 200 here too; without knowing that, this function would report a specification at every
    well-known path, which is precisely the false claim ADR-0047 exists to prevent. With the baseline,
    an indistinguishable response is named as such and `SPEC` is unreachable for it.

    Robots is applied per path (ADR-0036): a Disallowed path is RECORDED and never requested.
    """
    own_policy = policy is None
    if own_policy:
        kwargs = {"user_agent": user_agent}
        if robots_get is not None:
            kwargs["get"] = robots_get
        policy = robots_mod.fetch_policy(base_url, **kwargs)
    if pacer is None:
        pacer = make_pacer(policy, delay_seconds=delay_seconds, sleep=sleep,
                           max_total_wait=max_total_wait, already_issued=1 if own_policy else 0)
    pacer.check_budget(len(paths))

    findings: list[Finding] = []
    for path in paths:
        url = _join(base_url, path)
        verdict_r = policy.verdict(url)
        if not verdict_r.allowed:
            findings.append(Finding(path=path, url=url, verdict=DISALLOWED,
                                    robots_rule=verdict_r.rule,
                                    detail="robots-Disallowed; not requested"))
            continue

        resp = _probe(url, user_agent=user_agent, get=get, pacer=pacer)
        if resp.error or resp.status is None:
            findings.append(Finding(path=path, url=url, verdict=UNREACHABLE, status=resp.status,
                                    detail=resp.error or "no status"))
            continue
        if resp.status == 404:
            findings.append(Finding(path=path, url=url, verdict=HONEST_404, status=resp.status,
                                    raw_bytes=resp.raw_bytes, text_bytes=resp.text_bytes))
            continue
        if resp.status >= 500 or resp.status < 200:
            findings.append(Finding(path=path, url=url, verdict=UNREACHABLE, status=resp.status,
                                    raw_bytes=resp.raw_bytes, text_bytes=resp.text_bytes,
                                    detail=f"HTTP {resp.status}"))
            continue
        if 300 <= resp.status < 400:
            findings.append(Finding(path=path, url=url, verdict=NOT_A_SPEC, status=resp.status,
                                    raw_bytes=resp.raw_bytes, text_bytes=resp.text_bytes,
                                    detail=f"redirect (HTTP {resp.status})"))
            continue

        # A 2xx. The baseline decides whether that means anything at all.
        if baseline.established and baseline.soft_404 and resp.signature == baseline.signature:
            findings.append(Finding(
                path=path, url=url, verdict=SHELL_INDISTINGUISHABLE, status=resp.status,
                raw_bytes=resp.raw_bytes, text_bytes=resp.text_bytes,
                detail=(f"byte-for-byte the response a nonexistent path returns "
                        f"(signature {resp.signature})")))
            continue

        is_spec, detail = _looks_like_a_spec(resp.raw_text)
        if not is_spec:
            findings.append(Finding(path=path, url=url, verdict=NOT_A_SPEC, status=resp.status,
                                    raw_bytes=resp.raw_bytes, text_bytes=resp.text_bytes,
                                    detail=detail))
            continue
        if not baseline.established:
            findings.append(Finding(
                path=path, url=url, verdict=SPEC_UNVERIFIED, status=resp.status,
                raw_bytes=resp.raw_bytes, text_bytes=resp.text_bytes,
                detail=(f"{detail}; NO baseline was established for this host, so this is not "
                        f"reported as a specification")))
            continue
        findings.append(Finding(path=path, url=url, verdict=SPEC, status=resp.status,
                                raw_bytes=resp.raw_bytes, text_bytes=resp.text_bytes, detail=detail))
    return findings


def run_controls(base_url: str, *, unrelated_url: str | None = None,
                 paths: tuple[str, ...] = WELL_KNOWN_SPEC_PATHS,
                 nonsense_paths: tuple[str, ...] = NONSENSE_PATHS,
                 user_agent: str = USER_AGENT, get=_http_probe, robots_get=None,
                 delay_seconds: float | None = None, sleep=time.sleep,
                 max_total_wait: float = MAX_TOTAL_WAIT_SECONDS) -> ControlReport:
    """All three controls, in the order a recon must run them.

    The baseline is established BEFORE the well-known sweep, not alongside it, because the sweep's
    verdicts are meaningless without it.

    ONE policy and ONE pacer are built here and passed down, rather than left to each control. Two
    pacers would each treat their own first request as owing nothing, so the last baseline probe and the
    first sweep probe would fire back to back — the one seam a per-function pacer cannot see. The whole
    projected wait is checked before any request is issued, so a host asking for more than the budget is
    refused up front rather than halfway through a sweep.
    """
    kwargs = {"user_agent": user_agent}
    if robots_get is not None:
        kwargs["get"] = robots_get
    policy = robots_mod.fetch_policy(base_url, **kwargs)
    pacer = make_pacer(policy, delay_seconds=delay_seconds, sleep=sleep,
                       max_total_wait=max_total_wait, already_issued=1)
    pacer.check_budget(len(nonsense_paths) + len(paths))

    baseline = soft_404_baseline(base_url, paths=nonsense_paths, user_agent=user_agent, get=get,
                                 policy=policy, pacer=pacer)
    # NOT `policy=policy` — that is the target's robots.txt and this is a different host, which owes
    # its own. Passing the target's would be inventing permission from an unrelated server's file.
    reach = (reachability_control(unrelated_url, user_agent=user_agent, get=get,
                                  robots_get=robots_get)
             if unrelated_url else None)
    findings = well_known_spec_probe(base_url, baseline=baseline, paths=paths, policy=policy,
                                     user_agent=user_agent, get=get, pacer=pacer)

    notes: list[str] = []
    if not baseline.established:
        notes.append("No baseline was established for this host, so no path can be reported as "
                     "serving a specification (verdicts cap at 'spec-unverified').")
    elif baseline.soft_404:
        notes.append(f"This host SOFT-404s: a nonexistent path returns HTTP {baseline.status} with "
                     f"{baseline.text_bytes} B of extracted text. Every 2xx it serves is "
                     f"uninformative until compared against that response.")
    if reach is not None and (reach.error or reach.below_text_floor):
        notes.append("The reachability control did NOT return substantial text, so a thin result at "
                     "the target cannot yet be attributed to the target. Choose a different control "
                     "host before reporting anything.")
    if pacer.source == DELAY_EXPLICIT and (policy.crawl_delay or 0) > pacer.seconds:
        notes.append(f"The caller's delay of {pacer.seconds}s OVERRIDES the {policy.crawl_delay}s this "
                     f"host declared. That is a decision, and it is on the record here.")
    return ControlReport(baseline=baseline, reachability=reach, findings=tuple(findings),
                         user_agent=user_agent, notes=notes, pacer=pacer)


# --- rendering -------------------------------------------------------------------------------- #

def as_record(report: ControlReport) -> dict:
    """The `controls:` block a recon record commits, as plain data.

    Generated rather than typed, for the reason `core.report` records in its own docstring:
    hand-maintained derived numbers go stale silently while the gated ones stay right.
    """
    b = report.baseline
    out: dict = {
        "user_agent": report.user_agent,
        "soft_404_control": {
            "base_url": b.base_url,
            "established": b.established,
            "probes": [{"url": p.url, "status": p.status, "raw_bytes": p.raw_bytes,
                        "text_bytes": p.text_bytes, "signature": p.signature,
                        **({"error": p.error} if p.error else {})} for p in b.probes],
            "verdict": ("soft-404 (a nonexistent path returns success)" if b.soft_404
                        else "honest 404s" if b.honest_404
                        else "no single baseline behaviour" if not b.established
                        else f"HTTP {b.status} for a nonexistent path"),
        },
        "well_known_spec_probe": {
            "paths_probed": len(report.findings),
            "specs_found": len(report.specs_found),
            "findings": [{"path": f.path, "status": f.status, "verdict": f.verdict,
                          "raw_bytes": f.raw_bytes, "text_bytes": f.text_bytes,
                          **({"detail": f.detail} if f.detail else {}),
                          **({"robots_rule": f.robots_rule} if f.robots_rule else {})}
                         for f in report.findings],
        },
    }
    if report.pacer is not None:
        p = report.pacer
        # Stated as three separate facts, because "we paced" is the claim a reader would otherwise have
        # to take on trust: what rate, who set it, and how much waiting actually happened.
        out["pacing"] = {
            "delay_seconds": p.seconds,
            "delay_source": p.source,
            "requests_issued": p.issued,
            "total_waited_seconds": round(p.waited, 3),
        }
    if report.reachability is not None:
        r = report.reachability
        out["fetcher_control"] = {
            "url": r.url, "status": r.status, "raw_bytes": r.raw_bytes, "text_bytes": r.text_bytes,
            **({"error": r.error} if r.error else {}),
            "verdict": ("the same fetcher retrieves substantial text from an unrelated host, so a thin "
                        "result at the target is a property of the target"
                        if not r.error and not r.below_text_floor
                        else "INCONCLUSIVE — this control host returned no substantial text either"),
        }
    if report.notes:
        out["notes"] = list(report.notes)
    return out
