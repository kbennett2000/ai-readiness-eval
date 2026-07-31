"""Conditions: what context the model gets besides the task prompt (ADR-0001).

A condition is pluggable behind a small interface and a name-keyed registry, so a pack adds
conditions without touching the runner or scorer. Shipped: `no-context` (the floor, task
prompt only), `public-docs` (the vendor's own docs injected), and the optional `mcp` context
layer. Everything vendor-specific arrives through a loaded `Pack`; this module hardcodes no
vendor string.
"""
from __future__ import annotations

import json
import tempfile
from abc import ABC, abstractmethod

from .docs_fetch import ROLE_PRIORITY
from .model import CliPolicy, deny_all_policy
from .pack import Pack
from .prompt import build_prompt

_CHARS_PER_TOKEN = 4  # keep in step with scorer/specsize token estimates

# The condition names this module knows how to build, in report order. Which ones a given pack
# actually exposes depends on whether it declares a context layer (see build_registry).
KNOWN_CONDITIONS = ("no-context", "public-docs", "mcp")


def _sterile_mcp_config(ctx) -> str:
    """Path to an MCP config that starts the context-layer server with an ABSOLUTE `--directory`.

    A committed project `.mcp.json` typically uses a *relative* `--directory`, which resolves only
    when the CLI is launched from the repo root. Sterile runs (ADR-0009 lineage) launch from an empty
    temp cwd, so that relative path would point nowhere and the server would silently FAIL to start — a
    dead server is indistinguishable from a model that chose not to consult. This writes an equivalent
    config from the pack's spawn command (assumed absolute) so the server starts from any cwd.
    """
    cfg = {"mcpServers": {ctx.mcp_server_key: {
        "type": "stdio",
        "command": ctx.spawn_command[0],
        "args": list(ctx.spawn_command[1:]),
    }}}
    fd, path = tempfile.mkstemp(prefix="mcp-abs-", suffix=".mcp.json")
    with open(fd, "w") as fh:
        json.dump(cfg, fh)
    return path


class Condition(ABC):
    """Builds the messages sent to the model for a given task, and its CLI tool policy."""

    name: str

    @abstractmethod
    def build_messages(self, task: dict) -> list[dict]:
        """Return an Anthropic-style messages list for this task."""
        raise NotImplementedError

    def system_prompt(self, task: dict) -> str | None:
        """Optional system prompt. None for conditions that need none."""
        return None

    def cli_policy(self) -> CliPolicy:
        """The Claude Code CLI tool policy for this condition (ADR-0008 lineage). Default: no tools."""
        return deny_all_policy()

    def check_tools(self, tool_uses: list[dict]) -> tuple[bool, str]:
        """Assert per-run tool discipline from the transcript. Default: zero tools allowed."""
        names = [t.get("name") for t in tool_uses]
        offenders = [n for n in names if n]
        if offenders:
            return False, f"used tools in a tool-free condition: {sorted(set(offenders))}"
        return True, "no tools used (as required)"


class NoContextCondition(Condition):
    """Floor reference: the model gets the task prompt (+ answer contract) and nothing else."""

    name = "no-context"

    def build_messages(self, task: dict) -> list[dict]:
        return [{"role": "user", "content": build_prompt(task["prompt"])}]


class PublicDocsCondition(Condition):
    """Inject the vendor's own documentation (cached snapshot) as context (ADR-0005 lineage).

    Loads the per-task pages from the pack's committed manifest + the gitignored cache, orders them
    by role priority, enforces the token budget (dropping lowest-priority pages first, then
    truncating the tail of the last kept page), and prepends the labelled context to the task.
    """

    name = "public-docs"

    def __init__(self, pack: Pack, manifest: dict | None = None):
        self._pack = pack
        self._manifest_override = manifest  # loaded lazily so construction is cheap
        self._label = pack.public_docs_source_label

    @property
    def _manifest(self) -> dict:
        if self._manifest_override is not None:
            return self._manifest_override
        return self._pack.docs_manifest()

    @property
    def _budget(self) -> int:
        return int(self._manifest.get("budget_tokens", self._pack.public_docs_budget_tokens))

    def _role_rank(self, role: str) -> int:
        return ROLE_PRIORITY.index(role) if role in ROLE_PRIORITY else len(ROLE_PRIORITY)

    def _pages_for(self, task_id: str) -> list[dict]:
        entry = (self._manifest.get("tasks") or {}).get(task_id)
        if not entry:
            raise KeyError(f"public-docs manifest has no entry for task '{task_id}'")
        return sorted(entry.get("pages", []), key=lambda p: self._role_rank(p.get("role", "")))

    def _load_text(self, task_id: str, page: dict) -> str:
        # ADR-0036, and it is checked HERE rather than only at fetch time on purpose. Refusing to
        # retrieve a Disallowed page leaves any snapshot an earlier fetch already took sitting in the
        # cache, and a host that adds a Disallow after we fetched would otherwise keep being injected
        # from disk forever. Permission is a present-tense fact, so it is read at the point of use.
        if page.get("robots_disallowed"):
            return ""
        path = self._pack.cache_path_for(task_id, page["url"])
        if not path.exists():
            # Fidelity to the machine reader (ADR-0005): public-docs models what a fetch actually
            # RETRIEVES. A page the manifest records as unfetchable — a developer portal that does
            # not resolve, an SPA that returned nothing — injects nothing, exactly as a real pipeline
            # would get nothing; it is not an error. A page that CLAIMS content (byte_size > 0 and no
            # fetch_error) but has no cached snapshot is a genuine "forgot to run fetch-docs" and
            # still raises, so a real fetch is never silently skipped.
            if page.get("fetch_error") or page.get("byte_size") == 0:
                return ""
            raise FileNotFoundError(
                f"no cached doc for {task_id} <- {page['url']}. Run "
                "`python -m core fetch-docs` first."
            )
        return path.read_text()

    def build_context(self, task_id: str) -> str:
        """Assemble the labelled, budget-limited docs context block for a task."""
        budget_chars = self._budget * _CHARS_PER_TOKEN
        used = 0
        blocks: list[str] = []
        for page in self._pages_for(task_id):
            text = self._load_text(task_id, page).strip()
            if not text:
                continue
            header = f"\n===== {self._label}: {page['url']} =====\n"
            remaining = budget_chars - used - len(header)
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[:remaining].rstrip() + "\n[... truncated to fit context budget ...]"
            blocks.append(header + text)
            used += len(header) + len(text)
        joined = "\n".join(blocks)
        return (
            f"You have been given excerpts from {self._label} below. "
            "Use them to answer accurately.\n" + joined
        )

    def full_text(self, task_id: str) -> str:
        """Every cached page for a task, concatenated, with NO budget applied.

        The unbudgeted counterpart to `build_context`, and it exists only so the two can be compared.
        See `audit_docs_truncation`.
        """
        return "\n".join(self._load_text(task_id, page) for page in self._pages_for(task_id))

    def build_messages(self, task: dict) -> list[dict]:
        context = self.build_context(task["id"])
        content = context + "\n\n" + build_prompt(task["prompt"])
        return [{"role": "user", "content": content}]


class McpCondition(Condition):
    """The fix: the model gets the task prompt (same as no-context) plus the pack's context-layer
    MCP tools — and nothing else (ADR-0007/0008 lineage).

    Deliberately no injected docs and no "use the tools" nudge: the tools are advertised by the CLI
    exactly as they are for a developer who has the server installed, and the model decides whether
    to consult them. If it under-uses them, that is a first-class finding, not something we engineer
    away. The tool policy allows only the pack's tool prefix (+ the discovery meta-tool); everything
    else is denied and asserted against per run.
    """

    name = "mcp"

    def __init__(self, pack: Pack, mcp_config: str | None = None):
        ctx = pack.context_layer
        if ctx is None:
            raise ValueError(
                f"pack '{pack.vendor_id}' has no context_layer; the 'mcp' condition is unavailable "
                "(this pack runs in two-condition mode)."
            )
        self._ctx = ctx
        self._prefix = ctx.mcp_tool_prefix
        self._discovery = ctx.discovery_tool
        # Default to the absolute-directory config so the server starts under a sterile temp cwd.
        self._mcp_config = mcp_config or _sterile_mcp_config(ctx)

    def build_messages(self, task: dict) -> list[dict]:
        return [{"role": "user", "content": build_prompt(task["prompt"])}]

    def cli_policy(self) -> CliPolicy:
        # Deny every built-in tool EXCEPT the discovery meta-tool (needed to surface the deferred MCP
        # tools); allow the context-layer tools; strict-mcp so no other MCP server can leak in; bypass
        # the first-use trust prompt that would otherwise silently drop the server in headless mode.
        from .model import CLI_BUILTIN_TOOLS
        disallowed = [t for t in CLI_BUILTIN_TOOLS if t != self._discovery]
        return CliPolicy(
            disallowed_tools=disallowed,
            allowed_tools=[f"{self._prefix}*", self._discovery],
            mcp_config=self._mcp_config,
            strict_mcp=True,
            permission_mode="bypassPermissions",
        )

    def check_tools(self, tool_uses: list[dict]) -> tuple[bool, str]:
        names = [t.get("name") for t in tool_uses if t.get("name")]
        bad = [n for n in names if not (n.startswith(self._prefix) or n == self._discovery)]
        if bad:
            return False, f"used tools outside the context layer: {sorted(set(bad))}"
        layer_calls = [n for n in names if n.startswith(self._prefix)]
        # zero context-layer calls is allowed (the model chose not to consult the server — a finding),
        # but note it so the report can surface how often that happened.
        note = (f"only context-layer tools ({len(layer_calls)} call(s))"
                if layer_calls else "no context-layer tools used (model answered from memory)")
        return True, note


def build_registry(pack: Pack) -> dict[str, Condition]:
    """Build the condition registry for a pack. A pack with no context layer omits `mcp`
    (two-condition mode)."""
    registry: dict[str, Condition] = {
        "no-context": NoContextCondition(),
        "public-docs": PublicDocsCondition(pack),
    }
    if pack.context_layer is not None:
        registry["mcp"] = McpCondition(pack)
    return registry


def get_condition(name: str, pack: Pack) -> Condition:
    registry = build_registry(pack)
    if name not in registry:
        available = ", ".join(sorted(registry)) or "(none)"
        raise KeyError(f"unknown condition '{name}'; available for this pack: {available}")
    return registry[name]


def available_conditions() -> list[str]:
    """The condition names core can build (help text); a pack may expose a subset."""
    return list(KNOWN_CONDITIONS)


# --------------------------------------------------------------------------------------------- #
# Truncation audit — the docs condition must not measure our own budget
# --------------------------------------------------------------------------------------------- #

def _path_spellings(path: str, base_prefixes) -> list[str]:
    """The literal forms a documentation page might use for one ground-truth path.

    Only the base-prefix pairs, because that is the one rewriting a vendor is entitled to do and this
    project already models it (ADR-0013/0017): a spec may write the whole address while a guide writes
    the fragment after the base URL. No normalization beyond that, deliberately — see the docstring of
    `audit_docs_truncation` for why an approximate matcher is safe here and a clever one would not be.

    A pack may declare more than one prefix (ADR-0039); each contributes its own pair. Accepts a bare
    string for the single-prefix packs that predate that widening.
    """
    if isinstance(base_prefixes, str):
        base_prefixes = [base_prefixes]
    out = [path]
    for base_prefix in base_prefixes or []:
        pre = "/" + base_prefix.strip("/")
        if path.startswith(pre):
            out.append(path[len(pre):] or "/")
        else:
            out.append(pre.rstrip("/") + path)
    return [s for s in dict.fromkeys(out) if s]


def audit_docs_truncation(pack: Pack) -> list[dict]:
    """Where did the token budget delete an answer the cached page actually contained?

    `public-docs` drops low-priority pages and then truncates the tail of the last one it keeps. When
    the page it crops is the page carrying the operation a task asks about, the resulting number is a
    measurement of OUR budget rather than of the vendor's documentation — the same class of instrument
    fault as ADR-0013, where a dimension read 13.7% while the model was right 98% of the time. Nothing
    downstream can tell the two apart: a truncated-away endpoint and an undocumented endpoint produce
    the identical transcript.

    What this deliberately does NOT do is require the docs to contain the answer. A vendor whose
    documentation omits an endpoint is a finding this method exists to report, and turning that into a
    gate failure would quietly forbid the very result the cohort most wants to publish. So the check is
    strictly RELATIVE — present in the full cached text, absent from the injected text — and a path
    absent from both is reported as `documented: False` and is nobody's fault.

    Because it is relative, the matcher does not have to be clever, and that is the point: both sides
    are the same bytes from the same page, so any consistent substring test answers the only question
    asked. A normalizing matcher would be strictly worse — it could differ between the two sides and
    manufacture a loss, and a false truncation report would send a cycle hunting a budget bug that does
    not exist.

    Returns one record per (task, endpoint). A caller treats `truncated: True` as the defect.
    """
    condition = PublicDocsCondition(pack)
    prefix = getattr(pack, "declared_base_prefixes", None) or \
        getattr(pack, "endpoint_base_prefix", None)
    records: list[dict] = []
    for task in pack.load_tasks():
        task_id = task["id"]
        try:
            full = condition.full_text(task_id)
            injected = condition.build_context(task_id)
        except (KeyError, FileNotFoundError) as exc:
            records.append({"task_id": task_id, "path": None, "documented": False,
                            "injected": False, "truncated": False, "error": str(exc)})
            continue
        for ep in task["ground_truth"]["endpoints"]:
            path = ep.get("path")
            if not path:
                continue
            spellings = _path_spellings(path, prefix)
            in_full = any(s in full for s in spellings)
            in_injected = any(s in injected for s in spellings)
            records.append({
                "task_id": task_id, "path": path,
                "documented": in_full, "injected": in_injected,
                "truncated": bool(in_full and not in_injected),
            })
    return records


def truncation_losses(pack: Pack) -> list[dict]:
    """Just the defects from `audit_docs_truncation` — paths the budget deleted."""
    return [r for r in audit_docs_truncation(pack) if r.get("truncated")]
