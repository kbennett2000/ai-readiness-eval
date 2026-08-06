"""Fail the build unless the privacy guard ACTUALLY RAN — ADR-0042.

A green pytest run is not evidence that a test executed. Three ways it is not, all of which this
project has already been bitten by:

  * **A skip reads as a pass.** `test_core_no_vendor.py` skips wherever `AIRE_PACKS_DIR` is unset,
    which is the whole point of ADR-0018 and the recorded price of it. `AIRE_GUARD_REQUIRED` now
    turns that skip into a failure inside pytest, but only for tests that were COLLECTED.
  * **An empty parametrize is a silent pass.** A parametrized test whose argument list comes out
    empty collects to one skipped case and reports green. That exact shape produced a vacuous
    verification pass in the private repo's cohort gate this same cycle.
  * **A test that is not collected at all reports nothing.** Rename the file, edit `testpaths`, or
    let a collection error be swallowed by a `|| true`, and the guard's absence looks identical to
    the guard's success.

So CI does not read the exit code alone. It reads the JUnit XML and asserts, by name, that the tests
which carry the privacy rule are present and passed. If one is renamed, this fails and the rename has
to be deliberate — the same discipline `docs/hazards.yaml` applies to `gated_by` references.

**It also prints nothing but test names, ever**, and that is the second job it does. This repository
is public, so its Actions logs are public. A failing privacy check's message contains the prospect
name; a failing manifest check's message contains private vendor URLs. So no CI step on a public
runner prints a pytest message, a traceback, or a JUnit `<failure message=…>` — the report says WHICH
tests failed and the operator reproduces locally, where the detail belongs.

The same reasoning applies one file over, to any gate whose absence would look like its success.
ADR-0059's version tolerance can only move a dimension UP, so the three checks that keep it honest
are required by name too — in `--names-only` mode, which is what the job that actually runs them
invokes. That mode used to report only what FAILED, and a check that was never collected fails
nothing.

Usage:
    python3 tools/assert_guard_ran.py <junit.xml>              # the guard: required names, no skips
    python3 tools/assert_guard_ran.py <junit.xml> --names-only # any suite: failures by name, plus
                                                               # SUITE_REQUIRED present and passing
"""
import sys
from pathlib import Path
from xml.etree import ElementTree

# The tests that carry a rule, BY THE FILE THEY LIVE IN. Not "every test in the file" — that would
# break on every addition, and a guard people have to keep re-approving is a guard people delete.
#
# `core/tests/test_ci_arms_the_guard.py` resolves every (file, name) pair here against the file with
# `ast`, so a name that no longer exists fails the suite rather than silently never matching.
#
# The map has two halves because the two CI jobs run different things, and a required name is only
# meaningful in a report that could contain it:
#
#   * GUARD_FILE is run ALONE by the privacy-guard job, under the strict rule that nothing in it may
#     skip. Requiring a name from any other file there would report "did not run" for a test that
#     was never asked to.
#   * SUITE_FILES are run by the whole-suite job, which reports failures by name. Their required
#     names are checked in `--names-only` mode, so a gate that was renamed away, or never collected,
#     fails the build instead of reporting a green tick for the absence of a check.
GUARD_FILE = "core/tests/test_core_no_vendor.py"
VERSION_ALTERNATES_FILE = "core/tests/test_version_alternates.py"

REQUIRED_BY_FILE: dict[str, list[str]] = {
    # The privacy rule: the assertions whose absence would let a prospect name reach a public tree.
    GUARD_FILE: [
        # the scan itself, over tracked file content
        "test_public_repo_names_no_prospect",
        # …and over refs, which `git ls-files` structurally cannot see
        "test_public_repo_ref_names_no_prospect",
        # the name list is real and derived from the authoritative source
        "test_prospect_tokens_are_derived_from_the_private_queue",
        "test_the_product_token_list_is_not_empty",
        # the two ways the scan's own coverage could be hollowed out
        "test_the_guard_does_not_exempt_its_own_file",
        "test_the_archive_exclusion_covers_archives_and_nothing_else",
        # this run, specifically, was armed — the check that makes the rest non-vacuous
        "test_an_armed_run_here_is_actually_armed",
    ],
    # ADR-0059. A version tolerance can only move a dimension UP, so the three properties that keep
    # it honest are required by name rather than trusted to a green run: it fires only when cited,
    # it is refused when uncited, and it is invisible to a task that declares nothing.
    VERSION_ALTERNATES_FILE: [
        "test_a_cited_alternate_fires",
        "test_an_uncited_alternate_is_refused",
        "test_a_task_declaring_nothing_scores_exactly_as_before",
    ],
}

#: The privacy-guard view, unchanged in meaning: the names the guard job requires, and the set the
#: "no other skip in this file" rule is measured against.
REQUIRED = list(REQUIRED_BY_FILE[GUARD_FILE])

#: Names required of the whole-suite report. Checked in `--names-only` mode, where the skip rule
#: does NOT apply — the full suite skips legitimately in several places.
SUITE_REQUIRED = [name for path, names in REQUIRED_BY_FILE.items()
                  if path != GUARD_FILE for name in names]


def _base_name(case_name: str) -> str:
    """`test_x[3]` -> `test_x`. Parametrized cases must satisfy the requirement they belong to."""
    return case_name.split("[", 1)[0]


def _outcomes(cases) -> dict[str, set[str]]:
    """`{base test name: {"passed"|"skipped"|"failure"|"error", ...}}` over a JUnit report."""
    outcome: dict[str, set[str]] = {}
    for case in cases:
        name = _base_name(case.get("name", ""))
        state = "passed"
        for child in case:
            if child.tag in ("skipped", "failure", "error"):
                state = child.tag
                break
        outcome.setdefault(name, set()).add(state)
    return outcome


def _required_problems(outcome: dict[str, set[str]], required) -> list[str]:
    """Every required name that did not run, or ran and did not pass. Names only, never a message.

    Shared by both modes, so the two jobs cannot drift about what "the check ran" means. The SKIP
    RULE is deliberately not here: it applies only to the guard file, which is run alone, whereas
    the whole suite skips legitimately in several places.
    """
    found: list[str] = []
    for name in required:
        states = outcome.get(name)
        if states is None:
            found.append(f"{name} did not run. It is named in tools/assert_guard_ran.py as a test "
                         f"that must execute; either it was renamed (update both) or it was never "
                         f"collected (a green build here would have meant nothing).")
            continue
        for bad, phrase in (("skipped", "skipped"), ("failure", "failed"), ("error", "errored")):
            if bad in states:
                hint = ("A skip means the run was not armed after all — export AIRE_GUARD_REQUIRED "
                        "and AIRE_PACKS_DIR." if bad == "skipped" else
                        "Reproduce locally; the detail is withheld from CI on purpose.")
                found.append(f"{name} {phrase}, which is not a pass. {hint}")
    return found


def problems(xml_text: str, required=None) -> tuple[list[str], int]:
    """Return (human-readable problems, number of test cases seen).

    Pure over its input so the tests can feed it synthetic XML and prove it rejects what it claims
    to reject. Mirrors the `(problems, count)` contract of `core/validate.py`.
    """
    required = list(REQUIRED if required is None else required)
    found: list[str] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        return [f"the JUnit report did not parse: {exc}. A run that produced no readable report is "
                f"a run that proved nothing."], 0

    cases = list(root.iter("testcase"))
    if not cases:
        return ["the JUnit report contains no test cases at all — the guard was not collected, not "
                "merely not run. Check the file path and pytest's `testpaths`."], 0

    outcome = _outcomes(cases)
    found += _required_problems(outcome, required)

    # Beyond the named set: nothing in this file may skip in an armed run, because every skip here
    # is either an unarmed environment or a check that quietly opted out.
    skipped = sorted(n for n, s in outcome.items() if "skipped" in s and n not in set(required))
    if skipped:
        found.append("these tests SKIPPED in a run that declared itself armed, and a skip is what a "
                     "green build is made of:\n  " + "\n  ".join(skipped))

    return found, len(cases)


def failures_by_name(xml_text: str, required=None) -> tuple[list[str], int]:
    """Every test that failed or errored, by NAME only. Never a message, never a traceback.

    Used for the whole-suite job, where the print-nothing-but-names rule still applies — a manifest
    assertion's message carries private vendor URLs exactly as a privacy assertion's carries a
    prospect name.

    It ALSO checks `SUITE_REQUIRED` by name (ADR-0059). A report where a required gate is simply
    absent has nothing to report as failed, so without this the mode that runs the whole suite would
    print `OK` for a build in which the check was renamed away or never collected — the same vacuous
    pass the guard mode exists to end, one file over. The skip rule does not apply here: the full
    suite skips legitimately (no packs on disk, no archived conditions), so only a REQUIRED name
    skipping is a problem, and `_required_problems` already says so.
    """
    required = list(SUITE_REQUIRED if required is None else required)
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        return [f"the JUnit report did not parse: {exc}"], 0
    cases = list(root.iter("testcase"))
    if not cases:
        return ["the JUnit report contains no test cases at all — nothing was collected"], 0
    bad = sorted({
        f"{case.get('classname', '')}::{case.get('name', '')}".lstrip(":")
        for case in cases
        for child in case
        if child.tag in ("failure", "error")
    })
    return _required_problems(_outcomes(cases), required) + bad, len(cases)


def main(argv: list[str]) -> int:
    names_only = "--names-only" in argv[1:]
    positional = [a for a in argv[1:] if not a.startswith("--")]
    if len(positional) != 1:
        print(__doc__)
        return 2
    report = Path(positional[0])
    if not report.is_file():
        print(f"FAIL: no JUnit report at {report}. pytest did not get far enough to write one, "
              f"which is itself the answer: it did not run.")
        return 1
    text = report.read_text()

    if names_only:
        found, count = failures_by_name(text)
        if found:
            print(f"FAIL: {len(found)} problem(s) across {count} test cases — a test that failed, "
                  f"or a required check that did not run. Shown by name only; messages are withheld "
                  f"because this log is public:\n")
            for name in found:
                print(f"  - {name}")
            print("\nReproduce locally for the detail:\n"
                  "  export AIRE_PACKS_DIR=/path/to/airead-packs AIRE_GUARD_REQUIRED=1\n"
                  "  python3 -m pytest")
            return 1
        print(f"OK: {count} test cases, none failed, and all {len(SUITE_REQUIRED)} required "
              f"suite checks present and passing.")
        return 0

    found, count = problems(text)
    if found:
        print(f"FAIL: the privacy guard did not actually run ({count} cases seen).\n")
        for p in found:
            print(f"  - {p}")
        return 1
    print(f"OK: the privacy guard ran armed — {count} cases, {len(REQUIRED)} required checks "
          f"present and passing, no skips.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
