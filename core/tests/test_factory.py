"""The factory dispatcher (ADR-0006): queue model, gates, and the unattended pipeline.

All model-free — the pipeline runs with `provider="mock"`, so the whole spine (recon → validate →
roundtrip → anchoring → mock → grid → compare → card → advance) is exercised offline against the
synthetic `pack-acme` fixture. The guard (`test_core_no_vendor`) proves the factory names no vendor.
"""
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


def test_gates_are_declared_in_pipeline_order():
    """STAGES is documentation; GATES is what runs. They must not drift — the old code inlined the
    order inside run_pipeline, which is exactly how a stage lands in one and not the other."""
    assert [name for name, _ in factory.GATES] == factory.STAGES[:len(factory.GATES)]
    assert [name for name, _ in factory.GATES] == ["recon", "validate", "roundtrip", "anchoring"]


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
                        lambda gt, ans: (ans or "").strip() == "canonical phrase")
    ok, detail = factory.check_roundtrip(Pack.load(ACME))
    assert not ok
    assert "auth_flow scored 0.00" in detail


def test_anchoring_blocks_on_an_unresolvable_spec_ref(tmp_path):
    pack_dir = tmp_path / "pack-acme"
    shutil.copytree(ACME, pack_dir)
    task = pack_dir / "tasks" / "widget-create.yaml"
    task.write_text(task.read_text().replace("createWidget", "conjureWidget"))
    ok, detail = factory.check_anchoring(Pack.load(pack_dir))
    assert not ok
    assert "conjureWidget" in detail


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
                        lambda gt, ans: (ans or "").strip() == "canonical phrase")
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
    ]
    out = factory.render_status(entries)
    assert "Alpha" in out and "Beta" in out and "Gamma" in out
    assert "$5.50" in out
    assert "blocked: [recon] no spec" in out
    assert "1 carded · 1 blocked · 1 open" in out
