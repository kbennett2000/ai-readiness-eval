"""The factory dispatcher (ADR-0006): queue model, gates, and the unattended pipeline.

All model-free — the pipeline runs with `provider="mock"`, so the whole spine (recon → validate →
roundtrip → anchoring → mock → grid → compare → card → advance) is exercised offline against the
synthetic `pack-acme` fixture. The guard (`test_core_no_vendor`) proves the factory names no vendor.
"""
import os
import shutil
from pathlib import Path

import pytest

from core import factory, scorer
from core.factory import QueueEntry
from core.pack import Pack

ACME = Path(__file__).resolve().parent / "fixtures" / "pack-acme"


# --------------------------------------------------------------------------- #
# Queue model
# --------------------------------------------------------------------------- #

def test_queue_round_trips_including_unknown_fields(tmp_path):
    src = tmp_path / "queue.yaml"
    src.write_text(
        "# a header comment\n"
        "targets:\n"
        "  - id: alpha\n"
        "    display_name: Alpha Corp\n"
        "    tier: 1\n"
        "    status: queued\n"
        "    spec_state: verified\n"
        "    notes: publishes its own MCP servers\n"
        "    future_field: keep me\n"
    )
    entries = factory.load_queue(src)
    assert [e.id for e in entries] == ["alpha"]
    assert entries[0].extra == {"future_field": "keep me"}

    out = tmp_path / "out.yaml"
    factory.save_queue(out, entries, header="# a header comment")
    reloaded = factory.load_queue(out)
    assert reloaded[0].display_name == "Alpha Corp"
    assert reloaded[0].notes == "publishes its own MCP servers"
    assert reloaded[0].extra == {"future_field": "keep me"}          # unknown field survived
    assert out.read_text().startswith("# a header comment")           # header preserved


def test_next_target_skips_blocked_and_carded():
    entries = [
        QueueEntry(id="a", status="carded"),
        QueueEntry(id="b", status="blocked"),
        QueueEntry(id="c", status="queued"),
        QueueEntry(id="d", status="queued"),
    ]
    assert factory.next_target(entries).id == "c"
    entries[2].status = "carded"
    assert factory.next_target(entries).id == "d"
    entries[3].status = "blocked"
    assert factory.next_target(entries) is None


def test_next_target_skips_parked():
    """`parked` is terminal. It has to be, or writing it arms the dispatcher at the target.

    Before ADR-0019 `parked` was English prose in a comment describing what `blocked` meant, not a
    value the code knew — so an author who wrote the word that already appeared in the file's own
    documentation would have made that target the NEXT thing the factory dispatched and spent on.
    """
    entries = [QueueEntry(id="a", status="parked"), QueueEntry(id="b", status="queued")]
    assert factory.next_target(entries).id == "b"
    entries[1].status = "parked"
    assert factory.next_target(entries) is None


def test_load_queue_rejects_an_unknown_status(tmp_path):
    """An unrecognized status must not be read as "not done", i.e. as "dispatch this next"."""
    src = tmp_path / "queue.yaml"
    src.write_text("targets:\n  - id: alpha\n    status: barked\n")
    with pytest.raises(ValueError) as exc:
        factory.load_queue(src)
    assert "barked" in str(exc.value) and "alpha" in str(exc.value)
    assert "parked" in str(exc.value), "the error must list what IS allowed, not just what is not"


@pytest.mark.parametrize("status", sorted(factory.STATUSES))
def test_every_declared_status_actually_loads(status, tmp_path):
    src = tmp_path / "queue.yaml"
    src.write_text(f"targets:\n  - id: alpha\n    status: {status}\n")
    assert factory.load_queue(src)[0].status == status


def test_guard_tokens_default_to_the_id_and_can_be_replaced_or_narrowed():
    """The public leak guard's name list is computed from these, and holds no names of its own.

    Replacement rather than extension is the load-bearing choice: an id that is also an ordinary word
    must be able to say "never match me case-insensitively", and `guard_tokens: []` says exactly that.
    An extension-only field could not express it, and the word would fire on unrelated prose until
    someone routed around the guard.
    """
    assert QueueEntry(id="alpha").leak_guard_tokens() == (["alpha"], [])
    # a hyphenated id also yields its collapsed form, since a leak may write it either way
    assert QueueEntry(id="acme-widgets").leak_guard_tokens() == (["acme-widgets", "acmewidgets"], [])
    # explicit tokens REPLACE the default: the id itself is gone unless it is listed again
    assert QueueEntry(id="alpha", guard_tokens=["beta"]).leak_guard_tokens() == (["beta"], [])
    # the empty list is meaningful and is not the same as omitting the field
    entry = QueueEntry(id="alpha", guard_tokens=[], guard_tokens_cased=["Alpha"])
    assert entry.leak_guard_tokens() == ([], ["Alpha"])


def test_guard_tokens_round_trip_through_save(tmp_path):
    src = tmp_path / "q.yaml"
    src.write_text("targets:\n  - id: alpha\n    guard_tokens: []\n    guard_tokens_cased: [Alpha]\n")
    entries = factory.load_queue(src)
    out = tmp_path / "out.yaml"
    factory.save_queue(out, entries)
    # `guard_tokens: []` must survive a save; dropping it as falsy would silently re-arm the default
    assert factory.load_queue(out)[0].leak_guard_tokens() == ([], ["Alpha"])


# --------------------------------------------------------------------------- #
# Product tokens (ADR-0028) — a vendor is identifiable by what it sells
# --------------------------------------------------------------------------- #

def test_product_tokens_are_returned_apart_from_the_name_tokens():
    """The guard compares the two differently, so nothing may hand back one merged list."""
    entry = QueueEntry(id="alpha",
                       guard_product_tokens=["Widgetron"],
                       guard_product_tokens_cased=["Data Fabric"])
    assert entry.leak_guard_tokens() == (["alpha"], [])
    assert entry.leak_guard_product_tokens() == (["Widgetron"], ["Data Fabric"])


def test_narrowing_the_name_does_not_disarm_the_products():
    """`guard_tokens` REPLACES, and that replacement must not reach the product declaration.

    An id that is an ordinary English word is declared with `guard_tokens: []`. If product tokens
    rode on the same list, that one narrowing would silently switch off a second, unrelated guard —
    and it would do so invisibly, because the entry would still LOOK like it declared products.
    """
    entry = QueueEntry(id="apple", guard_tokens=[], guard_product_tokens=["Orchardctl"])
    assert entry.leak_guard_tokens() == ([], [])
    assert entry.leak_guard_product_tokens() == (["Orchardctl"], [])


def test_product_tokens_are_absent_by_default_and_are_never_invented():
    """No product name is derivable from an id, so there is no default to fall back on."""
    assert QueueEntry(id="alpha").leak_guard_product_tokens() == ([], [])


def test_product_tokens_round_trip_through_save(tmp_path):
    src = tmp_path / "q.yaml"
    src.write_text("targets:\n  - id: alpha\n"
                   "    guard_product_tokens: [Widgetron]\n"
                   "    guard_product_tokens_cased: ['Data Fabric']\n")
    out = tmp_path / "out.yaml"
    factory.save_queue(out, factory.load_queue(src))
    reloaded = factory.load_queue(out)[0]
    assert reloaded.leak_guard_product_tokens() == (["Widgetron"], ["Data Fabric"])


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #

def test_recon_passes_for_a_vendored_licensed_spec():
    ok, detail = factory.check_recon(Pack.load(ACME))
    assert ok, detail
    assert "vendored" in detail


def test_recon_blocks_when_spec_claimed_but_not_vendored(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    shutil.rmtree(pack_dir / "vendored-spec")           # claims spec (yes) but vendored none
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok
    assert "vendored-spec" in detail


def test_recon_allows_doc_anchored_pack_with_no_spec(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    specs = (pack_dir / "specs.yaml").read_text().replace(
        "machine_readable_spec_available: yes", "machine_readable_spec_available: no")
    (pack_dir / "specs.yaml").write_text(specs)
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert ok                                            # no spec is not a block — doc-anchored mode
    assert "doc-anchored" in detail


# ----------------------------------------------------------------------------------- #
# Availability and vendorability are two findings (ADR-0029)
# ----------------------------------------------------------------------------------- #

def _acme(tmp_path, *repl: tuple[str, str]):
    """A throwaway copy of the fixture pack with substitutions applied to specs.yaml.

    Each substitution is ASSERTED to have matched. A helper that silently no-ops when the fixture is
    reworded would leave every test below passing against an unmodified pack — green, vacuous, and
    indistinguishable from a real result. That is the failure mode this repo keeps re-learning, so it
    is closed here rather than trusted.
    """
    pack_dir = tmp_path / "pack-acme"
    if not pack_dir.exists():
        shutil.copytree(ACME, pack_dir)
    text = (pack_dir / "specs.yaml").read_text()
    for old, new in repl:
        assert old in text, f"fixture no longer contains {old!r} — this substitution is a no-op"
        text = text.replace(old, new)
    (pack_dir / "specs.yaml").write_text(text)
    return pack_dir


_PERMITS_YES = "permits_vendoring: yes"
_AVAIL_YES = "machine_readable_spec_available: yes"

#: The exact refusal the pipeline's one original hard failure has always produced. Pinned as a literal
#: so the new branches cannot quietly re-word or re-route it.
_ORIGINAL_INCOHERENCE = "spec_finding says spec is 'yes' but vendored-spec/ has no spec file"


def test_recon_still_blocks_a_pack_that_claims_a_vendorable_spec_and_vendored_nothing(tmp_path):
    """THE MUST-NOT-WEAKEN TEST. ADR-0029 opens a branch that excuses a pack from vendoring, and the
    one thing it may not do is soften the original failure: a pack that claims an available spec it is
    permitted to keep, and keeps nothing, is incoherent and must still block with the same words.

    The fixture's `permits_vendoring: yes` is load-bearing here, not incidental. Flip it and this pack
    stops being incoherent and becomes the new, legitimate not-vendorable case — so a later edit to the
    fixture could silently convert the pipeline's oldest hard failure into a pass. Asserting the detail
    string character for character is what makes that conversion impossible to do by accident.
    """
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    assert _PERMITS_YES in (pack_dir / "specs.yaml").read_text()
    shutil.rmtree(pack_dir / "vendored-spec")
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok
    assert detail == _ORIGINAL_INCOHERENCE


def test_permits_vendoring_no_is_not_a_shortcut_past_the_vendoring_requirement(tmp_path):
    """THE ESCAPE-HATCH TEST. Writing `no` must buy nothing on its own.

    Three steps in sequence, because the danger is not that the branch exists but that reaching it is
    cheaper than vendoring. Step 1: the flag alone, spec still committed — blocked, because a pack may
    not redistribute what it says it may not. Step 2: flag plus the file removed, but no locator —
    still blocked, because a spec nobody can follow is an unlinked claim. Only the complete exchange
    passes, and by then the pack has taken on a hand-authored doc_ref per endpoint instead of one file.
    """
    pack_dir = _acme(tmp_path, (_PERMITS_YES, "permits_vendoring: no"))

    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok and "redistributes what it says it may not" in detail

    shutil.rmtree(pack_dir / "vendored-spec")
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok and "`where`" in detail

    (pack_dir / "specs.yaml").write_text(
        (pack_dir / "specs.yaml").read_text() + "  where: https://example.invalid/docs/openapi\n")
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert ok, detail
    assert "not vendorable" in detail


def test_recon_blocks_an_unvendorable_pack_that_vendored_the_spec_anyway(tmp_path):
    """Clause 1 in isolation, and on an *unavailable* pack, proving the rule is a fact about the
    licence rather than a consequence of the availability finding."""
    pack_dir = _acme(tmp_path,
                    (_PERMITS_YES, "permits_vendoring: no"),
                    (_AVAIL_YES, "machine_readable_spec_available: no"))
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok
    assert "redistributes what it says it may not" in detail


def test_recon_blocks_an_unvendorable_pack_that_does_not_say_where_the_spec_is(tmp_path):
    pack_dir = _acme(tmp_path, (_PERMITS_YES, "permits_vendoring: no"))
    shutil.rmtree(pack_dir / "vendored-spec")
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok
    assert "`where`" in detail and "`where_now`" in detail


def test_recon_accepts_either_spelling_of_the_locator(tmp_path):
    """Five packs on disk write `where` and five write `where_now`. A gate that knew one spelling
    would move five packs; unifying the names is a filed cleanup, not a thing a gate may impose."""
    for i, key in enumerate(("where", "where_now")):
        pack_dir = _acme(tmp_path / str(i), (_PERMITS_YES, "permits_vendoring: no"))
        shutil.rmtree(pack_dir / "vendored-spec")
        (pack_dir / "specs.yaml").write_text(
            (pack_dir / "specs.yaml").read_text() + f"  {key}: https://example.invalid/spec\n")
        ok, detail = factory.check_recon(Pack.load(pack_dir))
        assert ok, f"{key}: {detail}"


def test_recon_blocks_a_pack_that_never_states_whether_vendoring_is_permitted(tmp_path):
    """Absent is not the same as no. Whether the licence lets us keep a copy is its own finding, so
    silence blocks rather than defaulting either way."""
    pack_dir = _acme(tmp_path, (_PERMITS_YES, "license_note: none"))
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok
    assert "no permits_vendoring" in detail


@pytest.mark.parametrize("value", ["unclear", '"under review"', '""', "[]", "maybe"])
def test_recon_blocks_an_unreadable_permits_vendoring(tmp_path, value):
    """Fail closed, and in BOTH directions. Reading an unreadable value as yes would re-create the
    trap ADR-0029 removes; reading it as no would hand every pack the exemption for free."""
    pack_dir = _acme(tmp_path / (value.strip('"[]') or "x"),
                     (_PERMITS_YES, f"permits_vendoring: {value}"))
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok
    assert "permits_vendoring reads" in detail


@pytest.mark.parametrize("value", ["unknown", "maybe", "partially"])
def test_recon_blocks_an_unreadable_availability(tmp_path, value):
    """Closes a hole that predates ADR-0029: availability was compared literally, so anything outside
    yes/partial — a typo, a hedge — fell through to the doc-anchored PASS and the pack ran a full grid
    in a mode nobody chose for it. The value that most needed to block was the only one that passed."""
    pack_dir = _acme(tmp_path / value,
                     (_AVAIL_YES, f"machine_readable_spec_available: {value}"))
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert not ok
    assert "machine_readable_spec_available reads" in detail


def test_recon_passes_a_spec_that_exists_but_may_not_be_vendored(tmp_path):
    """The new branch end to end — the combination that had no honest encoding before ADR-0029."""
    pack_dir = _acme(tmp_path,
                     (_AVAIL_YES, "machine_readable_spec_available: partial"),
                     (_PERMITS_YES, "permits_vendoring: no"),
                     ("license: Apache-2.0", "license: All rights reserved (site terms of use)"))
    shutil.rmtree(pack_dir / "vendored-spec")
    (pack_dir / "specs.yaml").write_text(
        (pack_dir / "specs.yaml").read_text() + "  where: https://example.invalid/reference\n")
    ok, detail = factory.check_recon(Pack.load(pack_dir))
    assert ok, detail
    assert "not vendorable" in detail and "docs-manifest" in detail


@pytest.mark.parametrize("raw,expected", [
    (True, "yes"), (False, "no"), ("yes", "yes"), ("no", "no"), ("partial", "partial"),
    ("  Partial  ", "partial"),
    # The two prose shapes that are already committed across the cohort, paraphrased so this file
    # carries no vendor's words: lead with the ruling, then argue it — including one that rules both
    # ways in a single field, about two different copies of one document.
    ("Yes, for the copy this pack vendors; NOT for the vendor-hosted copy.", "yes"),
    ("No. The documentation is published as prose and carries no licence grant.", "no"),
    # Unreadable -> '' -> every caller blocks.
    ("unclear", ""), ("", ""), ("   ", ""), (None, ""), ([], ""), (42, ""),
])
def test_a_prose_permits_vendoring_is_read_from_its_leading_ruling(raw, expected):
    """DRIFT PIN for the leading-word parse. `_ruling` reads the first token and ignores the argument
    after it, which is the convention the packs were written in — and is also the hazard: a pack whose
    prose opens with the wrong ruling is read backwards. Editing that behaviour must fail here."""
    assert factory._ruling(raw) == expected


def test_an_unvendorable_pack_cannot_have_a_spec_anchored_endpoint(tmp_path):
    """THE CROSS-GATE THEOREM PIN. ADR-0029 deliberately does NOT re-state "every endpoint must be
    doc_ref-anchored" inside check_recon, because it is already a consequence of two other gates:
    `validate` requires each endpoint to carry a spec_ref OR a doc_ref, and `check_anchoring` resolves
    every spec_ref against the vendored spec — of which, once recon forbids the file, there is none.

    A property that holds across three gates and is asserted in none is the archetype of a hazard that
    decays, so it is asserted here: recon passes, and anchoring is what refuses.
    """
    pack_dir = _acme(tmp_path, (_PERMITS_YES, "permits_vendoring: no"))
    shutil.rmtree(pack_dir / "vendored-spec")
    (pack_dir / "specs.yaml").write_text(
        (pack_dir / "specs.yaml").read_text() + "  where: https://example.invalid/spec\n")
    pack = Pack.load(pack_dir)
    ok, detail = factory.check_recon(pack)
    assert ok, detail                                   # recon is satisfied ...
    anchored, why = factory.check_anchoring(pack)
    assert not anchored                                 # ... and anchoring is what refuses
    assert "spec" in why.lower()


def test_every_external_pack_on_disk_still_passes_recon():
    """Backward compatibility for ADR-0029, over the real cohort rather than the fixture.

    Deliberately EXCLUDES this repo's own `packs/` tree. The reference pack there declares an available
    permissive spec and deliberately vendors nothing — a frozen upstream repository holds the closure —
    which is a third honest combination this gate still cannot express. It has failed recon since
    ADR-0006 and nobody noticed, because recon runs only when the factory dispatches a target and the
    reference pack is never dispatched. That is a pre-existing, separately filed defect, and a sweep
    that pretended otherwise would either fail on day one or have to be written to hide it.
    """
    packs_dir = os.environ.get("AIRE_PACKS_DIR")
    if not packs_dir or not Path(packs_dir).is_dir():
        pytest.skip("AIRE_PACKS_DIR not set — external packs unavailable")
    roots = [d for d in sorted(Path(packs_dir).iterdir()) if (d / "pack.yaml").exists()]
    assert roots, f"AIRE_PACKS_DIR={packs_dir} contains no packs — this gate must not pass vacuously"
    for d in roots:
        ok, detail = factory.check_recon(Pack.load(d))
        assert ok, f"{d.name}: {detail}"


def test_the_reference_pack_recon_state_is_pinned():
    """DRIFT PIN on a live, pre-existing defect (ADR-0015 vocabulary).

    This asserts a defect, which is unusual and deliberate. It proves ADR-0029 neither caused the
    reference pack's recon failure nor papered over it, and the day someone resolves it this test
    fails and forces the resolution to be a decision rather than a side effect.
    """
    ref = Path(__file__).resolve().parents[2] / "packs" / "sailpoint"
    if not (ref / "pack.yaml").exists():
        pytest.skip("reference pack not present")
    ok, detail = factory.check_recon(Pack.load(ref))
    assert not ok
    assert detail == "spec_finding says spec is 'yes' but vendored-spec/ has no spec file"


def test_gates_are_declared_in_pipeline_order():
    """STAGES is documentation; GATES is what runs. They must not drift — the old code inlined the
    order inside run_pipeline, which is exactly how a stage lands in one and not the other."""
    assert [name for name, _ in factory.GATES] == factory.STAGES[:len(factory.GATES)]
    assert [name for name, _ in factory.GATES] == [
        "recon", "validate", "prompts", "roundtrip", "anchoring", "truncation", "disclosure"]


def test_the_prompt_gate_runs_before_the_answer_key_gates():
    """The order is the argument (ADR-0031).

    `validate` says a prompt exists; `prompts` says the prompt identifies what it is asking about;
    only then is it worth proving the answer key scores itself and resolves. Every gate after this
    one reads the ANSWER KEY, which is why a question naming nobody passed all of them and burned a
    grid. Pinned so a later edit cannot quietly demote it below the gates it has to precede.
    """
    names = [name for name, _ in factory.GATES]
    assert names.index("validate") < names.index("prompts") < names.index("roundtrip")
    assert names.index("prompts") < names.index("anchoring")


def test_prompts_gate_passes_for_the_fixture_pack():
    ok, detail = factory.check_prompts(Pack.load(ACME))
    assert ok, detail
    assert "3 prompt(s)" in detail


def test_prompts_gate_blocks_a_pack_whose_prompt_names_nobody(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    victim = pack_dir / "tasks" / "widget-list.yaml"
    text = victim.read_text()
    old = "How do I list widgets in Acme Widget Cloud?"
    assert old in text, f"fixture no longer contains {old!r} — this substitution is a no-op"
    victim.write_text(text.replace(old, "How do I list the things over this vendor's API?"))

    ok, detail = factory.check_prompts(Pack.load(pack_dir))
    assert not ok
    assert "widget-list" in detail and "names no vendor" in detail


def test_prompts_gate_blocks_a_pack_that_declares_nothing(tmp_path):
    """Fail-closed. There is no default and no grandfather clause: a pack that never says what
    counts as naming its target cannot be measured."""
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    cfg = pack_dir / "pack.yaml"
    text = cfg.read_text()
    for old in ("  vendor_names: [Acme]\n", "  product_names: [Widget Cloud]\n"):
        assert old in text, f"fixture no longer contains {old!r} — this substitution is a no-op"
        text = text.replace(old, "")
    cfg.write_text(text)

    ok, detail = factory.check_prompts(Pack.load(pack_dir))
    assert not ok and "vendor_names" in detail


def test_validate_gate_passes_for_the_fixture_pack():
    ok, detail = factory.check_validate(Pack.load(ACME))
    assert ok, detail


def test_validate_gate_blocks_on_a_schema_violation(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    task = pack_dir / "tasks" / "widget-create.yaml"
    task.write_text(task.read_text().replace("category: foundational", "category: not-a-category"))
    ok, detail = factory.check_validate(Pack.load(pack_dir))
    assert not ok
    assert "schema problem(s)" in detail


def test_roundtrip_gate_passes_for_the_fixture_pack():
    ok, detail = factory.check_roundtrip(Pack.load(ACME))
    assert ok, detail
    assert "score their own ground truth 1.0" in detail


def test_roundtrip_gate_blocks_when_a_task_cannot_score_itself(monkeypatch):
    """An asymmetric scoring rule — one that credits only a canonical answer phrase while ground
    truth is documented prose — makes the dimension unwinnable for every pack. The gate stops it
    before a grid burns rather than reporting the resulting 0.00 as a finding about a vendor."""
    monkeypatch.setattr(scorer, "auth_flow_matches",
                        lambda gt, ans, alternates=(): (ans or "").strip() == "canonical phrase")
    ok, detail = factory.check_roundtrip(Pack.load(ACME))
    assert not ok
    assert "auth_flow scored 0.00" in detail


def test_roundtrip_gate_blocks_a_login_style_the_scorer_cannot_name(tmp_path):
    """No monkeypatch — the real block a future pack hits (ADR-0011).

    A vendor whose auth is mutual TLS would otherwise score a free 1.0 on auth for any answer that
    also named nothing recognizable, and get carded on a dimension that tested nothing.
    """
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    task = pack_dir / "tasks" / "widget-list.yaml"
    task.write_text(task.read_text().replace(
        "auth_flow: OAuth2 bearer token",
        "auth_flow: Mutual TLS — the caller presents a client certificate"))
    ok, detail = factory.check_roundtrip(Pack.load(pack_dir))
    assert not ok
    assert "widget-list" in detail
    assert "no login style the scorer recognizes" in detail


def test_anchoring_blocks_on_an_unresolvable_spec_ref(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    task = pack_dir / "tasks" / "widget-create.yaml"
    task.write_text(task.read_text().replace("createWidget", "conjureWidget"))
    ok, detail = factory.check_anchoring(Pack.load(pack_dir))
    assert not ok
    assert "conjureWidget" in detail


# --- the spec's server prefix is notation, not address (ADR-0013) ----------- #

@pytest.mark.parametrize("server_url, path_key", [
    ("/Vendor/api", "/v1/things"),          # OpenAPI 3, prefix split off into servers
    ("https://h.example/Vendor/api", "/v1/things"),   # absolute server URL — path component only
])
def test_a_pack_may_write_the_path_from_any_point_in_the_spec_prefix(server_url, path_key):
    """All three notations name the same endpoint, so all three must anchor.

    Which one is CORRECT is decided by the vendor's documentation, not by the spec — a vendor whose
    spec folds `/api` into servers[0].url routinely documents its base URL as the host and writes
    every worked example as `/api/v1/...`. Pinning ground truth to the spec's notation scored a
    correct answer wrong on one path segment (ADR-0013).
    """
    spec = {"servers": [{"url": server_url}],
            "paths": {path_key: {"get": {"operationId": "listThings"}}}}
    _method, accepted = factory._index_operations(spec)["listThings"]
    assert "/v1/things" in accepted            # the spec's own notation
    assert "/api/v1/things" in accepted        # what the docs usually say
    assert "/Vendor/api/v1/things" in accepted # from the host
    assert "/things" not in accepted           # not a free-for-all: the prefix is what the spec declares


def test_swagger2_base_path_is_the_same_prefix():
    spec = {"basePath": "/Vendor/api",
            "paths": {"/v1/things": {"get": {"operationId": "listThings"}}}}
    _method, accepted = factory._index_operations(spec)["listThings"]
    assert {"/v1/things", "/api/v1/things", "/Vendor/api/v1/things"} <= set(accepted)


def test_a_spec_with_no_server_prefix_accepts_only_its_own_path():
    """The no-prefix case is what the frozen reference pack is, and it must not widen."""
    spec = {"paths": {"/v3/accounts": {"get": {"operationId": "listAccounts"}}}}
    _method, accepted = factory._index_operations(spec)["listAccounts"]
    assert accepted == ["/v3/accounts"]


def test_anchoring_still_blocks_a_path_that_matches_no_notation(tmp_path):
    """Widening the accepted set must not turn the gate off."""
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    task = pack_dir / "tasks" / "widget-create.yaml"
    task.write_text(task.read_text().replace("path: /v3/widgets", "path: /v3/gadgets"))
    ok, detail = factory.check_anchoring(Pack.load(pack_dir))
    assert not ok
    assert "/v3/gadgets" in detail


# --------------------------------------------------------------------------- #
# Pipeline (offline, mock provider)
# --------------------------------------------------------------------------- #

def test_pipeline_carding_a_clean_pack(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    entry = QueueEntry(id="pack-acme", display_name="Acme Widget Cloud", tier=1)
    report = factory.run_pipeline(entry, Pack.load(pack_dir), today="2026-07-24",
                                  provider="mock", log=lambda *a: None)
    assert report["outcome"] == "carded"
    assert entry.status == "carded"
    assert entry.last_run == "2026-07-24"
    assert (pack_dir / "REPORT.scaffold.md").exists()
    card = (pack_dir / "REPORT.scaffold.md").read_text()
    assert "DRAFT — UNREVIEWED, NOT FOR OUTREACH" in card
    assert "## Headline" in card
    assert report["conditions"]                          # at least one condition graded


def test_pipeline_blocks_with_reason_on_a_broken_pack(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    task = pack_dir / "tasks" / "widget-create.yaml"
    task.write_text(task.read_text().replace("createWidget", "conjureWidget"))
    entry = QueueEntry(id="pack-acme", display_name="Acme Widget Cloud", tier=1)
    report = factory.run_pipeline(entry, Pack.load(pack_dir), today="2026-07-24",
                                  provider="mock", log=lambda *a: None)
    assert report["outcome"] == "blocked"
    assert report["stage"] == "anchoring"
    assert entry.status == "blocked"
    assert entry.blocked_reason.startswith("[anchoring]")
    assert not (pack_dir / "REPORT.scaffold.md").exists()   # never carded past a failed gate


def test_pipeline_blocks_at_roundtrip_before_any_grid(tmp_path, monkeypatch):
    """The whole point of the gate: an unscoreable pack never reaches a paid condition. The stage
    name in `blocked_reason` is what tells an operator this is a harness fault, not a schema one."""
    monkeypatch.setattr(scorer, "auth_flow_matches",
                        lambda gt, ans, alternates=(): (ans or "").strip() == "canonical phrase")
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    entry = QueueEntry(id="pack-acme", display_name="Acme Widget Cloud", tier=1)
    report = factory.run_pipeline(entry, Pack.load(pack_dir), today="2026-07-24",
                                  provider="mock", log=lambda *a: None)
    assert report["outcome"] == "blocked"
    assert report["stage"] == "roundtrip"
    assert entry.blocked_reason.startswith("[roundtrip]")
    assert not (pack_dir / "results").exists()              # blocked before the mock run, let alone a grid
    assert not (pack_dir / "REPORT.scaffold.md").exists()


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #

def test_render_status_shows_counts_and_block_reasons():
    entries = [
        QueueEntry(id="a", display_name="Alpha", tier=1, status="carded", spend_usd=5.5),
        QueueEntry(id="b", display_name="Beta", tier=2, status="blocked",
                   blocked_reason="[recon] no spec"),
        QueueEntry(id="c", display_name="Gamma", tier=3, status="queued"),
        QueueEntry(id="d", display_name="Delta", tier=4, status="parked",
                   blocked_reason="needs a second answer contract"),
    ]
    out = factory.render_status(entries)
    assert "Alpha" in out and "Beta" in out and "Gamma" in out and "Delta" in out
    assert "$5.50" in out
    assert "blocked: [recon] no spec" in out
    # A parked target's reason is the entire record of a decision not to measure something. It was
    # silently dropped before ADR-0019, because the reason line keyed off the literal "blocked".
    assert "parked: needs a second answer contract" in out
    assert "1 carded · 1 blocked · 1 parked · 1 open" in out
