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

This module holds no vendor string and adds no retrieval policy of its own: robots is
`core.robots` (ADR-0036), extraction is `core.html_text` / `core.docs_fetch`, and the floor is
`core.docs_fetch.MIN_TEXT_BYTES` (ADR-0021).
"""
from __future__ import annotations

import hashlib
import json
import re
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

    @property
    def specs_found(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.verdict == SPEC)


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


def _probe(url: str, *, user_agent: str = USER_AGENT, get=_http_probe) -> Response:
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
                      user_agent: str = USER_AGENT, get=_http_probe) -> Baseline:
    """Ask `base_url`'s host what it returns for a path that cannot exist."""
    return Baseline(base_url=base_url,
                    probes=tuple(_probe(_join(base_url, p), user_agent=user_agent, get=get)
                                 for p in paths))


def reachability_control(url: str, *, user_agent: str = USER_AGENT, get=_http_probe) -> Response:
    """Retrieve an unrelated host through the same fetcher, so "your fetcher is broken" is answerable.

    The caller chooses the URL, and the choice is part of the record: the useful control is a host that
    is expected to serve substantial server-rendered text, so a thin result HERE means the instrument,
    and a thin result THERE means the target.
    """
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
                          get=_http_probe, robots_get=None) -> list[Finding]:
    """Probe the well-known specification paths on `base_url`'s host.

    `baseline` is required, and that is the whole design. A host answering HTTP 200 for every path
    returns 200 here too; without knowing that, this function would report a specification at every
    well-known path, which is precisely the false claim ADR-0047 exists to prevent. With the baseline,
    an indistinguishable response is named as such and `SPEC` is unreachable for it.

    Robots is applied per path (ADR-0036): a Disallowed path is RECORDED and never requested.
    """
    if policy is None:
        kwargs = {"user_agent": user_agent}
        if robots_get is not None:
            kwargs["get"] = robots_get
        policy = robots_mod.fetch_policy(base_url, **kwargs)

    findings: list[Finding] = []
    for path in paths:
        url = _join(base_url, path)
        verdict_r = policy.verdict(url)
        if not verdict_r.allowed:
            findings.append(Finding(path=path, url=url, verdict=DISALLOWED,
                                    robots_rule=verdict_r.rule,
                                    detail="robots-Disallowed; not requested"))
            continue

        resp = _probe(url, user_agent=user_agent, get=get)
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
                 user_agent: str = USER_AGENT, get=_http_probe, robots_get=None) -> ControlReport:
    """All three controls, in the order a recon must run them.

    The baseline is established BEFORE the well-known sweep, not alongside it, because the sweep's
    verdicts are meaningless without it.
    """
    baseline = soft_404_baseline(base_url, paths=nonsense_paths, user_agent=user_agent, get=get)
    reach = (reachability_control(unrelated_url, user_agent=user_agent, get=get)
             if unrelated_url else None)
    findings = well_known_spec_probe(base_url, baseline=baseline, paths=paths,
                                     user_agent=user_agent, get=get, robots_get=robots_get)

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
    return ControlReport(baseline=baseline, reachability=reach, findings=tuple(findings),
                         user_agent=user_agent, notes=notes)


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
