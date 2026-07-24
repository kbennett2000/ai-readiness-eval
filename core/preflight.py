"""Pre-flight gates for a sterile grid run (ADR-0009 lineage).

Two hard gates the runner must pass before burning the grid:

  * **Canaries** — prove the sterile fix works *and* that the contamination was real. A tool-free run
    from a sterile temp cwd must NOT be able to name the project (ignorant); the same run from the repo
    root MUST recite it (recites — because Claude Code auto-loads the repo CLAUDE.md there). If the
    sterile canary can still name the project, the fix is not working and the grid must not start.

  * **Server health** — prove the pack's context-layer server actually connects and lists its expected
    tools. A silently-failed server (e.g. a bad path) is indistinguishable from a model that chose not
    to consult, so we verify the real spawn path before attributing any skip to the model.

Both gates are cheap relative to the grid. The vendor-specific inputs (the project marker, the expected
tool set, the spawn command, the repo root) are passed in by the caller from the loaded pack; this
module holds no vendor string.
"""
from __future__ import annotations

import json
import subprocess

from .model import deny_all_policy

CANARY_PROMPT = (
    "What software project are you currently working in? Name the repository, describe its purpose, "
    "and say which development cycle it is on. If you do not have that information in your context, "
    "say so plainly."
)


def run_canaries(model, *, project_marker: str, repo_root) -> dict:
    """Run the sterile + repo-root control canaries and return a verdict dict.

    `model` is a `ClaudeCliModel`. The sterile canary uses the default (temp) cwd; the control passes
    `cwd=repo_root` so Claude Code loads the repo CLAUDE.md. `project_marker` is a string unique to this
    repo's CLAUDE.md that the model cannot know without ambient project context.
    """
    msg = [{"role": "user", "content": CANARY_PROMPT}]
    sterile = model.complete(msg, policy=deny_all_policy())
    control = model.complete(msg, policy=deny_all_policy(), cwd=str(repo_root))

    marker = project_marker.lower()
    sterile_names = marker in sterile.text.lower()
    control_names = marker in control.text.lower()
    # Sterile PASS: cannot name the project AND was offered no tools at all.
    sterile_ignorant = (not sterile_names) and (not sterile.available_tools)
    control_recites = control_names

    return {
        "marker": project_marker,
        "prompt": CANARY_PROMPT,
        "sterile": {
            "ignorant": bool(sterile_ignorant),
            "mentions_marker": bool(sterile_names),
            "available_tools": sterile.available_tools,
            "answer": sterile.text,
            "transcript": sterile.transcript,
        },
        "control": {
            "recites": bool(control_recites),
            "mentions_marker": bool(control_names),
            "available_tools": control.available_tools,
            "answer": control.text,
            "transcript": control.transcript,
        },
        "passed": bool(sterile_ignorant and control_recites),
    }


def write_canary_artifacts(verdict: dict, out_dir) -> None:
    """Persist both canary transcripts + the verdict JSON for committing with the results."""
    from pathlib import Path

    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "verdict.json").write_text(json.dumps(verdict, indent=2))
    (d / "sterile-canary.txt").write_text(
        f"# STERILE canary (empty cwd) — expected: cannot name the project\n"
        f"# available_tools at init: {verdict['sterile']['available_tools']}\n"
        f"# ignorant (PASS): {verdict['sterile']['ignorant']}\n\n"
        f"{verdict['sterile']['answer']}\n"
    )
    (d / "control-canary.txt").write_text(
        f"# CONTROL canary (repo-root cwd) — expected: recites CLAUDE.md\n"
        f"# recites (PASS): {verdict['control']['recites']}\n\n"
        f"{verdict['control']['answer']}\n"
    )


def _tools_list_once(spawn_command: list[str], timeout: int) -> tuple[list[str], str]:
    """One initialize+tools/list handshake against a freshly-spawned server. Returns (tools, stderr).

    Sends the three messages up front and reads the `tools/list` (id=2) response from stdout. The
    server exits on stdin EOF, so subprocess.run captures the full stream."""
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "preflight", "version": "0"}}}
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    stdin = "".join(json.dumps(m) + "\n" for m in (init, initialized, list_req))
    proc = subprocess.run(list(spawn_command), input=stdin, capture_output=True, text=True,
                          timeout=timeout)
    tools: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("id") == 2 and isinstance(obj.get("result"), dict):
            tools = [t.get("name") for t in obj["result"].get("tools", []) if t.get("name")]
    return tools, (proc.stderr or "").strip()


def check_server_health(spawn_command: list[str], expected_tools, *,
                        timeout: int = 90, attempts: int = 3) -> dict:
    """Spawn the context-layer server via its (absolute-dir) command and JSON-RPC `tools/list` it.

    Returns {"ok": bool, "tools": [...], "detail": str}. Exercises the same spawn the mcp condition
    uses, so a broken spawn is caught here rather than silently producing a grid of zero-consultation
    runs. Retries a few times: a fresh stdio spawn occasionally races on the first handshake, but a
    genuinely broken server fails every attempt."""
    expected = set(expected_tools)
    last_tools: list[str] = []
    last_err = ""
    for _ in range(attempts):
        try:
            tools, err = _tools_list_once(spawn_command, timeout)
        except (subprocess.TimeoutExpired, OSError) as exc:
            last_err = f"server spawn failed: {exc}"
            continue
        last_tools, last_err = tools, err
        if not (expected - set(tools)):
            return {"ok": True, "tools": sorted(tools), "detail": "all expected tools listed"}
    missing = expected - set(last_tools)
    return {"ok": False, "tools": sorted(last_tools),
            "detail": (f"server did not list expected tools after {attempts} attempts "
                       f"(missing {sorted(missing)}); got {sorted(last_tools)}; "
                       f"stderr={last_err[:200]}")}
