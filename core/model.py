"""Model-under-test client: Anthropic API, Claude-CLI (subscription), and a MockModel.

Two live transports (ADR-0006):
  * `AnthropicModel` — the Anthropic Messages API (needs ANTHROPIC_API_KEY + the SDK).
  * `ClaudeCliModel` — the Claude Code CLI in headless mode (`claude -p`), authenticated
    by the operator's Claude subscription; no API key or SDK required.
Both return a `ModelResponse`; the scorer and runner are transport-agnostic. Retries use
simple exponential backoff. Secrets are never logged.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from contextlib import nullcontext
from dataclasses import dataclass, field


@dataclass
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    model_reported: str | None = None
    tool_uses: list[dict] = field(default_factory=list)   # [{name, input}] the model invoked
    transcript: list[dict] = field(default_factory=list)  # compact per-turn record (audit trail)
    available_tools: list[str] = field(default_factory=list)  # tools the CLI offered (init event)
    mcp_servers: list[dict] = field(default_factory=list)     # MCP server states (init event)


class ModelError(RuntimeError):
    """Raised when a model call ultimately fails (after retries)."""


# Built-in Claude Code tools to disallow so a condition is tool-free. This is the FULL set this CLI
# version exposes (2.1.204) — verified against the stream-json `init` event, which reports `tools: []`
# under this list (see ADR-0009). The cycle-6 list named only a dozen; a run could still reach for an
# un-denied tool like `Monitor` and use it as a Bash substitute to read files off disk. Denying every
# built-in up front closes that door; the per-run transcript assertion (conditions.check_tools) is the
# durable second net (this list is CLI-version-specific, the assertion is not). An unknown name here is
# a non-fatal "matches no known tool" WARNING, so we still keep the list to confirmed-valid names only
# (e.g. `MultiEdit` is omitted — it warns in 2.1.204). ToolSearch matters: Claude Code uses it to
# DISCOVER deferred MCP tools, so it is denied where MCP tools are unwanted (no-context / public-docs)
# and allowed in the mcp condition as plumbing.
CLI_BUILTIN_TOOLS = [
    "Bash", "BashOutput", "KillShell", "KillBash", "Edit", "Write", "Read", "Glob", "Grep",
    "NotebookEdit", "WebFetch", "WebSearch", "TodoWrite", "Task", "Agent", "Skill", "ExitPlanMode",
    "Monitor", "ListMcpResources", "ReadMcpResource", "ToolSearch", "Artifact", "CronCreate",
    "CronDelete", "CronList", "DesignSync", "EnterWorktree", "ExitWorktree", "PushNotification",
    "RemoteTrigger", "ReportFindings", "ScheduleWakeup", "SendMessage", "Workflow",
]
# Back-compat alias (older tests import this name).
CLI_DISALLOWED_TOOLS = CLI_BUILTIN_TOOLS


@dataclass
class CliPolicy:
    """Per-run Claude Code CLI tool policy — the load-bearing control between conditions (ADR-0008).

    The *only* thing that differs between no-context / public-docs / mcp is this policy: which tools
    exist for the run. A transcript assertion then proves, per run, that the model stayed within it.
    """
    disallowed_tools: list[str] = field(default_factory=lambda: list(CLI_BUILTIN_TOOLS))
    allowed_tools: list[str] | None = None
    mcp_config: str | None = None
    strict_mcp: bool = False
    permission_mode: str | None = None


def deny_all_policy() -> CliPolicy:
    """No tools of any kind — for no-context and public-docs. `strict_mcp` (with no mcp_config) makes
    the CLI IGNORE the ambient project `.mcp.json`, so any context-layer server is not loaded and its
    tools cannot leak into a tool-free condition."""
    return CliPolicy(disallowed_tools=list(CLI_BUILTIN_TOOLS), strict_mcp=True)


class AnthropicModel:
    """Calls the model under test through the Anthropic Messages API."""

    def __init__(self, api_key: str, model: str, *, temperature: float = 0.0,
                 max_tokens: int = 4096, max_retries: int = 4):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        try:
            import anthropic  # imported lazily; not needed for tests/--mock
        except ImportError as exc:  # pragma: no cover - exercised only on live path
            raise ModelError(
                "the 'anthropic' package is required for live runs; "
                "install it with: pip install -r requirements.txt"
            ) from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, messages: list[dict], system: str | None = None,
                 policy: "CliPolicy | None" = None) -> ModelResponse:
        anthropic = self._anthropic  # policy is CLI-only; the API path has no Claude Code tools
        transient = (
            getattr(anthropic, "APIStatusError", Exception),
            getattr(anthropic, "APIConnectionError", Exception),
            getattr(anthropic, "RateLimitError", Exception),
        )
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                kwargs = dict(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=messages,
                )
                if system:
                    kwargs["system"] = system
                resp = self._client.messages.create(**kwargs)
                text = "".join(
                    block.text for block in resp.content
                    if getattr(block, "type", None) == "text"
                )
                usage = getattr(resp, "usage", None)
                return ModelResponse(
                    text=text,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                )
            except transient as exc:  # pragma: no cover - live-path retry
                last_exc = exc
                if attempt == self.max_retries - 1:
                    break
                # exponential backoff: 1s, 2s, 4s, ...
                time.sleep(2 ** attempt)
        raise ModelError(f"model call failed after {self.max_retries} attempts: {last_exc}")


def _primary_model(payload: dict) -> str | None:
    """The CLI reports no top-level model; derive the primary answering model from
    `modelUsage` (the one with the most output tokens — auxiliary steps use a small
    helper model like haiku)."""
    usage_by_model = payload.get("modelUsage") or {}
    if not usage_by_model:
        return None
    return max(
        usage_by_model.items(),
        key=lambda kv: (kv[1] or {}).get("outputTokens", (kv[1] or {}).get("output_tokens", 0)) or 0,
    )[0]


def _parse_stream(stdout: str):
    """Parse `--output-format stream-json --verbose` NDJSON.

    Returns (final result object, tool_uses [{name,input}], compact transcript, model string,
    available_tools [str], mcp_servers [dict]). Assistant events carry `message.content[]`
    (tool_use/text/thinking blocks) and `message.model`; the `type:system subtype:init` line carries
    the tools ACTUALLY available to the model and the MCP server connection states (the sterile-canary
    and server-health gates key off these); the final `type:result` line carries the answer text,
    usage, cost, and duration.
    """
    tool_uses: list[dict] = []
    transcript: list[dict] = []
    model: str | None = None
    result: dict | None = None
    available_tools: list[str] = []
    mcp_servers: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = obj.get("type")
        if kind == "system" and obj.get("subtype") == "init":
            available_tools = list(obj.get("tools") or [])
            mcp_servers = list(obj.get("mcp_servers") or [])
        elif kind == "assistant":
            msg = obj.get("message", {}) or {}
            model = model or msg.get("model")
            turn = {"role": "assistant", "tool_uses": [], "text": ""}
            for block in msg.get("content", []) or []:
                bt = block.get("type")
                if bt == "tool_use":
                    tu = {"name": block.get("name"), "input": block.get("input")}
                    tool_uses.append(tu)
                    turn["tool_uses"].append(block.get("name"))
                elif bt == "text":
                    turn["text"] += block.get("text", "")
            transcript.append(turn)
        elif kind == "result":
            result = obj
    return result, tool_uses, transcript, model, available_tools, mcp_servers


def _messages_to_prompt(messages: list[dict]) -> str:
    """Flatten an Anthropic-style messages list to a single prompt string for the CLI."""
    parts = []
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):  # content blocks
                content = "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            parts.append(str(content))
    return "\n\n".join(parts)


class ClaudeCliModel:
    """Model-under-test via the Claude Code CLI (`claude -p`), using the Claude subscription.

    No API key or SDK required. Tools are disallowed so the completion is a pure single-shot
    answer with no external retrieval or filesystem access (ADR-0006). The CLI does not expose
    a temperature control, so runs use the model's default sampling.
    """

    def __init__(self, model: str | None = None, *, timeout: int = 300, max_retries: int = 3,
                 cli_path: str = "claude"):
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.cli_path = shutil.which(cli_path) or cli_path
        if not shutil.which(cli_path):
            raise ModelError(
                f"the Claude CLI ('{cli_path}') was not found on PATH; the subscription "
                "transport needs Claude Code installed."
            )

    def _build_cmd(self, system: str | None, policy: CliPolicy) -> list[str]:
        # stream-json + --verbose is what surfaces per-turn tool_use blocks for the audit assertion.
        cmd = [self.cli_path, "-p", "--output-format", "stream-json", "--verbose"]
        if self.model:
            cmd += ["--model", self.model]
        if policy.disallowed_tools:
            cmd += ["--disallowedTools", ",".join(policy.disallowed_tools)]
        if policy.allowed_tools:
            cmd += ["--allowedTools", ",".join(policy.allowed_tools)]
        if policy.mcp_config:
            cmd += ["--mcp-config", policy.mcp_config]
        if policy.strict_mcp:
            # With a config: use only it. Without one: load NO servers, ignoring the ambient
            # project .mcp.json (so a tool-free condition never sees any context-layer server).
            cmd += ["--strict-mcp-config"]
        if policy.permission_mode:
            cmd += ["--permission-mode", policy.permission_mode]
        if system:
            cmd += ["--system-prompt", system]
        return cmd

    def _invoke(self, prompt: str, system: str | None, policy: CliPolicy,
                cwd: str | None = None) -> ModelResponse:
        cmd = self._build_cmd(system, policy)
        # Sterile by default (ADR-0009): with no explicit cwd, run from a fresh empty temp dir so the
        # CLI cannot auto-load the repo's CLAUDE.md (or anything else on disk) as ambient context. An
        # explicit cwd (e.g. the repo root, used only by the control canary) is honoured as-is.
        work_ctx = tempfile.TemporaryDirectory(prefix="eval-sterile-") if cwd is None \
            else nullcontext(cwd)
        with work_ctx as work_dir:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                timeout=self.timeout, cwd=work_dir,
            )
        if proc.returncode != 0:
            raise ModelError(
                f"claude CLI exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}"
            )
        result, tool_uses, transcript, model, available_tools, mcp_servers = _parse_stream(proc.stdout)
        if result is None:
            raise ModelError("claude CLI stream produced no result event")
        if result.get("is_error"):
            raise ModelError(f"claude CLI reported an error: {str(result.get('result'))[:300]}")
        usage = result.get("usage") or {}
        return ModelResponse(
            text=result.get("result") or "",
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            cost_usd=float(result.get("total_cost_usd", 0.0) or 0.0),
            duration_ms=int(result.get("duration_ms", 0) or 0),
            model_reported=model or self.model,
            tool_uses=tool_uses,
            transcript=transcript,
            available_tools=available_tools,
            mcp_servers=mcp_servers,
        )

    def complete(self, messages: list[dict], system: str | None = None,
                 policy: CliPolicy | None = None, cwd: str | None = None) -> ModelResponse:
        prompt = _messages_to_prompt(messages)
        policy = policy or deny_all_policy()
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._invoke(prompt, system, policy, cwd=cwd)
                if not resp.text.strip():
                    raise ModelError("claude CLI returned an empty result")
                return resp
            except (ModelError, subprocess.TimeoutExpired) as exc:
                last_exc = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
        raise ModelError(f"claude CLI call failed after {self.max_retries} attempts: {last_exc}")

    def ping(self) -> ModelResponse:
        """Cheap health check: confirm the subscription transport answers before a full run."""
        return self._invoke("Reply with exactly the word: pong", None, deny_all_policy())


class MockModel:
    """Deterministic stand-in for tests and offline smoke runs.

    `responses` maps a task id to the canned response text. Unknown ids get
    `default`. No network, no key, no SDK.
    """

    def __init__(self, responses: dict[str, str] | None = None, default: str = ""):
        self.responses = responses or {}
        self.default = default
        self.model = "mock-model"
        self.calls: list[str] = []

    def complete_for_task(self, task_id: str) -> ModelResponse:
        self.calls.append(task_id)
        return ModelResponse(text=self.responses.get(task_id, self.default))
