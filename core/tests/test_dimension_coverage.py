"""A dimension declared by a contract and exercised by no task (ADR-0045).

The converse of the round-trip control (ADR-0010). `check_task` asks whether each TASK can score
something; nothing asked whether each DIMENSION has a task, so a pack could declare three, exercise
two, and publish an overall that is the mean of two while its card, its contract and its results
table all said three. Every gate passed over exactly that (public #81).

Every rule below is verified by BREAKING it on purpose, on the synthetic neutral fixture — a pack
carrying no real vendor identity, so `core/` stays name-free.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from core import contract as contract_mod
from core import docs_answer, roundtrip
from core.contract import API_CONTRACT, DOCS_CONTRACT, bind_observations
from core.pack import Pack

FIXTURES = Path(__file__).parent / "fixtures"
NEUTRAL_DOCS = FIXTURES / "pack-docs-neutral"


def _copy(tmp_path: Path, src: Path = NEUTRAL_DOCS) -> Path:
    dest = tmp_path / src.name
    shutil.copytree(src, dest)
    return dest


def _edit_pack(root: Path, **changes) -> Pack:
    cfg = yaml.safe_load((root / "pack.yaml").read_text()) or {}
    cfg.update(changes)
    (root / "pack.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return Pack.load(root)


def _coverage(pack: Pack) -> roundtrip.TaskControl:
    controls = [c for c in roundtrip.check_pack(pack) if c.task_id == "(dimension-coverage)"]
    assert len(controls) == 1, "the coverage control must be emitted exactly once per pack"
    return controls[0]


# --------------------------------------------------------------------------- #
# The gate, broken in each direction it can be broken
# --------------------------------------------------------------------------- #

def test_the_neutral_fixture_exercises_every_dimension_it_declares(tmp_path):
    """Non-vacuity first. If the fixture already failed, every break test below would 'pass' for
    the wrong reason — the shape `test_the_sweep_enumerates_packs` exists to prevent."""
    control = _coverage(Pack.load(_copy(tmp_path)))
    assert control.ok, control.problems
    assert any("3 of 3 declared dimension(s) exercised" in n for n in control.notes), control.notes


def test_a_dimension_with_no_task_blocks_in_the_docs_cohort(tmp_path):
    root = _copy(tmp_path)
    # `pick-controller` is the only task carrying a catalog number.
    (root / "tasks" / "pick-controller.yaml").unlink()
    _edit_pack(root, expected_task_ids=["check-pairing"])
    control = _coverage(Pack.load(root))
    assert not control.ok
    assert any("no task exercises 'catalog_number'" in p for p in control.problems), control.problems


def test_a_written_reason_lets_the_gate_pass_and_is_echoed(tmp_path):
    """A reason, not a boolean — the `short_text_ok` (ADR-0021) bargain. And it is ECHOED: a
    declaration filed where nobody reads it is the decay mode ADR-0015 exists to catch."""
    root = _copy(tmp_path)
    (root / "tasks" / "pick-controller.yaml").unlink()
    reason = "This surface publishes no orderable part number; it is configured, not selected."
    pack = _edit_pack(root, expected_task_ids=["check-pairing"],
                      unexercised_dimensions={"catalog_number": reason})
    control = _coverage(pack)
    assert control.ok, control.problems
    assert any(reason in n for n in control.notes), control.notes
    text, _total = roundtrip.format_report(roundtrip.check_pack(pack))
    assert reason in text, "the reason must reach the report a reviewer actually reads"


def test_an_empty_reason_does_not_buy_the_tolerance(tmp_path):
    root = _copy(tmp_path)
    (root / "tasks" / "pick-controller.yaml").unlink()
    pack = _edit_pack(root, expected_task_ids=["check-pairing"],
                      unexercised_dimensions={"catalog_number": "   "})
    control = _coverage(pack)
    assert not control.ok
    assert any("no written reason" in p for p in control.problems), control.problems


def test_a_stale_declaration_blocks_even_though_coverage_is_complete(tmp_path):
    """The direction that rots quietly: a pack adds the missing task and keeps the pack.yaml saying
    it has none. Nothing is missing any more, and the file now states a falsehood."""
    pack = _edit_pack(_copy(tmp_path),
                      unexercised_dimensions={"catalog_number": "a reason that is no longer true"})
    control = _coverage(pack)
    assert not control.ok
    assert any("stale declaration" in p for p in control.problems), control.problems


def test_declaring_a_dimension_the_contract_does_not_have_blocks(tmp_path):
    """Mirrors the unknown-category check `validate` already applies to `na_categories`."""
    pack = _edit_pack(_copy(tmp_path), unexercised_dimensions={"endpoint": "not on this surface"})
    control = _coverage(pack)
    assert not control.ok
    assert any("which the 'docs' contract does not declare" in p for p in control.problems), \
        control.problems


def test_a_pack_with_no_tasks_cannot_pass_by_having_nothing_to_check(tmp_path):
    """The vacuous-green shape, stated as its own rule: zero tasks means zero exercised dimensions,
    and a gate that read that as 'nothing failed' would pass an empty pack."""
    root = _copy(tmp_path)
    for task in (root / "tasks").glob("*.yaml"):
        task.unlink()
    pack = _edit_pack(root, expected_task_ids=[])
    control = _coverage(pack)
    assert not control.ok
    assert any("no tasks" in p for p in control.problems), control.problems


# --------------------------------------------------------------------------- #
# Cohort-scoped severity
# --------------------------------------------------------------------------- #

def test_the_api_cohort_warns_where_the_docs_cohort_blocks():
    """Measured, not assumed. Running this gate over every pack on disk for the first time found a
    dimension with no task in 13 of 18, so blocking the api cohort would have failed eleven
    already-published packs over a pre-existing condition (ADR-0045). The warning still names it."""
    assert DOCS_CONTRACT.coverage_blocks is True
    assert API_CONTRACT.coverage_blocks is False


def test_an_api_pack_missing_a_dimension_is_warned_not_blocked(tmp_path):
    src = FIXTURES / "pack-acme"
    root = _copy(tmp_path, src)
    pack = Pack.load(root)
    assert pack.cohort == "api"
    for task in (root / "tasks").glob("*.yaml"):
        doc = yaml.safe_load(task.read_text())
        (doc.get("ground_truth") or {}).pop("required_scopes", None)
        task.write_text(yaml.safe_dump(doc, sort_keys=False))
    control = _coverage(Pack.load(root))
    assert control.ok, control.problems
    assert any(n.startswith("WARNING") and "required_scopes" in n for n in control.notes), \
        control.notes


def test_a_bad_declaration_blocks_in_every_cohort(tmp_path):
    """The split's other half: coverage is cohort-scoped, but a pack's own false statement is not.
    These exist only because a pack opted in, so no existing pack is touched."""
    root = _copy(tmp_path, FIXTURES / "pack-acme")
    pack = _edit_pack(root, unexercised_dimensions={"catalog_number": "wrong cohort's dimension"})
    control = _coverage(pack)
    assert not control.ok
    assert any("does not declare" in p for p in control.problems), control.problems


# --------------------------------------------------------------------------- #
# The unscored-observation channel: structurally incapable of scoring
# --------------------------------------------------------------------------- #

OBS = {"allowable_load": "The rated load in lb. NOT A DIMENSION — recorded, never scored."}


def test_an_observation_key_can_never_become_a_dimension(tmp_path):
    pack = _edit_pack(_copy(tmp_path), unscored_observations=OBS)
    contract = pack.contract
    assert contract.observations == ("allowable_load",)
    assert "allowable_load" not in contract.dimensions
    assert "allowable_load" not in contract.dim_labels
    assert contract.dimensions == DOCS_CONTRACT.dimensions, \
        "declaring an observation must not widen the scored dimension set"


def test_an_observation_is_recorded_in_the_exhibit_and_absent_from_the_score(tmp_path):
    pack = _edit_pack(_copy(tmp_path), unscored_observations=OBS)
    contract = pack.contract
    task = {
        "id": "t", "prompt": "p",
        "ground_truth": {"catalog_numbers": ["XR-8300"], "observations": {"allowable_load": "1250"}},
    }
    answer = contract.answer_from_ground_truth(task)
    from core.contract import score_response
    score, parsed = score_response(task, contract.render_block(answer), contract)
    assert not parsed.is_failure, parsed.failure
    assert score.exhibit["observed"] == {"allowable_load": "1250"}
    assert score.dim("allowable_load") is None, "an observation must not appear as a scored dimension"
    assert set(score.dimensions) <= set(contract.dimensions)


def test_a_wrong_observation_cannot_lower_a_score(tmp_path):
    """The property that makes this channel safe to add to a pre-registered instrument: the score is
    identical whether the observation is right, wrong or absent."""
    pack = _edit_pack(_copy(tmp_path), unscored_observations=OBS)
    contract = pack.contract
    from core.contract import score_response
    gt = {"catalog_numbers": ["XR-8300"], "observations": {"allowable_load": "1250"}}
    task = {"id": "t", "prompt": "p", "ground_truth": gt}

    def block(load):
        return docs_answer.render_block(docs_answer.DocsAnswer(
            catalog_numbers=["XR-8300"], firmware_version=None, software_version=None,
            publication=None, observations={"allowable_load": load}))

    def scored(s):
        return {d: (s.dim(d).score if s.dim(d) else None) for d in contract.dimensions}

    right, _ = score_response(task, block("1250"), contract)
    wrong, _ = score_response(task, block("99999"), contract)
    missing, _ = score_response(task, block(None), contract)
    assert scored(right) == scored(wrong) == scored(missing) == {
        "catalog_number": 1.0, "firmware_version": None, "software_version": None}
    assert wrong.exhibit["observed"] == {"allowable_load": "99999"}


def test_an_observation_name_that_collides_with_a_contract_key_is_refused(tmp_path):
    for name in ("catalog_number", "publication", "firmware_version"):
        pack = _edit_pack(_copy(tmp_path / name), unscored_observations={name: "a reason"})
        with pytest.raises(KeyError, match="already defines"):
            _ = pack.contract


def test_an_observation_with_no_written_reason_is_refused(tmp_path):
    pack = _edit_pack(_copy(tmp_path), unscored_observations={"allowable_load": "  "})
    with pytest.raises(KeyError, match="no written reason"):
        _ = pack.contract


def test_the_api_cohort_has_no_observation_channel():
    """Adding one to another cohort is an ADR, not a pack field."""
    with pytest.raises(KeyError, match="no unscored-observation channel"):
        bind_observations(API_CONTRACT, {"allowable_load": "a reason"})


# --------------------------------------------------------------------------- #
# The prompt a measured pack already answered must not move
# --------------------------------------------------------------------------- #

def test_a_pack_declaring_no_observation_renders_the_frozen_prompt_byte_for_byte():
    """ADR-0014's rule: a prompt cannot be edited retroactively, because the archive stops being an
    answer to the prompt that produced it. So this channel had to be additive or not exist."""
    assert docs_answer.observation_lines(None) == ""
    assert docs_answer.observation_lines({}) == ""
    plain = docs_answer.build_prompt("Q?")
    assert plain == "Q?\n" + docs_answer.DOCS_ANSWER_BLOCK_SUFFIX
    assert docs_answer.build_prompt("Q?", None) == plain
    assert docs_answer.build_prompt("Q?", {}) == plain


def test_declaring_none_returns_the_base_contract_object_itself():
    """Identity, not a copy: `contract is DOCS_CONTRACT` stays true for every pack that predates
    this field, which is the cheapest possible proof that nothing about them changed."""
    assert bind_observations(DOCS_CONTRACT, None) is DOCS_CONTRACT
    assert bind_observations(DOCS_CONTRACT, {}) is DOCS_CONTRACT
    assert bind_observations(API_CONTRACT, None) is API_CONTRACT


def test_a_declared_observation_reaches_the_prompt_and_survives_a_round_trip(tmp_path):
    pack = _edit_pack(_copy(tmp_path), unscored_observations=OBS)
    contract = pack.contract
    text = contract.build_prompt("Q?")
    assert text.startswith("Q?\n" + docs_answer.DOCS_ANSWER_BLOCK_SUFFIX)
    assert "allowable_load:" in text
    assert "NOT part of how the answer is judged" in text
    answer = docs_answer.DocsAnswer(catalog_numbers=["XR-8300"], firmware_version=None,
                                    software_version=None, publication=None,
                                    observations={"allowable_load": "1250"})
    again = contract.parse(contract.render_block(answer))
    assert not again.is_failure, again.failure
    assert again.summary.observations == {"allowable_load": "1250"}


def test_an_undeclared_key_a_model_volunteers_is_ignored():
    """What lands in the archive has to be what was asked for, or the exhibit becomes a place data
    arrives without a decision."""
    block = ("```answer-summary\ncatalog_numbers: [XR-8300]\nallowable_load: '1250'\n```\n")
    assert DOCS_CONTRACT.parse(block).summary.observations == {}


def test_an_observation_alone_does_not_rescue_a_block_from_format_failure():
    """Otherwise a pack could improve its own format-failure rate by declaring an extra key."""
    contract = bind_observations(DOCS_CONTRACT, OBS)
    result = contract.parse("```answer-summary\nallowable_load: '1250'\n```\n")
    assert result.is_failure
    assert "none of the contract's keys" in result.failure.reason


# --------------------------------------------------------------------------- #
# The sweep is non-vacuous
# --------------------------------------------------------------------------- #

def test_every_registered_contract_declares_a_coverage_severity():
    """A cohort added later must decide this rather than inherit a default nobody argued."""
    assert contract_mod.CONTRACTS
    for name, contract in contract_mod.CONTRACTS.items():
        assert isinstance(contract.coverage_blocks, bool), name
        assert contract.observations == (), f"{name}: a base contract binds no pack's observations"
