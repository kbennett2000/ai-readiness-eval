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
            tool_discipline: dict | None = None) -> dict:
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
    return rec


def _score_response(task: dict, raw_text: str):
    parsed = answer_block.parse(raw_text)
    if parsed.is_failure:
        return format_failure_score(task["id"], parsed.failure.reason), None
    return score_task(task, parsed.summary), parsed.block_text


# --------------------------------------------------------------------------- #
# Mock responses for offline smoke runs (--mock). Built from ground truth so the
# pipeline is exercised end-to-end; one task is deliberately broken to a no-block
# response so format-failure handling is demonstrated. Never committed as a baseline.
# --------------------------------------------------------------------------- #

def _mock_block_for_task(task: dict) -> str:
    import yaml

    from .scorer import canonical_auth_flow

    gt = task["ground_truth"]
    scopes = [s.split("#", 1)[0].strip() for s in gt.get("required_scopes", [])]
    scopes = [s for s in scopes if s]
    params = [p["name"] for p in gt.get("key_parameters", [])
              if isinstance(p, dict) and p.get("name")]
    # Clean, canonical auth phrase so the block is always valid YAML (ground-truth
    # prose contains ": " sequences that would break a naive echo).
    auth = ("OAuth2 client-credentials"
            if canonical_auth_flow(gt.get("auth_flow")) == "oauth2-client-credentials"
            else "OAuth2 bearer token")
    block = {
        "endpoints": [
            {"method": e["method"], "path": e["path"], "api_version": e["api_version"]}
            for e in gt["endpoints"]
        ],
        "auth_flow": auth,
        "required_scopes": scopes,
        "key_parameters": params,
    }
    body = yaml.safe_dump(block, sort_keys=False, default_flow_style=False)
    return (
        f"Here is how you would approach **{task['id']}**.\n\n"
        f"```answer-summary\n{body}```\n"
    )


def _build_mock_responses(tasks: list[dict]) -> dict[str, str]:
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


def cmd_run(args: argparse.Namespace) -> int:
    pack = _load_pack(args)
    condition = conditions.get_condition(args.condition, pack)
    only = set(args.tasks.split(",")) if args.tasks else None
    tasks = pack.load_tasks(only)
    if not tasks:
        print("ERROR: no tasks matched", file=sys.stderr)
        return EXIT_ERROR

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
    for task in tasks:
        for run_index in range(args.n):
            run_path = runs_dir / f"{task['id']}-run{run_index}.json"
            # Resumable: reuse an archived run that already passed its tool-discipline assertion.
            if run_path.exists() and not args.overwrite:
                prev = json.loads(run_path.read_text())
                if prev.get("tool_discipline", {}).get("ok", True):
                    records.append(prev)
                    total_cost += prev.get("cost_usd", 0.0)
                    total_ms += prev.get("duration_ms", 0)
                    reused += 1
                    print(f"  {task['id']} run {run_index + 1}/{args.n}: reused (archived)")
                    continue

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
            score, _block = _score_response(task, resp.text)
            rec = _record(task["id"], run_index, score, resp, tool_discipline=discipline)
            records.append(rec)
            run_path.write_text(json.dumps(rec, indent=2))
            status = "FMT-FAIL" if score.format_failure else "scored"
            disc = "" if discipline["ok"] else " [DISCIPLINE-FAIL]"
            print(f"  {task['id']} run {run_index + 1}/{args.n}: {status}{disc} "
                  f"({discipline['detail']})")

    if reported_models:
        metadata["model_reported"] = sorted(reported_models)
    metadata["total_cost_usd"] = round(total_cost, 4)
    metadata["total_duration_ms"] = total_ms
    metadata["reused_runs"] = reused
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
          f"  |  format failures: {agg['format_failures']}/{agg['total_runs']}")
    if total_cost or total_ms:
        print(f"Subscription usage: ${total_cost:.4f}  |  wall (sum of call durations): "
              f"{total_ms / 1000:.0f}s")
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

    val = sub.add_parser("validate", help="validate a pack's task files against the shared schema")
    val.set_defaults(func=cmd_validate)

    fac = sub.add_parser("factory",
                         help="dispatcher: work a ranked queue through recon→…→card (next|run|status)")
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
    from .validate import format_report, validate_pack
    pack = _load_pack(args)
    results = validate_pack(pack)
    text, total = format_report(results)
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
        summary = fetch_all(pack.docs_manifest_path, pack.docs_cache_dir,
                            user_agent=pack.public_docs_user_agent)
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
