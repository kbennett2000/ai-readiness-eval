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
        )

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
