"""Which published surface did an answer come from? (ADR-0037)

A vendor may publish more than one live API surface at once: a current one, a deprecated one it
still serves, a legacy one it still documents. When a model answers a task about the current surface
with a real endpoint from a superseded one, the six dimensions record a miss and cannot say WHY it
missed — a stale-but-real answer and a fabricated one score identically. This module is the overlay
that tells them apart.

Three properties make it safe to bolt onto a project whose whole product is numbers.

1. **It never touches a score.** Nothing in the scoring path imports this module (a structural test
   asserts that), and it reads archived runs rather than producing them. Declaring `answer_surfaces`
   on a pack leaves every dimension byte-identical. It can only ever redistribute outcomes the
   scorer already recorded, among buckets a pack already declared; there is no arrangement of
   inventories that manufactures a point. That asymmetry is the whole licence for the feature.

2. **It borrows normalization rather than re-implementing it.** Every path and version comparison
   goes through `scorer.normalize_path` / `normalize_version` / `version_segments`, so a pack can
   never be classified under one vocabulary and scored under another.

3. **It refuses rather than guesses.** An endpoint two surfaces both publish, with nothing to tell
   them apart, is `ambiguous` — not assigned to whichever surface a config file happened to list
   first. An endpoint no declared inventory contains is `unrecognized`, never "invented": that word
   is an accusation, and an inventory pinned on a date cannot support it.

Core knows nothing about any particular kind of API. There is no protocol branch here and no magic
path: a surface is a declared id, a label, some markers and a list of paths, all of it pack data.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .scorer import (_match_endpoints, normalize_path, normalize_version, states_host,
                     version_segments)

# Residual buckets. Named as observations about our own evidence, never as claims about the model:
# "we could not tell", "the answer disagreed with itself", "our inventories do not cover this".
AMBIGUOUS = "ambiguous"
CONFLICTED = "conflicted"
UNRECOGNIZED = "unrecognized"
RESIDUAL_BUCKETS = (AMBIGUOUS, CONFLICTED, UNRECOGNIZED)

# Run-level only: the answer identified none of the task's ground-truth endpoints, so there is no
# endpoint on which the surface question is even posed. Distinct from `unrecognized`, which is a
# statement about one endpoint we did classify.
NO_MATCH = "no-match"

DEFAULT_AMBIGUOUS_CEILING = 0.10


# --------------------------------------------------------------------------- #
# Declaration
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Surface:
    """One published API surface a pack declares, with the inventory that pins it."""
    id: str
    label: str
    measured: bool = False
    rationale: str = ""
    version_markers: tuple[str, ...] = ()
    # Recorded as EVIDENCE and reported as a count; never a discriminator. The prompt contract tells
    # the model "request path only — no scheme/host/tenant", so a host can only appear on an answer
    # that broke the contract. Leaning on it would make the highest-precedence signal the one that
    # fires least and least legitimately. See `SurfaceReport.host_stated`.
    host_markers: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    # Declared operation names, counted as PROSE CORROBORATION only (see `count_operation_mentions`).
    # Never matched against the path field: an operation name is not a path, and a bare list of short
    # names carries exactly the false-positive pathology that `scorer._AUTH_STYLES` documents at
    # length and that the vendor-token guard was burned by.
    operations: tuple[str, ...] = ()
    coverage: str = ""
    source_url: str = ""
    fetched_at: str = ""
    digest: str = ""

    @property
    def normalized_paths(self) -> frozenset[tuple[str, ...]]:
        return frozenset(tuple(normalize_path(p)) for p in self.paths)

    @property
    def normalized_markers(self) -> frozenset[str]:
        return frozenset(normalize_version(m) for m in self.version_markers if str(m).strip())


@dataclass(frozen=True)
class SurfaceSet:
    """The surfaces a pack declares. Declaration order is DISPLAY order and nothing else.

    Order deliberately does not break ties. If it did, listing the measured surface first would
    classify every under-specified answer as correct (manufacturing the null result) and listing a
    superseded one first would manufacture the finding. Either way it would be a thumb on the scale
    wearing a config field's clothing. `test_declaration_order_changes_no_classification` pins it.
    """
    surfaces: tuple[Surface, ...]
    ambiguous_ceiling: float = DEFAULT_AMBIGUOUS_CEILING

    def __bool__(self) -> bool:
        return bool(self.surfaces)

    @property
    def measured(self) -> Surface | None:
        return next((s for s in self.surfaces if s.measured), None)

    def by_id(self, sid: str) -> Surface | None:
        return next((s for s in self.surfaces if s.id == sid), None)

    def label_for(self, bucket: str) -> str:
        surface = self.by_id(bucket)
        return surface.label if surface else bucket

    def coverage_note(self) -> str:
        parts = [f"{s.id}: {s.coverage.strip()}" for s in self.surfaces if s.coverage.strip()]
        return " | ".join(parts)


def load_surface_set(config: dict | None, root: Path | None = None) -> SurfaceSet:
    """Build a `SurfaceSet` from a pack's `answer_surfaces` block.

    A surface's paths may be written inline (`paths:`) or, for a transcription long enough to want
    its own provenance, in a sibling file named by `inventory:`. The sibling is the shape used for
    anything copied out of a published artifact, because it can carry the fields that make the copy
    checkable later — `source_url`, `fetched_at`, `digest`, `coverage` — which an inline list cannot.
    """
    if not config:
        return SurfaceSet(())
    import yaml

    out: list[Surface] = []
    for entry in (config.get("surfaces") or []):
        entry = dict(entry or {})
        inv: dict = {}
        if entry.get("inventory"):
            if root is None:
                raise ValueError(f"surface {entry.get('id')!r} names an inventory file but no pack "
                                 f"root was given to resolve it against")
            inv_path = Path(root) / entry["inventory"]
            inv = yaml.safe_load(inv_path.read_text()) or {}
        out.append(Surface(
            id=str(entry.get("id", "")),
            label=str(entry.get("label", entry.get("id", ""))),
            measured=bool(entry.get("measured", False)),
            rationale=str(entry.get("rationale", "") or ""),
            version_markers=tuple(str(m) for m in (entry.get("version_markers") or [])),
            host_markers=tuple(str(m) for m in (entry.get("host_markers") or [])),
            paths=tuple(str(p) for p in (entry.get("paths") or inv.get("paths") or [])),
            operations=tuple(str(o) for o in (entry.get("operations") or inv.get("operations") or [])),
            coverage=str(inv.get("coverage", entry.get("coverage", "")) or ""),
            source_url=str(inv.get("source_url", "") or ""),
            fetched_at=str(inv.get("fetched_at", "") or ""),
            digest=str(inv.get("digest", "") or ""),
        ))
    ceiling = config.get("ambiguous_ceiling", DEFAULT_AMBIGUOUS_CEILING)
    return SurfaceSet(tuple(out), float(ceiling))


# --------------------------------------------------------------------------- #
# Classifying one answer endpoint
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class EndpointVerdict:
    bucket: str            # a surface id, or one of RESIDUAL_BUCKETS
    basis: str             # why, in words, so a reader can re-derive it by hand
    host_stated: bool = False


def _sole(candidates: list[Surface], versions: list[str]) -> Surface | None:
    """The single candidate whose declared markers cover any of `versions`; None if 0 or >1."""
    seen = {v for v in versions if v}
    if not seen:
        return None
    hits = [s for s in candidates if s.normalized_markers & seen]
    return hits[0] if len(hits) == 1 else None


def classify_endpoint(path: str | None, api_version: str | None,
                      surfaces: SurfaceSet) -> EndpointVerdict:
    """Which declared surface does one answer endpoint belong to?

    Version evidence is read from BOTH the verbatim path's version segments and the stated
    `api_version` field, because they are independent and either may be absent. Across the archived
    cohort the path carries a version 79% of the time and the field 99% of the time; using only one
    would strand answers that used the other.
    """
    host = states_host(path)
    npath = tuple(normalize_path(path))
    candidates = [s for s in surfaces.surfaces if npath in s.normalized_paths]

    if not candidates:
        return EndpointVerdict(UNRECOGNIZED, "no declared inventory contains this path", host)
    if len(candidates) == 1:
        return EndpointVerdict(candidates[0].id,
                               f"the path appears only in {candidates[0].id}'s inventory", host)

    # Published by more than one surface — which is the interesting case, and the reason the
    # endpoint dimension alone cannot answer the question: `normalize_path` strips the version
    # segment that distinguishes them, on purpose, so two surfaces sharing a resource compare equal.
    ids = ", ".join(s.id for s in candidates)
    by_path = _sole(candidates, version_segments(path))
    by_field = _sole(candidates, [normalize_version(api_version)])

    if by_path and by_field and by_path.id != by_field.id:
        return EndpointVerdict(
            CONFLICTED,
            f"the path says {by_path.id} and the stated version says {by_field.id}", host)
    winner = by_path or by_field
    if winner:
        where = "the path's version segment" if by_path else "the stated api_version"
        return EndpointVerdict(winner.id, f"published by {ids}; {where} resolves it", host)
    return EndpointVerdict(
        AMBIGUOUS, f"published by {ids}, and the answer states no version that tells them apart",
        host)


def count_operation_mentions(text: str, surfaces: SurfaceSet) -> dict[str, int]:
    """Declared operation names appearing in an answer's prose, as CORROBORATION only.

    Reported in its own column and never folded into the classification. A model may name one
    surface's operation while emitting another surface's path; what it emitted is what an integrator
    would call, so the emitted path is what classifies the answer. This count exists so the prose
    signal is visible rather than lost, not so it can overrule the path.
    """
    import re
    out: dict[str, int] = {}
    for surface in surfaces.surfaces:
        n = 0
        for op in surface.operations:
            if op and re.search(rf"\b{re.escape(op)}\b", text or ""):
                n += 1
        if n:
            out[surface.id] = n
    return out


# --------------------------------------------------------------------------- #
# Rolling up to runs, and over a results directory
# --------------------------------------------------------------------------- #

@dataclass
class SurfaceReport:
    endpoints: Counter = field(default_factory=Counter)      # bucket -> answer endpoints
    runs: Counter = field(default_factory=Counter)           # bucket -> runs (incl. NO_MATCH)
    per_task: dict = field(default_factory=dict)             # task_id -> Counter of run buckets
    examples: dict = field(default_factory=dict)             # bucket -> Counter of (method, path)
    operation_mentions: Counter = field(default_factory=Counter)
    host_stated: int = 0
    total_endpoints: int = 0
    total_runs: int = 0

    @property
    def ambiguous_rate(self) -> float:
        return (self.endpoints[AMBIGUOUS] / self.total_endpoints) if self.total_endpoints else 0.0


def classify_run(task: dict, parsed, surfaces: SurfaceSet,
                 base_prefix: list[str] | None = None) -> tuple[str, list[EndpointVerdict]]:
    """Label one run, and return the per-endpoint verdicts behind the label.

    THE ROLLUP RULE, pre-registered rather than discovered: a run is labelled by the answer endpoint
    that MATCHED ground truth. 58% of archived answers carry more than one endpoint and 28% already
    state more than one version, so a rule is required and any rule is a substantive choice. This one
    is principled: where two surfaces publish the same resource the matched endpoint is exactly where
    the surface question lives, and where nothing matched the run already scores 0 on `endpoint` and
    the question is moot — reported as `no-match` rather than folded into a surface's count.
    """
    endpoints = list(parsed.summary.endpoints)
    verdicts = [classify_endpoint(e.path, e.api_version, surfaces) for e in endpoints]

    records = _match_endpoints(task["ground_truth"]["endpoints"], endpoints, base_prefix or [])
    matched_paths = {r["answer_path"] for r in records if r.get("matched")}
    for endpoint, verdict in zip(endpoints, verdicts):
        if "/" + "/".join(normalize_path(endpoint.path)) in matched_paths:
            return verdict.bucket, verdicts
    return NO_MATCH, verdicts


def classify_results_dir(results_dir: str | Path, tasks_by_id: dict, surfaces: SurfaceSet,
                         base_prefix: list[str] | None = None) -> SurfaceReport:
    """Classify every archived answer in a results dir. Reads only; writes nothing."""
    from .analyze import iter_parsed_runs

    report = SurfaceReport()
    if not surfaces:
        return report
    for task_id, task, record, parsed in iter_parsed_runs(results_dir, tasks_by_id):
        label, verdicts = classify_run(task, parsed, surfaces, base_prefix)
        report.total_runs += 1
        report.runs[label] += 1
        report.per_task.setdefault(task_id, Counter())[label] += 1
        for endpoint, verdict in zip(parsed.summary.endpoints, verdicts):
            report.total_endpoints += 1
            report.endpoints[verdict.bucket] += 1
            report.host_stated += 1 if verdict.host_stated else 0
            if verdict.bucket in RESIDUAL_BUCKETS:
                report.examples.setdefault(verdict.bucket, Counter())[
                    (endpoint.method or "?", endpoint.path or "?")] += 1
        for sid, n in count_operation_mentions(record.get("raw_response", ""), surfaces).items():
            report.operation_mentions[sid] += n
    return report


def _pct(n: int, total: int) -> str:
    return f"{100.0 * n / total:5.1f}%" if total else "    — "


def format_report(report: SurfaceReport, surfaces: SurfaceSet) -> tuple[str, int]:
    """Render the split. Returns `(text, n_residual)` on the established report contract."""
    if not surfaces:
        return "(no answer surfaces declared for this pack)", 0
    if not report.total_endpoints:
        return "(no parsed answers in this results directory)", 0

    lines: list[str] = []
    over = report.ambiguous_rate > surfaces.ambiguous_ceiling
    lines.append("## Answer surfaces — which published surface did the model answer with?\n")

    if over:
        # Refusing to print a table we have said is not reportable is the point of declaring a
        # ceiling. A number printed with a caveat gets quoted without the caveat.
        lines.append(
            f"**NOT REPORTABLE.** {report.endpoints[AMBIGUOUS]} of {report.total_endpoints} answer "
            f"endpoints ({report.ambiguous_rate:.1%}) name a path that more than one declared "
            f"surface publishes, with no version to tell them apart — above the pack's declared "
            f"ceiling of {surfaces.ambiguous_ceiling:.0%}. The split is not printed, because a "
            f"denominator that unresolved would be quoted without its caveat.\n")

    lines.append("### By answer endpoint\n")
    lines.append("| bucket | endpoints | share |")
    lines.append("|---|---:|---:|")
    for surface in surfaces.surfaces:
        n = report.endpoints[surface.id]
        mark = " *(measured)*" if surface.measured else ""
        lines.append(f"| {surface.label}{mark} | {n} | {_pct(n, report.total_endpoints)} |")
    for bucket in RESIDUAL_BUCKETS:
        lines.append(f"| _{bucket}_ | {report.endpoints[bucket]} | "
                     f"{_pct(report.endpoints[bucket], report.total_endpoints)} |")
    lines.append(f"| **total** | **{report.total_endpoints}** | |")

    lines.append("\n### By run (labelled by the endpoint that matched ground truth)\n")
    lines.append("| bucket | runs | share |")
    lines.append("|---|---:|---:|")
    for surface in surfaces.surfaces:
        n = report.runs[surface.id]
        lines.append(f"| {surface.label} | {n} | {_pct(n, report.total_runs)} |")
    for bucket in (*RESIDUAL_BUCKETS, NO_MATCH):
        lines.append(f"| _{bucket}_ | {report.runs[bucket]} | "
                     f"{_pct(report.runs[bucket], report.total_runs)} |")
    lines.append(f"| **total** | **{report.total_runs}** | |")

    lines.append(f"\n- Answers stating a scheme or host in `path` (the prompt contract forbids it): "
                 f"**{report.host_stated}** of {report.total_endpoints}. Reported rather than "
                 f"assumed: no classification rule here uses the host.")
    if report.operation_mentions:
        named = ", ".join(f"{surfaces.label_for(k)} ×{v}"
                          for k, v in sorted(report.operation_mentions.items()))
        lines.append(f"- Declared operation names appearing in answer prose (corroboration only, "
                     f"never classification): {named}.")
    for bucket in RESIDUAL_BUCKETS:
        entries = report.examples.get(bucket)
        if not entries:
            continue
        lines.append(f"\n**{bucket}, verbatim:**\n")
        for (method, path), count in entries.most_common(12):
            lines.append(f"  {method:6s} {path}   (x{count})")

    # The coverage strings go LAST and one per line. They are what stops `unrecognized` being read as
    # "these endpoints do not exist", so they have to be legible — joined into one paragraph they were
    # a wall nobody would read, which is the same as not printing them.
    if report.endpoints[UNRECOGNIZED] and surfaces.coverage_note():
        lines.append("\n`unrecognized` means **outside the inventories below**, not non-existent. "
                     "Each is a copy taken on a date:\n")
        for surface in surfaces.surfaces:
            if surface.coverage.strip():
                lines.append(f"- **{surface.id}** — {' '.join(surface.coverage.split())}")

    n_residual = sum(report.endpoints[b] for b in RESIDUAL_BUCKETS)
    return "\n".join(lines), n_residual


def unclassified_ground_truth(tasks: list[dict], surfaces: SurfaceSet,
                              base_prefix: list[str] | None = None) -> list[str]:
    """Ground-truth endpoints that do NOT classify as the pack's measured surface.

    The known-good control for an inventory, in the shape ADR-0010 established for answer keys: a
    pack's own ground truth, run through the classifier, must land on the surface the pack says it
    measures. A mis-transcribed or over-broad inventory fails here — at the `roundtrip` gate, before
    a grid burns — rather than silently reporting a wrong split afterwards.
    """
    measured = surfaces.measured
    if not surfaces or measured is None:
        return []
    problems: list[str] = []
    for task in tasks:
        for endpoint in task.get("ground_truth", {}).get("endpoints", []) or []:
            verdict = classify_endpoint(endpoint.get("path"), endpoint.get("api_version"), surfaces)
            if verdict.bucket != measured.id:
                problems.append(
                    f"{task['id']}: ground truth {endpoint.get('method')} {endpoint.get('path')} "
                    f"classifies as '{verdict.bucket}', not the measured surface "
                    f"'{measured.id}' — {verdict.basis}")
    return problems


def load_report(results_dir: str | Path) -> dict:
    """The archived `scores.json` metadata for a results dir, or {} when absent."""
    path = Path(results_dir) / "scores.json"
    return json.loads(path.read_text()).get("metadata", {}) if path.is_file() else {}
