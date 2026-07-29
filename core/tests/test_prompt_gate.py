"""The prompt-sanity gate: does the question name what it is asking about? (ADR-0031)

Every other gate reads the answer key. This is the only one that reads the question, and it exists
because a cohort of twelve prompts that named no vendor passed `validate`, `roundtrip`, `anchoring`
and the truncation audit, then burned a whole grid measuring our own prompt.

The tests below fall into four groups:

  1. The matcher — word-bounded, case-insensitive, multi-word. The must-not test is the important
     one: a plain substring match would find a short product abbreviation inside an ordinary English
     word, and a gate that can pass by accident reports coverage it does not have.
  2. The declaration — a pack that declares neither list, or a blank name, fails closed.
  3. The rule — vendor AND product, both required, each independently.
  4. The world — every pack on disk is swept, and the reference pack's FAILING state is pinned by
     exact task id, because it is deliberately not fixed.
"""
import os
from pathlib import Path

import pytest
import yaml

from core.pack import Pack
from core.prompt_gate import (
    check_pack,
    check_task_prompt,
    declaration_problems,
    dual_listed,
    format_report,
    names_in,
    summarize_failures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACME = Path(__file__).resolve().parent / "fixtures" / "pack-acme"
REFERENCE = REPO_ROOT / "packs" / "sailpoint"


def _task(prompt: str, task_id: str = "t1") -> dict:
    return {"id": task_id, "prompt": prompt}


# --- 1. the matcher -------------------------------------------------------- #

def test_a_name_is_matched_case_insensitively():
    assert names_in("how do I call the WIDGET CLOUD api", ["Widget Cloud"]) == ["Widget Cloud"]


def test_a_multi_word_name_matches_across_any_whitespace():
    assert names_in("the Widget\n  Cloud API", ["Widget Cloud"]) == ["Widget Cloud"]


def test_a_name_matches_next_to_punctuation_and_possessives():
    # Real prompts write "Vendor's API", "Product-native group", "(Product)".
    for text in ["Acme's widgets", "an Acme-native group", "in (Acme) terms", "Acme, specifically"]:
        assert names_in(text, ["Acme"]) == ["Acme"], text


def test_a_name_buried_inside_a_longer_word_does_NOT_match():
    """The must-not test. Short product abbreviations are real, and so is this failure mode.

    With a plain substring test every one of these passes, and a pack whose prompts never name the
    target would be reported as fully compliant. That is worse than having no gate, because it is a
    green check on a claim that is false.
    """
    abbreviation = "ISC"
    for text in ["service discovery is enabled", "a basic auth header", "the disc image",
                 "MISCELLANEOUS fields"]:
        assert names_in(text, [abbreviation]) == [], f"{abbreviation!r} must not match in {text!r}"


def test_the_matcher_still_finds_a_name_that_is_really_there():
    """The other half of the must-not above. A matcher tightened until it matches NOTHING would pass
    that test perfectly and fail every prompt in the cohort, so both directions are pinned."""
    assert names_in("in ISC, how do I list identities", ["ISC"]) == ["ISC"]
    assert names_in("ISC. Then what?", ["ISC"]) == ["ISC"]


def test_names_are_returned_in_declaration_order():
    assert names_in("Acme Widget Cloud", ["Acme", "Widget Cloud"]) == ["Acme", "Widget Cloud"]


# --- 2. the declaration ---------------------------------------------------- #

def test_a_pack_declaring_neither_list_fails_closed():
    pack = Pack.load(ACME)
    pack.vendor_names, pack.product_names = [], []
    problems = declaration_problems(pack)
    assert len(problems) == 2
    assert any("vendor.vendor_names" in p for p in problems)
    assert any("vendor.product_names" in p for p in problems)


def test_a_pack_declaring_only_one_list_still_fails():
    pack = Pack.load(ACME)
    pack.product_names = []
    assert len(declaration_problems(pack)) == 1


def test_a_blank_name_is_refused_because_it_would_match_every_prompt():
    pack = Pack.load(ACME)
    pack.vendor_names = ["Acme", "   "]
    problems = declaration_problems(pack)
    assert problems and "vacuous" in problems[0]


def test_an_unusable_declaration_short_circuits_before_the_prompts_are_read():
    """Otherwise one missing list becomes N consequential task failures that hide the real cause."""
    pack = Pack.load(ACME)
    pack.vendor_names = []
    report = check_pack(pack)
    assert report.declaration_problems and report.tasks == []
    assert "vendor_names" in summarize_failures(report)


def test_dual_listing_is_reported_and_never_rejected():
    pack = Pack.load(ACME)
    pack.vendor_names = ["Acme", "Widget Cloud"]
    assert dual_listed(pack) == ["Widget Cloud"]
    assert declaration_problems(pack) == []          # a note, not an error
    report = check_pack(pack)
    assert report.ok and report.dual_listed == ["Widget Cloud"]
    assert "declared as BOTH vendor and product" in format_report(report)[0]


# --- 3. the rule ----------------------------------------------------------- #

def test_a_prompt_naming_both_passes():
    check = check_task_prompt(_task("How do I list widgets in Acme Widget Cloud?"),
                              ["Acme"], ["Widget Cloud"])
    assert check.ok and check.vendor_hits == ["Acme"] and check.product_hits == ["Widget Cloud"]


def test_a_prompt_naming_only_the_vendor_fails():
    check = check_task_prompt(_task("How do I list widgets in Acme?"), ["Acme"], ["Widget Cloud"])
    assert not check.ok
    assert len(check.problems) == 1 and "names no product" in check.problems[0]


def test_a_prompt_naming_only_the_product_fails():
    check = check_task_prompt(_task("How do I list widgets in Widget Cloud?"),
                              ["Acme"], ["Widget Cloud"])
    assert not check.ok
    assert len(check.problems) == 1 and "names no vendor" in check.problems[0]


def test_the_prompt_that_started_this_fails_on_both_counts():
    """The literal shape that cost a grid: answerable, well-formed, and names nobody."""
    check = check_task_prompt(
        _task("Using this vendor's consumer API, how do I read a single user's profile?"),
        ["Acme"], ["Widget Cloud"])
    assert not check.ok and len(check.problems) == 2


def test_a_task_with_no_prompt_text_is_a_problem_not_a_crash():
    assert not check_task_prompt({"id": "t"}, ["Acme"], ["Widget Cloud"]).ok
    assert not check_task_prompt(_task("   "), ["Acme"], ["Widget Cloud"]).ok


def test_the_gate_never_raises_on_an_unreadable_pack(tmp_path):
    (tmp_path / "pack.yaml").write_text(
        "vendor:\n  id: x\n  vendor_names: [X]\n  product_names: [Y]\n")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "broken.yaml").write_text("id: [unclosed\n")
    report = check_pack(Pack.load(tmp_path))
    assert not report.ok  # reported, not raised — the factory loop has no exception handling

def test_a_pack_with_no_tasks_does_not_pass_vacuously(tmp_path):
    (tmp_path / "pack.yaml").write_text(
        "vendor:\n  id: x\n  vendor_names: [X]\n  product_names: [Y]\n")
    (tmp_path / "tasks").mkdir()
    report = check_pack(Pack.load(tmp_path))
    assert not report.ok and "vacuously" in report.declaration_problems[0]


def test_the_fixture_pack_passes():
    report = check_pack(Pack.load(ACME))
    assert report.ok, format_report(report)[0]


# --- 4. the world ---------------------------------------------------------- #

def _discover() -> list[Path]:
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external:
        roots.append(Path(external))
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += [p.parent for p in sorted(root.glob("*/pack.yaml"))]
    return found


PACK_DIRS = _discover()
EXTERNAL_DIRS = [p for p in PACK_DIRS if p.parent != REPO_ROOT / "packs"]


def test_pack_discovery_is_not_empty():
    """A glob that silently matches nothing would make everything below vacuously green."""
    assert PACK_DIRS, "pack discovery found nothing — the sweeps below would be no-ops"


@pytest.mark.skipif(not PACK_DIRS, reason="no packs on disk to check")
@pytest.mark.parametrize("pack_dir", PACK_DIRS, ids=lambda p: p.name)
def test_every_pack_on_disk_declares_what_naming_it_means(pack_dir):
    """No grandfathering: the declaration binds every pack, including the frozen reference one.

    Separated from the gate itself because these are different claims. Declaring the lists is a
    thing every pack must do; PASSING the gate is a thing the reference pack deliberately does not
    do, and collapsing the two would hide that behind a skip.
    """
    problems = declaration_problems(Pack.load(pack_dir))
    assert not problems, f"{pack_dir.name}: " + "; ".join(problems)


@pytest.mark.skipif(not EXTERNAL_DIRS, reason="AIRE_PACKS_DIR not set (external packs live outside)")
@pytest.mark.parametrize("pack_dir", EXTERNAL_DIRS, ids=lambda p: p.name)
def test_every_external_pack_is_readable_by_the_gate(pack_dir):
    """The gate can read every external pack and reaches a verdict on every task.

    Deliberately NOT "every external pack passes". Some do not, and their failing state is pinned by
    exact task id in the packs repo's own suite rather than here — a pin has to name the pack it
    pins, and this repo is public and names no measured target. Splitting it that way keeps the
    enforcement where the evidence is instead of creating an exemption list here, which is the thing
    that decays.
    """
    pack = Pack.load(pack_dir)
    report = check_pack(pack)
    assert not report.declaration_problems, "; ".join(report.declaration_problems)
    assert len(report.tasks) == len(pack.load_tasks())


# The reference pack's prompts say "ISC" and not "SailPoint". They are NOT being fixed: they are the
# questions that produced the frozen 73/68/93 anchor, and rewriting them would silently re-baseline
# the one table this repo checks itself against. So the failure is pinned rather than skipped — this
# is a state pin, not an exemption, and editing any of these prompts breaks it on purpose.
REFERENCE_FAILING_TASKS = [
    "access-request", "audit-report", "cert-campaign", "find-identity", "grant-revoke",
    "identity-accounts", "lifecycle-trigger", "search-filter", "source-aggregation", "transform",
]


def test_the_reference_pack_prompt_state_is_pinned():
    report = check_pack(Pack.load(REFERENCE))
    assert report.failing_task_ids == REFERENCE_FAILING_TASKS
    # Every failure is the same one — an abbreviation-only prompt naming no vendor. If a DIFFERENT
    # kind of failure appeared here it would be hidden by a count-only assertion.
    for check in report.tasks:
        if check.task_id in REFERENCE_FAILING_TASKS:
            assert check.problems == [
                "prompt names no vendor — none of SailPoint appears in it"
            ], check.task_id


def test_the_one_reference_prompt_that_names_the_vendor_still_does():
    """Guards the pin against going vacuous from the other direction: if the matcher broke, every
    task would fail and the list above would simply be re-pinned longer."""
    report = check_pack(Pack.load(REFERENCE))
    passing = [c for c in report.tasks if c.ok]
    assert [c.task_id for c in passing] == ["auth-token"]
    assert passing[0].vendor_hits == ["SailPoint"]


def test_the_ambiguous_abbreviation_is_not_declared_as_a_vendor_name():
    """The flattering fix this cycle refused: listing `ISC` under vendor_names would turn the gate
    green without changing anything true about the prompts."""
    vendor = (yaml.safe_load((REFERENCE / "pack.yaml").read_text()) or {})["vendor"]
    assert "ISC" in vendor["product_names"]
    assert not any(n.strip().lower() == "isc" for n in vendor["vendor_names"])
