"""The CI config is a gate, so it is held by tests like every other gate here — ADR-0042.

A workflow file is the one artifact in this project that nothing else reads. It can rot in every
direction at once — a renamed test it invokes, a job made advisory with `continue-on-error`, an
`AIRE_GUARD_REQUIRED` quietly dropped when someone debugs a red build — and the only symptom is a
green tick, which is the symptom of success. That is the same failure shape as ADR-0015's decayed
notes and as the vacuous-pass hazard `tools/assert_guard_ran.py` exists to catch, one layer up.

So three things are asserted here and nothing else is:

1. **The workflow still arms the guard.** Both variables, in the guard job, and no `continue-on-error`
   anywhere near it.
2. **The names `assert_guard_ran.py` requires still exist**, resolved against the file with `ast` —
   the same discipline `docs/hazards.yaml` applies to a `gated_by` reference, and for the same
   reason: a requirement naming a test that was renamed away reports coverage that is gone.
3. **The checker refuses what it claims to refuse**, and never prints a failure MESSAGE — because on
   a public repository that message is the leak.
"""
import ast
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GUARD_JOB = "privacy-guard"

sys.path.insert(0, str(REPO_ROOT / "tools"))
import assert_guard_ran  # noqa: E402


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _guard_job() -> dict:
    jobs = _workflow()["jobs"]
    assert GUARD_JOB in jobs, (
        f"the workflow no longer defines a '{GUARD_JOB}' job. If it was renamed, rename it here too "
        f"— this test is the only thing that notices."
    )
    return jobs[GUARD_JOB]


# ------------------------------------------------------------------- the workflow is still armed ---


def test_the_workflow_exists_at_all():
    """The cheapest way for this whole design to evaporate is for the file to be deleted."""
    assert WORKFLOW.is_file(), f"{WORKFLOW.relative_to(REPO_ROOT)} is gone; nothing runs the guard"


@pytest.mark.parametrize("var", ["AIRE_GUARD_REQUIRED", "AIRE_PACKS_DIR"])
def test_the_guard_job_sets_both_variables(var):
    """Either one missing turns the gate back into a skip, which is where this started."""
    steps = _guard_job()["steps"]
    envs = [s.get("env") or {} for s in steps]
    assert any(var in e for e in envs), (
        f"no step in the '{GUARD_JOB}' job sets {var}. Without it the guard skips, the job passes, "
        f"and the build is green for the one reason that must never make it green."
    )


def test_the_armed_flag_is_set_to_something_the_code_reads_as_true():
    """`AIRE_GUARD_REQUIRED: "0"` would arm nothing and look identical in a diff."""
    from core.tests.test_core_no_vendor import _FALSEY
    values = [
        (s.get("env") or {}).get("AIRE_GUARD_REQUIRED")
        for s in _guard_job()["steps"]
        if "AIRE_GUARD_REQUIRED" in (s.get("env") or {})
    ]
    assert values, "no step sets AIRE_GUARD_REQUIRED"
    for v in values:
        assert str(v).strip().lower() not in _FALSEY, (
            f"AIRE_GUARD_REQUIRED={v!r} is a value the loader reads as NOT required, so the job "
            f"declares itself armed in the YAML and is unarmed in fact"
        )


def test_no_step_in_the_guard_job_is_advisory():
    """`continue-on-error: true` is how a gate becomes decoration without anyone deciding to."""
    job = _guard_job()
    assert not job.get("continue-on-error"), f"the '{GUARD_JOB}' job is advisory"
    for step in job["steps"]:
        assert not step.get("continue-on-error"), (
            f"step {step.get('name') or step.get('uses')!r} is advisory, so the gate it belongs to "
            f"cannot fail the build"
        )


def test_the_guard_job_invokes_the_non_vacuity_checker():
    """pytest's exit code alone cannot distinguish 'passed' from 'never collected'."""
    body = WORKFLOW.read_text()
    assert "tools/assert_guard_ran.py" in body, (
        "the workflow no longer runs the non-vacuity checker, so a guard that was never collected "
        "would report green"
    )


def test_the_public_checkout_is_not_shallow():
    """A depth-1 clone empties the ref scan without failing it."""
    steps = _guard_job()["steps"]
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkouts, "the guard job checks nothing out"
    public = [s for s in checkouts if not (s.get("with") or {}).get("repository")]
    assert public, "no checkout of THIS repository in the guard job"
    for step in public:
        assert (step.get("with") or {}).get("fetch-depth") == 0, (
            "the public checkout must use fetch-depth: 0, or the runner has one ref and "
            "test_public_repo_ref_names_no_prospect passes by having nothing to read"
        )


def test_nothing_prints_or_uploads_the_guards_own_output():
    """The inversion this workflow has to avoid: publishing the string it protects.

    A public repository's Actions logs are public, and both the pytest log and the JUnit report carry
    the offending line verbatim. Printing either, or attaching either as an artifact, would broadcast
    the prospect name to a wider and more durable audience than the tracked file that was caught.
    """
    body = WORKFLOW.read_text()
    assert "upload-artifact" not in body, (
        "an artifact upload was added; if it carries guard.xml or guard.log it publishes the "
        "prospect name, which is the failure this whole file exists to prevent"
    )
    for forbidden in (r"cat\s+.*guard\.(log|xml)", r"echo\s+.*\$\(.*guard\.(log|xml)"):
        assert not re.search(forbidden, body), f"the workflow echoes the guard's own output: {forbidden}"


# ------------------------------------------------- the checker's required names still exist ---


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_the_required_list_is_not_empty():
    """An empty requirement list makes the checker a no-op that reports success."""
    assert assert_guard_ran.REQUIRED, "assert_guard_ran.REQUIRED is empty; it would assert nothing"


@pytest.mark.parametrize("name", assert_guard_ran.REQUIRED)
def test_every_required_test_name_resolves(name):
    """A required name that no longer exists would fail CI for the wrong reason — or, worse, be
    quietly deleted from the list to make CI green again. Fail here first, where the fix is obvious."""
    target = REPO_ROOT / assert_guard_ran.GUARD_FILE
    assert target.is_file(), f"{assert_guard_ran.GUARD_FILE} does not exist"
    assert name in _top_level_functions(target), (
        f"{assert_guard_ran.GUARD_FILE} defines no top-level '{name}'. If it was renamed, update "
        f"tools/assert_guard_ran.py — do not delete the requirement."
    )


# --------------------------------------------------------- the checker refuses what it claims ---


def _xml(cases: list[tuple[str, str | None]]) -> str:
    out = ['<testsuites><testsuite name="pytest">']
    for name, state in cases:
        if state is None:
            out.append(f'<testcase name="{name}"/>')
        else:
            out.append(f'<testcase name="{name}"><{state} message="detail"/></testcase>')
    out.append("</testsuite></testsuites>")
    return "".join(out)


def _all_required_passing() -> list[tuple[str, str | None]]:
    return [(n, None) for n in assert_guard_ran.REQUIRED]


def test_a_clean_armed_report_passes():
    problems, count = assert_guard_ran.problems(_xml(_all_required_passing()))
    assert not problems, problems
    assert count == len(assert_guard_ran.REQUIRED)


def test_an_empty_report_is_a_failure_not_a_pass():
    """The type case: nothing collected looks exactly like nothing wrong."""
    problems, count = assert_guard_ran.problems("<testsuites/>")
    assert problems and count == 0
    assert "no test cases" in problems[0]


def test_unparseable_output_is_a_failure():
    problems, _ = assert_guard_ran.problems("not xml at all")
    assert problems and "did not parse" in problems[0]


@pytest.mark.parametrize("missing", assert_guard_ran.REQUIRED)
def test_a_missing_required_test_is_caught_one_at_a_time(missing):
    """Per name, not in aggregate. A break test that could pass because a DIFFERENT requirement
    still fired proves nothing — the same lesson `test_prospect_regex_actually_matches_every_token`
    was written to record."""
    cases = [(n, None) for n in assert_guard_ran.REQUIRED if n != missing]
    problems, _ = assert_guard_ran.problems(_xml(cases))
    assert any(missing in p and "did not run" in p for p in problems), problems


@pytest.mark.parametrize("state,phrase", [("skipped", "skipped"), ("failure", "failed"),
                                          ("error", "errored")])
def test_a_required_test_that_did_not_pass_is_caught(state, phrase):
    cases = [(n, None) for n in assert_guard_ran.REQUIRED[1:]]
    cases.insert(0, (assert_guard_ran.REQUIRED[0], state))
    problems, _ = assert_guard_ran.problems(_xml(cases))
    assert any(assert_guard_ran.REQUIRED[0] in p and phrase in p for p in problems), problems


def test_any_other_skip_in_an_armed_run_is_caught():
    """Not only the named set. In an armed run every skip in that file is either an unarmed
    environment or a check that opted out, and both are the failure."""
    cases = _all_required_passing() + [("test_something_else_entirely", "skipped")]
    problems, _ = assert_guard_ran.problems(_xml(cases))
    assert any("test_something_else_entirely" in p for p in problems), problems


def test_a_parametrized_case_satisfies_its_requirement():
    """`test_x[3]` must count as `test_x`, or the checker fails on tests that are merely
    parametrized — and the cheapest way to make a nagging checker quiet is to delete it."""
    cases = [(f"{n}[0]", None) for n in assert_guard_ran.REQUIRED]
    problems, _ = assert_guard_ran.problems(_xml(cases))
    assert not problems, problems


def test_the_checker_never_prints_the_failure_message():
    """The checker runs where pytest's own output is suppressed, so it must not reintroduce it.

    A JUnit `<failure message=…>` carries the assertion text, and the assertion text carries the
    prospect's name. Anything this tool prints goes into a public log.
    """
    marker = "PROSPECT-NAME-THAT-MUST-NOT-BE-PRINTED"
    xml = (f'<testsuites><testsuite><testcase name="{assert_guard_ran.REQUIRED[0]}">'
           f'<failure message="{marker}">{marker}</failure></testcase></testsuite></testsuites>')
    report = REPO_ROOT / "_guard_message_probe.xml"
    report.write_text(xml)
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = assert_guard_ran.main(["assert_guard_ran.py", str(report)])
    finally:
        report.unlink()
    assert rc == 1, "a failing required test must fail the checker"
    assert marker not in buffer.getvalue(), (
        "the checker printed the JUnit failure message, which on a public repository publishes the "
        "prospect name to the CI log — a wider audience than the file that was caught"
    )


def test_a_missing_report_file_fails_rather_than_passing():
    """pytest crashing before it writes a report is not an absence of findings."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc = assert_guard_ran.main(["assert_guard_ran.py", str(REPO_ROOT / "no-such-report.xml")])
    assert rc == 1 and "did not run" in buffer.getvalue()


# --------------------------------------------- names-only reporting, on every public-runner job ---


def test_every_job_that_runs_pytest_withholds_its_output():
    """The rule at the top of the workflow, held per job rather than trusted.

    It is not only the privacy guard. Every job loads the private packs repo, so a failing manifest
    or robots assertion prints private vendor URLs into a public log exactly as readily as a failing
    privacy assertion prints a prospect name. The discipline is therefore uniform: redirect pytest,
    report by name.
    """
    body = WORKFLOW.read_text()
    for job_name, job in _workflow()["jobs"].items():
        runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
        if "pytest" not in runs:
            continue
        assert "> \"${RUNNER_TEMP}/" in runs or "> ${RUNNER_TEMP}/" in runs, (
            f"job '{job_name}' runs pytest without redirecting its output; on a public runner that "
            f"publishes assertion messages, which is where the sensitive strings are"
        )
        assert "assert_guard_ran.py" in runs, (
            f"job '{job_name}' runs pytest but never reports the result by name, so a failure is "
            f"either invisible or printed in full"
        )
    assert "--tb=no" in body, "tracebacks are not suppressed; a traceback shows source and values"


def test_the_names_only_reporter_prints_names_and_nothing_else():
    """`--names-only` is used by the whole-suite job, where the required-name check does not apply
    but the print-no-messages rule still does."""
    marker = "PRIVATE-URL-THAT-MUST-NOT-BE-PRINTED"
    xml = (f'<testsuites><testsuite><testcase classname="core.tests.test_x" name="test_a">'
           f'<failure message="{marker}">{marker}</failure></testcase>'
           f'<testcase classname="core.tests.test_x" name="test_b"/></testsuite></testsuites>')
    report = REPO_ROOT / "_names_only_probe.xml"
    report.write_text(xml)
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = assert_guard_ran.main(["assert_guard_ran.py", str(report), "--names-only"])
    finally:
        report.unlink()
    out = buffer.getvalue()
    assert rc == 1, "a failing test must fail the reporter"
    assert marker not in out, "the reporter printed the failure message into a public log"
    assert "test_a" in out, "the reporter must name the failing test, or it reports nothing usable"
    assert "test_b" not in out, "the reporter named a passing test"


def test_the_names_only_reporter_passes_a_clean_run():
    xml = '<testsuites><testsuite><testcase classname="c" name="test_a"/></testsuite></testsuites>'
    report = REPO_ROOT / "_names_only_clean_probe.xml"
    report.write_text(xml)
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = assert_guard_ran.main(["assert_guard_ran.py", str(report), "--names-only"])
    finally:
        report.unlink()
    assert rc == 0, buffer.getvalue()


def test_the_names_only_reporter_still_fails_on_an_empty_report():
    """A collection failure writes an empty report, and 'nothing failed' is the wrong reading."""
    problems, count = assert_guard_ran.failures_by_name("<testsuites/>")
    assert problems and count == 0


# ------------------------------------------------ a skipped job is a passing required check ---


def test_no_job_can_be_skipped_wholesale():
    """GitHub counts a SKIPPED job as a PASSING required status check.

    That is a documented behaviour, not a quirk, and it makes any job-level `if:` a way to satisfy
    the privacy gate without running it — the same vacuous pass the rest of this file guards against,
    relocated into the branch-protection layer where nothing in the tree can see it.

    The first draft carried exactly such a condition, to keep fork pull requests from failing on a
    secret they cannot read. It was harmless while nothing required the check and became a hole the
    moment `main` was protected. The case is real; the mechanism is now a first step that FAILS.
    """
    for job_name, job in _workflow()["jobs"].items():
        assert "if" not in job, (
            f"job '{job_name}' has a job-level 'if:'. A skipped job satisfies a required status "
            f"check, so this is a green privacy gate that ran nothing. Fail in a step instead."
        )


@pytest.mark.parametrize("job_name", sorted(_workflow()["jobs"]))
def test_a_fork_pull_request_fails_rather_than_skipping(job_name):
    """The converse: having banned the skip, the fork case must still be handled, and handled by
    failing. A job that simply had the condition deleted would run unarmed on a fork and report
    whatever an unreachable name list reports."""
    steps = _workflow()["jobs"][job_name]["steps"]
    guarded = [
        s for s in steps
        if "head.repo.full_name != github.repository" in str(s.get("if", ""))
    ]
    assert guarded, (
        f"job '{job_name}' has no step that detects a fork pull request. Fork runs cannot read "
        f"PACKS_REPO_TOKEN, so without this the job runs unarmed or fails obscurely."
    )
    assert any("exit 1" in str(s.get("run", "")) for s in guarded), (
        f"job '{job_name}' detects a fork pull request but does not fail on it"
    )
    assert steps.index(guarded[0]) == 0, (
        f"job '{job_name}' checks for a fork after doing other work; it must be the first step so "
        f"the failure is unambiguous and nothing runs half-armed before it"
    )


def test_there_is_no_job_that_runs_the_suite_without_the_private_packs():
    """The first draft had one, and it was red on `main` for a reason already known.

    `test_the_sweep_below_is_not_vacuous` and `test_the_matcher_finds_paths_that_are_really_there`
    are anti-vacuity gates that REQUIRE the private packs. A CI job that is red for a known reason
    teaches people to ignore red, which costs more than the job is worth.
    """
    for job_name, job in _workflow()["jobs"].items():
        runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
        if "pytest" not in runs:
            continue
        envs = [s.get("env") or {} for s in job["steps"]]
        assert any("AIRE_PACKS_DIR" in e for e in envs), (
            f"job '{job_name}' runs pytest without AIRE_PACKS_DIR. This repository's suite does not "
            f"pass without the private packs repo (ADR-0042), so such a job is red by construction."
        )
