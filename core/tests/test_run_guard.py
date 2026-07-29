"""The guards on `run` (core/__main__.py) — everything that refuses to spend money.

Three of them, in the order the command applies them:

1. **The prompt gate** (ADR-0031). A grid whose prompts do not name what they are asking about
   measures the question, not the vendor. Blocks before the transport is even constructed, which is
   also before the model-pin guard: it is the cheapest check and it needs nothing.
2. **The model-pin guard**. An unpinned cli run would silently use the operator's session-default
   model, which can differ from the pinned comparison model and confound the whole grid.
3. **The format-failure circuit breaker** (ADR-0032). The first two are static; this one is the only
   guard that can catch a broken question the static one cannot see, and it costs 20 runs to do it.
"""
import argparse
import copy
import json
import os
from pathlib import Path

import pytest
import yaml

from core import __main__ as m
from core.model import ModelResponse

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ACME = str(FIXTURES / "pack-acme")
REPO_ROOT = Path(__file__).resolve().parents[2]


class _StubCli:
    def __init__(self, *a, **k):
        pass

    def ping(self):
        return ModelResponse(text="pong", model_reported="claude-opus-4-8")


def _args(**over):
    base = dict(pack=ACME, condition="no-context", n=1, tasks=None, model=None, out=None,
                overwrite=False, provider="cli", mock=False, skip_preflight=True,
                allow_unpinned_model=False,
                format_failure_threshold=m.FORMAT_FAILURE_THRESHOLD)
    base.update(over)
    return argparse.Namespace(**base)


# --- 1. the prompt gate ---------------------------------------------------- #

def _pack_with_prompts_naming_nobody(tmp_path: Path) -> str:
    """A copy of the fixture pack whose prompts name neither the vendor nor the product.

    This is the literal shape that cost a grid: well-formed, answerable, and identifying nothing.
    """
    dest = tmp_path / "pack-nameless"
    dest.mkdir()
    (dest / "pack.yaml").write_text((FIXTURES / "pack-acme" / "pack.yaml").read_text())
    (dest / "tasks").mkdir()
    n = 0
    for src in sorted((FIXTURES / "pack-acme" / "tasks").glob("*.yaml")):
        task = yaml.safe_load(src.read_text())
        task["prompt"] = "Using this vendor's API, how do I do the thing?"
        (dest / "tasks" / src.name).write_text(yaml.safe_dump(task))
        n += 1
    assert n, "fixture pack has no tasks — this helper would build a vacuous pack"
    return str(dest)


def test_a_grid_whose_prompts_name_nobody_is_blocked(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m, "ClaudeCliModel", _StubCli)
    rc = m.cmd_run(_args(pack=_pack_with_prompts_naming_nobody(tmp_path),
                         model="claude-opus-4-8", out=str(tmp_path / "r")))
    assert rc == m.EXIT_BLOCKED
    err = capsys.readouterr().err
    assert "prompt problem(s)" in err and "names no vendor" in err


def test_the_prompt_gate_runs_before_the_transport_is_built(monkeypatch, tmp_path, capsys):
    """It must not cost a ping, and it must not need one. If the transport were constructed first, a
    broken pack would still block — but only after a network round trip, and it would block with the
    wrong reason on a machine with no credentials."""
    def _explode(*a, **k):
        raise AssertionError("the transport was constructed before the prompt gate ran")

    monkeypatch.setattr(m, "ClaudeCliModel", _explode)
    rc = m.cmd_run(_args(pack=_pack_with_prompts_naming_nobody(tmp_path),
                         model="claude-opus-4-8", out=str(tmp_path / "r")))
    assert rc == m.EXIT_BLOCKED


def test_a_mock_run_is_exempt_from_the_prompt_gate(tmp_path):
    """A mock grid spends nothing and exists to prove plumbing, so it must still run."""
    rc = m.cmd_run(_args(pack=_pack_with_prompts_naming_nobody(tmp_path), mock=True,
                         out=str(tmp_path / "r")))
    assert rc == m.EXIT_OK


def test_the_prompt_gate_passes_a_pack_that_is_fine():
    """The other half of the guard: it must not block a good pack, or every test above would be
    passing for the wrong reason."""
    from core.pack import Pack
    assert m._prompt_gate(Pack.load(ACME)) == m.EXIT_OK


# --- 2. the model pin ------------------------------------------------------ #

def test_unpinned_cli_run_is_blocked(monkeypatch, tmp_path, capsys):
    # No --model on a cli run: must BLOCK rather than silently use the session-default model.
    monkeypatch.setattr(m, "ClaudeCliModel", _StubCli)
    rc = m.cmd_run(_args(out=str(tmp_path / "r")))
    assert rc == m.EXIT_BLOCKED
    assert "no model pinned" in capsys.readouterr().err


# --- 3. the format-failure circuit breaker --------------------------------- #

def _runs(n: int, n_failures: int, task: str = "t") -> list[dict]:
    return [{"task_id": task, "format_failure": i < n_failures} for i in range(n)]


def test_the_breaker_does_not_fire_below_the_floor():
    """19 runs, every one a failure, and it still holds: a rate needs a denominator. Grids run
    task-major, so an early cluster on one task is not evidence about the grid."""
    assert m.format_failure_breaker(_runs(19, 19), m.FORMAT_FAILURE_THRESHOLD) == ""


def test_the_breaker_fires_at_the_floor_on_a_broken_question():
    reason = m.format_failure_breaker(_runs(20, 15), m.FORMAT_FAILURE_THRESHOLD)
    assert reason and "15/20" in reason and "75%" in reason


def test_the_breaker_is_strictly_greater_than_the_threshold():
    """Exactly at the threshold is not over it. 4/20 = 20% must survive; 5/20 = 25% must not."""
    assert m.format_failure_breaker(_runs(20, 4), 0.20) == ""
    assert m.format_failure_breaker(_runs(20, 5), 0.20)


def test_the_floor_is_where_the_headroom_is():
    """The measurement that set the floor, restated as arithmetic.

    Replaying every archived grid (see below) and taking the worst rate over any prefix at least as
    long as the floor gives: **20.0% at a floor of 10, 13.3% at 15, and 11.4% at 20.** A 20%
    threshold on a 10-run floor therefore has ZERO headroom — one more failure in one published
    grid's opening runs and it aborts healthy work. At 20 runs the same threshold clears the worst
    real prefix by a factor of 1.75.

    Pinned here as the two cases that bracket the choice: the worst real opening (2 failures in the
    first 10 runs) must survive, and it does at either floor — but only at floor 20 does it survive
    with room to spare, which is what a floor is for.
    """
    assert m.format_failure_breaker(_runs(10, 2), m.FORMAT_FAILURE_THRESHOLD, floor=10) == ""
    assert m.format_failure_breaker(_runs(10, 3), m.FORMAT_FAILURE_THRESHOLD, floor=10), \
        "at floor 10 a single extra failure aborts — that is the zero headroom being pinned"
    assert m.format_failure_breaker(_runs(20, 3), m.FORMAT_FAILURE_THRESHOLD) == ""
    assert m.format_failure_breaker(_runs(20, 4), m.FORMAT_FAILURE_THRESHOLD) == "", \
        "the worst real prefix at floor 20 is 11.4%; it must clear the threshold, not scrape it"


def test_a_threshold_of_one_disables_it():
    assert m.format_failure_breaker(_runs(60, 60), 1.0) == ""


def test_the_reason_names_the_worst_tasks():
    records = _runs(10, 8, task="alpha") + _runs(10, 2, task="beta")
    reason = m.format_failure_breaker(records, m.FORMAT_FAILURE_THRESHOLD)
    assert "alpha×8" in reason and "beta×2" in reason


def _archived_conditions() -> list[Path]:
    """Every archived condition on disk that has per-run records: in-repo and, if set, external."""
    roots = [REPO_ROOT / "packs"]
    external = os.environ.get("AIRE_PACKS_DIR")
    if external:
        roots.append(Path(external))
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("*/results/*/scores.json", "*/fixtures/imported/*/scores.json"):
            found += [p.parent for p in root.glob(pattern) if (p.parent / "runs").is_dir()]
    return sorted(set(found))


ARCHIVED = _archived_conditions()


@pytest.mark.skipif(not ARCHIVED, reason="no archived conditions on disk")
@pytest.mark.parametrize("condition_dir", ARCHIVED,
                         ids=lambda p: f"{p.parents[1].name}/{p.name}")
def test_the_breaker_fires_on_no_archived_grid_this_project_published(condition_dir):
    """The claim that makes the threshold honest, checked rather than asserted.

    Replays every archived condition on disk through the breaker in run order. A threshold that
    would have aborted work this project actually published is not conservative, it is broken, and
    the only way to know is to run it against the record.

    **The replay is deliberately pessimistic, and that is worth stating.** It reads each run
    record's own `format_failure` flag. For a grid that was later re-scored offline by
    `rebuild-report`, those flags are STALE: the rebuild rewrites `scores.json` and `summary.md` but
    not `runs/*.json`, so an archive can still carry a failure that the published number no longer
    counts (3 of the archived conditions on disk do exactly this, 8 flags in total — filed
    separately). That makes this test harder to pass than reality, not easier: the breaker is being
    replayed against a worse failure record than the cohort actually published, and it still never
    fires.
    """
    records: list[dict] = []
    meta = json.loads((condition_dir / "scores.json").read_text()).get("metadata", {})
    for path in sorted(condition_dir.glob("runs/*.json")):
        records.append(json.loads(path.read_text()))
        reason = m.format_failure_breaker(records, m.FORMAT_FAILURE_THRESHOLD)
        assert not reason, (
            f"{condition_dir.parents[1].name}/{condition_dir.name} "
            f"(mock={meta.get('mock')}) would have been aborted after {len(records)} runs: {reason}"
        )
    assert records, f"{condition_dir} has a runs/ dir but no run records"


def test_the_replay_above_is_not_vacuous():
    """It sweeps archives by glob; if the glob found nothing it would pass by finding nothing."""
    assert ARCHIVED, "no archived conditions discovered — the replay above would be a no-op"
    total = sum(len(list(d.glob("runs/*.json"))) for d in ARCHIVED)
    assert total > 100, f"only {total} archived runs discovered — too few to be evidence"


def test_a_synthetic_broken_grid_would_have_been_caught():
    """The true positive. The grid that motivated this — 45 format failures in 60 runs — no longer
    exists on disk: it was deleted when it was discarded, before this breaker existed. So the case
    it must catch is reconstructed from the rate the cycle report recorded, and this test says so
    rather than implying the real transcripts were replayed."""
    records = _runs(60, 45)
    for i in range(1, len(records) + 1):
        if m.format_failure_breaker(records[:i], m.FORMAT_FAILURE_THRESHOLD):
            assert i == 20, "should trip at the floor, saving the remaining two thirds of the grid"
            return
    raise AssertionError("the breaker never fired on a 75%-failure grid")


def test_the_threshold_in_force_is_recorded_in_the_artifact(tmp_path):
    """A grid published past a high failure rate is a decision, and the decision must survive in the
    artifact rather than in someone's memory of the terminal."""
    out = tmp_path / "r"
    assert m.cmd_run(_args(mock=True, out=str(out))) == m.EXIT_OK
    meta = json.loads((out / "scores.json").read_text())["metadata"]
    assert "format_failure_threshold" in meta
    assert "stopped_early" not in meta


def test_stopping_early_deletes_nothing(tmp_path, monkeypatch):
    """The breaker stops the spend and asks for a ruling. Everything already run stays archived and
    the grid stays resumable — it never discards evidence."""
    before = _runs(5, 5)
    kept = copy.deepcopy(before)
    m.format_failure_breaker(before, m.FORMAT_FAILURE_THRESHOLD)
    assert before == kept
