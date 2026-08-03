"""A vendor pack: the tasks, spec pin, docs manifest, and vendor config that feed the
vendor-agnostic core (ADR-0001, ADR-0002).

Everything vendor-specific reaches core through a loaded `Pack`. Core holds no vendor
string, path, or task assumption; a pack supplies them from its `pack.yaml` and sibling
files. A pack with no `context_layer` block runs the two-condition mode (no-context vs
public-docs) and still produces a full report.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_DOCS_BUDGET_TOKENS = 15000
DEFAULT_DISCOVERY_TOOL = "ToolSearch"

#: Product tokens that appear only in a real browser's User-Agent. A declared `gated_docs.user_agent`
#: carrying any of them is refused (ADR-0051).
#:
#: The list is deliberately a denylist of RENDERING-ENGINE and BROWSER-PRODUCT tokens rather than an
#: allowlist of acceptable agents, for the reason ADR-0017's first-party check gives: an allowlist
#: fails OPEN on the string nobody thought of, and the string nobody thought of is exactly what a
#: cycle under time pressure would paste in. `Mozilla/5.0` alone is NOT here and must not be: it is a
#: vestigial token that every conventional crawler — Googlebot, bingbot — carries, and banning it
#: would ban the one honest form that passes a filter of this kind.
_BROWSER_UA_TOKENS = ("AppleWebKit", "Gecko/", "Chrome/", "Chromium/", "CriOS/", "Safari/",
                      "Firefox/", "FxiOS/", "Edg/", "Edge/", "EdgA/", "OPR/", "Opera",
                      "Trident/", "MSIE", "Version/", "Mobile/", "SamsungBrowser")


def _looks_like_a_browser(agent: str) -> bool:
    """Does this User-Agent claim to be a browser rather than name its operator (ADR-0051)?

    Two independent tests, because either alone lets a real browser string through:

    1. Any browser-product or rendering-engine token above. A Chrome string carries several.
    2. A `Mozilla/`-prefixed string whose parenthetical does NOT open with `compatible;`. That form
       is the conventional bot declaration; `Mozilla/5.0 (Windows NT 10.0; …)` is a claim to be a
       specific browser on a specific operating system, and no crawler needs to make it.

    Returns True to REFUSE. Nothing here inspects what a host does with the string — the rule is
    about what this project is willing to say about itself, which is a decision and not a
    measurement.
    """
    if any(tok.lower() in agent.lower() for tok in _BROWSER_UA_TOKENS):
        return True
    if agent.lstrip().lower().startswith("mozilla/"):
        head, sep, rest = agent.partition("(")
        if not sep or not rest.lstrip().lower().startswith("compatible;"):
            return True
    return False


@dataclass
class ContextLayer:
    """Config for the optional third (context-layer) condition. When the server lives outside
    this repository, `external` is true and `spawn_command` points at it (documented in
    `external_note`); the offline re-score path never starts it."""
    external: bool
    external_note: str
    mcp_server_key: str
    mcp_tool_prefix: str
    discovery_tool: str
    expected_tools: list[str]
    spawn_command: list[str]


@dataclass
class RawSpec:
    """Config for the optional `raw-spec` condition (ADR-0050): the vendor's OWN machine-readable
    specification, injected uncurated.

    There is no budget field here, and that omission is the decision. `raw-spec` spends the SAME
    token budget as `public-docs`, because a column with a larger budget than the one it is set
    beside would measure this harness's generosity rather than the difference between a
    specification and prose. A pack that wants more context for both moves `public_docs.budget_tokens`
    and moves both columns together, visibly.

    `source_label` is what the injected block is headed with, and it must name the ARTIFACT — "…'s
    OpenAPI 3 documents", not "…'s documentation". A reader of a transcript has to be able to tell
    which condition produced it without consulting the pack.
    """
    source_label: str
    #: Written justification for a task whose `spec_documents` overlap its `anchors` — the condition
    #: is then scored against its own source. Keyed by task id; `check_spec_disclosure` requires an
    #: entry for every overlapping task and refuses a pack that has one and says nothing.
    scored_against_own_source: dict


@dataclass
class GatedDocs:
    """Config for the optional `gated-docs` condition (ADR-0051).

    For a docs host that decides what to serve from the User-Agent string. `public-docs` asks with
    this project's plain self-identifying agent and records what comes back — on such a host, a
    refusal. This condition asks the SAME URLs with a conventional self-identifying agent and records
    what comes back instead. The two columns together price the filter.

    `user_agent` is REQUIRED and is published verbatim on the card. That is the whole conduct
    position: the declared agent must NAME this project, in the conventional
    `Mozilla/5.0 (compatible; <name>/<version>)` form that ordinary crawlers have used for decades.
    It is not a browser string and must never be one. A column obtained by claiming to be someone
    else would measure what a vendor shows a person it was deceived about, and no honest number can
    be built from that — so the string is a field a reviewer reads, not a default anyone can inherit.

    There is no budget field, for ADR-0050's reason, which applies here more sharply: this column is
    set directly beside `public-docs` on the same URLs, and any budget difference between them would
    be indistinguishable from the effect being measured.
    """
    source_label: str
    #: The exact User-Agent header this pack's `gated_pages` were retrieved with. Published on the
    #: card; recorded per page by the fetcher as `fetched_with_user_agent`, so the claim is checkable
    #: against the manifest rather than only against this field.
    user_agent: str
    #: Written justification for a task whose `gated_pages` overlap its `anchors` — see `RawSpec`.
    scored_against_own_source: dict


@dataclass
class Pack:
    root: Path
    vendor_id: str
    display_name: str
    # What counts as a task prompt naming this target (ADR-0031). Both are REQUIRED — the prompt gate
    # fails closed on a pack that declares neither, so there is no silent default. They are declared
    # rather than derived from `display_name` because that field is a card heading, not a matcher: it
    # is vendor-only in some packs and a whole "Vendor Product (Surface API)" string in others, and a
    # gate built on splitting it would pass or fail on punctuation.
    vendor_names: list[str]
    product_names: list[str]
    tasks_dir: Path
    docs_manifest_path: Path
    specs_path: Path
    docs_cache_dir: Path
    public_docs_source_label: str
    public_docs_budget_tokens: int
    project_marker: str
    spec_scope_prefix: str
    context_layer: ContextLayer | None = None
    # The optional `raw-spec` condition (ADR-0050). None for every pack that does not declare it,
    # which is every pack written before that ADR, so no published number moves by this existing.
    raw_spec: RawSpec | None = None
    # The optional `gated-docs` condition (ADR-0051). None for every pack that does not declare it,
    # so no published number moves by this existing.
    gated_docs: "GatedDocs | None" = None
    # Fetch-time User-Agent for the public-docs snapshot. Only set it when a vendor's docs host
    # bot-gates the default self-identifying agent (ADR-0007); the gating itself is a scored finding.
    public_docs_user_agent: str | None = None
    # Seconds to pause between page fetches. Only set it when a vendor's docs host throttles a
    # rapid loop (ADR-0009); the throttling itself is recorded as a finding, not worked around.
    public_docs_fetch_delay_seconds: float = 0.0
    # Validation / mode metadata (ADR-0002, ADR-0003). All optional.
    mode: str | None = None                       # e.g. "diagnosis" for a two-condition prospect pack
    spec_ref_file_prefix: str | None = None       # constrain task spec_ref.file paths to a spec subtree
    expected_task_ids: list[str] | None = None     # completeness check for `validate`
    na_categories: dict | None = None              # {taxonomy category: one-line reason}
    # {contract dimension: written reason} — a dimension this pack's tasks deliberately do not
    # exercise (ADR-0045). A REASON, never a boolean: the tolerance is granted to a pack that asked
    # for it in writing, where a reviewer can disagree with the argument.
    unexercised_dimensions: dict | None = None
    # {observation key: written reason} — a value class recorded per run and NEVER scored
    # (ADR-0045). Adds a key to the answer block and a field to `TaskScore.exhibit`; it can never
    # become a dimension, contribute to `overall`, or appear in a scored table.
    unscored_observations: dict | None = None
    # OPT-IN endpoint-address tolerance (ADR-0017). A path prefix the scorer may ignore on either
    # side of an endpoint comparison, for a vendor whose documentation and whose machine-readable
    # description disagree about where the base URL ends. Empty for every pack that does not declare
    # it, so no pack's numbers move by adding this field. Never derived from `base_url`: that field
    # points at a spec REPOSITORY for several packs, not at an API base.
    #
    # ADR-0039 widens this to accept a LIST of prefixes as well as a single string, for a vendor
    # whose own documents disagree about the base in more than one place at once. A string still
    # means exactly what it meant, so the six packs that declare one are byte-identical.
    endpoint_base_prefix: str | list[str] | None = None

    # Named task groups a pack declares as a reporting axis (ADR-0026), e.g. surface age. Shape:
    # `{key: {label, rationale, tasks: [...]}}`. Optional and empty for every pack that does not
    # declare it, so no published number moves by adding this field. It is a PACK-level analysis
    # axis rather than a property of a task, which is why it lives here and not in the (closed) task
    # schema: the same tasks can be grouped more than one way, and the grouping is an argument the
    # card makes, not a fact the task file carries.
    task_groups: dict | None = None

    # Published API surfaces this pack can tell apart in an answer (ADR-0037). Optional and empty
    # for every pack that does not declare it, so no published number moves by adding this field —
    # and it CANNOT move one even when declared, because nothing in the scoring path reads it. Like
    # `task_groups` this is a pack-level reporting axis; unlike `task_groups`, each surface's path
    # list is a transcription from a published artifact rather than an argument, which is why the
    # long ones live in a pinned sibling file that can carry their provenance.
    answer_surfaces_config: dict | None = None

    # Which answer contract this pack is measured under (ADR-0044). `api` is the default and is what
    # every pack written before that ADR gets without declaring anything, so no published number can
    # move by this field existing. It is NOT a free-text label: `contract.contract_for` refuses a
    # cohort it has no contract for rather than falling back, because a pack scored on six
    # dimensions its ground truth does not have would report every one of them n/a and pass green
    # while measuring nothing.
    cohort: str = "api"

    @classmethod
    def load(cls, pack_dir: str | Path) -> "Pack":
        root = Path(pack_dir).resolve()
        cfg = yaml.safe_load((root / "pack.yaml").read_text()) or {}
        vendor = cfg.get("vendor", {}) or {}
        vid = vendor.get("id", root.name)
        display = vendor.get("display_name", vid)
        pd = cfg.get("public_docs", {}) or {}

        context_layer = None
        cl = cfg.get("context_layer")
        if cl:
            context_layer = ContextLayer(
                external=bool(cl.get("external", False)),
                external_note=cl.get("external_note", ""),
                mcp_server_key=cl["mcp_server_key"],
                mcp_tool_prefix=cl["mcp_tool_prefix"],
                discovery_tool=cl.get("discovery_tool", DEFAULT_DISCOVERY_TOOL),
                expected_tools=list(cl.get("expected_tools", [])),
                spawn_command=list(cl.get("spawn_command", [])),
            )

        raw_spec = None
        rs = cfg.get("raw_spec")
        if rs:
            raw_spec = RawSpec(
                source_label=rs["source_label"],
                scored_against_own_source=dict(rs.get("scored_against_own_source") or {}),
            )

        gated_docs = None
        gd = cfg.get("gated_docs")
        if gd:
            agent = str(gd.get("user_agent") or "").strip()
            if not agent:
                raise ValueError(
                    f"pack '{vid}' declares gated_docs without a user_agent. The agent this column "
                    "was retrieved with IS the finding and is published verbatim on the card, so "
                    "there is no default to inherit (ADR-0051).")
            if _looks_like_a_browser(agent):
                raise ValueError(
                    f"pack '{vid}' declares a gated_docs user_agent that impersonates a browser: "
                    f"{agent!r}. This condition is retrieved with a CONVENTIONAL SELF-IDENTIFYING "
                    "agent — 'Mozilla/5.0 (compatible; <name>/<version>)' — never with a browser "
                    "string. A column obtained by claiming to be someone else measures what a "
                    "vendor shows a reader it was deceived about (ADR-0051).")
            gated_docs = GatedDocs(
                source_label=gd["source_label"],
                user_agent=agent,
                scored_against_own_source=dict(gd.get("scored_against_own_source") or {}),
            )

        return cls(
            root=root,
            vendor_id=vid,
            display_name=display,
            vendor_names=[str(n) for n in (vendor.get("vendor_names") or [])],
            product_names=[str(n) for n in (vendor.get("product_names") or [])],
            tasks_dir=root / cfg.get("tasks_dir", "tasks"),
            docs_manifest_path=root / cfg.get("docs_manifest", "docs-manifest.yaml"),
            specs_path=root / cfg.get("specs", "specs.yaml"),
            docs_cache_dir=root / cfg.get("docs_cache_dir", "docs-cache"),
            public_docs_source_label=pd.get("source_label", f"{display} documentation"),
            public_docs_budget_tokens=int(pd.get("budget_tokens", DEFAULT_DOCS_BUDGET_TOKENS)),
            public_docs_user_agent=pd.get("user_agent") or None,
            public_docs_fetch_delay_seconds=float(pd.get("fetch_delay_seconds", 0) or 0),
            project_marker=(cfg.get("canary", {}) or {}).get("project_marker", ""),
            spec_scope_prefix=(cfg.get("specs_scope", "") or ""),
            context_layer=context_layer,
            raw_spec=raw_spec,
            gated_docs=gated_docs,
            mode=cfg.get("mode"),
            spec_ref_file_prefix=cfg.get("spec_ref_file_prefix"),
            expected_task_ids=(list(cfg["expected_task_ids"]) if cfg.get("expected_task_ids") else None),
            na_categories=(dict(cfg["na_categories"]) if cfg.get("na_categories") else None),
            unexercised_dimensions=(dict(cfg["unexercised_dimensions"])
                                    if cfg.get("unexercised_dimensions") else None),
            unscored_observations=(dict(cfg["unscored_observations"])
                                   if cfg.get("unscored_observations") else None),
            endpoint_base_prefix=cfg.get("endpoint_base_prefix") or None,
            task_groups=(dict(cfg["task_groups"]) if cfg.get("task_groups") else None),
            answer_surfaces_config=(dict(cfg["answer_surfaces"])
                                    if cfg.get("answer_surfaces") else None),
            cohort=str(cfg.get("cohort") or "api"),
        )

    @property
    def contract(self):
        """This pack's `AnswerContract` (ADR-0044). Imported lazily to keep the import graph acyclic."""
        from .contract import contract_for
        return contract_for(self)

    @property
    def answer_surfaces(self):
        """The declared `SurfaceSet` (ADR-0037); an empty one when the pack declares none."""
        from .surfaces import load_surface_set
        return load_surface_set(self.answer_surfaces_config, self.root)

    def task_to_group(self) -> dict:
        """`{task_id: group_key}` from the declared `task_groups`; empty when none are declared."""
        out: dict[str, str] = {}
        for key, block in (self.task_groups or {}).items():
            for tid in (block or {}).get("tasks", []) or []:
                out[tid] = key
        return out

    @property
    def declared_base_prefixes(self) -> list[str]:
        """The declared endpoint-base tolerance as the literal strings a pack wrote; [] if unset.

        One string declares one prefix; a list declares several (ADR-0039). Callers that compare
        PATHS want `base_prefix_segments`; this property exists for the one caller that compares
        literal documentation text (`contract._path_spellings`).
        """
        p = self.endpoint_base_prefix
        if not p:
            return []
        return [p] if isinstance(p, str) else [s for s in p if s]

    @property
    def base_prefix_segments(self) -> list[list[str]]:
        """The declared endpoint-base tolerance as comparable segments (ADR-0017/0039).

        Always a LIST OF PREFIXES, each a list of segments — one entry for a pack declaring a single
        string, so nothing downstream changes for the six packs that do. `[]` when unset, which is
        the pre-ADR-0017 behaviour and the reason no archived score can move.
        """
        from .scorer import normalize_path
        return [seg for seg in (normalize_path(p) for p in self.declared_base_prefixes) if seg]

    # --- task ground truth -------------------------------------------------- #
    def load_tasks(self, only: set[str] | None = None) -> list[dict]:
        tasks: list[dict] = []
        for path in sorted(self.tasks_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            if only and data["id"] not in only:
                continue
            tasks.append(data)
        return tasks

    def tasks_by_id(self, only: set[str] | None = None) -> dict[str, dict]:
        return {t["id"]: t for t in self.load_tasks(only)}

    # --- spec pin ----------------------------------------------------------- #
    def spec_sha(self) -> str:
        try:
            return yaml.safe_load(self.specs_path.read_text()).get("spec_sha", "unknown")
        except Exception:  # pragma: no cover - specs.yaml is committed
            return "unknown"

    def spec_pin(self) -> tuple[str, str]:
        cfg = yaml.safe_load(self.specs_path.read_text())
        return cfg["spec_repo"], cfg["spec_sha"]

    # --- public-docs manifest + cache --------------------------------------- #
    def docs_manifest(self) -> dict:
        return yaml.safe_load(self.docs_manifest_path.read_text())

    def cache_path_for(self, task_id: str, url: str, *, manifest_key: str | None = None) -> Path:
        """Where this pack caches one retrieval. Delegates the `manifest_key` ruling to `docs_fetch`
        so the reader and the writer cannot disagree about a path (ADR-0051)."""
        from .docs_fetch import cache_path_for
        return cache_path_for(self.docs_cache_dir, task_id, url, prefix=manifest_key)
