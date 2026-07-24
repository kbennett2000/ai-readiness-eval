"""Tests for the Claude-CLI transport parsing (core/model.py).

The subprocess is mocked — no real CLI calls. Verifies stream-json parsing (result text, usage,
model, and tool_use capture) and the per-condition tool policy in the command (ADR-0008).
"""
import json
import subprocess

import pytest

from core import model as model_mod
from core.model import CliPolicy, ClaudeCliModel, ModelError, deny_all_policy


def _stream(*events) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _assistant(model="claude-sonnet-4-6", *, text=None, tool=None):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool is not None:
        content.append({"type": "tool_use", "name": tool, "input": {}})
    return {"type": "assistant", "message": {"model": model, "content": content}}


def _result(text="the answer", **kw):
    base = {"type": "result", "is_error": False, "result": text,
            "total_cost_usd": 0.0321, "duration_ms": 4200,
            "usage": {"input_tokens": 100, "output_tokens": 50}}
    base.update(kw)
    return base


def _fake_run(stdout):
    def run(cmd, input=None, capture_output=True, text=True, timeout=None, cwd=None):
        run.cmd = cmd
        run.cwd = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return run


@pytest.fixture(autouse=True)
def _on_path(monkeypatch):
    monkeypatch.setattr(model_mod.shutil, "which", lambda name: "/usr/bin/claude")


def test_parses_result_usage_and_model(monkeypatch):
    stdout = _stream(_assistant(text="the answer"), _result())
    monkeypatch.setattr(model_mod.subprocess, "run", _fake_run(stdout))
    resp = ClaudeCliModel("claude-sonnet-4-6").complete([{"role": "user", "content": "hi"}])
    assert resp.text == "the answer"
    assert resp.input_tokens == 100 and resp.output_tokens == 50
    assert resp.cost_usd == 0.0321
    assert resp.model_reported == "claude-sonnet-4-6"
    assert resp.tool_uses == []


def test_captures_tool_uses(monkeypatch):
    stdout = _stream(
        _assistant(tool="ToolSearch"),
        _assistant(tool="mcp__acme__get_scopes"),
        _assistant(text="done"),
        _result(text="done"),
    )
    monkeypatch.setattr(model_mod.subprocess, "run", _fake_run(stdout))
    resp = ClaudeCliModel("m").complete([{"role": "user", "content": "hi"}])
    names = [t["name"] for t in resp.tool_uses]
    assert names == ["ToolSearch", "mcp__acme__get_scopes"]


def test_is_error_raises(monkeypatch):
    stdout = _stream(_result(text="quota exceeded", is_error=True))
    monkeypatch.setattr(model_mod.subprocess, "run", _fake_run(stdout))
    with pytest.raises(ModelError):
        ClaudeCliModel(max_retries=1).complete([{"role": "user", "content": "hi"}])


def test_no_result_event_raises(monkeypatch):
    stdout = _stream(_assistant(text="partial"))  # stream truncated before the result line
    monkeypatch.setattr(model_mod.subprocess, "run", _fake_run(stdout))
    with pytest.raises(ModelError):
        ClaudeCliModel(max_retries=1).complete([{"role": "user", "content": "hi"}])


def test_nonzero_exit_raises(monkeypatch):
    def run(cmd, input=None, capture_output=True, text=True, timeout=None, cwd=None):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
    monkeypatch.setattr(model_mod.subprocess, "run", run)
    with pytest.raises(ModelError):
        ClaudeCliModel(max_retries=1).complete([{"role": "user", "content": "hi"}])


def test_sterile_cwd_by_default(monkeypatch):
    # ADR-0009: with no explicit cwd the CLI runs from a fresh empty temp dir (not the repo root),
    # so it cannot auto-load CLAUDE.md. Inspect the dir DURING the call (it is cleaned up after).
    import os

    seen = {}

    def run(cmd, input=None, capture_output=True, text=True, timeout=None, cwd=None):
        seen["cwd"] = cwd
        seen["is_dir"] = cwd is not None and os.path.isdir(cwd)
        seen["empty"] = seen["is_dir"] and os.listdir(cwd) == []
        seen["is_repo_root"] = cwd == str(model_mod_repo_root())
        return subprocess.CompletedProcess(cmd, 0, stdout=_stream(_result()), stderr="")

    monkeypatch.setattr(model_mod.subprocess, "run", run)
    ClaudeCliModel("m").complete([{"role": "user", "content": "hi"}])
    assert seen["is_dir"] and seen["empty"]      # sterile: a real, empty working dir
    assert not seen["is_repo_root"]              # emphatically NOT the repo root


def model_mod_repo_root():
    from core.env import REPO_ROOT
    return REPO_ROOT


def test_explicit_cwd_is_honored(monkeypatch, tmp_path):
    # The control canary passes cwd=repo-root to prove CLAUDE.md loads there; honour it verbatim.
    fake = _fake_run(_stream(_result()))
    monkeypatch.setattr(model_mod.subprocess, "run", fake)
    ClaudeCliModel("m").complete([{"role": "user", "content": "hi"}], cwd=str(tmp_path))
    assert fake.cwd == str(tmp_path)


def test_deny_all_covers_monitor_and_workflow(monkeypatch):
    # The cycle-6 gap: Monitor (a Bash substitute) and other exec-capable built-ins were not denied.
    fake = _fake_run(_stream(_result()))
    monkeypatch.setattr(model_mod.subprocess, "run", fake)
    ClaudeCliModel("m").complete([{"role": "user", "content": "hi"}], policy=deny_all_policy())
    cmd = " ".join(fake.cmd)
    for tool in ("Monitor", "BashOutput", "Workflow", "Task", "Agent"):
        assert tool in cmd


def test_command_uses_stream_json_and_deny_all(monkeypatch):
    fake = _fake_run(_stream(_result()))
    monkeypatch.setattr(model_mod.subprocess, "run", fake)
    ClaudeCliModel("m").complete([{"role": "user", "content": "hi"}], policy=deny_all_policy())
    cmd = " ".join(fake.cmd)
    assert "--output-format stream-json" in cmd and "--verbose" in cmd
    assert "--disallowedTools" in cmd
    assert "WebFetch" in cmd and "ToolSearch" in cmd  # deny-all includes discovery tool
    assert "--mcp-config" not in cmd and "--allowedTools" not in cmd
    # strict-mcp with no config => the ambient project .mcp.json is ignored (no MCP tools leak in)
    assert "--strict-mcp-config" in cmd


def test_command_mcp_policy(monkeypatch):
    fake = _fake_run(_stream(_result()))
    monkeypatch.setattr(model_mod.subprocess, "run", fake)
    policy = CliPolicy(
        disallowed_tools=["Bash", "WebFetch"],
        allowed_tools=["mcp__acme__*", "ToolSearch"],
        mcp_config="/repo/.mcp.json", strict_mcp=True, permission_mode="bypassPermissions",
    )
    ClaudeCliModel("m").complete([{"role": "user", "content": "hi"}], policy=policy)
    cmd = fake.cmd
    joined = " ".join(cmd)
    assert "--allowedTools" in cmd and "mcp__acme__*,ToolSearch" in joined
    assert "--mcp-config" in cmd and "/repo/.mcp.json" in cmd
    assert "--strict-mcp-config" in cmd
    assert "bypassPermissions" in cmd
