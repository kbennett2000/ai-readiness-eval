"""Validate a pack's task files against the shared schema (ADR-0002, ADR-0003).

Offline and deterministic. The schema is vendor-agnostic; per-pack specifics (the `spec_ref.file`
prefix, the expected task-id set, the not-applicable categories) come from the loaded `Pack`. Because
answer keys grow bugs, this is the quality gate that runs before and after any ground truth is written.

What it checks, per task file:
  1. Parses as YAML with the required top-level fields; `id` equals the filename stem; ids are unique.
  2. `category` is a valid difficulty tier; `job_category` is a valid taxonomy category (ADR-0003) and
     is not one the pack marked N/A.
  3. `ground_truth` has a non-empty `endpoints` list plus the required sibling fields.
  4. Every endpoint is anchored: EITHER a `spec_ref{file, operation_id}` (file matching the pack's
     `spec_ref_file_prefix`, if set) OR `coverage: doc-only` with a `doc_ref{url}`.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from jsonschema import Draft7Validator

from .pack import Pack
from .scorer import KNOWN_AUTH_STYLES
from .taxonomy import CATEGORIES

VALID_DIFFICULTY = ["foundational", "daily-automation", "multi-step"]
VALID_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _endpoint_anchor(spec_ref_file_prefix: str | None) -> dict:
    """An endpoint is anchored EITHER by a spec_ref OR by a documented coverage gap."""
    file_schema = {"type": "string", "minLength": 1}
    if spec_ref_file_prefix:
        file_schema["pattern"] = "^" + spec_ref_file_prefix
    return {
        "oneOf": [
            {
                "required": ["spec_ref"],
                "properties": {
                    "spec_ref": {
                        "type": "object",
                        "required": ["file", "operation_id"],
                        "properties": {
                            "file": file_schema,
                            "operation_id": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            {
                "required": ["coverage", "doc_ref"],
                "properties": {
                    "coverage": {"const": "doc-only"},
                    "doc_ref": {
                        "type": "object",
                        "required": ["url"],
                        "properties": {"url": {"type": "string", "pattern": r"^https?://"}},
                    },
                },
            },
        ],
    }


def build_schema(*, spec_ref_file_prefix: str | None = None) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "category", "job_category", "prompt", "ground_truth"],
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "category": {"enum": VALID_DIFFICULTY},
            "job_category": {"enum": list(CATEGORIES)},
            "prompt": {"type": "string", "minLength": 1},
            "notes": {"type": "string", "minLength": 1},  # optional (editorial)
            "ground_truth": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "endpoints", "auth_flow", "required_scopes",
                    "key_parameters", "success_shape", "common_failure_modes",
                ],
                "properties": {
                    "endpoints": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["method", "path", "api_version", "operation_id"],
                            "properties": {
                                "method": {"enum": VALID_METHODS},
                                "path": {"type": "string", "pattern": r"^/"},
                                "api_version": {"type": "string", "minLength": 1},
                                "operation_id": {"type": "string", "minLength": 1},
                                "spec_ref": {"type": "object"},
                                "coverage": {"type": "string"},
                                "doc_ref": {"type": "object"},
                            },
                            "allOf": [_endpoint_anchor(spec_ref_file_prefix)],
                        },
                    },
                    "auth_flow": {"type": "string", "minLength": 1},
                    # Optional (ADR-0023). The additional login styles the vendor documents as valid
                    # for this operation. Shape only here; the rules that keep a set from becoming a
                    # way to make any answer right are argued and enforced in
                    # `scorer.alternate_problems`, which the `roundtrip` gate runs before any grid.
                    "auth_flow_alternates": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["style", "evidence", "note"],
                            "properties": {
                                "style": {"enum": list(KNOWN_AUTH_STYLES)},
                                "evidence": {"type": "string", "pattern": r"^https?://"},
                                "note": {"type": "string", "minLength": 40},
                            },
                        },
                    },
                    "required_scopes": {"type": "array"},
                    "key_parameters": {"type": "array", "minItems": 1},
                    "success_shape": {"type": "string", "minLength": 1},
                    "common_failure_modes": {"type": "array", "minItems": 1},
                },
            },
        },
    }


def validate_file(path: Path, schema: dict, *, na_categories: dict | None = None) -> list[str]:
    """Return a list of human-readable error strings for one task file ([] if valid)."""
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]
    if not isinstance(data, dict):
        return ["top-level document is not a mapping"]

    errors: list[str] = []
    for err in sorted(Draft7Validator(schema).iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{loc}: {err.message}")

    # id must match filename stem (schema can't express this).
    if data.get("id") and data["id"] != path.stem:
        errors.append(f"id '{data['id']}' does not match filename stem '{path.stem}'")

    # a task must not map to a category the pack declared not-applicable.
    jc = data.get("job_category")
    if jc and na_categories and jc in na_categories:
        errors.append(f"job_category '{jc}' is marked N/A for this pack ({na_categories[jc]})")

    return errors


def validate_pack(pack: Pack) -> dict[str, list[str]]:
    """Validate every task file in a pack. Returns {filename: [errors]} — empty lists mean valid.

    Whole-suite checks (duplicate ids, expected-id completeness, N/A category keys) are reported under
    the pseudo-file key ``"(suite)"``.
    """
    schema = build_schema(spec_ref_file_prefix=pack.spec_ref_file_prefix)
    na = pack.na_categories or {}
    results: dict[str, list[str]] = {}
    seen_ids: dict[str, str] = {}
    suite: list[str] = []

    # N/A keys must be real categories.
    for cat in na:
        if cat not in CATEGORIES:
            suite.append(f"na_categories names unknown category '{cat}'")

    files = sorted(pack.tasks_dir.glob("*.yaml"))
    if not files:
        suite.append(f"no task files found in {pack.tasks_dir}")

    for path in files:
        errs = validate_file(path, schema, na_categories=na)
        try:
            tid = (yaml.safe_load(path.read_text()) or {}).get("id")
        except yaml.YAMLError:
            tid = None
        if tid:
            if tid in seen_ids:
                errs.append(f"duplicate id '{tid}' (also in {seen_ids[tid]})")
            seen_ids[tid] = path.name
        results[path.name] = errs

    expected = set(pack.expected_task_ids or [])
    if expected:
        missing = expected - seen_ids.keys()
        unexpected = seen_ids.keys() - expected
        if missing:
            suite.append(f"missing expected tasks: {', '.join(sorted(missing))}")
        if unexpected:
            suite.append(f"unexpected tasks: {', '.join(sorted(unexpected))}")

    suite.extend(validate_task_groups(pack.task_groups, seen_ids.keys()))

    if suite:
        results["(suite)"] = suite
    return results


def validate_task_groups(task_groups: dict | None, task_ids) -> list[str]:
    """Check a pack's declared `task_groups` (ADR-0026). Returns errors; [] when none are declared.

    Groups are a reporting axis, so the bar is that the axis PARTITIONS the pack: every task in
    exactly one group, every named task real, no empty group, and a written rationale on each. A
    group split that silently dropped or double-counted a task would publish a per-group mean that
    no reader could reconstruct from the per-task table beside it.
    """
    if not task_groups:
        return []
    errors: list[str] = []
    known = set(task_ids)
    assigned: dict[str, list[str]] = {}

    for key, block in task_groups.items():
        block = block or {}
        tasks = list(block.get("tasks") or [])
        if not tasks:
            errors.append(f"task_groups['{key}'] lists no tasks")
        if not str(block.get("rationale") or "").strip():
            errors.append(
                f"task_groups['{key}'] has no rationale — a group is an argument the card makes, "
                f"and nothing else in this repo can check that the grouping is true of the world")
        for tid in tasks:
            assigned.setdefault(tid, []).append(key)
            if known and tid not in known:
                errors.append(f"task_groups['{key}'] names unknown task '{tid}'")

    for tid, keys in sorted(assigned.items()):
        if len(keys) > 1:
            errors.append(f"task '{tid}' is in more than one group: {', '.join(sorted(keys))}")

    ungrouped = sorted(known - assigned.keys())
    if known and ungrouped:
        errors.append(
            "task_groups is declared but does not cover every task; ungrouped: "
            + ", ".join(ungrouped))

    return errors


def format_report(results: dict[str, list[str]]) -> tuple[str, int]:
    """Render results to (text, total_error_count)."""
    lines: list[str] = []
    total = 0
    for name in sorted(results):
        errs = results[name]
        if errs:
            total += len(errs)
            lines.append(f"FAIL  {name}")
            for e in errs:
                lines.append(f"        - {e}")
        else:
            lines.append(f"ok    {name}")
    n_files = len([k for k in results if k != "(suite)"])
    lines.append("")
    if total:
        lines.append(f"✗ {total} problem(s) across {n_files} task file(s)")
    else:
        lines.append(f"✓ all {n_files} task file(s) valid")
    return "\n".join(lines), total
