"""The recon controls (ADR-0047), with every rule broken on purpose.

Entirely offline: `get` is injected everywhere, so no test here touches a network. The fixture hosts
are synthetic and carry no vendor identity, which is what keeps `core/` name-free.

The rule that matters most is the last group: a host answering HTTP 200 for everything must not be
reported as publishing a specification at every well-known path. That claim was nearly published once
(the ADR quotes it), so it is asserted from four directions rather than one.
"""
from __future__ import annotations

import json

import pytest

from core import controls
from core.robots import RobotsPolicy

SHELL = b"<html><head><title>App</title></head><body><div id=root></div><script>boot()</script></body></html>"
REAL_PAGE = b"<html><body><h1>Payments</h1><p>" + b"documented prose. " * 40 + b"</p></body></html>"
SPEC_DOC = json.dumps({"openapi": "3.0.1", "paths": {"/things": {}}}).encode()
SWAGGER_DOC = json.dumps({"swagger": "2.0", "basePath": "/v1", "paths": {}}).encode()


def _host(mapping, *, default=(404, b"<html><body>Not found</body></html>", "text/html")):
    """A stub host. `mapping` is {path: (status, body, content_type)}; everything else 404s."""
    calls = []

    def get(url, user_agent=controls.USER_AGENT, timeout=30):
        calls.append(url)
        path = url.split("://", 1)[1].split("/", 1)[1]
        return mapping.get("/" + path, default)

    get.calls = calls
    return get


def _always(status, body, content_type="text/html"):
    calls = []

    def get(url, user_agent=controls.USER_AGENT, timeout=30):
        calls.append(url)
        return status, body, content_type

    get.calls = calls
    return get


ALLOW_ALL = RobotsPolicy(host="example.test", directives=[], source="no-robots-txt")


def _robots(body: str = ""):
    """A stub for `core.robots`'s fetcher, so `run_controls` resolves a policy without a network."""
    def get(url, user_agent, timeout=25):
        return (200, body) if body else (404, "")

    return get


@pytest.fixture(autouse=True)
def _clear_robots_cache():
    from core import robots as robots_mod
    robots_mod.clear_cache()
    yield
    robots_mod.clear_cache()


# --- the soft-404 baseline -------------------------------------------------------------------- #

def test_a_success_status_for_a_nonexistent_path_is_a_soft_404():
    b = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=_always(200, SHELL))
    assert b.established and b.soft_404 and not b.honest_404


def test_a_404_for_a_nonexistent_path_is_recorded_as_honest():
    b = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=_always(404, b"<html>no</html>"))
    assert b.established and b.honest_404 and not b.soft_404


def test_a_host_that_answers_two_bad_paths_differently_establishes_no_baseline():
    """Not averaged over. With two behaviours there is no single shell for anything to differ from."""
    def get(url, user_agent=controls.USER_AGENT, timeout=30):
        return (404, b"<html>no</html>", "text/html") if url.endswith("path") else (200, SHELL, "text/html")

    b = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    assert not b.established
    assert b.signature is None and b.text_bytes is None


def test_a_baseline_probe_that_errors_is_not_a_baseline():
    def boom(url, user_agent=controls.USER_AGENT, timeout=30):
        raise OSError("connection reset")

    b = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=boom)
    assert not b.established
    assert all(p.error for p in b.probes)


def test_the_signature_ignores_a_per_request_nonce_in_a_script():
    """Raw bytes differ, extracted text does not — so two responses are recognised as the same page."""
    seen = []

    def get(url, user_agent=controls.USER_AGENT, timeout=30):
        seen.append(url)
        nonce = str(len(seen)) * 12
        return 200, SHELL.replace(b"boot()", b"boot('" + nonce.encode() + b"')"), "text/html"

    b = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    assert len({p.raw_bytes for p in b.probes}) == 1  # same length here, but the bodies differ
    assert b.probes[0].raw_text != b.probes[1].raw_text
    assert b.established, "a nonce inside a <script> must not defeat the baseline"


# --- the reachability control ----------------------------------------------------------------- #

def test_the_reachability_control_reports_extracted_text_not_raw_bytes():
    """A 100 KB shell extracting to nothing is the exact case this control exists to expose."""
    big_shell = b"<html><body><div id=root></div><script>" + b"x" * 100_000 + b"</script></body></html>"
    r = controls.reachability_control("https://unrelated.test/", get=_always(200, big_shell))
    assert r.raw_bytes > 100_000
    assert r.text_bytes < controls.MIN_TEXT_BYTES
    assert r.below_text_floor


def test_a_control_host_that_serves_real_prose_passes_the_floor():
    r = controls.reachability_control("https://unrelated.test/", get=_always(200, REAL_PAGE))
    assert not r.below_text_floor and r.error is None


# --- the well-known sweep, and the claim it must never make ------------------------------------ #

def test_the_probe_cannot_be_called_without_a_baseline():
    """`baseline` is keyword-only and required. This is the guarantee, so it is asserted directly."""
    with pytest.raises(TypeError):
        controls.well_known_spec_probe("https://example.test/")  # type: ignore[call-arg]


def test_a_host_that_200s_everything_reports_no_specification():
    """The ADR-0047 case. Without the baseline this reports a spec at every well-known path."""
    get = _always(200, SHELL)
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)

    assert len(findings) == len(controls.WELL_KNOWN_SPEC_PATHS)
    assert {f.verdict for f in findings} == {controls.SHELL_INDISTINGUISHABLE}
    assert not [f for f in findings if f.verdict == controls.SPEC]


def test_a_real_specification_at_a_well_known_path_is_found():
    """The control must not be so cautious that it can never say yes."""
    get = _host({"/openapi.json": (200, SPEC_DOC, "application/json")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)

    specs = [f for f in findings if f.verdict == controls.SPEC]
    assert [f.path for f in specs] == ["/openapi.json"]
    assert "3.0.1" in specs[0].detail


def test_a_swagger_2_document_is_a_specification_too():
    get = _host({"/swagger.json": (200, SWAGGER_DOC, "application/json")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    assert [f.path for f in findings if f.verdict == controls.SPEC] == ["/swagger.json"]


def test_a_specification_served_by_a_soft_404_host_is_still_found():
    """A soft-404 host may ALSO publish a real spec. The shell comparison must not swallow it."""
    get = _host({"/openapi.json": (200, SPEC_DOC, "application/json")},
                default=(200, SHELL, "text/html"))
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    assert baseline.soft_404
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    by_path = {f.path: f.verdict for f in findings}
    assert by_path["/openapi.json"] == controls.SPEC
    assert by_path["/swagger.json"] == controls.SHELL_INDISTINGUISHABLE


def test_json_that_is_not_a_specification_is_not_credited():
    """A `/graphql` endpoint answering 200 with an error object is JSON, and is not a spec."""
    get = _host({"/graphql": (200, b'{"errors":[{"message":"must POST"}]}', "application/json")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    f = next(f for f in findings if f.path == "/graphql")
    assert f.verdict == controls.NOT_A_SPEC
    assert "no openapi/swagger key" in f.detail


def test_a_json_list_is_not_a_specification():
    get = _host({"/api": (200, b'["a","b"]', "application/json")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    assert next(f for f in findings if f.path == "/api").verdict == controls.NOT_A_SPEC


def test_a_spec_body_is_read_from_the_raw_response_not_the_extracted_text():
    """Extraction is built for prose. A JSON document put through it must still parse.

    Broken by reading `resp.text`: the `&` in the description is unescaped to something the parser
    would still accept, but the `<` in a value is what a prose extractor eats.
    """
    doc = json.dumps({"openapi": "3.0.1", "info": {"title": "a <b> & c", "version": "1"}}).encode()
    get = _host({"/openapi.json": (200, doc, "application/json")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    assert next(f for f in findings if f.path == "/openapi.json").verdict == controls.SPEC


def test_without_an_established_baseline_a_spec_is_reported_as_unverified():
    """The invariant, stated the other way round: no `spec` verdict is reachable without a baseline."""
    def get(url, user_agent=controls.USER_AGENT, timeout=30):
        if url == "https://example.test/openapi.json":
            return 200, SPEC_DOC, "application/json"
        if url.endswith("no-such-path"):
            return 404, b"<html>no</html>", "text/html"
        return 200, SHELL, "text/html"          # the second nonsense path disagrees with the first

    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    assert not baseline.established
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    f = next(f for f in findings if f.path == "/openapi.json")
    assert f.verdict == controls.SPEC_UNVERIFIED
    assert not [x for x in findings if x.verdict == controls.SPEC]


def test_an_honest_404_is_recorded_as_one():
    get = _host({})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    assert {f.verdict for f in findings} == {controls.HONEST_404}


def test_a_server_error_is_unreachable_not_a_finding_about_the_path():
    get = _host({"/openapi.json": (503, b"upstream", "text/plain")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    assert next(f for f in findings if f.path == "/openapi.json").verdict == controls.UNREACHABLE


# --- conduct ---------------------------------------------------------------------------------- #

def test_a_disallowed_path_is_recorded_and_never_requested():
    """ADR-0036. The assertion is on the CALL LIST, not on the verdict: a rule that only changed the
    label while still fetching would pass a verdict-only test and violate the actual undertaking."""
    policy = RobotsPolicy(host="example.test", directives=[("disallow", "/.well-known/")],
                          source="robots.txt")
    get = _host({})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    before = len(get.calls)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=policy, get=get)

    refused = [f for f in findings if f.verdict == controls.DISALLOWED]
    assert {f.path for f in refused} == {p for p in controls.WELL_KNOWN_SPEC_PATHS
                                         if p.startswith("/.well-known/")}
    assert all(f.robots_rule == "Disallow: /.well-known/" for f in refused)
    requested = get.calls[before:]
    assert not [u for u in requested if "/.well-known/" in u], \
        "a Disallowed path was requested; the label changed and the conduct did not"


def test_every_verdict_emitted_is_one_the_module_declares():
    get = _host({"/openapi.json": (200, SPEC_DOC, "application/json"),
                 "/graphql": (200, b'{"data":null}', "application/json"),
                 "/api": (503, b"x", "text/plain")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=ALLOW_ALL, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=ALLOW_ALL, get=get)
    assert {f.verdict for f in findings} <= set(controls.VERDICTS)


def test_the_well_known_list_covers_what_both_prior_recons_probed():
    """The list is the UNION of two sets each invented separately. If it shrinks, that was the point."""
    for path in ("/openapi.json", "/swagger.json", "/swagger/v1/swagger.json", "/.well-known/openapi",
                 "/.well-known/ai-plugin.json", "/.well-known/mcp.json", "/graphql"):
        assert path in controls.WELL_KNOWN_SPEC_PATHS


# --- the emitted record ----------------------------------------------------------------------- #

def test_the_record_round_trips_through_yaml_and_names_the_soft_404():
    import yaml

    get = _always(200, SHELL)
    report = controls.run_controls("https://example.test/", unrelated_url="https://unrelated.test/",
                                   get=get, robots_get=_robots())
    record = controls.as_record(report)
    parsed = yaml.safe_load(yaml.safe_dump({"controls": record}, sort_keys=False))["controls"]

    assert parsed["soft_404_control"]["established"] is True
    assert "soft-404" in parsed["soft_404_control"]["verdict"]
    assert parsed["well_known_spec_probe"]["specs_found"] == 0
    assert parsed["well_known_spec_probe"]["paths_probed"] == len(controls.WELL_KNOWN_SPEC_PATHS)
    assert parsed["fetcher_control"]["url"] == "https://unrelated.test/"
    assert any("SOFT-404" in n for n in parsed["notes"])


def test_the_record_says_so_when_the_control_host_is_itself_thin():
    """An inconclusive control must read as inconclusive, not as a finding about the target."""
    report = controls.run_controls("https://example.test/", unrelated_url="https://unrelated.test/",
                                   get=_always(200, SHELL), robots_get=_robots())
    record = controls.as_record(report)
    assert "INCONCLUSIVE" in record["fetcher_control"]["verdict"]
    assert any("cannot yet be attributed" in n for n in record["notes"])


def test_a_clean_run_carries_no_alarming_notes():
    def get(url, user_agent=controls.USER_AGENT, timeout=30):
        if "unrelated.test" in url:
            return 200, REAL_PAGE, "text/html"
        if url == "https://example.test/openapi.json":
            return 200, SPEC_DOC, "application/json"
        return 404, b"<html>no</html>", "text/html"

    report = controls.run_controls("https://example.test/", unrelated_url="https://unrelated.test/",
                                   get=get, robots_get=_robots())
    assert report.notes == []
    assert [f.path for f in report.specs_found] == ["/openapi.json"]
    assert "property of the target" in controls.as_record(report)["fetcher_control"]["verdict"]


def test_run_controls_establishes_the_baseline_before_it_sweeps():
    """Ordering is the guarantee, so it is asserted against the call log rather than assumed."""
    get = _host({})
    controls.run_controls("https://example.test/", get=get, robots_get=_robots())
    nonsense = [u for u in get.calls if "aire-control" in u]
    well_known = [u for u in get.calls if "/openapi.json" in u]
    assert nonsense and well_known
    assert get.calls.index(well_known[0]) > get.calls.index(nonsense[-1])


# --- the bug this cycle found, in both fetch paths ---------------------------------------------- #

def _gzipped(body: bytes) -> bytes:
    import gzip
    return gzip.compress(body)


def test_a_gzipped_body_is_decompressed_rather_than_decoded_as_garbage():
    """The control that certified its own failure (ADR-0047).

    A host returned `Content-Encoding: gzip` without being asked. Nothing decompressed it, and
    11,569 B of gzip decoded with errors="replace" into 20,176 B of U+FFFD — which cleared the
    200 B floor by two orders of magnitude and was reported as "substantial text", from the very
    control whose job is to prove the fetcher works.
    """
    import gzip as _gzip

    payload = REAL_PAGE
    calls = []

    def get(url, user_agent=controls.USER_AGENT, timeout=30):
        calls.append(url)
        return 200, _gzip.compress(payload), "text/html"

    # `_probe` receives already-decompressed bytes from `_http_probe`; this stub stands in for a
    # transport that did NOT decompress, which is the state the bug was found in.
    r = controls._probe("https://example.test/", get=get)
    assert r.error and "replacement characters" in r.error
    assert r.text == "", "undecodable bytes must never be reported as text"
    assert r.below_text_floor


def test_the_transport_decompresses_a_declared_content_encoding():
    """`_http_probe` itself must undo the encoding, so `_probe` sees real bytes."""
    import gzip as _gzip

    class _Resp:
        status = 200
        headers = type("H", (), {
            "get_content_type": lambda self: "text/html",
            "get": lambda self, k, d=None: "gzip" if k == "Content-Encoding" else d})()

        def read(self):
            return _gzip.compress(REAL_PAGE)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request as _u
    real = _u.urlopen
    try:
        _u.urlopen = lambda req, timeout=30: _Resp()
        status, raw, ctype = controls._http_probe("https://example.test/")
    finally:
        _u.urlopen = real
    assert raw == REAL_PAGE, "the declared Content-Encoding was not undone"


def test_an_undecodable_reachability_control_is_inconclusive_not_a_pass():
    """The failure mode exactly: garbage that is LONGER than the floor must not read as a pass."""
    import gzip as _gzip

    r = controls.reachability_control(
        "https://unrelated.test/",
        get=lambda url, user_agent=controls.USER_AGENT, timeout=30: (
            200, _gzip.compress(b"x" * 40_000), "text/html"))
    assert r.error is not None
    report = controls.ControlReport(baseline=controls.Baseline("https://example.test/"),
                                    reachability=r)
    assert "INCONCLUSIVE" in controls.as_record(report)["fetcher_control"]["verdict"]


def test_the_baseline_itself_obeys_robots_and_requests_nothing_when_refused():
    """The asymmetry the first draft shipped: the sweep checked robots and the baseline did not.

    A `Disallow: /` host would have received the two nonsense-path requests from the control that
    runs FIRST. Asserted on the call log, like the sweep's own conduct test, because a version that
    recorded the refusal and fetched anyway would satisfy any assertion about the result.
    """
    refuse_all = RobotsPolicy(host="example.test", directives=[("disallow", "/")],
                              source="robots.txt")
    get = _host({})
    baseline = controls.soft_404_baseline("https://example.test/", policy=refuse_all, get=get)

    assert get.calls == [], "the baseline requested a path its host forbids"
    assert not baseline.established
    assert all("robots-Disallowed" in (p.error or "") for p in baseline.probes)


def test_a_refused_host_can_never_report_a_specification():
    """No baseline means no `spec` verdict — so a forbidden host yields findings, never a claim."""
    refuse_all = RobotsPolicy(host="example.test", directives=[("disallow", "/")],
                              source="robots.txt")
    get = _host({"/openapi.json": (200, SPEC_DOC, "application/json")})
    baseline = controls.soft_404_baseline("https://example.test/", policy=refuse_all, get=get)
    findings = controls.well_known_spec_probe("https://example.test/", baseline=baseline,
                                              policy=refuse_all, get=get)
    assert get.calls == []
    assert {f.verdict for f in findings} == {controls.DISALLOWED}
    assert not [f for f in findings if f.verdict == controls.SPEC]
