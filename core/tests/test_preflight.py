"""Tests for the sterile-run pre-flight gates (core/preflight.py).

The model is stubbed — no real CLI calls. Verifies the canary verdict logic: sterile must be
ignorant (no marker, no tools) and control must recite, and the gate fails if either is wrong. The
project marker and repo root are passed in (pack-supplied); core hardcodes neither.
"""
from core import preflight

MARKER = "acme-eval-project"


class StubModel:
    """Returns a scripted (text, available_tools) per call, keyed by cwd presence."""

    def __init__(self, sterile_text, sterile_tools, control_text):
        self._sterile = (sterile_text, sterile_tools)
        self._control = (control_text, [])

    def complete(self, messages, policy=None, cwd=None):
        text, tools = self._control if cwd else self._sterile
        return _Resp(text, tools)


class _Resp:
    def __init__(self, text, tools):
        self.text = text
        self.available_tools = tools
        self.transcript = [{"role": "assistant", "text": text, "tool_uses": []}]


def _run(model):
    return preflight.run_canaries(model, project_marker=MARKER, repo_root="/some/repo/root")


def test_canary_passes_when_sterile_ignorant_and_control_recites():
    m = StubModel(
        sterile_text="I don't have information about a specific project in my context.",
        sterile_tools=[],
        control_text=f"You're in the {MARKER} repo, currently on Cycle 7.",
    )
    v = _run(m)
    assert v["sterile"]["ignorant"] is True
    assert v["control"]["recites"] is True
    assert v["passed"] is True


def test_canary_fails_if_sterile_names_project():
    m = StubModel(
        sterile_text=f"This is the {MARKER} project on Cycle 7.",
        sterile_tools=[],
        control_text=f"{MARKER}, Cycle 7.",
    )
    v = _run(m)
    assert v["sterile"]["ignorant"] is False
    assert v["passed"] is False


def test_canary_fails_if_sterile_had_tools():
    m = StubModel(
        sterile_text="I can't identify the project.",
        sterile_tools=["Bash"],
        control_text=f"{MARKER}, Cycle 7.",
    )
    v = _run(m)
    assert v["sterile"]["ignorant"] is False
    assert v["passed"] is False


def test_canary_fails_if_control_cannot_recite():
    m = StubModel(
        sterile_text="I don't know the project.",
        sterile_tools=[],
        control_text="I don't know the project either.",
    )
    v = _run(m)
    assert v["control"]["recites"] is False
    assert v["passed"] is False


def test_write_canary_artifacts(tmp_path):
    m = StubModel("no idea", [], f"{MARKER}, Cycle 7")
    v = _run(m)
    preflight.write_canary_artifacts(v, tmp_path)
    assert (tmp_path / "verdict.json").exists()
    assert (tmp_path / "sterile-canary.txt").exists()
    assert (tmp_path / "control-canary.txt").exists()
    assert MARKER in (tmp_path / "control-canary.txt").read_text()
