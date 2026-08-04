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

from . import scorer, surfaces
from .contract import API_CONTRACT, contract_for
from .pack import Pack
from .roundtrip_api import _MOCK_AUTH_PHRASE, answer_from_ground_truth  # noqa: F401 (re-exported)
from .scorer import TaskScore


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


def _collect(control: TaskControl, score: TaskScore, path_label: str, dimensions) -> None:
    """Fold one TaskScore into the control: any applicable dimension below 1.0 is a problem."""
    for name in dimensions:
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


def check_task(task: dict, base_prefix: list[str] | None = None, contract=None) -> TaskControl:
    """Round-trip one task. Takes a plain dict so a caller can hand it deliberately hostile input.

    `contract` defaults to the API contract, so every existing caller — including a test handing in
    a bare dict with no pack — behaves exactly as it did before ADR-0044.
    """
    contract = contract or API_CONTRACT
    control = TaskControl(task_id=str(task.get("id") or "(unnamed task)"))
    gt = task.get("ground_truth")
    if not isinstance(gt, dict):
        control.ok = False
        control.problems.append("task has no ground_truth mapping")
        return control

    answer = contract.answer_from_ground_truth(task)

    # Path 1 — direct: the scorer against an answer object built straight from ground truth.
    control.direct = contract.score_task(task, answer, base_prefix)
    _collect(control, control.direct, "direct", contract.dimensions)

    # Path 2 — text: the same answer serialized to a block and parsed back, which is the path a
    # real response takes. This is what proves the answer key is expressible in the contract.
    control.block_text = contract.render_block(answer)
    result = contract.parse(control.block_text)
    if result.is_failure:
        control.problems.append(
            f"parsed: ground truth rendered as an answer block does not parse — "
            f"{result.failure.reason}"
        )
    else:
        control.parsed = contract.score_task(task, result.summary, base_prefix)
        _collect(control, control.parsed, "parsed", contract.dimensions)

    # Blocking checks the contract runs before any grid may burn. For the API cohort these are
    # ADR-0011's unnameable login style and ADR-0023's alternate-style declaration rules; for the
    # docs cohort, a task that declares no scorable value at all. Both answer the same question —
    # can every dimension this task will be scored on actually be tested?
    control.problems.extend(contract.roundtrip_problems(task))

    # Non-blocking notes: shapes that score but measure less than they appear to.
    control.notes.extend(contract.roundtrip_notes(task))

    # Defensive: `auth_flow` is always applicable today, so an all-n/a task is unreachable for the
    # API cohort. The guard stands so that a future n/a rule cannot quietly create tasks that pass
    # by measuring nothing at all — and for the docs cohort, where several classes are legitimately
    # n/a per task, it is the backstop behind the contract's own check.
    applicable = [d for d in contract.dimensions if d not in control.na_dimensions]
    if not applicable:
        control.problems.append(
            "every dimension is n/a — this task would pass the control vacuously and measure nothing"
        )

    control.ok = not control.problems
    return control


def dimension_coverage(pack: Pack, contract, task_controls: list[TaskControl]) -> TaskControl:
    """Does every dimension this contract declares have at least one task? (ADR-0045)

    THE CONVERSE OF THE ROUND-TRIP CONTROL, AND IT HAD TO BE ASKED SEPARATELY. `check_task` asks
    whether each TASK can score something; a task whose every dimension is n/a blocks there. Nothing
    asked whether each DIMENSION has a task, so a pack could declare three dimensions, exercise two,
    and publish an overall that is the mean of two while its card, its contract and its results table
    all said three. That is what happened (public #81), and every gate passed.

    It is the vacuous-green shape this project keeps closing, one level up: the existing guards are
    about an empty ROW, and this is the same fault about an empty COLUMN. Harder to see, too — the
    cell reads `n/a`, a word this project uses legitimately and often.

    A pack may declare a dimension unexercised, but only in writing. The reason is the whole point:
    "this vendor publishes no firmware revision" is a legitimate finding a reviewer can check and
    disagree with, and silence is not. Same bargain as `short_text_ok` (ADR-0021) and
    `auth_flow_not_corroborable` (ADR-0041).

    A STALE DECLARATION BLOCKS TOO, and that direction matters more than it looks: a pack that later
    adds a firmware task keeps a pack.yaml saying it has none, and the next reader believes the file.

    TWO SEVERITIES, AND THE SPLIT IS THE ARGUMENT.

    * A dimension with no task and no declaration is COHORT-SCOPED (`contract.coverage_blocks`).
      Running this gate over every pack on disk for the first time found the condition in 13 of 18,
      so blocking every cohort would have failed eleven already-published packs over something this
      cycle is not repairing. `docs` blocks; `api` warns, with the count recorded in ADR-0045 and
      each pack filed. A warning that names the dimension is still the thing that was missing.
    * A DECLARATION that is wrong — an unknown name, a blank reason, or one contradicted by a task —
      blocks in EVERY cohort. Those exist only because a pack opted in, so no existing pack is
      touched, and a false statement in a pack file is worse than the silence it replaced.
    """
    declared = dict(getattr(pack, "unexercised_dimensions", None) or {})
    scored = [c for c in task_controls if c.task_id != "(suite)"]
    exercised = {
        d for d in contract.dimensions
        if any(d not in c.na_dimensions for c in scored)
    }
    problems: list[str] = []       # blocking
    coverage: list[str] = []       # blocking only where `contract.coverage_blocks`
    notes: list[str] = []

    unknown = sorted(set(declared) - set(contract.dimensions))
    if unknown:
        problems.append(
            f"unexercised_dimensions names {', '.join(unknown)}, which the '{contract.name}' "
            f"contract does not declare (its dimensions are {', '.join(contract.dimensions)})"
        )

    if not scored:
        problems.append("the pack has no tasks, so no dimension can be exercised by one")

    for dim in contract.dimensions:
        reason = str(declared.get(dim, "")).strip()
        if dim in exercised:
            if dim in declared:
                problems.append(
                    f"pack.yaml declares '{dim}' unexercised, but a task does exercise it — a stale "
                    "declaration is a false statement about the pack, so it blocks rather than "
                    "being ignored"
                )
            continue
        if dim not in declared:
            coverage.append(
                f"no task exercises '{dim}', which the '{contract.name}' contract declares and the "
                "overall is a mean over. Add a task, or declare it in pack.yaml under "
                "`unexercised_dimensions` with a written reason a reviewer can disagree with"
            )
        elif not reason:
            problems.append(
                f"'{dim}' is declared unexercised with no written reason. The reason is what makes "
                "the tolerance reviewable; a bare key grants it for free"
            )
        else:
            # Echoed, not merely accepted: a declaration filed where nobody reads it is the decay
            # mode ADR-0015 exists to catch.
            notes.append(f"'{dim}' unexercised by declaration — {reason}")

    if getattr(contract, "coverage_blocks", False):
        problems += coverage
    else:
        notes += [f"WARNING (advisory for the '{contract.name}' cohort): {c}" for c in coverage]

    n = len(exercised)
    if not problems:
        notes.append(
            f"{n} of {len(contract.dimensions)} declared dimension(s) exercised by a task"
            + ("" if n == len(contract.dimensions) else
               f"; every published overall for this pack is a mean over those {n}")
        )
    return TaskControl(task_id="(dimension-coverage)", ok=not problems,
                       problems=problems, notes=notes)


def check_pack(pack: Pack) -> list[TaskControl]:
    """Round-trip every task in a pack. Never raises: a broken task becomes a reported problem.

    The factory's gate loop has no exception handling around it, so a gate that raises would crash
    the dispatcher instead of blocking the target with a written reason. Blocking is the contract.
    """
    try:
        tasks = pack.load_tasks()
    except Exception as exc:  # unreadable/invalid task YAML is a control failure, not a crash
        return [TaskControl(task_id="(suite)", ok=False, problems=[f"tasks could not be loaded: {exc}"])]

    try:
        contract = contract_for(pack)
    except KeyError as exc:
        return [TaskControl(task_id="(suite)", ok=False, problems=[str(exc)])]

    controls: list[TaskControl] = []
    for task in tasks:
        if not isinstance(task, dict):
            controls.append(TaskControl(
                task_id="(suite)", ok=False, problems=["a task file did not parse to a mapping"],
            ))
            continue
        try:
            controls.append(check_task(task, getattr(pack, "base_prefix_segments", None), contract))
        except Exception as exc:
            controls.append(TaskControl(
                task_id=str(task.get("id") or "(unnamed task)"), ok=False,
                problems=[f"round-trip raised {type(exc).__name__}: {exc}"],
            ))

    controls.append(dimension_coverage(pack, contract, controls))

    # An endpoint-base tolerance must cite the first-party artifact that writes the address that
    # way (ADR-0055). Checked HERE, at the gate that runs before a grid burns, for the reason the
    # cohort-wide audit found: a tolerance can only move the endpoint dimension UP, so an uncited
    # one is indistinguishable from a score rescue until someone reads the vendor's documents by
    # hand. The round-trip control structurally cannot catch it either — an answer key always
    # matches itself, whatever notation it is written in.
    #
    # The bare-string form is NOT blocked here, and that is a deployment constraint rather than a
    # softened bar: this gate ships in `core`, the packs ship in a separate repository, and each
    # cannot land the other's half first (ADR-0055, rule 5). Every unconverted entry is counted in
    # a note instead, so the number is visible on every gate run rather than resting on someone
    # remembering — which is the decay mode ADR-0015 exists to catch. Issue #98 flips it.
    try:
        raw_bp = getattr(pack, "endpoint_base_prefix", None)
        bp = scorer.base_prefix_problems(raw_bp)
        bare = scorer.bare_prefix_entries(raw_bp)
        controls.append(TaskControl(
            task_id="(endpoint-base-evidence)", ok=not bp, problems=bp,
            notes=([f"{len(bare)} endpoint-base prefix(es) still declared in the pre-ADR-0055 "
                    f"bare-string form, citing nothing: {', '.join(bare)}"] if bare else [])))
    except Exception as exc:
        controls.append(TaskControl(
            task_id="(endpoint-base-evidence)", ok=False,
            problems=[f"base-prefix control raised {type(exc).__name__}: {exc}"]))

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
