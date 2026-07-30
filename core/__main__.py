"""Eval harness CLI (ADR-0001, ADR-0002).

Usage:
    python -m core --pack packs/<vendor> run --condition no-context [--n 5] [--tasks id,id]
                                             [--model STR] [--out DIR] [--mock]
    python -m core --pack packs/<vendor> rebuild-report <results_dir>

Everything vendor-specific comes from the loaded pack (`--pack`, or the AIRE_PACK env var). Runs each
task N times under the chosen condition, parses the structured answer, scores it deterministically,
archives every raw response, and writes summary.md + scores.json. With no ANTHROPIC_API_KEY and no
--mock, a live run prints a BLOCKED message and exits without fabricating results.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

from . import answer_block, conditions
from .env import get_config, load_env
from .model import AnthropicModel, ClaudeCliModel, MockModel, ModelError
from .pack import Pack
from .report import write_reports
from .scorer import DIMENSIONS, format_failure_score, score_task

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_BLOCKED = 3


def _today() -> str:
    return datetime.date.today().isoformat()


def _load_pack(args: argparse.Namespace) -> Pack:
    pack_dir = getattr(args, "pack", None) or os.environ.get("AIRE_PACK")
    if not pack_dir:
        raise SystemExit("ERROR: no pack selected — pass --pack <dir> or set AIRE_PACK.")
    # A pack may live anywhere (including a private repo outside this tree). If --pack is not itself an
    # existing directory, resolve it as a bare name against --packs-dir / AIRE_PACKS_DIR.
    if not Path(pack_dir).is_dir():
        packs_dir = getattr(args, "packs_dir", None) or os.environ.get("AIRE_PACKS_DIR")
        if packs_dir and (Path(packs_dir) / pack_dir).is_dir():
            pack_dir = str(Path(packs_dir) / pack_dir)
    return Pack.load(pack_dir)


def _results_dir(pack: Pack) -> Path:
    return pack.root / "results"


def _record(task_id: str, run_index: int, score, resp, *,
            tool_discipline: dict | None = None, parsed=None, mock: bool = False) -> dict:
    dims = {d: (score.dim(d).score if score.dim(d) else None) for d in DIMENSIONS}
    rec = {
        "task_id": task_id,
        "run_index": run_index,
        "format_failure": score.format_failure,
        "failure_reason": score.failure_reason,
        "dimensions": dims,
        "endpoint_matches": score.endpoint_matches,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "cost_usd": getattr(resp, "cost_usd", 0.0),
        "duration_ms": getattr(resp, "duration_ms", 0),
        "tool_uses": getattr(resp, "tool_uses", []),
        "transcript": getattr(resp, "transcript", []),
        "raw_response": resp.text,
    }
    if tool_discipline is not None:
        rec["tool_discipline"] = tool_discipline
    # Provenance stamp. Written only on a mock run, so every real archive stays byte-identical and no
    # committed result moves — the same discipline `format_repaired` follows below. The resume path
    # reads it to refuse reusing a mock answer in a real grid; absence therefore has to mean "real",
    # which is exactly what it means for every archive written before this stamp existed.
    if mock:
        rec["mock"] = True
    # ADR-0014: present only on a run the repair actually rescued, so every
    # untouched archive stays byte-identical. The repaired text is archived with
    # it — a repaired score must stay reproducible from what was really parsed.
    if parsed is not None and getattr(parsed, "repaired", False):
        rec["format_repaired"] = True
        rec["repaired_block_text"] = parsed.repaired_block_text
    return rec


def may_reuse_archived_run(prev: dict, *, is_mock: bool) -> tuple[bool, str]:
    """Whether an archived run may stand in for a run we are about to make, and why not if not.

    Two independent conditions, both of which have to hold:

    * **Discipline.** A run that failed its tool-discipline assertion was never a valid measurement,
      so it is re-run rather than reused.
    * **Provenance.** A mock answer may only satisfy a mock run, and a real answer a real run.
      `--mock` writes its per-condition runs into the SAME date-stamped directory a real grid uses
      (only the mock *preflight* gets a directory of its own), so the documented dry-run sequence —
      `factory next --provider mock`, then `factory next --model <id>` on the same day — would
      otherwise resume straight off the mock answers and publish them under a metadata block naming
      the real model.

    Absence of the `mock` key means "real", which is what it means for every archive written before
    the stamp existed — so no committed result is invalidated and no re-run is forced.
    """
    if bool(prev.get("mock", False)) != is_mock:
        return False, ("archived run is mock, this run is not" if prev.get("mock")
                       else "archived run is real, this run is mock")
    if not prev.get("tool_discipline", {}).get("ok", True):
        return False, "archived run failed its tool-discipline assertion"
    return True, ""


def _score_response(task: dict, raw_text: str, base_prefix: list[str] | None = None):
    parsed = answer_block.parse(raw_text)
    if parsed.is_failure:
        return format_failure_score(task["id"], parsed.failure.reason), parsed
    return score_task(task, parsed.summary, base_prefix), parsed


# --------------------------------------------------------------------------- #
# Mock responses for offline smoke runs (--mock). Built from ground truth so the
# pipeline is exercised end-to-end; one task is deliberately broken to a no-block
# response so format-failure handling is demonstrated. Never committed as a baseline.
# --------------------------------------------------------------------------- #

def _mock_block_for_task(task: dict) -> str:
    from .answer_block import render_block
    from .roundtrip import answer_from_ground_truth

    # Shares one serializer with the round-trip control (ADR-0010) so the mock provider cannot drift
    # from the thing that gates it. `canonical_auth=True` is a mock-only convenience: the control
    # itself deliberately emits the ground truth's own auth prose verbatim.
    answer = answer_from_ground_truth(task, canonical_auth=True)
    answer.required_scopes = [s.split("#", 1)[0].strip() for s in answer.required_scopes]
    answer.required_scopes = [s for s in answer.required_scopes if s]
    return render_block(answer, preamble=f"Here is how you would approach **{task['id']}**.\n\n")


def _build_mock_responses(tasks: list[dict]) -> dict[str, str]:
    # NOT a round-trip control: the last task is deliberately broken so format-failure handling is
    # exercised. The control that requires every task to score its own ground truth is the
    # `roundtrip` gate (ADR-0010).
    responses: dict[str, str] = {}
    for i, task in enumerate(tasks):
        if i == len(tasks) - 1:
            # Deliberate format failure: prose with no answer-summary block.
            responses[task["id"]] = (
                f"To handle {task['id']} you'd call the relevant endpoint, "
                "but I'm not including a structured block here."
            )
        else:
            responses[task["id"]] = _mock_block_for_task(task)
    return responses


# --------------------------------------------------------------------------- #

def _preflight_gate(client, condition, pack: Pack, results_dir: Path) -> int:
    """Run the sterile/control canaries (+ server health for mcp) and gate the grid on them."""
    from . import preflight
    from .env import REPO_ROOT

    canary_dir = results_dir / f"{_today()}-sterile-canary"
    print("  preflight: canaries (sterile + repo-root control)...")
    try:
        verdict = preflight.run_canaries(client, project_marker=pack.project_marker,
                                         repo_root=REPO_ROOT)
    except ModelError as exc:
        print(f"BLOCKED: canary run failed on the transport: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    preflight.write_canary_artifacts(verdict, canary_dir)
    print(f"    sterile ignorant: {verdict['sterile']['ignorant']} "
          f"(tools={verdict['sterile']['available_tools']}) | "
          f"control recites: {verdict['control']['recites']}  →  {canary_dir}")
    if not verdict["passed"]:
        print("BLOCKED: canary gate failed — sterility not proven; refusing to start the grid "
              "(sterile must be ignorant, control must recite CLAUDE.md).", file=sys.stderr)
        return EXIT_BLOCKED
    if condition.name == "mcp":
        ctx = pack.context_layer
        print("  preflight: context-layer server health...")
        health = preflight.check_server_health(ctx.spawn_command, ctx.expected_tools)
        print(f"    server ok={health['ok']} tools={health['tools']}")
        if not health["ok"]:
            print(f"BLOCKED: mcp server health check failed: {health['detail']}", file=sys.stderr)
            return EXIT_BLOCKED
    return EXIT_OK


def cmd_canary(args: argparse.Namespace) -> int:
    """Run the sterile + repo-root control canaries standalone; write transcripts + verdict."""
    from . import preflight
    from .env import REPO_ROOT

    pack = _load_pack(args)
    explicit_model = args.model or load_env().get("EVAL_MODEL")
    try:
        client = ClaudeCliModel(explicit_model)
    except ModelError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    out = Path(args.out) if args.out else _results_dir(pack) / f"{_today()}-sterile-canary"
    try:
        verdict = preflight.run_canaries(client, project_marker=pack.project_marker,
                                         repo_root=REPO_ROOT)
    except ModelError as exc:
        print(f"BLOCKED: canary transport failure: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    preflight.write_canary_artifacts(verdict, out)
    print(f"sterile ignorant: {verdict['sterile']['ignorant']} "
          f"(available_tools={verdict['sterile']['available_tools']})")
    print(f"control recites:  {verdict['control']['recites']}")
    print(f"wrote transcripts + verdict → {out}")
    if args.check_server and pack.context_layer is not None:
        ctx = pack.context_layer
        health = preflight.check_server_health(ctx.spawn_command, ctx.expected_tools)
        print(f"server health: ok={health['ok']} tools={health['tools']} — {health['detail']}")
        if not health["ok"]:
            return EXIT_BLOCKED
    return EXIT_OK if verdict["passed"] else EXIT_BLOCKED


def _prompt_gate(pack: Pack) -> int:
    """Refuse to start a grid whose prompts do not name what they are asking about (ADR-0031).

    Called here rather than left to the factory because grids are run through this command far more
    often than they are dispatched by the factory, and the requirement is that NO grid spends money
    on an under-specified question. The rule itself is not duplicated — `prompt_gate.check_pack` is
    the single implementation, and `factory.check_prompts` is the other caller.
    """
    from .prompt_gate import check_pack, format_report

    report = check_pack(pack)
    if report.ok:
        return EXIT_OK
    text, total = format_report(report)
    print(
        f"BLOCKED: {total} prompt problem(s) — a grid against these would measure the question, not "
        "the vendor.\n"
        "A prompt that does not name its target is answerable-but-under-specified: it passes every "
        "other gate,\nbecause every other gate reads the answer key (ADR-0031).\n\n"
        f"{text}",
        file=sys.stderr,
    )
    return EXIT_BLOCKED


# The format-failure circuit breaker (ADR-0032). Both numbers are derived from the cohort's own
# history, not chosen — see the ADR for the derivation and for what this cannot do.
FORMAT_FAILURE_THRESHOLD = 0.20
FORMAT_FAILURE_FLOOR = 20


def format_failure_breaker(records: list[dict], threshold: float,
                           floor: int = FORMAT_FAILURE_FLOOR) -> str:
    """A written reason to stop this condition, or "" to keep going.

    Pure over the records so the decision can be replayed against any archived grid — which is how
    the claim "this fires on none of the cohort's published conditions" is actually checked rather
    than asserted.

    Reused archived runs are counted like fresh ones. A resume that ignored them could work through
    a grid that already had a broken question and never trip, which is laundering, not resuming.
    """
    n = len(records)
    if threshold >= 1.0 or n < floor:
        return ""
    n_fail = sum(1 for r in records if r.get("format_failure"))
    rate = n_fail / n
    if rate <= threshold:
        return ""
    by_task: dict[str, int] = {}
    for r in records:
        if r.get("format_failure"):
            key = r.get("task_id", "?")
            by_task[key] = by_task.get(key, 0) + 1
    worst = ", ".join(f"{t}×{c}" for t, c in sorted(by_task.items(), key=lambda kv: -kv[1])[:5])
    return (f"{n_fail}/{n} runs ({rate:.0%}) failed to produce a parseable answer block, over the "
            f"{threshold:.0%} threshold; worst tasks: {worst}")


def cmd_run(args: argparse.Namespace) -> int:
    pack = _load_pack(args)
    condition = conditions.get_condition(args.condition, pack)
    only = set(args.tasks.split(",")) if args.tasks else None
    tasks = pack.load_tasks(only)
    if not tasks:
        print("ERROR: no tasks matched", file=sys.stderr)
        return EXIT_ERROR

    # Before the transport is even constructed: the cheapest gate runs first, and a mock run is
    # exempt because it spends nothing and exists to prove plumbing.
    if not args.mock:
        rc = _prompt_gate(pack)
        if rc != EXIT_OK:
            return rc

    api_key, default_model = get_config()
    explicit_model = args.model or load_env().get("EVAL_MODEL")  # None => let transport default

    client, mock, provider, sampling = None, None, args.provider, None
    if args.mock:
        mock = MockModel(_build_mock_responses(tasks))
        provider, sampling = "mock", "n/a"
        model_name = "mock-model"
    elif args.provider == "cli":
        try:
            client = ClaudeCliModel(explicit_model)  # None => CLI/subscription default model
        except ModelError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_ERROR
        # Pre-run health check so we fail fast instead of mid-run.
        try:
            pong = client.ping()
        except ModelError as exc:
            print(f"BLOCKED: Claude subscription transport is not working: {exc}",
                  file=sys.stderr)
            return EXIT_BLOCKED
        model_name = explicit_model or pong.model_reported or "claude-cli-default"
        sampling = "cli default (temperature not configurable via CLI)"
        print(f"  ping OK ({pong.model_reported or 'model?'}): {pong.text.strip()[:20]!r}")
        # Model-pin guard: an unpinned CLI run silently uses the operator's session-default model,
        # which may differ from the pinned comparison model and confound the whole grid. Refuse to
        # run unpinned unless explicitly allowed.
        if not explicit_model and not args.allow_unpinned_model:
            print(
                "BLOCKED: no model pinned for a cli run — the CLI would use the session default "
                f"(ping reported {pong.model_reported!r}), which may not match the comparison "
                "baseline. Pass --model <id>, or --allow-unpinned-model to run on the session "
                "default deliberately.",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        if explicit_model and pong.model_reported and explicit_model not in pong.model_reported:
            print(f"  WARNING: requested model {explicit_model!r} but ping reported "
                  f"{pong.model_reported!r} — check the alias resolves as intended.")
    else:  # api
        model_name = explicit_model or default_model
        if not api_key:
            print(
                "BLOCKED: --provider api needs ANTHROPIC_API_KEY (none in environment or .env).\n"
                "Use --provider cli to run via the Claude subscription, or --mock offline.",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        try:
            client = AnthropicModel(api_key, model_name)
        except ModelError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_ERROR
        sampling = "temperature=0"

    date = _today()
    out_dir = Path(args.out) if args.out else _results_dir(pack) / f"{date}-{condition.name}"
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    policy = condition.cli_policy() if hasattr(condition, "cli_policy") else None
    metadata = {
        "condition": condition.name,
        "model": model_name,
        "provider": provider,
        "sampling": sampling,
        "date": date,
        "spec_sha": pack.spec_sha(),
        "n": args.n,
        "mock": bool(args.mock),
    }
    if policy is not None and provider == "cli":
        metadata["cli_policy"] = {
            "disallowed_tools": policy.disallowed_tools,
            "allowed_tools": policy.allowed_tools,
            "mcp_config": policy.mcp_config,
            "strict_mcp": policy.strict_mcp,
            "permission_mode": policy.permission_mode,
        }

    # Pre-flight hard gate: prove sterility works (and, for mcp, the server connects) BEFORE burning
    # the grid. Skippable only for resumes after a canary has already passed.
    if provider == "cli" and not args.mock and not getattr(args, "skip_preflight", False):
        rc = _preflight_gate(client, condition, pack, _results_dir(pack))
        if rc != EXIT_OK:
            return rc

    max_tool_retries = 3
    records: list[dict] = []
    reported_models: set[str] = set()
    total_cost, total_ms = 0.0, 0
    reused = 0
    violations: list[dict] = []
    # A mock grid answers from a fixed phrase table, so its failure rate says nothing about a
    # question; the breaker is off for it, exactly as the pre-grid gate is.
    ff_threshold = 1.0 if args.mock else float(args.format_failure_threshold)
    stopped_early = ""
    for task in tasks:
        if stopped_early:
            break
        for run_index in range(args.n):
            run_path = runs_dir / f"{task['id']}-run{run_index}.json"
            # Resumable: reuse an archived run only if it is still a valid stand-in for the run we
            # would otherwise make. See `may_reuse_archived_run` for the two conditions and why the
            # provenance one is load-bearing rather than bookkeeping.
            if run_path.exists() and not args.overwrite:
                prev = json.loads(run_path.read_text())
                reusable, why_not = may_reuse_archived_run(prev, is_mock=mock is not None)
                if reusable:
                    records.append(prev)
                    total_cost += prev.get("cost_usd", 0.0)
                    total_ms += prev.get("duration_ms", 0)
                    reused += 1
                    print(f"  {task['id']} run {run_index + 1}/{args.n}: reused (archived)")
                    stopped_early = format_failure_breaker(records, ff_threshold)
                    if stopped_early:
                        break
                    continue
                print(f"  {task['id']} run {run_index + 1}/{args.n}: re-running ({why_not})")

            messages = condition.build_messages(task)
            system = condition.system_prompt(task)
            discipline = {"ok": True, "detail": "n/a (mock/api)", "attempts": 1}
            if mock is not None:
                resp = mock.complete_for_task(task["id"])
            else:
                resp = None
                try:
                    for attempt in range(1, max_tool_retries + 1):
                        resp = client.complete(messages, system=system, policy=policy)
                        ok, detail = condition.check_tools(resp.tool_uses)
                        discipline = {"ok": ok, "detail": detail, "attempts": attempt}
                        if ok:
                            break
                        violations.append({"task": task["id"], "run": run_index, "attempt": attempt,
                                           "detail": detail,
                                           "tools": [t.get("name") for t in resp.tool_uses]})
                        print(f"  ! {task['id']} run {run_index + 1}: DISCIPLINE VIOLATION "
                              f"(attempt {attempt}): {detail} — re-running")
                except ModelError as exc:
                    print(f"  ! {task['id']} run {run_index + 1}: transport error, skipping "
                          f"(resume will retry): {str(exc)[:120]}")
                    continue
            if getattr(resp, "model_reported", None):
                reported_models.add(resp.model_reported)
            total_cost += getattr(resp, "cost_usd", 0.0)
            total_ms += getattr(resp, "duration_ms", 0)
            score, parsed = _score_response(task, resp.text, pack.base_prefix_segments)
            rec = _record(task["id"], run_index, score, resp, tool_discipline=discipline,
                          parsed=parsed, mock=mock is not None)
            records.append(rec)
            run_path.write_text(json.dumps(rec, indent=2))
            status = "FMT-FAIL" if score.format_failure else "scored"
            if rec.get("format_repaired"):
                status += " [FMT-REPAIRED]"
            disc = "" if discipline["ok"] else " [DISCIPLINE-FAIL]"
            print(f"  {task['id']} run {run_index + 1}/{args.n}: {status}{disc} "
                  f"({discipline['detail']})")
            stopped_early = format_failure_breaker(records, ff_threshold)
            if stopped_early:
                break

    if reported_models:
        metadata["model_reported"] = sorted(reported_models)
    metadata["total_cost_usd"] = round(total_cost, 4)
    metadata["total_duration_ms"] = total_ms
    metadata["reused_runs"] = reused
    # Recorded whether or not it fired, and whether or not it was overridden. A grid published past a
    # high failure rate is a deliberate decision, and the decision belongs in the artifact rather
    # than in someone's memory of the terminal (ADR-0032).
    metadata["format_failure_threshold"] = ff_threshold
    if stopped_early:
        metadata["stopped_early"] = stopped_early
    metadata["tool_discipline_summary"] = {
        "runs_asserted": sum(1 for r in records if "tool_discipline" in r),
        "violations_logged": len(violations),
        "violations": violations,
        "final_all_ok": all(r.get("tool_discipline", {}).get("ok", True) for r in records),
    }

    agg = write_reports(out_dir, records, metadata)
    print(f"\nWrote {out_dir}/summary.md and scores.json")
    print(f"Overall accuracy: "
          f"{'n/a' if agg['overall_accuracy'] is None else f'{agg['overall_accuracy'] * 100:.0f}%'}"
          f"  |  format failures: {agg['format_failures']}/{agg['total_runs']}"
          + (f"  |  format repairs: {agg['format_repairs']}" if agg.get("format_repairs") else ""))
    if total_cost or total_ms:
        print(f"Subscription usage: ${total_cost:.4f}  |  wall (sum of call durations): "
              f"{total_ms / 1000:.0f}s")
    if stopped_early:
        # Everything already run is written and archived; nothing is deleted and the run dir stays
        # resumable. The breaker stops the spend and asks for a ruling — it does not make one.
        print(
            f"BLOCKED: stopped this condition early — {stopped_early}\n"
            "A refusal rate this far above anything the cohort has legitimately produced is evidence "
            "that the\nQUESTION is broken, not that the vendor is (ADR-0032). Read a failing "
            "transcript before re-running.\n"
            "Nothing was deleted; the archived runs above are intact and the grid resumes. To "
            "proceed deliberately,\nre-run with --format-failure-threshold (1.0 disables it); the "
            "value in force is recorded in scores.json.",
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core")
    parser.add_argument("--pack", help="path to a vendor pack dir, or a bare pack name resolved "
                                       "against --packs-dir (or set AIRE_PACK)")
    parser.add_argument("--packs-dir", help="directory holding packs; a bare --pack <name> resolves "
                                            "to <packs-dir>/<name> (or set AIRE_PACKS_DIR)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a condition against the tasks and score it")
    run.add_argument("--condition", default="no-context",
                     help=f"one of: {', '.join(conditions.available_conditions())} "
                          "(mcp only if the pack declares a context layer)")
    run.add_argument("--n", type=int, default=5, help="runs per task (default 5)")
    run.add_argument("--tasks", help="comma-separated task ids (default: all)")
    run.add_argument("--model", help="override EVAL_MODEL")
    run.add_argument("--out", help="output dir (default <pack>/results/<date>-<condition>)")
    run.add_argument("--overwrite", action="store_true",
                     help="re-run and overwrite archived runs instead of resuming (default: resume)")
    run.add_argument("--provider", choices=["cli", "api"], default="cli",
                     help="model transport: cli = Claude subscription via Claude Code CLI "
                          "(default, no API key); api = Anthropic API (needs ANTHROPIC_API_KEY)")
    run.add_argument("--mock", action="store_true",
                     help="use the offline mock model (no API key needed)")
    run.add_argument("--skip-preflight", action="store_true",
                     help="skip the sterile/server pre-flight gate (only for resumes after a "
                          "canary has already passed; the grid normally refuses to start on failure)")
    run.add_argument("--allow-unpinned-model", action="store_true",
                     help="permit a cli run with no --model (uses the session-default model); "
                          "off by default so an unpinned run can't silently confound the comparison")
    run.add_argument("--format-failure-threshold", type=float, default=FORMAT_FAILURE_THRESHOLD,
                     help=f"stop the condition when the running format-failure rate exceeds this "
                          f"(default {FORMAT_FAILURE_THRESHOLD:.2f}, after "
                          f"{FORMAT_FAILURE_FLOOR} runs; 1.0 disables). A rate far above anything "
                          "the cohort produces means the question is broken, not the vendor")
    run.set_defaults(func=cmd_run)

    ping = sub.add_parser("ping", help="confirm the Claude subscription (CLI) transport works")
    ping.add_argument("--model", help="override EVAL_MODEL")
    ping.set_defaults(func=cmd_ping)

    canary = sub.add_parser("canary", help="run the sterile + repo-root control canaries")
    canary.add_argument("--model", help="override EVAL_MODEL")
    canary.add_argument("--out", help="output dir (default <pack>/results/<date>-sterile-canary)")
    canary.add_argument("--check-server", action="store_true",
                        help="also run the context-layer server health check (if the pack has one)")
    canary.set_defaults(func=cmd_canary)

    ss = sub.add_parser("spec-size", help="measure the pinned OpenAPI spec repo size + token estimate")
    ss.set_defaults(func=cmd_spec_size)

    fd = sub.add_parser("fetch-docs", help="fetch + cache the public-docs snapshot; populate the manifest")
    fd.set_defaults(func=cmd_fetch_docs)

    ar = sub.add_parser("annotate-robots",
                        help="record, for every manifest URL, whether its host's robots.txt permits "
                             "an automated reader to retrieve it (ADR-0036)")
    ar.add_argument("packs", nargs="*",
                    help="pack dirs (default: every pack under packs/ and --packs-dir)")
    ar.add_argument("--check", action="store_true",
                    help="re-read each host and report drift; change nothing")
    ar.set_defaults(func=cmd_annotate_robots)

    cmp = sub.add_parser("compare", help="side-by-side comparison report for 2+ results dirs")
    cmp.add_argument("dirs", nargs="+",
                     help="results dirs in order (last is the 'after', e.g. ...-no-context "
                          "...-public-docs ...-mcp)")
    cmp.add_argument("--out", help="output markdown file (default: print to stdout)")
    cmp.add_argument("--note", help="disclosure/context note rendered at the top of the report")
    cmp.add_argument("--baseline", nargs="+",
                     help="prior results dirs (matched by condition) to append a delta table vs")
    cmp.add_argument("--new-label", default="new",
                     help="label for the current run in the delta table")
    cmp.add_argument("--base-label", default="baseline",
                     help="label for the baseline in the delta table")
    cmp.add_argument("--by-group", action="store_true",
                     help="render the pack's declared task_groups split instead of the per-task "
                          "tables (ADR-0026); requires exactly 2 results dirs and --pack")
    cmp.set_defaults(func=cmd_compare)

    inv = sub.add_parser("invented",
                         help="list model-proposed endpoints that are not ground truth (exhibits)")
    inv.add_argument("results_dir", help="a results dir under <pack>/results/")
    inv.set_defaults(func=cmd_invented)

    cons = sub.add_parser("consultation",
                          help="per-task mcp tool-consultation / skip rates")
    cons.add_argument("results_dir", help="an mcp-condition results dir under <pack>/results/")
    cons.add_argument("--json", help="also write the rates as JSON to this path")
    cons.set_defaults(func=cmd_consultation)

    rb = sub.add_parser("rebuild-report",
                        help="regenerate summary.md + scores.json from archived runs/ (recovery + gate)")
    rb.add_argument("results_dir", help="a results dir with a runs/ subdir")
    rb.add_argument("--note", help="disclosure note recorded in metadata + summary (e.g. why re-scored)")
    rb.set_defaults(func=cmd_rebuild_report)

    rc = sub.add_parser("reconcile-runs",
                        help="sync scorer-derived fields from a results dir's scores.json into its "
                             "runs/*.json (never re-scores; scores.json is read-only)")
    rc.add_argument("results_dirs", nargs="+", help="one or more results dirs with a runs/ subdir")
    rc.add_argument("--check", action="store_true",
                    help="report what is stale and change nothing")
    rc.set_defaults(func=cmd_reconcile_runs)

    val = sub.add_parser("validate", help="validate a pack's task files against the shared schema")
    val.set_defaults(func=cmd_validate)

    rt = sub.add_parser("roundtrip",
                        help="round-trip control: every task must score its own ground truth 1.0 "
                             "(proves each task is scoreable; cannot detect a wrong answer key)")
    rt.set_defaults(func=cmd_roundtrip)

    pg = sub.add_parser("prompts",
                        help="prompt-sanity gate: every task prompt must name the pack's declared "
                             "vendor AND product (the one gate that reads the question, not the "
                             "answer key)")
    pg.set_defaults(func=cmd_prompts)

    fac = sub.add_parser("factory",
                         help="dispatcher: work a ranked queue through recon→validate→prompts→"
                              "roundtrip→anchoring→…→card (next|run|status)")
    fac.add_argument("mode", choices=["next", "run", "status"],
                     help="next: drive the next non-blocked target once; run: loop until all "
                          "carded/blocked; status: print the queue")
    fac.add_argument("--queue", help="path to the ranked queue.yaml (or set AIRE_QUEUE)")
    fac.add_argument("--model", help="pinned model for the grids (required for cli runs)")
    fac.add_argument("--n", type=int, default=5, help="runs per (task, condition) in the grid (default 5)")
    fac.add_argument("--provider", choices=["cli", "mock"], default="cli",
                     help="cli = real grid via the Claude subscription (default); mock = offline dry-run "
                          "of the whole spine, no model burn")
    fac.set_defaults(func=cmd_factory)
    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    from .prompt_gate import dual_listed
    from .validate import format_report, validate_pack
    pack = _load_pack(args)
    results = validate_pack(pack)
    text, total = format_report(results)
    print(text)
    # A NOTE, never an error: ADR-0031 permits a name in both the vendor and product lists when the
    # product is distinctive enough to identify its vendor, and forbids it for a bare corporate
    # parent. Core cannot tell those apart, so the overlap is surfaced for a human to check. It is
    # printed here rather than folded into `validate_pack`'s results, because those are counted as
    # problems and a note that blocked the validate gate would be a rule this project never made.
    overlap = dual_listed(pack)
    if overlap:
        print(f"\nnote: declared as BOTH vendor and product — {', '.join(overlap)}\n"
              "      Permitted for a product distinctive enough to identify its vendor; never for a "
              "bare\n      corporate parent (ADR-0031). Not an error — a review item.")
    return EXIT_OK if total == 0 else EXIT_ERROR


def cmd_prompts(args: argparse.Namespace) -> int:
    """The prompt-sanity gate standalone, so an author can run it while writing the tasks rather
    than discovering it at dispatch. Same gate `cmd_run` and the factory run (ADR-0031)."""
    from .prompt_gate import check_pack, format_report
    pack = _load_pack(args)
    text, total = format_report(check_pack(pack))
    print(text)
    return EXIT_OK if total == 0 else EXIT_ERROR


def cmd_roundtrip(args: argparse.Namespace) -> int:
    """The round-trip control as a standalone command, so a pack author can run it before the
    factory ever sees the pack. Same gate the dispatcher runs at the `roundtrip` stage (ADR-0010)."""
    from .roundtrip import check_pack, format_report
    pack = _load_pack(args)
    text, total = format_report(check_pack(pack))
    print(text)
    return EXIT_OK if total == 0 else EXIT_ERROR


def cmd_rebuild_report(args: argparse.Namespace) -> int:
    from .rebuild import rebuild_report

    pack = _load_pack(args)
    try:
        agg = rebuild_report(args.results_dir, pack, note=args.note)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    d = Path(args.results_dir)
    print(f"Rebuilt {d}/summary.md + scores.json "
          f"(overall {'n/a' if agg['overall_accuracy'] is None else f'{agg['overall_accuracy']*100:.0f}%'}, "
          f"{agg['format_failures']} format failures)")
    return EXIT_OK


def cmd_reconcile_runs(args: argparse.Namespace) -> int:
    """ADR-0033. Needs no pack: the corrected scores are already in the directory's own scores.json,
    so this reads one archive against itself and never consults ground truth."""
    from .archive import format_report, reconcile_runs

    results = [reconcile_runs(d, write=not args.check) for d in args.results_dirs]
    text, problems = format_report(results)
    if text:
        print(text)
    if problems:
        print(f"\n{problems} problem(s) — nothing was written for the affected directory(ies)",
              file=sys.stderr)
        return EXIT_BLOCKED
    stale = sum(r.total_fields for r in results)
    if args.check:
        print(f"\n{stale} stale field(s) across {len(results)} directory(ies)"
              + ("" if stale else " — every run record agrees with its report"))
        return EXIT_ERROR if stale else EXIT_OK
    print(f"\nSynced {stale} field(s) across {len(results)} directory(ies); "
          "scores.json and summary.md untouched")
    return EXIT_OK


def cmd_annotate_robots(args: argparse.Namespace) -> int:
    """ADR-0036. Fetch each host's robots.txt once and record, on every manifest URL, whether that host
    permits an automated reader to retrieve it.

    The only online path in this project's test-facing surface. The standing sweep in the suite reads
    the committed annotations and never touches the network; this command is what refreshes them, so a
    host editing its robots.txt after a pack was authored is a detectable event rather than a silent
    change in what we were allowed to do.
    """
    from .robots import annotate_manifest, clear_cache, format_report

    pack_dirs = [Path(p) for p in args.packs]
    if not pack_dirs:
        packs_dir = args.packs_dir or os.environ.get("AIRE_PACKS_DIR")
        roots = [Path(__file__).resolve().parent.parent / "packs"]
        if packs_dir:
            roots.append(Path(packs_dir))
        pack_dirs = sorted({p.parent for r in roots if r.is_dir() for p in r.glob("*/pack.yaml")})
    if not pack_dirs:
        print("ERROR: no packs — pass pack dirs, or --packs-dir <dir>.", file=sys.stderr)
        return EXIT_ERROR

    clear_cache()
    audits = []
    for pack_dir in pack_dirs:
        pack = Pack.load(pack_dir)
        if not Path(pack.docs_manifest_path).is_file():
            continue
        audits.append(annotate_manifest(
            pack.docs_manifest_path,
            user_agent=pack.public_docs_user_agent or robots_default_agent(),
            write=not args.check))
    text, disallowed = format_report(audits)
    print(text)
    drift = sum(len(a.drift) for a in audits)
    if disallowed:
        print(f"\nBLOCKED: {disallowed} manifest URL(s) may not be fetched. A pack must not name a "
              "page its host disallows; record the Disallow as a finding instead (ADR-0036).",
              file=sys.stderr)
        return EXIT_BLOCKED
    if args.check:
        print(f"{drift} annotation(s) disagree with the hosts' current robots.txt"
              + ("" if drift else " — every pack's record is current"))
        return EXIT_ERROR if drift else EXIT_OK
    print(f"Annotated {len(audits)} manifest(s); no url, hash, byte_size or cache_file was touched.")
    return EXIT_OK


def robots_default_agent() -> str:
    from .robots import USER_AGENT
    return USER_AGENT


def cmd_invented(args: argparse.Namespace) -> int:
    from .analyze import format_unmatched, unmatched_endpoints
    pack = _load_pack(args)
    unmatched = unmatched_endpoints(args.results_dir, pack.tasks_by_id())
    print(format_unmatched(unmatched))
    return EXIT_OK


def cmd_consultation(args: argparse.Namespace) -> int:
    from .analyze import consultation_rates, format_consultation
    pack = _load_pack(args)
    if pack.context_layer is None:
        print("ERROR: this pack has no context layer (mcp condition); nothing to consult.",
              file=sys.stderr)
        return EXIT_ERROR
    rates = consultation_rates(args.results_dir, pack.context_layer.mcp_tool_prefix)
    print(format_consultation(rates))
    if args.json:
        Path(args.json).write_text(json.dumps(rates, indent=2))
        print(f"\nWrote {args.json}")
    return EXIT_OK


def _load_results(d: str) -> tuple[dict, dict]:
    from .report import aggregate
    data = json.loads((Path(d) / "scores.json").read_text())
    return aggregate(data["runs"]), data["metadata"]


def cmd_compare(args: argparse.Namespace) -> int:
    from .report import render_comparison_md, render_delta_table_md, render_multi_comparison_md
    try:
        loaded = [(_load_results(d)) for d in args.dirs]
        baseline = [(_load_results(d)) for d in (args.baseline or [])]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not load results: {exc}", file=sys.stderr)
        return EXIT_ERROR
    entries = [(meta.get("condition", chr(65 + i)), agg, meta)
               for i, (agg, meta) in enumerate(loaded)]
    if getattr(args, "by_group", False):
        from .category import rollup_by_group
        from .report import render_group_comparison_md
        if len(entries) != 2:
            print("ERROR: --by-group needs exactly 2 results dirs", file=sys.stderr)
            return EXIT_ERROR
        pack = _load_pack(args)
        if not pack.task_groups:
            print(f"ERROR: pack '{pack.vendor_id}' declares no task_groups in pack.yaml",
                  file=sys.stderr)
            return EXIT_ERROR
        mapping = pack.task_to_group()
        keys = list(pack.task_groups)
        (la, aa, _), (lb, ab, _) = entries
        md = render_group_comparison_md(la, rollup_by_group(aa, mapping, keys),
                                        lb, rollup_by_group(ab, mapping, keys),
                                        pack.task_groups, note=args.note)
        if args.out:
            Path(args.out).write_text(md)
            print(f"Wrote {args.out}")
        else:
            print(md)
        return EXIT_OK
    if len(entries) == 2 and not args.note and not baseline:
        (la, aa, ma), (lb, ab, mb) = entries
        md = render_comparison_md(la, aa, ma, lb, ab, mb)
    else:
        md = render_multi_comparison_md(entries, note=args.note)
    if baseline:
        base_entries = [(meta.get("condition", chr(65 + i)), agg, meta)
                        for i, (agg, meta) in enumerate(baseline)]
        md += "\n" + render_delta_table_md(entries, base_entries,
                                           new_label=args.new_label, base_label=args.base_label)
    if args.out:
        Path(args.out).write_text(md)
        print(f"Wrote {args.out}")
    else:
        print(md)
    return EXIT_OK


def cmd_fetch_docs(args: argparse.Namespace) -> int:
    from .docs_fetch import fetch_all
    pack = _load_pack(args)
    try:
        if pack.public_docs_user_agent:
            print(f"  (pack declares a fetch User-Agent: {pack.public_docs_user_agent})")
        if pack.public_docs_fetch_delay_seconds:
            print(f"  (pack declares a fetch delay: {pack.public_docs_fetch_delay_seconds}s between pages)")
        summary = fetch_all(pack.docs_manifest_path, pack.docs_cache_dir,
                            user_agent=pack.public_docs_user_agent,
                            delay_seconds=pack.public_docs_fetch_delay_seconds)
    except Exception as exc:
        print(f"ERROR: fetch-docs failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    ok, err = 0, 0
    for task_id, pages in summary.items():
        for url, size, status in pages:
            flag = "ok " if status == "ok" else "ERR"
            if status == "ok":
                ok += 1
            else:
                err += 1
            print(f"  {flag} {task_id:20s} {size:8,d} B  {url}")
    print(f"\nFetched {ok} page(s), {err} error(s). Cache: {pack.docs_cache_dir} (gitignored); "
          "manifest updated with hashes + sizes.")
    return EXIT_ERROR if err and not ok else EXIT_OK


def cmd_spec_size(args: argparse.Namespace) -> int:
    from .specsize import format_report, measure
    pack = _load_pack(args)
    try:
        m = measure(pack.specs_path, pack.spec_scope_prefix)
    except Exception as exc:  # network/tarball errors
        print(f"ERROR: spec-size measurement failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(format_report(m))
    return EXIT_OK


def cmd_ping(args: argparse.Namespace) -> int:
    explicit_model = args.model or load_env().get("EVAL_MODEL")
    try:
        client = ClaudeCliModel(explicit_model)
        resp = client.ping()
    except ModelError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    print(f"pong: {resp.text.strip()!r}  (model: {resp.model_reported}, "
          f"cost: ${resp.cost_usd:.4f}, {resp.duration_ms} ms)")
    return EXIT_OK


def _queue_header(path: str) -> str | None:
    """Preserve the queue file's leading comment block across a save."""
    head: list[str] = []
    for line in Path(path).read_text().splitlines():
        if line.startswith("#") or not line.strip():
            head.append(line)
        else:
            break
    text = "\n".join(head).strip()
    return text or None


def cmd_factory(args: argparse.Namespace) -> int:
    """The dispatcher: work the ranked queue through the per-target pipeline (ADR-0006).

    Three operator modes: `status` (print the queue), `next` (drive the next non-blocked target once),
    `run` (loop until every target is carded or blocked). Producing is unattended; every card it writes
    is a DRAFT and every gate blocks-with-reason rather than guessing past.
    """
    from . import factory

    queue_path = args.queue or os.environ.get("AIRE_QUEUE")
    if not queue_path:
        print("ERROR: no queue — pass --queue <path> or set AIRE_QUEUE.", file=sys.stderr)
        return EXIT_ERROR
    entries = factory.load_queue(queue_path)

    if args.mode == "status":
        print(factory.render_status(entries))
        return EXIT_OK

    packs_dir = args.packs_dir or os.environ.get("AIRE_PACKS_DIR")
    if not packs_dir:
        print("ERROR: factory next/run needs --packs-dir <dir> (where each target's pack lives).",
              file=sys.stderr)
        return EXIT_ERROR
    explicit_model = args.model or load_env().get("EVAL_MODEL")
    if args.provider == "cli" and not explicit_model:
        print("BLOCKED: a cli factory run needs a pinned --model so the grids stay comparable across "
              "vendors; pass --model <id>.", file=sys.stderr)
        return EXIT_BLOCKED

    header = _queue_header(queue_path)

    def _drive(entry) -> str:
        pack_dir = Path(packs_dir) / entry.id
        if not (pack_dir / "pack.yaml").is_file():
            entry.status = "blocked"
            entry.blocked_reason = (f"[recon] no pack authored at {pack_dir} — author + anchor the "
                                    "pack before the factory can card it")
            print(f"  BLOCKED: no pack authored at {pack_dir}")
            return "blocked"
        pack = Pack.load(pack_dir)
        report = factory.run_pipeline(entry, pack, today=_today(), model=explicit_model,
                                      n=args.n, provider=args.provider, packs_dir=packs_dir)
        return report["outcome"]

    outcome = None
    if args.mode == "next":
        entry = factory.next_target(entries)
        if entry is None:
            print("queue: nothing to do (all targets carded or blocked).")
        else:
            print(f"→ {entry.display_name or entry.id} (tier {entry.tier}, spec {entry.spec_state})")
            outcome = _drive(entry)
            factory.save_queue(queue_path, entries, header=header)
    else:  # run
        while True:
            entry = factory.next_target(entries)
            if entry is None:
                break
            print(f"→ {entry.display_name or entry.id} (tier {entry.tier}, spec {entry.spec_state})")
            _drive(entry)
            factory.save_queue(queue_path, entries, header=header)  # persist after each target

    print()
    print(factory.render_status(entries))
    return EXIT_BLOCKED if outcome == "blocked" else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
