"""The model-pin guard on `run` (core/__main__.py).

An unpinned cli run would silently use the operator's session-default model, which can differ from the
pinned comparison model and confound the whole grid. The guard blocks it.
"""
import argparse
from pathlib import Path

from core import __main__ as m
from core.model import ModelResponse

ACME = str(Path(__file__).resolve().parent / "fixtures" / "pack-acme")


class _StubCli:
    def __init__(self, *a, **k):
        pass

    def ping(self):
        return ModelResponse(text="pong", model_reported="claude-opus-4-8")


def _args(**over):
    base = dict(pack=ACME, condition="no-context", n=1, tasks=None, model=None, out=None,
                overwrite=False, provider="cli", mock=False, skip_preflight=True,
                allow_unpinned_model=False)
    base.update(over)
    return argparse.Namespace(**base)


def test_unpinned_cli_run_is_blocked(monkeypatch, tmp_path, capsys):
    # No --model on a cli run: must BLOCK rather than silently use the session-default model.
    monkeypatch.setattr(m, "ClaudeCliModel", _StubCli)
    rc = m.cmd_run(_args(out=str(tmp_path / "r")))
    assert rc == m.EXIT_BLOCKED
    assert "no model pinned" in capsys.readouterr().err
