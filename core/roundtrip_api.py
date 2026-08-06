"""The API cohort's half of the round-trip control (ADR-0010, split out by ADR-0044).

`core/roundtrip.py` is the control itself and is now contract-agnostic: it renders a task's ground
truth as an answer, parses it back, scores it and requires 1.0 on every applicable dimension. What
is COHORT-specific is three things — how ground truth becomes an answer, which blocking checks apply
before a grid may run, and which shapes deserve a non-blocking note. Those live here for the API
cohort and in `core/docs_scorer.py` for the docs cohort, and a contract names them.

Nothing in this module is new. Every function was lifted unchanged out of `roundtrip.py` so that the
generic driver could stop importing `scorer` internals directly; the behaviour it describes is the
behaviour ADR-0011, ADR-0023 and ADR-0041 already argued for.
"""
from __future__ import annotations

from .answer_block import AnswerSummary, Endpoint
from .scorer import (
    _AUTH_STYLES,
    UNKNOWN_AUTH,
    alternate_problems,
    canonical_auth_flow,
    version_alternate_problems,
)

_KNOWN_STYLES = ", ".join(style for style, _markers in _AUTH_STYLES)

# The phrase the `--mock` provider answers with for each login style. Mock answers must score 1.0,
# or a pack's free plumbing preflight would report a failure that says nothing about the plumbing.
_MOCK_AUTH_PHRASE = {
    "hmac-signature": "HMAC message signature",
    "session-token": "Session token from the login call",
    "oauth2-client-credentials": "OAuth2 client-credentials",
    # Deliberately does NOT mention the bearer token the grant produces: this phrase has to
    # canonicalize to itself, and a realistic sentence about this flow would also say "Bearer"
    # (ADR-0030). That it cannot be written realistically is the point of the ordering it tests.
    "oauth2-authorization-code": "OAuth2 authorization code grant with PKCE",
    # Same constraint as the line above and for the same reason (ADR-0040): a realistic sentence
    # about the implicit grant names the access token it returns, and this phrase must canonicalize
    # to ITSELF, so it deliberately stops short of saying so.
    "oauth2-implicit": "OAuth2 implicit grant",
    "bearer-token": "OAuth2 bearer token",
    "basic-auth": "HTTP Basic auth",
    "api-key": "API key",
    "access-token": "Access token",
}


def answer_from_ground_truth(task: dict, *, canonical_auth: bool = False) -> AnswerSummary:
    """Build the answer a model would give if it reproduced this task's ground truth exactly.

    This mapping is the one place where the answer shape and the ground-truth shape are reconciled,
    so each translation is explicit:

    - `key_parameters` is a list of dicts in ground truth and a list of names in an answer.
    - `required_scopes` is passed through verbatim, inline `# comment` and all; `scorer.bare_scope`
      strips the comment on both sides, so a comment must not change the score.
    - `auth_flow` is passed through **verbatim** by default. Canonicalizing it would mean testing a
      phrase this function invented rather than the answer key the pack actually documents; the
      `--mock` provider is the only caller that wants the canonical form.
    """
    gt = task["ground_truth"]
    auth = gt.get("auth_flow")
    if canonical_auth:
        auth = _MOCK_AUTH_PHRASE.get(canonical_auth_flow(auth), "OAuth2 bearer token")
    return AnswerSummary(
        endpoints=[
            Endpoint(method=e.get("method"), path=e.get("path"), api_version=e.get("api_version"))
            for e in gt.get("endpoints", [])
        ],
        auth_flow=auth,
        required_scopes=[str(s) for s in gt.get("required_scopes") or []],
        key_parameters=[
            str(p["name"]) for p in gt.get("key_parameters") or []
            if isinstance(p, dict) and p.get("name")
        ],
    )


def roundtrip_problems(task: dict) -> list[str]:
    """Blocking checks the API contract runs before any grid may burn."""
    gt = task.get("ground_truth") or {}
    problems: list[str] = []

    # A login style the scorer cannot name is a scoring hole, not a thin instrument. auth_flow would
    # score 1.0 for any answer that also names nothing recognizable, so the dimension reads as
    # applicable while testing nothing (ADR-0011). The fix is always a new style in
    # `scorer._AUTH_STYLES`, never a rewrite of the vendor's documented prose.
    if canonical_auth_flow(gt.get("auth_flow")) == UNKNOWN_AUTH:
        problems.append(
            "auth_flow names no login style the scorer recognizes, so the dimension scores 1.0 for "
            "any answer that also names none — it would read as applicable while measuring nothing. "
            f"Teach the style to scorer._AUTH_STYLES (known: {_KNOWN_STYLES})"
        )

    # A declared set of acceptable login styles is checked here, before any grid, because a bad
    # declaration never fails loudly at scoring time — it silently changes what counts as a correct
    # answer. Each rule is argued in `scorer.alternate_problems` (ADR-0023).
    problems.extend(alternate_problems(gt))

    # And the same for a declared set of acceptable VERSIONS (ADR-0059). Checked here for the
    # identical reason: a bad declaration never fails loudly at scoring time, it silently changes
    # what counts as a correct answer — and this one can only ever move the dimension UP. Each rule
    # is argued in `scorer.version_alternate_problems`.
    problems.extend(version_alternate_problems(gt))
    return problems


def roundtrip_notes(task: dict) -> list[str]:
    """Non-blocking notes: shapes that score but measure less than they appear to."""
    gt = task.get("ground_truth") or {}
    raw_params = gt.get("key_parameters") or []
    if raw_params and not any(
        isinstance(p, dict) and p.get("required") is True for p in raw_params
    ):
        return [
            "no key_parameter is marked `required: true`, so the key_parameters dimension is n/a "
            "for this task and measures nothing"
        ]
    return []
