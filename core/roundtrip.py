"""The ground-truth round-trip control: can a task score its own answer key? (ADR-0010)

Score every task against an answer equal to its own ground truth and require a perfect score. A
task that cannot score 1.0 against itself is an unscoreable instrument, and no amount of model
spend will produce a meaningful number from it.

WHAT THIS PROVES — and, just as importantly, what it does not.

An answer key equal to itself always matches itself, so this control **cannot detect a wrong answer
key**. It would pass a pack whose every path carried a mistaken prefix, which is exactly the fault
that produced it. What it does prove is:

  1. Every task is scoreable at all — a model returning exactly the documented answer key would be
     scored 1.0, not counted a format failure or marked against an unreachable dimension.
  2. The scorer treats ground truth and answers symmetrically. The control is symmetric by
     construction today, so it is a tripwire rather than a strong test: it fires the moment anyone
     adds a normalization rule to `scorer.py` that applies to one side and not the other.
  3. The answer key survives the answer-block contract's serialize -> parse boundary.
  4. Every dimension the task will be scored on can actually be tested. A ground-truth login style
     the scorer cannot name is blocked here (ADR-0011): auth_flow would score 1.0 for any answer
     that also named nothing recognizable, so the dimension would read as applicable while
     measuring nothing. That is the one failure this control catches *before* it becomes a number.

Its real value is procedural. When a dimension reads 0.00 across every task and both conditions,
the suspect-instrument rule says the harness is the suspect before the vendor is. This control
settles the scorer half of that question mechanically, before a grid is ever run, instead of
after the money is spent.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import surfaces
from .answer_block import AnswerSummary, Endpoint, parse, render_block
from .pack import Pack
from .scorer import (
    _AUTH_STYLES,
    DIMENSIONS,
    UNKNOWN_AUTH,
    TaskScore,
    alternate_problems,
    canonical_auth_flow,
    score_task,
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


@dataclass
class TaskControl:
    """The result of round-tripping one task's ground truth through the scorer."""

    task_id: str
    ok: bool = True
    problems: list[str] = field(default_factory=list)   # blocking: an imperfect or unparseable answer
    na_dimensions: list[str] = field(default_factory=list)  # reported, never a failure
    notes: list[str] = field(default_factory=list)      # thin-instrument warnings, non-blocking
    direct: TaskScore | None = None
    parsed: TaskScore | None = None                     # None when the text path format-failed
    block_text: str = ""                                # the rendered block, for audit


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


def _collect(control: TaskControl, score: TaskScore, path_label: str) -> None:
    """Fold one TaskScore into the control: any applicable dimension below 1.0 is a problem."""
    for name in DIMENSIONS:
        dim = score.dim(name)
        if dim is None:
            control.problems.append(f"{path_label}: dimension '{name}' was not scored at all")
            continue
        if dim.score is None:
            if name not in control.na_dimensions:
                control.na_dimensions.append(name)
            continue
        if dim.score != 1.0:
            control.problems.append(
                f"{path_label}: {name} scored {dim.score:.2f} against its own ground truth "
                f"({dim.detail})"
            )


def check_task(task: dict, base_prefix: list[str] | None = None) -> TaskControl:
    """Round-trip one task. Takes a plain dict so a caller can hand it deliberately hostile input."""
    control = TaskControl(task_id=str(task.get("id") or "(unnamed task)"))
    gt = task.get("ground_truth")
    if not isinstance(gt, dict):
        control.ok = False
        control.problems.append("task has no ground_truth mapping")
        return control

    answer = answer_from_ground_truth(task)

    # Path 1 — direct: the scorer against an answer object built straight from ground truth.
    control.direct = score_task(task, answer, base_prefix)
    _collect(control, control.direct, "direct")

    # Path 2 — text: the same answer serialized to a block and parsed back, which is the path a
    # real response takes. This is what proves the answer key is expressible in the contract.
    control.block_text = render_block(answer)
    result = parse(control.block_text)
    if result.is_failure:
        control.problems.append(
            f"parsed: ground truth rendered as an answer block does not parse — "
            f"{result.failure.reason}"
        )
    else:
        control.parsed = score_task(task, result.summary, base_prefix)
        _collect(control, control.parsed, "parsed")

    # Blocking: a login style the scorer cannot name is a scoring hole, not a thin instrument.
    # auth_flow would score 1.0 for any answer that also names nothing recognizable, so the
    # dimension reads as applicable while testing nothing (ADR-0011). The fix is always a new
    # style in `scorer._AUTH_STYLES`, never a rewrite of the vendor's documented prose.
    if canonical_auth_flow(gt.get("auth_flow")) == UNKNOWN_AUTH:
        control.problems.append(
            "auth_flow names no login style the scorer recognizes, so the dimension scores 1.0 for "
            "any answer that also names none — it would read as applicable while measuring nothing. "
            f"Teach the style to scorer._AUTH_STYLES (known: {_KNOWN_STYLES})"
        )

    # Blocking: a declared set of acceptable login styles is checked here, before any grid, because
    # a bad declaration never fails loudly at scoring time — it silently changes what counts as a
    # correct answer. Each rule is argued in `scorer.alternate_problems` (ADR-0023).
    control.problems.extend(alternate_problems(gt))

    # Non-blocking notes: shapes that score but measure less than they appear to.
    raw_params = gt.get("key_parameters") or []
    if raw_params and not any(
        isinstance(p, dict) and p.get("required") is True for p in raw_params
    ):
        control.notes.append(
            "no key_parameter is marked `required: true`, so the key_parameters dimension is n/a "
            "for this task and measures nothing"
        )
    # Defensive: `auth_flow` is always applicable today, so an all-n/a task is unreachable. The
    # guard stands so that a future n/a rule cannot quietly create tasks that pass by measuring
    # nothing at all.
    applicable = [d for d in DIMENSIONS if d not in control.na_dimensions]
    if not applicable:
        control.problems.append(
            "every dimension is n/a — this task would pass the control vacuously and measure nothing"
        )

    control.ok = not control.problems
    return control


def check_pack(pack: Pack) -> list[TaskControl]:
    """Round-trip every task in a pack. Never raises: a broken task becomes a reported problem.

    The factory's gate loop has no exception handling around it, so a gate that raises would crash
    the dispatcher instead of blocking the target with a written reason. Blocking is the contract.
    """
    try:
        tasks = pack.load_tasks()
    except Exception as exc:  # unreadable/invalid task YAML is a control failure, not a crash
        return [TaskControl(task_id="(suite)", ok=False, problems=[f"tasks could not be loaded: {exc}"])]

    controls: list[TaskControl] = []
    for task in tasks:
        if not isinstance(task, dict):
            controls.append(TaskControl(
                task_id="(suite)", ok=False, problems=["a task file did not parse to a mapping"],
            ))
            continue
        try:
            controls.append(check_task(task, getattr(pack, "base_prefix_segments", None)))
        except Exception as exc:
            controls.append(TaskControl(
                task_id=str(task.get("id") or "(unnamed task)"), ok=False,
                problems=[f"round-trip raised {type(exc).__name__}: {exc}"],
            ))

    # A pack that declares published surfaces (ADR-0037) must classify its OWN ground truth as the
    # surface it says it measures. Same register as the round-trip above and for the same reason: an
    # inventory that is mis-transcribed, stale or too broad produces a confident, wrong split, and
    # nothing downstream can tell. Checked here so it BLOCKS at the roundtrip gate — before a grid
    # burns — rather than being discovered in a card.
    try:
        declared = pack.answer_surfaces
        if declared:
            problems = surfaces.unclassified_ground_truth(
                tasks, declared, getattr(pack, "base_prefix_segments", None))
            if declared.measured is None:
                problems = ["no declared surface is marked `measured: true`", *problems]
            controls.append(TaskControl(task_id="(answer-surfaces)", ok=not problems,
                                        problems=problems))
    except Exception as exc:
        controls.append(TaskControl(
            task_id="(answer-surfaces)", ok=False,
            problems=[f"surface control raised {type(exc).__name__}: {exc}"]))
    return controls


def format_report(controls: list[TaskControl]) -> tuple[str, int]:
    """Render the control report and return (text, number of problems). Mirrors validate.format_report."""
    lines: list[str] = []
    total = 0
    for c in sorted(controls, key=lambda c: c.task_id):
        total += len(c.problems)
        flag = "ok  " if c.ok else "FAIL"
        suffix = f"  (n/a: {', '.join(c.na_dimensions)})" if c.na_dimensions else ""
        lines.append(f"{flag} {c.task_id}{suffix}")
        for problem in c.problems:
            lines.append(f"       - {problem}")
        for note in c.notes:
            lines.append(f"       ~ note: {note}")
    if total:
        failed = sum(1 for c in controls if not c.ok)
        lines.append(f"\n✗ {total} problem(s) across {failed} task(s): ground truth does not score itself")
    else:
        lines.append(f"\n✓ all {len(controls)} task(s) score their own ground truth 1.0")
    return "\n".join(lines), total


def summarize_failures(controls: list[TaskControl], *, limit: int = 3) -> str:
    """A one-line reason for the factory's queue entry — short, because it lands in a YAML field."""
    failed = [c for c in controls if not c.ok]
    if not failed:
        return ""
    shown = "; ".join(f"{c.task_id}: {c.problems[0]}" for c in failed[:limit])
    if len(failed) > limit:
        shown += f"; (+{len(failed) - limit} more)"
    return shown
