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
            mode=cfg.get("mode"),
            spec_ref_file_prefix=cfg.get("spec_ref_file_prefix"),
            expected_task_ids=(list(cfg["expected_task_ids"]) if cfg.get("expected_task_ids") else None),
            na_categories=(dict(cfg["na_categories"]) if cfg.get("na_categories") else None),
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

    def cache_path_for(self, task_id: str, url: str) -> Path:
        from .docs_fetch import slug_for
        return self.docs_cache_dir / task_id / f"{slug_for(url)}.txt"
