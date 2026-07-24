"""Deterministic scorer: compare a parsed answer to task ground truth (ADR-0004).

No LLM judging. Every dimension is a mechanical, normalized string comparison a
reviewer can reproduce from the archived raw response. Normalization rules and the
two judgment calls (any-of scopes; required-subset params) are documented in
ADR-0004 and echoed here at each rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .answer_block import AnswerSummary, Endpoint

# The six ADR-0002 dimensions.
DIMENSIONS = ("endpoint", "method", "api_version", "auth_flow", "required_scopes", "key_parameters")

# A path segment that is a version marker (stripped anywhere before path compare, so
# `/v3/search` and the newer per-service `/search/v1` both reduce to the resource `search`;
# the v3-vs-v1 difference is captured by the api_version dimension, not the path dimension).
_VERSION_SEG_RE = re.compile(r"^(v\d+|beta|oauth|v20\d\d)$", re.IGNORECASE)
_BRACE_SEG_RE = re.compile(r"^\{.*\}$")


# --------------------------------------------------------------------------- #
# Normalization helpers (each mirrors a rule in ADR-0004).
# --------------------------------------------------------------------------- #

def normalize_path(path: str | None) -> list[str]:
    """Return comparable, version-stripped, lowercased path segments.

    Strips scheme/host/tenant and any query string; strips a leading version
    segment (v3/beta/oauth/v20xx, or a `<service>/v1` pair); lowercases; and
    collapses any `{placeholder}` segment to a single `{}` sentinel so a
    ground-truth `{param}` matches any braced placeholder regardless of name.
    """
    if not path:
        return []
    p = path.strip()
    # strip scheme://host
    if "://" in p:
        p = p.split("://", 1)[1]
        slash = p.find("/")
        p = p[slash:] if slash != -1 else "/"
    # a bare host with no scheme but a dot before the first slash -> drop host
    elif not p.startswith("/") and "/" in p and "." in p.split("/", 1)[0]:
        p = "/" + p.split("/", 1)[1]
    # strip query string / fragment
    p = p.split("?", 1)[0].split("#", 1)[0]
    # drop version-marker segments wherever they appear (leading /v3, /beta, /oauth,
    # or a trailing per-service /v1), leaving the resource path for comparison
    segments = [s for s in p.split("/") if s != "" and not _VERSION_SEG_RE.match(s)]
    out: list[str] = []
    for seg in segments:
        seg = seg.strip()
        out.append("{}" if _BRACE_SEG_RE.match(seg) else seg.lower())
    return out


def normalize_method(method: str | None) -> str:
    return (method or "").strip().upper()


# Ways a model says "this API has no version segment". The answer-block contract names no
# canonical spelling for the empty case (unlike required_scopes, which specifies "[] if none"),
# so an unversioned API draws all of these — plus an omitted key, which is already "" (ADR-0008).
_NO_VERSION = {"none", "n/a", "na", "null", "nil", "unversioned", "no version", "-", "--"}


def normalize_version(version: str | None) -> str:
    """Canonical form of an API version. Every spelling of "there isn't one" collapses to "".

    Sentinels are stripped of surrounding <>, (), [] first, so `<none>` reads as `none`. This is
    symmetric: it applies to ground truth and answer alike, and a sentinel answered against a real
    version (`none` vs `v3`) still compares unequal, so no versioned vendor's score can move.
    """
    v = (version or "").strip().lstrip("/").lower()
    if len(v) >= 2 and v[0] in "<([" and v[-1] in ">)]":
        v = v[1:-1].strip()
    return "" if v in _NO_VERSION else v


def _auth_concepts(text: str | None) -> set[str]:
    """The set of auth concepts a string mentions, separator-insensitive.

    'client credentials', 'client-credentials', 'client_credentials' all count as the
    client-credentials grant; 'bearer' counts as a bearer token.
    """
    t = (text or "").lower().replace("-", " ").replace("_", " ")
    concepts: set[str] = set()
    if "client credentials" in t:
        concepts.add("client-credentials")
    if "bearer" in t:
        concepts.add("bearer")
    return concepts


def canonical_auth_flow(text: str | None) -> str:
    """A single display label for an auth string (client-credentials is the more specific)."""
    c = _auth_concepts(text)
    if "client-credentials" in c:
        return "oauth2-client-credentials"
    if "bearer" in c:
        return "bearer-token"
    return "unknown"


def auth_flow_matches(gt_text: str | None, answer_text: str | None) -> bool:
    """True if the answer contains the ground truth's PRIMARY auth concept.

    Ground-truth prose can mention both concepts (the grant task describes obtaining a JWT
    *bearer* token via *client-credentials*), so we pick the more specific present concept as
    the requirement: client-credentials for the token-grant task, bearer for the per-call tasks.
    The answer matches if it names that concept — an answer that additionally mentions the
    other concept (e.g. "client credentials bearer token") still matches.
    """
    gt = _auth_concepts(gt_text)
    if not gt:
        return canonical_auth_flow(gt_text) == canonical_auth_flow(answer_text)
    required = "client-credentials" if "client-credentials" in gt else "bearer"
    return required in _auth_concepts(answer_text)


def bare_scope(scope: str | None) -> str:
    """Strip an inline `# comment` and whitespace; lowercase to the raw token."""
    if not scope:
        return ""
    return scope.split("#", 1)[0].strip().lower()


# --------------------------------------------------------------------------- #
# Result types.
# --------------------------------------------------------------------------- #

@dataclass
class DimensionScore:
    name: str
    score: float | None            # 0.0-1.0, or None when not applicable to this task
    detail: str = ""

    @property
    def applicable(self) -> bool:
        return self.score is not None


@dataclass
class TaskScore:
    task_id: str
    format_failure: bool = False
    failure_reason: str | None = None
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)
    endpoint_matches: list[dict] = field(default_factory=list)

    def dim(self, name: str) -> DimensionScore | None:
        return self.dimensions.get(name)


# --------------------------------------------------------------------------- #
# Scoring.
# --------------------------------------------------------------------------- #

def _match_endpoints(gt_eps: list[dict], ans_eps: list[Endpoint]) -> list[dict]:
    """Greedily match each ground-truth endpoint to an answer endpoint by path.

    Returns one record per ground-truth endpoint with match + method/version flags.
    Method and api_version are only credited when the path matched (you cannot have
    the right method on an endpoint you never identified).
    """
    used: set[int] = set()
    ans_norm = [(i, normalize_path(e.path)) for i, e in enumerate(ans_eps)]
    records: list[dict] = []
    for gt in gt_eps:
        gt_path = normalize_path(gt.get("path"))
        gt_method = normalize_method(gt.get("method"))
        gt_version = normalize_version(gt.get("api_version"))
        match_idx = None
        for i, npath in ans_norm:
            if i in used:
                continue
            if npath == gt_path:
                match_idx = i
                break
        rec = {
            "gt_method": gt_method,
            "gt_path": "/" + "/".join(gt_path),
            "gt_api_version": gt_version,
            "matched": match_idx is not None,
            "method_ok": False,
            "version_ok": False,
            "answer_method": None,
            "answer_path": None,
            "answer_api_version": None,
        }
        if match_idx is not None:
            used.add(match_idx)
            ans = ans_eps[match_idx]
            rec["answer_method"] = normalize_method(ans.method)
            rec["answer_path"] = "/" + "/".join(normalize_path(ans.path))
            rec["answer_api_version"] = normalize_version(ans.api_version)
            rec["method_ok"] = rec["answer_method"] == gt_method
            rec["version_ok"] = rec["answer_api_version"] == gt_version
        records.append(rec)
    return records


def score_task(task: dict, answer: AnswerSummary) -> TaskScore:
    """Score one parsed answer against one task's ground truth."""
    gt = task["ground_truth"]
    result = TaskScore(task_id=task["id"])

    # --- endpoint / method / api_version (per-endpoint, aggregated) ---------
    gt_eps = gt["endpoints"]
    records = _match_endpoints(gt_eps, answer.endpoints)
    result.endpoint_matches = records
    total = len(records)
    matched = sum(1 for r in records if r["matched"])
    result.dimensions["endpoint"] = DimensionScore(
        "endpoint", matched / total if total else None,
        f"{matched}/{total} ground-truth endpoints found",
    )
    result.dimensions["method"] = DimensionScore(
        "method", (sum(1 for r in records if r["method_ok"]) / total) if total else None,
        f"{sum(1 for r in records if r['method_ok'])}/{total} methods correct on matched paths",
    )
    result.dimensions["api_version"] = DimensionScore(
        "api_version", (sum(1 for r in records if r["version_ok"]) / total) if total else None,
        f"{sum(1 for r in records if r['version_ok'])}/{total} api_versions correct",
    )

    # --- auth_flow (concept containment; ADR-0004) --------------------------
    gt_auth = canonical_auth_flow(gt.get("auth_flow"))
    ans_auth = canonical_auth_flow(answer.auth_flow)
    matched = auth_flow_matches(gt.get("auth_flow"), answer.auth_flow)
    result.dimensions["auth_flow"] = DimensionScore(
        "auth_flow", 1.0 if matched else 0.0,
        f"required {gt_auth}, got {ans_auth}",
    )

    # --- required_scopes (any-of overlap; ADR-0004 judgment call) -----------
    gt_scopes = {bare_scope(s) for s in gt.get("required_scopes", []) if bare_scope(s)}
    ans_scopes = {bare_scope(s) for s in answer.required_scopes if bare_scope(s)}
    if not gt_scopes:
        result.dimensions["required_scopes"] = DimensionScore(
            "required_scopes", None, "no scopes required by ground truth (n/a)",
        )
    else:
        overlap = gt_scopes & ans_scopes
        result.dimensions["required_scopes"] = DimensionScore(
            "required_scopes", 1.0 if overlap else 0.0,
            f"matched {sorted(overlap) or '[]'} of acceptable {sorted(gt_scopes)}",
        )

    # --- key_parameters (required-subset containment; ADR-0004 judgment call)
    gt_required = {
        str(p["name"]).strip().lower()
        for p in gt.get("key_parameters", [])
        if isinstance(p, dict) and p.get("required") is True and p.get("name")
    }
    ans_params = {p.strip().lower() for p in answer.key_parameters if p and p.strip()}
    if not gt_required:
        result.dimensions["key_parameters"] = DimensionScore(
            "key_parameters", None, "no required parameters in ground truth (n/a)",
        )
    else:
        missing = gt_required - ans_params
        result.dimensions["key_parameters"] = DimensionScore(
            "key_parameters", 1.0 if not missing else 0.0,
            f"missing {sorted(missing)}" if missing else f"all required present {sorted(gt_required)}",
        )

    return result


def format_failure_score(task_id: str, reason: str) -> TaskScore:
    """A TaskScore standing in for an unparseable answer — distinct, never zeroed."""
    return TaskScore(task_id=task_id, format_failure=True, failure_reason=reason)
