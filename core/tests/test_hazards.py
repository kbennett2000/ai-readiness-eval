"""The hazard registry is a gate, not a document (ADR-0015).

`docs/hazards.yaml` lists every recorded way this project's instruments can mislead.
Its value depends entirely on two properties that prose cannot hold on its own:

1. **Every entry declares a disposition.** Either a test fires on the hazard
   (`gated`), or the entry says why none does and where the fix is queued
   (`ungated`). An entry declaring neither is the note-that-decays this registry
   exists to prevent, so it fails the suite.

2. **Every claimed test exists.** A registry whose `gated_by` names a test that was
   renamed away is worse than no registry — it reports coverage that is gone. The
   refs are resolved against the files on disk, so the claim rots loudly.

The third property is the subtle one. A test can fire on a hazard in two very
different ways, and collapsing them would make this file lie in the flattering
direction:

  * **gated** — the test prevents the hazard from occurring or regressing silently.
  * **drift_pin** — the test fires if the hazard's *state* is edited, while the
    hazard itself stays live. ADR-0011's single OAuth example is the type case: the
    pin makes changing it a deliberate cohort re-baseline. It does not remove the
    bias any measured model has already read.

So `drift_pin` is a field an *ungated* entry may carry, and it must never satisfy
the gated requirement. `test_a_drift_pin_never_satisfies_the_gated_requirement`
is the assertion that keeps those two apart.
"""
import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "docs" / "hazards.yaml"
ADR_DIR = REPO_ROOT / "docs" / "adr"

STATUSES = {"gated", "ungated"}
ALLOWED_FIELDS = {
    "id", "adr", "hazard", "status", "gated_by", "ungated_reason", "fix_queued_to", "drift_pin",
}
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_DATA = yaml.safe_load(REGISTRY.read_text())
ENTRIES = _DATA["entries"]


def entry_problems(entry: dict) -> list[str]:
    """Every rule the registry enforces, as human-readable problems.

    A pure function over one entry so the guard-the-guard tests below can feed it
    synthetic entries and prove it actually rejects them. Mirrors the
    `(problems, count)` reporting contract of `core/validate.py`.
    """
    where = entry.get("id") or "(entry with no id)"
    problems: list[str] = []

    for field in ("id", "adr", "hazard", "status"):
        if not str(entry.get(field) or "").strip():
            problems.append(f"{where}: missing required field '{field}'")

    unknown = sorted(set(entry) - ALLOWED_FIELDS)
    if unknown:
        problems.append(f"{where}: unknown field(s) {unknown}")

    status = entry.get("status")
    if status not in STATUSES:
        problems.append(f"{where}: status {status!r} is not one of {sorted(STATUSES)}")
        return problems

    if status == "gated":
        if not entry.get("gated_by"):
            problems.append(f"{where}: status 'gated' requires a non-empty 'gated_by'")
        # A gated hazard is closed; a drift pin is a property of a live one.
        if entry.get("drift_pin"):
            problems.append(f"{where}: 'drift_pin' is only meaningful on an ungated entry")
        for field in ("ungated_reason", "fix_queued_to"):
            if entry.get(field):
                problems.append(f"{where}: '{field}' does not belong on a gated entry")
    else:
        # This is the rule the registry exists for. A drift_pin is deliberately not
        # consulted here: it names a test that fires, but the hazard is still live,
        # so it can never stand in for a reason and a queue.
        for field in ("ungated_reason", "fix_queued_to"):
            if not str(entry.get(field) or "").strip():
                problems.append(f"{where}: status 'ungated' requires a non-empty '{field}'")
        if entry.get("gated_by"):
            problems.append(f"{where}: 'gated_by' does not belong on an ungated entry")

    return problems


def ref_problems(ref: str) -> list[str]:
    """Resolve a `path.py` or `path.py::test_name` reference against the tree."""
    path, _, func = ref.partition("::")
    target = REPO_ROOT / path
    if not target.is_file():
        return [f"{ref}: no such file"]
    if not func:
        return []
    tree = ast.parse(target.read_text())
    defined = {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if func not in defined:
        return [f"{ref}: {path} defines no top-level '{func}'"]
    return []


def _ids(entries):
    return [e.get("id", "?") for e in entries]


# --------------------------------------------------------------------------- the gate ---


@pytest.mark.parametrize("entry", ENTRIES, ids=_ids(ENTRIES))
def test_every_entry_is_gated_or_gives_a_reason_and_a_queue(entry):
    """The requested gate: an entry that declares neither disposition fails.

    "Recorded as open work" with no queue is a note that decays — ADR-0011 said so
    about its own item, and it decayed twice before ADR-0015.
    """
    problems = entry_problems(entry)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("entry", ENTRIES, ids=_ids(ENTRIES))
def test_every_gate_reference_resolves(entry):
    """A `gated_by` naming a test that no longer exists reports coverage that is gone."""
    problems = [p for ref in entry.get("gated_by") or [] for p in ref_problems(ref)]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("entry", ENTRIES, ids=_ids(ENTRIES))
def test_every_drift_pin_resolves(entry):
    problems = [p for ref in entry.get("drift_pin") or [] for p in ref_problems(ref)]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("entry", ENTRIES, ids=_ids(ENTRIES))
def test_every_entry_cites_an_adr_that_exists(entry):
    adr = entry.get("adr", "")
    assert (ADR_DIR / adr).is_file(), f"{entry.get('id')}: docs/adr/{adr} does not exist"


def test_ids_are_unique_and_slug_shaped():
    ids = _ids(ENTRIES)
    assert len(ids) == len(set(ids)), f"duplicate ids: {sorted({i for i in ids if ids.count(i) > 1})}"
    bad = [i for i in ids if not ID_RE.match(i)]
    assert not bad, f"ids must be lowercase kebab-case slugs: {bad}"


# ------------------------------------------------------------------ guarding the guard ---


def test_a_drift_pin_never_satisfies_the_gated_requirement():
    """The distinction this registry exists to hold.

    A drift pin fires when the hazard's state is *edited*; it does not stop the
    hazard. Letting one stand in for a reason and a queue would let a live hazard
    read as handled — which is exactly the flattering error the ADR trail keeps
    catching after the money is spent.
    """
    pinned_but_unexplained = {
        "id": "synthetic",
        "adr": "adr-0011-auth-login-styles.md",
        "hazard": "x",
        "status": "ungated",
        "drift_pin": ["core/tests/test_prompt_contract.py::test_the_auth_flow_example_is_pinned"],
    }
    problems = entry_problems(pinned_but_unexplained)
    assert any("ungated_reason" in p for p in problems)
    assert any("fix_queued_to" in p for p in problems)


def test_the_gate_rejects_an_entry_that_declares_neither_disposition():
    assert entry_problems({"id": "s", "adr": "a.md", "hazard": "h", "status": "ungated"})
    assert entry_problems({"id": "s", "adr": "a.md", "hazard": "h", "status": "gated"})
    assert entry_problems({"id": "s", "adr": "a.md", "hazard": "h", "status": "maybe"})


def test_the_reference_resolver_actually_rejects_a_dead_link():
    """A link checker that has never failed is not known to work."""
    assert ref_problems("core/tests/test_hazards.py::test_no_such_test_exists_anywhere")
    assert ref_problems("core/tests/test_definitely_not_a_file.py")
    assert not ref_problems("core/tests/test_hazards.py::test_ids_are_unique_and_slug_shaped")


# ------------------------------------------------------------------------- anti-decay ---


def test_every_adr_on_disk_is_accounted_for():
    """A new ADR cannot add a hazard and stay silent.

    Every ADR either has an entry here or is named in `adrs_with_no_recorded_hazard`.
    Omission is not an option, because omission is indistinguishable from oversight —
    which is the failure mode that cost ADR-0014 a cycle.
    """
    on_disk = {p.name for p in ADR_DIR.glob("adr-*.md")}
    cited = {e.get("adr") for e in ENTRIES}
    declared_clean = set(_DATA.get("adrs_with_no_recorded_hazard") or [])
    missing = sorted(on_disk - cited - declared_clean)
    assert not missing, (
        "these ADRs appear in neither an entry nor adrs_with_no_recorded_hazard: "
        f"{missing}"
    )
    stale = sorted(declared_clean - on_disk)
    assert not stale, f"adrs_with_no_recorded_hazard names files that do not exist: {stale}"
    overlap = sorted(declared_clean & cited)
    assert not overlap, f"declared hazard-free but has entries: {overlap}"


def test_the_registry_is_not_empty():
    """A glob or key that silently matches nothing would make every check above vacuous."""
    assert ENTRIES, "the registry has no entries — the parametrized gates would be no-ops"
    assert any(e["status"] == "gated" for e in ENTRIES)
    assert any(e["status"] == "ungated" for e in ENTRIES)
