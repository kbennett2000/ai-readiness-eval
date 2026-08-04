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

And, under the pseudo-file key ``"(docs-manifest)"``, one whole-pack check that is about evidence
rather than answer keys: a manifest entry may not record a successful retrieval and its own failure
at the same time (ADR-0056). See `validate_docs_manifest`.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from jsonschema import Draft7Validator

from .docs_fetch import ENTRY_KEYS
from .pack import Pack
from .scorer import KNOWN_AUTH_STYLES
from .taxonomy import BY_COHORT, CATEGORIES, DOCS_CATEGORIES

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
                    # ADR-0041. Optional and absent everywhere it is not asked for, so adding it
                    # moves no archived score. `minLength: 1` is the schema half of the rule the
                    # scorer enforces at read time: a dimension this project declines to score has
                    # to say why on the record, so a bare `true` is not expressible here either.
                    "auth_flow_not_corroborable": {"type": "string", "minLength": 1},
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


def build_docs_schema() -> dict:
    """The DOCS-cohort task schema (ADR-0044).

    A separate schema rather than a loosened one, and the separation is the point: the API schema's
    `additionalProperties: false` plus its six required ground-truth fields is what stops a task
    file from carrying a key nobody scores. Widening it to admit both shapes would have meant
    dropping exactly that, and a docs task could then have declared `endpoints:` — scored by
    nothing, read by nobody, and indistinguishable from a task that meant it.

    Every endpoint-shaped field is gone because the surface has none. What replaces them is the
    citation: `publication` is REQUIRED and must carry a number and a revision, which is this
    cohort's form of the anchoring rule the API cohort spells with `spec_ref`/`doc_ref` — ground
    truth rests on a first-party published document, identified precisely enough that a reader can
    fetch the same one.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "category", "job_category", "prompt", "ground_truth"],
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "category": {"enum": VALID_DIFFICULTY},
            "job_category": {"enum": list(DOCS_CATEGORIES)},
            "prompt": {"type": "string", "minLength": 1},
            "notes": {"type": "string", "minLength": 1},  # optional (editorial)
            "ground_truth": {
                "type": "object",
                "additionalProperties": False,
                "required": ["publication", "success_shape", "common_failure_modes"],
                "properties": {
                    # At least one scored value must be present. Which one is a property of the
                    # question, so the schema does not demand a particular key — `roundtrip` blocks
                    # a task that declares none of them, where the reason can be said in a sentence
                    # rather than as a JSON Schema `anyOf` a reader has to decode.
                    "catalog_numbers": {"type": "array", "minItems": 1,
                                        "items": {"type": "string", "minLength": 1}},
                    # Versions are STRINGS, and the schema is where that is enforced. Written bare,
                    # `35.011` is a YAML float and arrives as `35.01` — the answer key would be
                    # silently rewritten before anything compared it (ADR-0044).
                    "firmware_version": {"type": "string", "minLength": 1},
                    "software_version": {"type": "string", "minLength": 1},
                    "publication": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["number", "revision", "url"],
                        "properties": {
                            # The SERVED document's own footer id, never the request-URL slug: a
                            # literature host may alias one publication number onto another, so the
                            # URL is where it was found and the footer is what it is.
                            "number": {"type": "string", "minLength": 1},
                            "revision": {"type": "string", "minLength": 1},
                            "url": {"type": "string", "pattern": r"^https?://"},
                            "page": {"type": "string", "minLength": 1},
                            "quote": {"type": "string", "minLength": 1},
                        },
                    },
                    # A pack's declared UNSCORED observations (ADR-0045): {key: expected value}.
                    # Values are strings for the same reason the versions above are — a bare
                    # `1250.0` is a YAML float and would be rewritten before anyone read it. WHICH
                    # keys are legal is checked by the contract against `unscored_observations`,
                    # not here, because only the pack knows what it declared.
                    "observations": {
                        "type": "object",
                        "minProperties": 1,
                        "additionalProperties": {"type": "string", "minLength": 1},
                    },
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
    # The schema is the COHORT's (ADR-0044). `api` is the default, so a pack that declares nothing
    # is validated by exactly the schema it was validated by before that ADR.
    schema = (build_docs_schema() if pack.cohort == "docs"
              else build_schema(spec_ref_file_prefix=pack.spec_ref_file_prefix))
    categories = BY_COHORT.get(pack.cohort, CATEGORIES)
    na = pack.na_categories or {}
    results: dict[str, list[str]] = {}
    seen_ids: dict[str, str] = {}
    suite: list[str] = []

    # N/A keys must be real categories.
    for cat in na:
        if cat not in categories:
            suite.append(
                f"na_categories names unknown category '{cat}' for cohort '{pack.cohort}'")

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
    try:
        suite.extend(validate_answer_surfaces(pack.answer_surfaces))
    except Exception as exc:  # an unreadable inventory file is a schema problem, not a crash
        suite.append(f"answer_surfaces could not be loaded: {exc}")

    if suite:
        results["(suite)"] = suite
    manifest_errors = validate_docs_manifest(pack)
    if manifest_errors:
        results["(docs-manifest)"] = manifest_errors
    return results


def validate_docs_manifest(pack: Pack) -> list[str]:
    """A manifest entry may not describe a retrieval and its own failure at once (ADR-0056).

    Every fetched entry carries two independent records: whether content arrived (`content_hash`,
    `byte_size`, `cache_file`) and whether the attempt failed (`fetch_error`). Nothing made them
    agree. The fetcher overwrites every success field on a re-fetch but only the failure path ever
    wrote `fetch_error`, so an entry fetched twice — a retry, or ADR-0051's two-agent measurement,
    where the same URL is fetched under a plain agent and again under a conventional one — kept the
    first attempt's error beside the second attempt's hash.

    `fetch_error` is NOT inert: `_InjectedTextCondition._load_text` tests it first, before touching
    the disk, and a page carrying one injects nothing (ADR-0054). That is exactly why a stale one is
    worth a gate rather than a tidy-up — an error left behind by a superseded attempt suppresses a
    page that now fetches. Where it was found it sat on `anchors`, which no condition reads
    (ADR-0034), and the injected bytes were verified identical across every condition and task.

    What was wrong is what a reviewer sees: an anchor a ground-truth citation rests on, declared
    unreadable in the same breath as the hash, byte size and cache file proving it was read. The
    fetcher no longer produces the state; this refuses it wherever it already sits, including from a
    hand edit, which is the half a fetcher fix structurally cannot reach.

    The predicate is `fetch_error` beside ANY arrival evidence, which is the same predicate the
    cohort sweep applied when it established that no `pages` entry has ever carried one — so the
    gate and the evidence for the gate test the same thing rather than two nearby things.

    Returns errors; `[]` when the pack declares no manifest or the manifest is clean.
    """
    path = Path(pack.docs_manifest_path)
    if not path.is_file():
        return []                      # a pack with no docs condition has nothing to contradict
    try:
        manifest = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return [f"docs-manifest.yaml could not be parsed: {exc}"]

    errors: list[str] = []
    for task_id, entry in (manifest.get("tasks") or {}).items():
        if not isinstance(entry, dict):
            continue
        for key in ENTRY_KEYS:
            for i, page in enumerate(entry.get(key) or []):
                if not isinstance(page, dict):
                    continue
                where = f"{task_id}/{key}[{i}] {page.get('url', '(no url)')}"
                error = page.get("fetch_error")
                has_hash = bool(page.get("content_hash"))
                has_bytes = bool(page.get("byte_size"))
                cache_file = page.get("cache_file")
                # ANY arrival evidence, not all of it. The first draft required all four fields at
                # once, which would have passed an entry carrying a `fetch_error` beside a hash and a
                # non-zero byte size with no `cache_file` — still a page that injects nothing while
                # claiming content arrived. An honest failure records NO arrival evidence at all
                # (`content_hash: null`, `byte_size: 0`, no `cache_file`), which is the shape all 65
                # real failures in the cohort take, so widening costs none of them.
                arrived = [name for name, present in (("content_hash", has_hash),
                                                      ("byte_size", has_bytes),
                                                      ("cache_file", bool(cache_file)))
                           if present]
                if error and arrived:
                    errors.append(
                        f"{where}: records fetch_error {error!r} AND evidence content arrived "
                        f"({', '.join(arrived)}). An entry may not be both (ADR-0056) — if the "
                        "fetch succeeded, drop `fetch_error:`; if it failed, drop the content "
                        "fields.")
                elif cache_file and not has_hash:
                    errors.append(
                        f"{where}: names cache_file {cache_file} but records no content_hash, so "
                        "it points at bytes the manifest does not vouch for (ADR-0056).")
    return errors


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


def validate_answer_surfaces(surface_set) -> list[str]:
    """Check a pack's declared `answer_surfaces` (ADR-0037). Returns errors; [] when none declared.

    The bar is that the axis can DISCRIMINATE. A single surface has nothing to be told apart from;
    an unmarked measured surface leaves the round-trip control with no target; an empty inventory
    silently sends every answer to `unrecognized`. The last rule is the load-bearing one: where two
    surfaces publish the same normalized path, the pack must declare version markers that separate
    them, so an overlap is a stated fact with a stated resolution rather than something the
    classifier discovers and quietly reports as `ambiguous`.
    """
    if not surface_set:
        return []
    errors: list[str] = []
    ids = [s.id for s in surface_set.surfaces]

    if len(surface_set.surfaces) < 2:
        errors.append("answer_surfaces declares fewer than 2 surfaces — there is nothing to tell "
                      "apart, and a one-surface split reports only its own inventory's gaps")
    for sid in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"answer_surfaces declares id '{sid}' more than once")

    measured = [s.id for s in surface_set.surfaces if s.measured]
    if len(measured) != 1:
        errors.append(f"answer_surfaces must mark exactly one surface `measured: true`, "
                      f"found {len(measured)}: {', '.join(measured) or '(none)'}")

    for surface in surface_set.surfaces:
        if not surface.id:
            errors.append("a declared surface has no id")
        if not surface.paths:
            errors.append(f"surface '{surface.id}' has an empty path inventory — every answer "
                          f"would fall to `unrecognized` without it ever being wrong")
        if not str(surface.rationale or "").strip():
            errors.append(f"surface '{surface.id}' has no rationale — why this surface belongs in "
                          f"the comparison is an argument nothing else in this repo can check")

    seen: dict[tuple, list] = {}
    for surface in surface_set.surfaces:
        for npath in surface.normalized_paths:
            seen.setdefault(npath, []).append(surface)
    for npath, sharers in sorted(seen.items()):
        if len(sharers) < 2:
            continue
        without = [s.id for s in sharers if not s.normalized_markers]
        if without:
            errors.append(
                f"/{'/'.join(npath)} is published by {', '.join(s.id for s in sharers)}, but "
                f"{', '.join(without)} declares no version_markers to tell it apart")
        marker_sets = [s.normalized_markers for s in sharers if s.normalized_markers]
        for i, left in enumerate(marker_sets):
            for right in marker_sets[i + 1:]:
                if left & right:
                    errors.append(
                        f"/{'/'.join(npath)} is published by more than one surface and they share "
                        f"version marker(s) {', '.join(sorted(left & right))} — the overlap cannot "
                        f"be resolved")
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
