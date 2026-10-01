import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .dataset import assign_splits, load_queries, save_queries, validate
from .judge import RUBRIC_VERSION, Judge, gemini_call
from .kb import facts_missing_from_sources, load_kb_texts
from .runner import rejudge, run_eval
from .summary import pick_spot_checks, render_markdown, summarize

EVAL_DIR = Path(__file__).resolve().parents[2]
QUERIES = EVAL_DIR / "datasets" / "queries.jsonl"
KB_DIR = EVAL_DIR.parent / "kb"
KEY_ENV = {"weir-general/en/public": "WEIR_KEY_PUBLIC", "weir-general/en/staff": "WEIR_KEY_STAFF"}


def cmd_validate(_: argparse.Namespace) -> int:
    queries = load_queries(QUERIES)
    problems = validate(queries) + facts_missing_from_sources(queries, load_kb_texts(KB_DIR))
    print("\n".join(problems) or f"ok: {len(queries)} queries")
    return 1 if problems else 0


def cmd_assign_splits(_: argparse.Namespace) -> int:
    save_queries(QUERIES, assign_splits(load_queries(QUERIES)))
    return cmd_validate(_)


async def _run(args: argparse.Namespace) -> int:
    queries = [q for q in load_queries(QUERIES) if args.split == "all" or q.split == args.split]
    keys = {ns: os.environ[env] for ns, env in KEY_ENV.items()}
    judge_model = os.environ.get("JUDGE_MODEL", "gemini-3.8-flash")
    judge = Judge(gemini_call(os.environ["GEMINI_API_KEY"], judge_model), EVAL_DIR / ".judge_cache", judge_model)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = EVAL_DIR / "reports" / f"{stamp}-{args.config}-{args.split}"
    async with httpx.AsyncClient(base_url=args.weir_url, timeout=90) as http:
        health = (await http.get("/healthz")).json()
        if health.get("config_label") != args.config:
            print(f"Weir is running config {health.get('config_label')!r}, expected {args.config!r}. "
                  f"Restart it with WEIR_ABLATION={args.config}.", file=sys.stderr)
            return 2
        records = await run_eval(queries, http, keys, judge, load_kb_texts(KB_DIR), out_dir, args.min_interval)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    header = {"config": args.config, "split": args.split, "queries": len(queries), "judge_model": judge_model,
              "rubric": RUBRIC_VERSION, "git_commit": commit, "started_utc": stamp}
    _write_report(out_dir, header, records)
    return 0


async def _rejudge(args: argparse.Namespace) -> int:
    out_dir = Path(args.report_dir)
    header = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))["header"] \
        if (out_dir / "summary.json").exists() else {"report": out_dir.name}
    judge_model = os.environ.get("JUDGE_MODEL") or header.get("judge_model") or "gemini-3.8-flash"
    judge = Judge(gemini_call(os.environ["GEMINI_API_KEY"], judge_model), EVAL_DIR / ".judge_cache", judge_model)
    queries = {q.id: q for q in load_queries(QUERIES)}
    records = await rejudge(out_dir / "results.jsonl", judge, queries, load_kb_texts(KB_DIR))
    _write_report(out_dir, {**header, "judge_model": judge_model}, records)
    return 0


def _write_report(out_dir: Path, header: dict, records: list[dict]) -> None:
    summary = summarize(records)
    (out_dir / "summary.json").write_text(json.dumps({"header": header, "summary": summary}, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_markdown(summary, header, pick_spot_checks(records)), encoding="utf-8")
    print(f"report: {out_dir} (errors {summary['errors']}, not judged {summary.get('judge_errors', 0)})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="weir_eval")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    sub.add_parser("assign-splits").set_defaults(func=cmd_assign_splits)
    run = sub.add_parser("run")
    run.add_argument("--config", required=True, help="expected Weir config_label, e.g. baseline")
    run.add_argument("--split", choices=["tune", "holdout", "all"], default="tune")
    run.add_argument("--min-interval", type=float, default=15.0, help="seconds between requests (free-tier TPM)")
    run.add_argument("--weir-url", default=os.environ.get("WEIR_URL", "http://localhost:8000"))
    run.set_defaults(func=lambda a: asyncio.run(_run(a)))
    rejudge_cmd = sub.add_parser("rejudge", help="re-score rows without a judge verdict; no Weir calls")
    rejudge_cmd.add_argument("report_dir")
    rejudge_cmd.set_defaults(func=lambda a: asyncio.run(_rejudge(a)))
    args = parser.parse_args()
    sys.exit(args.func(args))
