"""The prompt-sanity gate: does the question name what it is asking about? (ADR-0031)

WHY THIS EXISTS

Every other gate in this project reads the **answer key**. `validate` checks the task file's schema,
`roundtrip` proves the answer key scores itself, `anchoring` proves the answer key points at a real
operation, and the truncation audit proves the documentation we inject still contains it. Not one of
them reads the **question**.

That gap cost a full grid. Twelve prompts described their target as "this vendor's API" and named
nobody; three quarters of the cold runs were the measured model correctly refusing to guess, and the
whole grid had to be thrown away after the money was spent. Every gate passed, because a prompt that
is answerable but under-specified is invisible to all of them.

THE RULE

A pack declares two lists of names in `pack.yaml`'s `vendor:` block, and every task prompt must name
at least one from each:

    vendor:
      vendor_names:  [...]   # who sells it
      product_names: [...]   # what the API is

Both are required, and a pack that declares neither fails closed — there is no default, no skip flag
and no exemption list. Making the pack SAY what counts as naming its target is most of the value: the
author has to write the claim down where a reviewer can read it.

A name may legitimately appear in both lists, because a distinctive product name identifies its
vendor exactly as well as the vendor's own name does. That judgement is the author's and is argued in
ADR-0031; this module only reports the overlap (see `dual_listed`) so it is visible in every run
rather than buried in a config file.

WHAT IT CANNOT DO — and these are recorded as hazards, not papered over

  1. **It cannot tell a vendor-unique product name from a bare corporate parent.** Both are strings.
     ADR-0031 rules that a distinctive product qualifies for dual-listing and a bare parent never
     does, and that rule is enforced by review, not by this file.
  2. **It cannot tell a good question from a bad one.** A prompt can name both and still be leading,
     ambiguous, or wrong about what it is asking for. This gate closes exactly one failure mode: the
     question that does not say what it is about.
  3. **It cannot see the answer-block contract suffix** appended by `core/prompt.py`, which is
     deliberately vendor-free and shared by every condition. Only the task's own prompt is read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pack import Pack


def _name_pattern(name: str) -> re.Pattern[str]:
    """A whole-word matcher for one declared name; internal runs of space match any whitespace.

    Word-bounded rather than a plain substring, and that is load-bearing rather than tidy. Several
    real product names are short abbreviations, and a bare `in` test would find one of them inside
    an ordinary English word — a prompt that never names the target would pass because the letters
    happen to occur in "discovery". A gate that can pass on an accident is worse than none, since it
    reports coverage it does not have.
    """
    escaped = r"\s+".join(re.escape(part) for part in name.split())
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def names_in(text: str, names: list[str]) -> list[str]:
    """Which of `names` the text actually names, in declaration order. [] means none."""
    return [n for n in names if _name_pattern(n).search(text or "")]


def dual_listed(pack: Pack) -> list[str]:
    """Names declared as BOTH a vendor name and a product name (case-insensitive).

    Reported, never rejected: ADR-0031 permits this for a product distinctive enough to identify its
    vendor, and forbids it for a bare corporate parent. Core cannot tell those apart, so the overlap
    is surfaced by name for a human to check instead of being silently allowed or wrongly blocked.
    """
    products = {n.strip().lower() for n in pack.product_names}
    return [n for n in pack.vendor_names if n.strip().lower() in products]


def declaration_problems(pack: Pack) -> list[str]:
    """Problems with the DECLARATION itself, before any prompt is read. Fail-closed."""
    problems: list[str] = []
    for field_name, names in (("vendor_names", pack.vendor_names),
                              ("product_names", pack.product_names)):
        if not names:
            problems.append(
                f"pack.yaml declares no `vendor.{field_name}`, so there is nothing to check a prompt "
                "against — a pack must state what counts as naming its target (ADR-0031)"
            )
            continue
        for name in names:
            if not str(name).strip():
                # A blank name matches every prompt, which would turn the gate into a rubber stamp
                # while still reporting a pass. Refuse it rather than silently ignore it.
                problems.append(f"`vendor.{field_name}` contains a blank name, which would match "
                                "every prompt and make this gate vacuous")
    return problems


@dataclass
class PromptCheck:
    """The result of reading one task's prompt against the pack's declared names."""

    task_id: str
    vendor_hits: list[str] = field(default_factory=list)
    product_hits: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class PackPromptReport:
    vendor_id: str
    declaration_problems: list[str] = field(default_factory=list)
    tasks: list[PromptCheck] = field(default_factory=list)
    # Names declared as both a vendor name and a product name. Never a failure — see `dual_listed`.
    dual_listed: list[str] = field(default_factory=list)

    @property
    def failing_task_ids(self) -> list[str]:
        return [t.task_id for t in self.tasks if not t.ok]

    @property
    def total_problems(self) -> int:
        return len(self.declaration_problems) + sum(len(t.problems) for t in self.tasks)

    @property
    def ok(self) -> bool:
        return self.total_problems == 0


def check_task_prompt(task: dict, vendor_names: list[str], product_names: list[str]) -> PromptCheck:
    """Read one task's prompt. Takes plain lists so a caller can hand it hostile input."""
    check = PromptCheck(task_id=str(task.get("id") or "(unnamed task)"))
    prompt = task.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        check.problems.append("task has no prompt text")
        return check

    check.vendor_hits = names_in(prompt, vendor_names)
    check.product_hits = names_in(prompt, product_names)
    if not check.vendor_hits:
        check.problems.append(
            f"prompt names no vendor — none of {', '.join(vendor_names)} appears in it"
        )
    if not check.product_hits:
        check.problems.append(
            f"prompt names no product — none of {', '.join(product_names)} appears in it"
        )
    return check


def check_pack(pack: Pack) -> PackPromptReport:
    """Read every task prompt in a pack. Never raises: a broken task becomes a reported problem.

    The factory's gate loop has no exception handling around it, so a gate that raises would crash
    the dispatcher instead of blocking the target with a written reason (the contract `roundtrip`
    already follows).
    """
    report = PackPromptReport(vendor_id=pack.vendor_id)
    report.declaration_problems = declaration_problems(pack)
    report.dual_listed = dual_listed(pack)
    if report.declaration_problems:
        # Reading prompts against an unusable declaration would produce a flood of consequential
        # failures that hide the one real cause.
        return report

    try:
        tasks = pack.load_tasks()
    except Exception as exc:  # unreadable/invalid task YAML is a gate failure, not a crash
        report.declaration_problems.append(f"tasks could not be loaded: {exc}")
        return report

    for task in tasks:
        if not isinstance(task, dict):
            report.tasks.append(PromptCheck(
                task_id="(suite)", problems=["a task file did not parse to a mapping"]))
            continue
        report.tasks.append(check_task_prompt(task, pack.vendor_names, pack.product_names))

    if not report.tasks:
        report.declaration_problems.append("pack has no tasks, so this gate would pass vacuously")
    return report


def format_report(report: PackPromptReport) -> tuple[str, int]:
    """Render the report and return (text, number of problems). Mirrors `validate.format_report`."""
    lines: list[str] = []
    for problem in report.declaration_problems:
        lines.append(f"FAIL (suite)\n       - {problem}")
    for check in sorted(report.tasks, key=lambda c: c.task_id):
        flag = "ok  " if check.ok else "FAIL"
        hits = ""
        if check.ok:
            hits = f"  (vendor: {check.vendor_hits[0]}; product: {check.product_hits[0]})"
        lines.append(f"{flag} {check.task_id}{hits}")
        for problem in check.problems:
            lines.append(f"       - {problem}")

    total = report.total_problems
    if total:
        n_failed = len(report.failing_task_ids) or 1
        lines.append(f"\n✗ {total} problem(s) across {n_failed} task(s): a prompt that does not name "
                     "its target measures the question, not the vendor")
    else:
        lines.append(f"\n✓ all {len(report.tasks)} prompt(s) name a vendor and a product")
    if report.dual_listed:
        # Printed on pass as well as on failure: the overlap is exactly the claim ADR-0031 asks a
        # reviewer to check, so it has to be visible in the ordinary output, not only when something
        # is already wrong.
        lines.append(f"  note: declared as BOTH vendor and product — {', '.join(report.dual_listed)}"
                     "\n        (ADR-0031 permits this for a product distinctive enough to identify "
                     "its vendor, and\n         never for a bare corporate parent; core cannot tell "
                     "them apart, so this is a review item)")
    return "\n".join(lines), total


def summarize_failures(report: PackPromptReport, *, limit: int = 3) -> str:
    """A one-line reason for the factory's queue entry — short, because it lands in a YAML field."""
    if report.ok:
        return ""
    if report.declaration_problems:
        return report.declaration_problems[0]
    failing = [c for c in report.tasks if not c.ok]
    shown = "; ".join(f"{c.task_id}: {c.problems[0]}" for c in failing[:limit])
    if len(failing) > limit:
        shown += f"; (+{len(failing) - limit} more)"
    return shown
