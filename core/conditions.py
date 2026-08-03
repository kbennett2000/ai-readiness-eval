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

from .contract import contract_for
from .docs_fetch import ANCHOR_KEY, GATED_KEY, INJECTED_KEY, ROLE_PRIORITY, SPEC_KEY
from .model import CliPolicy, deny_all_policy
from .pack import Pack

_CHARS_PER_TOKEN = 4  # keep in step with scorer/specsize token estimates

# The condition names this module knows how to build, in report order. Which ones a given pack
# actually exposes depends on whether it declares a context layer (see build_registry).
KNOWN_CONDITIONS = ("no-context", "public-docs", "gated-docs", "raw-spec", "mcp")


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
    """Floor reference: the model gets the task prompt (+ answer contract) and nothing else.

    Takes a pack so it can ask which answer contract to append (ADR-0044). The argument is optional
    and defaults to the API contract, so every existing caller — and every test that builds this
    condition with no arguments — is unchanged.
    """

    name = "no-context"

    def __init__(self, pack: Pack | None = None):
        from .contract import API_CONTRACT
        self._contract = contract_for(pack) if pack is not None else API_CONTRACT

    def build_messages(self, task: dict) -> list[dict]:
        return [{"role": "user", "content": self._contract.build_prompt(task["prompt"])}]


class _InjectedTextCondition(Condition):
    """Shared machinery for every condition that injects cached first-party text under a budget.

    Three conditions do that — `public-docs`, `raw-spec` (ADR-0050) and `gated-docs` (ADR-0051) — and
    they differ in exactly three things: which manifest list they read, what they label the block, and
    which budget applies.
    Everything else (the robots re-check at point of use, the missing-cache ruling, the drop-then-
    truncate assembly, the unbudgeted `full_text` the truncation audit compares against) is one
    behaviour and is written once.

    **`manifest_key` is the whole safety property.** ADR-0034 made "show the model the answer key's
    own source" unrepresentable for `public-docs` by putting anchors in a separate list rather than
    behind a `pages[].inject: false` flag. Subclassing preserves that: each subclass names exactly
    one key as a class attribute, so the list a condition can reach is fixed at class-definition
    time and cannot be widened by a manifest, a role string, or a config value.
    """

    #: The manifest task-entry list this condition injects. Exactly one, per class.
    manifest_key: str

    def __init__(self, pack: Pack, manifest: dict | None = None):
        self._pack = pack
        self._manifest_override = manifest  # loaded lazily so construction is cheap
        self._label = self._label_for(pack)
        self._contract = contract_for(pack)

    def _label_for(self, pack: Pack) -> str:
        raise NotImplementedError

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
            raise KeyError(f"{self.name} manifest has no entry for task '{task_id}'")
        return sorted(entry.get(self.manifest_key, []) or [],
                      key=lambda p: self._role_rank(p.get("role", "")))

    def _load_text(self, task_id: str, page: dict) -> str:
        # ADR-0036, and it is checked HERE rather than only at fetch time on purpose. Refusing to
        # retrieve a Disallowed page leaves any snapshot an earlier fetch already took sitting in the
        # cache, and a host that adds a Disallow after we fetched would otherwise keep being injected
        # from disk forever. Permission is a present-tense fact, so it is read at the point of use.
        if page.get("robots_disallowed"):
            return ""
        # The MANIFEST decides whether this page has text, not the filesystem (ADR-0054). A page
        # that failed to fetch injects nothing, and asking the disk first is what let a refused
        # `pages` entry read a file some OTHER list had written for the same URL. Ordering, not
        # paths, is what makes that impossible: with the check here, no failed retrieval can read
        # any file, however the cache is laid out.
        if page.get("fetch_error") or page.get("byte_size") == 0:
            return ""
        path = self._pack.cache_path_for(task_id, page["url"], manifest_key=self.manifest_key)
        if not path.exists():
            # Fidelity to the machine reader (ADR-0005): public-docs models what a fetch actually
            # RETRIEVES. A page the manifest records as unfetchable — a developer portal that does
            # not resolve, an SPA that returned nothing — injects nothing, exactly as a real pipeline
            # would get nothing; it is not an error — and that branch has moved ABOVE, so it is
            # decided before any path is touched. What is left here is the genuine "forgot to run
            # fetch-docs": a page that CLAIMS content and has no cached snapshot still raises, so a
            # real fetch is never silently skipped.
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
        # The preamble is the CONTRACT's, not this module's (ADR-0044). The API cohort's sentence is
        # emitted verbatim and unchanged — altering it would change what every archived API run was
        # asked, which is why public #67's repair belongs to a deliberate re-baseline and not here.
        # The docs cohort's is empty: that cohort is built without the excerpt promise from day one,
        # so it never tells a model it has been handed documentation that was not retrieved.
        return self._contract.context_preamble(self._label) + joined

    def full_text(self, task_id: str) -> str:
        """Every cached page for a task, concatenated, with NO budget applied.

        The unbudgeted counterpart to `build_context`, and it exists only so the two can be compared.
        See `audit_docs_truncation`.
        """
        return "\n".join(self._load_text(task_id, page) for page in self._pages_for(task_id))

    def build_messages(self, task: dict) -> list[dict]:
        context = self.build_context(task["id"])
        content = context + "\n\n" + self._contract.build_prompt(task["prompt"])
        return [{"role": "user", "content": content}]


class PublicDocsCondition(_InjectedTextCondition):
    """Inject the vendor's own documentation (cached snapshot) as context (ADR-0005 lineage).

    Loads the per-task pages from the pack's committed manifest + the gitignored cache, orders them
    by role priority, enforces the token budget (dropping lowest-priority pages first, then
    truncating the tail of the last kept page), and prepends the labelled context to the task.

    Reads `pages` and ONLY `pages`. Not `anchors` (ADR-0034), not `spec_documents` (ADR-0050).
    """

    name = "public-docs"
    manifest_key = INJECTED_KEY

    def _label_for(self, pack: Pack) -> str:
        return pack.public_docs_source_label


class RawSpecCondition(_InjectedTextCondition):
    """Inject the vendor's OWN machine-readable specification, uncurated (ADR-0050).

    The question this exists to answer is the one the MCP posture sweep deferred and issue #54
    filed: does handing a model the vendor's own specification close the gap its prose documentation
    leaves, or is there a residue that only a curated layer closes? The reference pack's curated
    context layer is worth +25 points over its documentation; nothing has ever measured what the
    RAW artifact is worth, which is why `public-docs` must not quietly become it.

    Two rules make the answer readable rather than flattering:

    **The budget is `public-docs`'s, unchanged.** It reads `public_docs_budget_tokens` through the
    inherited `_budget` deliberately. Give this column more room than the one beside it and the
    comparison measures how generous we were feeling, not the difference between an artifact and a
    page. Specification documents are large, so truncation is expected and often decisive — the
    truncation audit reports what did not fit, and that report is part of the finding rather than a
    defect to engineer away.

    **Document-level selection is retrieval; operation-level selection is curation.** A pack may say
    which spec document a task is shown — the same choice `public-docs` already makes about pages —
    and may NOT slice inside one to the operation a task asks about. Slicing is what the curated
    layer does, and a condition that did both would answer neither question. Nothing here can slice:
    this class only ever reads whole cached documents, exactly as `public-docs` reads whole pages.
    """

    name = "raw-spec"
    manifest_key = SPEC_KEY

    def _label_for(self, pack: Pack) -> str:
        if pack.raw_spec is None:
            raise ValueError(
                f"pack '{pack.vendor_id}' has no raw_spec block; the 'raw-spec' condition is "
                "unavailable for it. A pack declares the condition or does not have it — there is "
                "no default label, because a block headed with a guessed name would put a "
                "specification in front of a model under a heading that says 'documentation'.")
        return pack.raw_spec.source_label


class GatedDocsCondition(_InjectedTextCondition):
    """Inject the vendor's own documentation as served to a conventional self-identifying agent
    (ADR-0051).

    It exists for one shape of host: a docs server that decides what to return from the User-Agent
    string. `public-docs` asks with this project's plain agent and injects whatever arrives — on such
    a host, nothing, because what arrives is a refusal. This condition asks the SAME URLs with the
    agent declared in `pack.gated_docs.user_agent` and injects what arrives instead.

    **What the pair measures is the filter, not the documentation.** Every other input is held
    constant on purpose: the same URLs, the same budget, the same prompt, the same tasks. The only
    variable is the string this project puts in one header, so the difference between the two columns
    is the price of that string and nothing else. That is why the budget is inherited rather than
    configurable — ADR-0050's argument, sharper here, because these two columns share their corpus.

    **The declared agent names this project.** `pack.py` refuses a browser string outright, so this
    class can state the property rather than check it: whatever `gated_pages` holds was retrieved by
    a reader that said who it was. A column obtained by claiming to be a browser would measure what
    a vendor shows a reader it was deceived about, which is not a fact about AI readiness.

    Reads `gated_pages` and ONLY `gated_pages` — not `pages`, not `anchors` (ADR-0034), not
    `spec_documents` (ADR-0050). The separate key matters more here than anywhere: this is the only
    pair of lists that holds the SAME URLs, so a shared list with a per-page flag would make it one
    typo's work to inject the document into the column whose finding is that the document did not
    arrive.
    """

    name = "gated-docs"
    manifest_key = GATED_KEY

    def _label_for(self, pack: Pack) -> str:
        if pack.gated_docs is None:
            raise ValueError(
                f"pack '{pack.vendor_id}' has no gated_docs block; the 'gated-docs' condition is "
                "unavailable for it. A pack declares the condition or does not have it — there is "
                "no default label and no default agent, because the agent a column was retrieved "
                "with is the finding that column exists to report.")
        return pack.gated_docs.source_label


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
        self._contract = contract_for(pack)
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
        return [{"role": "user", "content": self._contract.build_prompt(task["prompt"])}]

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
    """Build the condition registry for a pack.

    Three of the five conditions are optional and each is gated on the pack DECLARING it: `mcp` on
    `context_layer`, `raw-spec` on `raw_spec` (ADR-0050), `gated-docs` on `gated_docs` (ADR-0051).
    Never on the manifest happening to carry a list — a manifest that grew a `gated_pages` entry by
    accident would otherwise add a column to a cohort table, and a column is a claim.
    """
    registry: dict[str, Condition] = {
        "no-context": NoContextCondition(pack),
        "public-docs": PublicDocsCondition(pack),
    }
    if pack.gated_docs is not None:
        registry["gated-docs"] = GatedDocsCondition(pack)
    if pack.raw_spec is not None:
        registry["raw-spec"] = RawSpecCondition(pack)
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

def audit_docs_truncation(pack: Pack, condition: "_InjectedTextCondition | None" = None) -> list[dict]:
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

    WHAT "THE ANSWER" IS depends on the cohort, so the search terms come from the pack's answer
    contract rather than from this module (ADR-0044). For the API cohort an item is a ground-truth
    endpoint path and its base-prefix spellings; for the docs cohort it is a ground-truth VALUE — a
    catalog number, a firmware revision — because on that surface the value IS the answer. The
    question asked of both is identical: is the thing we are about to score against still inside the
    text we injected?

    Returns one record per (task, item). A caller treats `truncated: True` as the defect.

    `condition` defaults to `public-docs` and may be any injecting condition (ADR-0050). The audit
    was always written against `full_text` + `build_context` and the contract's ground-truth terms,
    and never against anything specific to documentation — so covering a second injecting condition
    is a parameter, not a second implementation. The alternative was a copy of this function per
    condition, which is how the two would drift and how one of them would quietly stop being run.
    """
    condition = condition if condition is not None else PublicDocsCondition(pack)
    contract = contract_for(pack)
    records: list[dict] = []
    name = condition.name
    for task in pack.load_tasks():
        task_id = task["id"]
        try:
            full = condition.full_text(task_id)
            injected = condition.build_context(task_id)
        except (KeyError, FileNotFoundError) as exc:
            records.append({"task_id": task_id, "item": None, "documented": False,
                            "injected": False, "truncated": False, "error": str(exc),
                            "condition": name})
            continue
        for item, spellings in contract.ground_truth_terms(task, pack):
            if not spellings:
                continue
            in_full = any(s in full for s in spellings)
            in_injected = any(s in injected for s in spellings)
            records.append({
                "task_id": task_id, "item": item,
                # Which condition this verdict is about (ADR-0050). Two injecting conditions now
                # produce records of the same shape, and a report that merged them without this
                # field would read as one audit of one corpus.
                "condition": name,
                # What was injected against what existed, so a pack can DECLARE what did not fit
                # rather than describe it. For a specification these two routinely differ by an
                # order of magnitude, and the difference is the finding, not a defect.
                "injected_len": len(injected),
                "documented": in_full, "injected": in_injected,
                "truncated": bool(in_full and not in_injected),
                # How much cached text this verdict was reached against, and whether that verdict
                # could have gone the other way. `documented: False` against a page that was read
                # is a finding; against 0 bytes it is arithmetic, and a caller that cannot tell
                # them apart reads "nothing found" as "the matcher is broken" (ADR-0043).
                #
                # `searchable` is the honest form of that question and takes no magic number: if
                # the cached text is shorter than the shortest spelling being looked for, a miss
                # is forced and carries no information. Three ways to get there, only one of which
                # raises — a missing cache file (recorded as `error` above), a pack whose every
                # manifest page failed to fetch (empty string, no exception, and a PUBLISHED
                # finding rather than a fault), and a docs host that serves a JavaScript shell
                # whose extracted text is a single byte. The third is why a bytes-read test that
                # merely checked for non-zero was still wrong.
                "full_len": len(full),
                "searchable": len(full) >= min(len(s) for s in spellings),
            })
    return records


def truncation_losses(pack: Pack, condition: "_InjectedTextCondition | None" = None) -> list[dict]:
    """Just the defects from `audit_docs_truncation` — the items the budget deleted."""
    return [r for r in audit_docs_truncation(pack, condition) if r.get("truncated")]


def audit_spec_truncation(pack: Pack) -> list[dict]:
    """The same audit, run against `raw-spec` (ADR-0050). Empty for a pack that does not declare it.

    Separate from the `public-docs` call rather than folded into it, because the two answer different
    questions about different corpora and a caller must be able to report them apart. A pack whose
    documentation is a JavaScript shell and whose specification is complete will show `documented:
    False` everywhere in one and `truncated: True` in the other, and averaging those would describe
    neither.
    """
    if pack.raw_spec is None:
        return []
    return audit_docs_truncation(pack, RawSpecCondition(pack))


def _overlap_disclosure(pack: Pack, *, condition_name: str, inject_key: str,
                        declarations: dict) -> list[dict]:
    """Per task: does an injecting condition show the model the very document its answer key cites?

    One implementation for both optional injecting conditions (ADR-0050's `raw-spec`, ADR-0051's
    `gated-docs`), because the question and the ruling are identical and only the manifest key
    differs. Two copies would drift, and the way they would drift is that one of them quietly stops
    being run.
    """
    manifest = pack.docs_manifest()
    out: list[dict] = []
    for task in pack.load_tasks():
        entry = (manifest.get("tasks") or {}).get(task["id"]) or {}
        injected = {p["url"] for p in (entry.get(inject_key) or []) if p.get("url")}
        anchors = {p["url"] for p in (entry.get(ANCHOR_KEY) or []) if p.get("url")}
        shared = sorted(injected & anchors)
        out.append({
            "task_id": task["id"],
            "condition": condition_name,
            "injected_documents": sorted(injected),
            "overlapping_anchors": shared,
            "scored_against_own_source": bool(shared),
            "declared_reason": (declarations or {}).get(task["id"]),
        })
    return out


def spec_disclosure(pack: Pack) -> list[dict]:
    """Per task: does `raw-spec` inject the very document the answer key is cited to (ADR-0050)?

    This is the sharp one, and issue #54 named it before this condition existed: where a task's
    `spec_documents` and its `anchors` are the same URL, the condition is **scored against its own
    source**. Its number is then a CEILING — can the model read what it was handed — and not a
    measurement of what a model knows about the vendor.

    That is not a defect to be prevented. For a vendor whose only citable first-party artifact IS
    its specification, refusing the overlap would mean either anchoring ground truth to something
    weaker or not running the condition at all. What is refused is the overlap going UNSAID: the
    verdict is computed from the manifest rather than remembered, so a card cannot omit it and a
    reviewer cannot be left to infer it from two lists that happen to match.

    Returns one record per task. `check_spec_disclosure` turns them into a gate.

    Records also carry `spec_documents`, the pre-ADR-0051 spelling of `injected_documents`, so a
    caller written against the original shape keeps working.
    """
    if pack.raw_spec is None:
        return []
    records = _overlap_disclosure(pack, condition_name="raw-spec", inject_key=SPEC_KEY,
                                  declarations=pack.raw_spec.scored_against_own_source)
    for r in records:
        r["spec_documents"] = r["injected_documents"]
    return records


def gated_disclosure(pack: Pack) -> list[dict]:
    """The same question, asked of `gated-docs` (ADR-0051). Empty for a pack that does not declare it.

    It bites harder here than it does for a specification, and the reason is worth stating where the
    code is. On a user-agent-filtering host, `gated_pages` and `anchors` are drawn from the SAME
    corpus — often the same URLs — because the pages the filter withholds are also the only
    first-party artifact a ground-truth citation can point at. So the overlap is the expected case
    rather than the exception, and a pack that reports a large `gated-docs` number without saying so
    would be publishing a ceiling as a readiness measurement.
    """
    if pack.gated_docs is None:
        return []
    return _overlap_disclosure(pack, condition_name="gated-docs", inject_key=GATED_KEY,
                               declarations=pack.gated_docs.scored_against_own_source)


def _check_disclosure_records(records: list[dict], *, condition_name: str, config_path: str
                              ) -> tuple[bool, str]:
    """Gate: every task scored against its own source has to say so, in writing.

    A written reason and not a boolean, for the same argument ADR-0045 made about an unexercised
    dimension and ADR-0031 made about a waiver flag: a flag records that someone clicked past the
    question, and a sentence records what they thought — which is the thing a reviewer can disagree
    with. `True` would be satisfiable by a pack that never considered it.
    """
    missing = [r["task_id"] for r in records
               if r["scored_against_own_source"] and not (r["declared_reason"] or "").strip()]
    if missing:
        return False, (
            f"{len(missing)} task(s) inject a document that is also their ground-truth anchor, so "
            f"`{condition_name}` is scored against its own source, and the pack does not say so: "
            f"{', '.join(missing)}. Declare {config_path}.<task_id> with the reason a reviewer "
            f"would need to read this column as a ceiling rather than a measurement.")
    stale = [r["task_id"] for r in records
             if not r["scored_against_own_source"] and (r["declared_reason"] or "").strip()]
    if stale:
        return False, (
            f"{len(stale)} task(s) declare {config_path} but their injected documents and anchors "
            f"do not overlap: {', '.join(stale)}. A disclosure that is not true is worse than none "
            f"— it teaches a reader to discount the ones that are.")
    n = sum(1 for r in records if r["scored_against_own_source"])
    return True, (f"{n}/{len(records)} task(s) are scored against their own source under "
                  f"`{condition_name}`, each with a written reason" if n else
                  f"0/{len(records)} tasks overlap: `{condition_name}` injects no document its "
                  f"answer key cites")


def check_spec_disclosure(pack: Pack) -> tuple[bool, str]:
    """Gate for `raw-spec` (ADR-0050). See `_check_disclosure_records`."""
    records = spec_disclosure(pack)
    if not records:
        return True, "pack declares no raw-spec condition; nothing to disclose"
    return _check_disclosure_records(records, condition_name="raw-spec",
                                     config_path="raw_spec.scored_against_own_source")


def check_gated_disclosure(pack: Pack) -> tuple[bool, str]:
    """Gate for `gated-docs` (ADR-0051). See `_check_disclosure_records`."""
    records = gated_disclosure(pack)
    if not records:
        return True, "pack declares no gated-docs condition; nothing to disclose"
    return _check_disclosure_records(records, condition_name="gated-docs",
                                     config_path="gated_docs.scored_against_own_source")


def audit_gated_truncation(pack: Pack) -> list[dict]:
    """The truncation audit, run against `gated-docs` (ADR-0051). Empty if the pack does not declare it.

    Separate from the `public-docs` call for ADR-0050's reason: the two corpora differ, and on a
    filtering host they differ maximally — one column's cached text is a refusal stub and the other's
    is the document. Averaging those would describe neither.
    """
    if pack.gated_docs is None:
        return []
    return audit_docs_truncation(pack, GatedDocsCondition(pack))
