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

# A DOTTED numeric version, with the `v` optional: `2.0`, `2.1`, `v2.0` (ADR-0025, AMENDED by
# ADR-0027). Used by `normalize_version` to fold the `v`, and by `normalize_path` to strip the
# segment — the same treatment `_VERSION_SEG_RE` already gets, which is the whole point of ADR-0027.
#
# ADR-0025 originally kept this OUT of `normalize_path`, reasoning that stripping `2.0` would make
# the 404-ing `/api/v2.0/jobs/create` compare equal to the real path. That reasoning was true and
# beside the point: it is equally true of `/v99/accounts` against `/v3/accounts`, which this scorer
# has always compared EQUAL on purpose — see the `_VERSION_SEG_RE` comment above, which states the
# design in as many words. The effect of the exception was that a vendor spelling its version `2.1`
# rather than `v2` paid for ONE mistake in TWO dimensions while every other measured vendor paid in
# one, which makes its headline incomparable to theirs. See ADR-0027.
#
# The dot is required on purpose, and now does double duty. Folding a bare `v1` to `1` is a
# different question with a different risk profile — `v1` appears 694 times across the archived
# cohort, so that fold could move published numbers, and no measured vendor needs it. The dot is
# ALSO what keeps identifier segments out of the path stripper: `/accounts/123` keeps its `123`,
# because `123` has no dot and is not a version.
_DOTTED_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)+)$", re.IGNORECASE)


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
    segments = [s for s in p.split("/")
                if s != "" and not _VERSION_SEG_RE.match(s) and not _DOTTED_VERSION_RE.match(s)]
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
    # A service-qualified version is the same version (ADR-0020). The prompt contract offers
    # `<service>/v1` as a legal answer in its own right, so an API documented as versioned per
    # service — `ledger/v1`, `report/v1` — gets answered in that form by a model that has read the
    # documentation, and would otherwise compare unequal to a ground truth written `v1`. Applied
    # symmetrically, so it can only ever collapse a difference the contract already said was not
    # one. It cannot credit the wrong service: `api_version` is scored only on an endpoint whose
    # PATH already matched, and the path is where the service segment lives.
    head, sep, tail = v.rpartition("/")
    if sep and head and "/" not in head and (
            _VERSION_SEG_RE.match(tail) or _DOTTED_VERSION_RE.match(tail)):
        v = tail
    # A dotted numeric version means the same thing with or without a leading `v` (ADR-0025). Some
    # vendors number their paths `/api/2.0/...` with no `v` anywhere, while the prompt contract's own
    # example demonstrates `v1` — so a model following our contract answers `v2.0` for an API that
    # is genuinely `2.0` and loses the dimension on notation. Applied symmetrically to ground truth
    # and answer alike, so it can only collapse a difference, never create a match between two
    # different versions: `2.0` and `2.1` still compare unequal.
    dotted = _DOTTED_VERSION_RE.match(v)
    if dotted:
        v = dotted.group(1)
    return "" if v in _NO_VERSION else v


# The login styles the scorer can positively name, MOST SPECIFIC FIRST (ADR-0011). The first style
# present in a string is the one that string requires, so this order is load-bearing:
#
#   * session-token outranks the OAuth styles because a session token is minted by one vendor's own
#     login call, and because OAuth words appear inside session-token prose as NEGATIONS ("not an
#     OAuth2 flow: there is no client_credentials grant") that substring matching cannot read.
#   * basic-auth and api-key rank BELOW bearer because a Basic login that returns a bearer token
#     sends the bearer token on every subsequent call, and the per-request credential is what this
#     dimension measures.
#
# Markers are matched after `-`/`_` are folded to spaces and the text is lowercased, so
# `client_credentials`, `Basic-auth` and `sessionId` all land. A style is added here, never worked
# around in a pack's ground truth — the `roundtrip` gate blocks a pack whose style is not listed.
_AUTH_STYLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # hmac-signature ranks FIRST because prose describing request signing necessarily names the key
    # it signs with ("the `Api-Key` header ... signed with an API secret"), so any lower slot is
    # shadowed by `api-key` and the dimension inverts: the answer that correctly says "HMAC-SHA256
    # request signature" scores 0 while "send your API key" scores 1. Markers are deliberately
    # narrow — bare `signature`/`signed` would recapture "signed JWT client assertion", which is
    # OAuth prose in two already-published packs (ADR-0023).
    ("hmac-signature", ("hmac", "message signature", "request signature", "request signing")),
    # `session` and `logon` name the concept broadly on purpose. A first, narrower marker list of
    # exact phrases scored 0 for answers reading "session bearer token" and "session cookie via
    # authString login" — correct namings of the mechanism, failed on wording. That made the
    # dimension measure our phrasebook. Bare `login` is deliberately NOT a marker: it appears in
    # OAuth-shaped ground truth ("Basic-auth login ... POST /api/login") and would reclassify it.
    ("session-token", ("session", "logon")),
    ("oauth2-client-credentials", ("client credentials",)),
    ("bearer-token", ("bearer",)),
    ("basic-auth", ("basic auth", "basic authentication", "http basic")),
    ("api-key", ("api key", "apikey", "subscription key")),
    # access-token ranks LAST on purpose. "access token" appears inside OAuth prose across the
    # cohort ("send the returned value as `Authorization: Bearer <access_token>`"), so any higher
    # slot would re-canonicalize published ground truth. Last, it can only fire where nothing else
    # did, which makes its addition provably score-neutral for every archived pack (ADR-0023).
    ("access-token", ("access token", "accesstoken")),
)

UNKNOWN_AUTH = "unknown"

#: The style names a pack may declare in `ground_truth.auth_flow_alternates`.
KNOWN_AUTH_STYLES: tuple[str, ...] = tuple(style for style, _markers in _AUTH_STYLES)

# Hosts that rehost someone else's document rather than publish it. An alternate login style has to
# carry first-party evidence that the vendor itself documents it (ADR-0023), and this is the same
# bar ground-truth anchors already meet (ADR-0017). Kept as a denylist, not an allowlist: an
# allowlist of vendor docs hosts fails OPEN for a host nobody has listed yet, which is the wrong
# direction for a guard.
NOT_FIRST_PARTY: tuple[str, ...] = (
    "web.archive.org",
    "archive.org",
    "archive.is",
    "archive.ph",
    "archive.today",
    "webcache.googleusercontent.com",
    "cachedview.nl",
    "r.jina.ai",
    "12ft.io",
)


def rehosting_host(url: str | None) -> str | None:
    """The `NOT_FIRST_PARTY` host this URL sits on, or None if it is first-party.

    Returns None for a URL that is not http(s) at all; the caller reports that separately, because
    "no scheme" and "an archive host" are different authoring mistakes and deserve different words.
    """
    from urllib.parse import urlsplit
    host = (urlsplit(url or "").hostname or "").lower()
    return next((bad for bad in NOT_FIRST_PARTY if host == bad or host.endswith("." + bad)), None)


def _auth_concepts(text: str | None) -> set[str]:
    """The set of login styles a string mentions, separator-insensitive."""
    t = (text or "").lower().replace("-", " ").replace("_", " ")
    return {style for style, markers in _AUTH_STYLES if any(m in t for m in markers)}


def canonical_auth_flow(text: str | None) -> str:
    """The one login style a string requires: the first `_AUTH_STYLES` entry it mentions."""
    present = _auth_concepts(text)
    for style, _markers in _AUTH_STYLES:
        if style in present:
            return style
    return UNKNOWN_AUTH


def declared_alternates(ground_truth: dict | None) -> list[str]:
    """The alternate login-style names a task declares, in file order (ADR-0023).

    Reads only well-formed entries. A malformed declaration is not silently dropped — it is caught
    by `alternate_problems`, which the `roundtrip` gate runs before any grid, so a typo blocks the
    pack instead of quietly widening or quietly narrowing what counts as correct.
    """
    raw = (ground_truth or {}).get("auth_flow_alternates") or []
    if not isinstance(raw, list):
        return []
    return [str(a["style"]) for a in raw if isinstance(a, dict) and a.get("style")]


def alternate_problems(ground_truth: dict | None) -> list[str]:
    """Every reason a task's `auth_flow_alternates` declaration is not acceptable (ADR-0023).

    A set of acceptable login styles is otherwise a way to make any answer right, so each of these
    is blocking rather than a note. The rules, and why each one exists:

      1. The style must be a name the scorer knows. A typo would otherwise widen nothing and read
         as if it had widened something — the declaration would look honoured and score as if absent.
      2. It must differ from the style the prose already requires, so a redundant declaration can
         never be mistaken for evidence that two styles were considered.
      3. It must carry a first-party evidence URL. The claim being made is that *the vendor*
         documents this style as valid, and a copy of a document is not the vendor's claim (ADR-0017).
      4. Its markers must appear in `auth_flow` itself. This is the rule that keeps the widening
         honest: the answer key a human reads has to visibly say that both styles are accepted,
         rather than the acceptance living in a field nobody reads next to prose that contradicts it.
      5. The accepted set must stay a proper subset of the known styles, so no task can reach a
         state where the dimension is applicable but unfalsifiable.
    """
    gt = ground_truth or {}
    raw = gt.get("auth_flow_alternates")
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        return ["auth_flow_alternates must be a non-empty list (omit the key entirely if there are none)"]

    problems: list[str] = []
    prose = gt.get("auth_flow")
    required = canonical_auth_flow(prose)
    seen: set[str] = set()
    markers = dict(_AUTH_STYLES)

    for i, entry in enumerate(raw):
        where = f"auth_flow_alternates[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where} is not a mapping with style/evidence/note")
            continue
        style = str(entry.get("style") or "").strip()
        if style not in KNOWN_AUTH_STYLES:                                          # rule 1
            problems.append(
                f"{where}: '{style or '(missing)'}' is not a login style the scorer knows "
                f"(known: {', '.join(KNOWN_AUTH_STYLES)})"
            )
            continue
        if style == required:                                                       # rule 2
            problems.append(
                f"{where}: '{style}' is already the style auth_flow requires, so declaring it as an "
                "alternate widens nothing and misrepresents the key as covering two styles"
            )
        if style in seen:
            problems.append(f"{where}: '{style}' is declared more than once")
        seen.add(style)

        evidence = str(entry.get("evidence") or "").strip()
        if not evidence.startswith(("http://", "https://")):                        # rule 3
            problems.append(
                f"{where}: needs an `evidence:` URL on the vendor's own documentation showing that "
                "it documents this style as valid for this operation"
            )
        else:
            bad = rehosting_host(evidence)
            if bad is not None:
                problems.append(
                    f"{where}: evidence is on {bad}, which rehosts rather than publishes. An "
                    "alternate rests on the vendor's own claim (ADR-0017), never on a copy of it"
                )
        note = str(entry.get("note") or "").strip()
        if len(note) < 40:
            problems.append(
                f"{where}: needs a `note:` of at least 40 characters saying why the vendor treats "
                f"this style as valid here (got {len(note)})"
            )
        if not any(m in (prose or "").lower().replace("-", " ").replace("_", " ")
                   for m in markers.get(style, ())):                                # rule 4
            problems.append(
                f"{where}: auth_flow never names '{style}', so the answer key a reader sees does "
                "not say both styles are accepted. State it in the prose, not only in this field"
            )

    accepted = {required} | seen
    if required != UNKNOWN_AUTH and accepted >= set(KNOWN_AUTH_STYLES):              # rule 5
        problems.append(
            "auth_flow_alternates accepts every login style the scorer knows, so the dimension "
            "would be applicable but unfalsifiable"
        )
    return problems


def auth_flow_matches(gt_text: str | None, answer_text: str | None,
                      alternates: tuple[str, ...] | list[str] = ()) -> bool:
    """True if the answer names a login style this ground truth accepts.

    Ground-truth prose routinely mentions more than one style — the grant task describes obtaining a
    *bearer* token via *client-credentials*; a session-token product's prose says it is not OAuth —
    so the requirement is the most specific style present, per `_AUTH_STYLES` order. The answer
    matches if it names that style; naming additional styles as well does not hurt.

    `alternates` (ADR-0023) is the authored, evidenced set of *additional* styles the vendor
    documents as valid for this operation. It is never inferred from the prose: prose mentions a
    style for many reasons, including to deny it, and reading intent out of a substring is what
    made this dimension wrong in the first place. Default empty, so a single-style key scores
    exactly as it did before ADR-0023 — the accepted set is then `{required}` and nothing else.

    A ground truth naming no listed style falls back to comparing labels, which means `unknown`
    matches `unknown` — an answer scores as long as it too names nothing recognizable. That is why
    `roundtrip.check_task` refuses to let such a pack run at all (ADR-0011): the fallback is a
    scoring hole, kept only so the scorer degrades quietly instead of raising, never relied on.
    """
    required = canonical_auth_flow(gt_text)
    if required == UNKNOWN_AUTH:
        return canonical_auth_flow(answer_text) == UNKNOWN_AUTH
    return bool(({required} | set(alternates)) & _auth_concepts(answer_text))


def names_parameter(required: str, answer_names: set[str]) -> bool:
    """True if the answer names a required parameter, or a field inside it (ADR-0024).

    Ground truth names a request-body field at whatever depth the vendor's own documentation
    describes it — often a top-level container like `amount` or `source`. A model answering
    `amount.total` and `source.sourceType` has named that container *and* said which field inside it
    to fill, which is strictly more useful to a developer. Exact-match containment scored it 0.

    The rule is deliberately **asymmetric**, and the asymmetry is the whole design:

      - `amount.total` satisfies a requirement for `amount`. You cannot send `amount.total` without
        sending `amount`; naming the child proves the parent.
      - `amount` does NOT satisfy a requirement for `amount.total`. Naming a container proves
        nothing about which field inside it the caller supplied, and crediting it would let a vague
        answer pass a specific requirement. That direction is the one that manufactures a score, so
        it is refused and pinned by a must-not test.

    The separator must be a literal `.`, so `source_type` and `sourceDetails` do not satisfy
    `source` — only a genuine dotted path does.
    """
    return any(a == required or a.startswith(required + ".") for a in answer_names)


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

def _strip_base_prefix(segments: list[str], prefix: list[str]) -> list[str]:
    """Drop `prefix` from the front of `segments` if it is there. ADR-0017.

    Applied symmetrically to ground truth and answer, so the comparison stops depending on where
    two equally-official sources chose to end the base URL. Never guesses: the prefix is whatever
    the pack declared and nothing else, so this can only ever collapse a difference the pack has
    said in advance is not a difference.
    """
    if not prefix or len(segments) < len(prefix) or segments[:len(prefix)] != prefix:
        return segments
    return segments[len(prefix):]


def _match_endpoints(gt_eps: list[dict], ans_eps: list[Endpoint],
                     base_prefix: list[str] | None = None) -> list[dict]:
    """Greedily match each ground-truth endpoint to an answer endpoint by path.

    Returns one record per ground-truth endpoint with match + method/version flags.
    Method and api_version are only credited when the path matched (you cannot have
    the right method on an endpoint you never identified).

    `base_prefix` is empty for every pack that does not opt in, in which case this behaves
    exactly as it did before ADR-0017 and no archived score can move.
    """
    pre = base_prefix or []
    used: set[int] = set()
    ans_norm = [(i, _strip_base_prefix(normalize_path(e.path), pre)) for i, e in enumerate(ans_eps)]
    records: list[dict] = []
    for gt in gt_eps:
        gt_path = _strip_base_prefix(normalize_path(gt.get("path")), pre)
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
            # The EXHIBIT keeps what the model actually wrote; only the COMPARISON is normalized.
            # Recording the normalized form here would erase the evidence needed to tell a wrong
            # version from a differently-spelled right one — which is the investigation that found
            # ADR-0020 in the first place.
            rec["answer_api_version"] = ans.api_version
            rec["method_ok"] = rec["answer_method"] == gt_method
            rec["version_ok"] = normalize_version(ans.api_version) == gt_version
        records.append(rec)
    return records


def score_task(task: dict, answer: AnswerSummary,
               base_prefix: list[str] | None = None) -> TaskScore:
    """Score one parsed answer against one task's ground truth.

    `base_prefix` is the pack's opt-in endpoint-address tolerance (ADR-0017), already normalized to
    segments. Omitted or empty means the pre-ADR-0017 behaviour, exactly.
    """
    gt = task["ground_truth"]
    result = TaskScore(task_id=task["id"])

    # --- endpoint / method / api_version (per-endpoint, aggregated) ---------
    gt_eps = gt["endpoints"]
    records = _match_endpoints(gt_eps, answer.endpoints, base_prefix)
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

    # --- auth_flow (concept containment; ADR-0004, ADR-0023) ----------------
    gt_auth = canonical_auth_flow(gt.get("auth_flow"))
    ans_auth = canonical_auth_flow(answer.auth_flow)
    alternates = declared_alternates(gt)
    matched = auth_flow_matches(gt.get("auth_flow"), answer.auth_flow, alternates)
    accepted = f"{gt_auth} or {' or '.join(alternates)}" if alternates else gt_auth
    result.dimensions["auth_flow"] = DimensionScore(
        "auth_flow", 1.0 if matched else 0.0,
        f"required {accepted}, got {ans_auth}",
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
        missing = {g for g in gt_required if not names_parameter(g, ans_params)}
        result.dimensions["key_parameters"] = DimensionScore(
            "key_parameters", 1.0 if not missing else 0.0,
            f"missing {sorted(missing)}" if missing else f"all required present {sorted(gt_required)}",
        )

    return result


def format_failure_score(task_id: str, reason: str) -> TaskScore:
    """A TaskScore standing in for an unparseable answer — distinct, never zeroed."""
    return TaskScore(task_id=task_id, format_failure=True, failure_reason=reason)
