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
from .judge import RUBRIC_VERSION, Judge, gemini_call, groq_call
from .kb import facts_missing_from_sources, load_kb_texts
from .runner import rejudge, run_eval
from .summary import pick_spot_checks, render_markdown, summarize
from .workload import make_workload, repeat_rate

EVAL_DIR = Path(__file__).resolve().parents[2]
QUERIES = EVAL_DIR / "datasets" / "queries.jsonl"
KB_DIR = EVAL_DIR.parent / "kb"
KEY_ENV = {"weir-general/en/public": "WEIR_KEY_PUBLIC", "weir-general/en/staff": "WEIR_KEY_STAFF"}
ADMIN_KEY_ENV = "WEIR_KEY_ADMIN"


def cmd_validate(_: argparse.Namespace) -> int:
    queries = load_queries(QUERIES)
    problems = validate(queries) + facts_missing_from_sources(queries, load_kb_texts(KB_DIR))
    print("\n".join(problems) or f"ok: {len(queries)} queries")
    return 1 if problems else 0


def cmd_assign_splits(_: argparse.Namespace) -> int:
    save_queries(QUERIES, assign_splits(load_queries(QUERIES)))
    return cmd_validate(_)


async def _run(args: argparse.Namespace) -> int:
    all_queries = load_queries(QUERIES)
    if args.workload:
        by_id = {q.id: q for q in all_queries}
        ids = [json.loads(line)["id"] for line in Path(args.workload).read_text(encoding="utf-8").splitlines()
               if line.strip()]
        queries = [by_id[i] for i in ids]
    else:
        queries = [q for q in all_queries if args.split == "all" or q.split == args.split]
    if args.exclude_report:
        done = {r["id"] for r in _load_results(Path(args.exclude_report)) if r.get("status_code") == 200}
        queries = [q for q in queries if q.id not in done]
    keys = {ns: os.environ[env] for ns, env in KEY_ENV.items()}
    judge, judge_model = (None, None) if args.no_judge else _make_judge()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    label = f"{args.config}-{Path(args.workload).stem if args.workload else args.split}"
    out_dir = EVAL_DIR / "reports" / f"{stamp}-{label}"
    async with httpx.AsyncClient(base_url=args.weir_url, timeout=90) as http:
        health = (await http.get("/healthz")).json()
        if health.get("config_label") != args.config:
            print(f"Weir is running config {health.get('config_label')!r}, expected {args.config!r}. "
                  f"Restart it with WEIR_ABLATION={args.config}.", file=sys.stderr)
            return 2
        if args.purge_cache:
            for ns in KEY_ENV:
                r = await http.delete("/v1/cache", params={"namespace": ns},
                                      headers={"X-API-Key": os.environ[ADMIN_KEY_ENV]})
                if r.status_code != 200:
                    print(f"cache purge failed for {ns}: {r.status_code} {r.text}", file=sys.stderr)
                    return 2
                print(f"purged {r.json()['deleted']} cache entries in {ns}")
        records = await run_eval(queries, http, keys, judge, load_kb_texts(KB_DIR), out_dir, args.min_interval)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    header = {"config": args.config, "split": args.split, "workload": args.workload, "queries": len(queries),
              "judge_model": judge_model, "rubric": RUBRIC_VERSION, "git_commit": commit, "started_utc": stamp}
    if args.workload:
        header["workload_repeat_rate"] = round(repeat_rate([q.id for q in queries]), 3)
    _write_report(out_dir, header, records)
    return 0


def _load_results(report_dir: Path) -> list[dict]:
    path = report_dir / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cmd_merge_reports(args: argparse.Namespace) -> int:
    records, seen = [], set()
    for d in args.dirs:
        for r in _load_results(Path(d)):
            if r["id"] not in seen:
                seen.add(r["id"])
                records.append(r)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                                           encoding="utf-8")
    _write_report(out_dir, {"merged_from": [Path(d).name for d in args.dirs], "queries": len(records)}, records)
    return 0


def cmd_make_workload(args: argparse.Namespace) -> int:
    ids = make_workload([q.id for q in load_queries(QUERIES)], args.n, args.seed, args.exponent)
    out = EVAL_DIR / "datasets" / f"workload-{args.n}-seed{args.seed}.jsonl"
    out.write_text("".join(json.dumps({"id": i}) + "\n" for i in ids), encoding="utf-8")
    print(f"{out}: {len(ids)} requests, {len(set(ids))} unique, repeat rate {repeat_rate(ids):.1%}")
    return 0


async def _rejudge(args: argparse.Namespace) -> int:
    out_dir = Path(args.report_dir)
    header = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))["header"] \
        if (out_dir / "summary.json").exists() else {"report": out_dir.name}
    judge, judge_model = _make_judge()
    queries = {q.id: q for q in load_queries(QUERIES)}
    records = await rejudge(out_dir / "results.jsonl", judge, queries, load_kb_texts(KB_DIR))
    _write_report(out_dir, {**header, "judge_model": judge_model}, records)
    return 0


def _make_judge() -> tuple[Judge, str]:
    """JUDGE_PROVIDER groq (default, decision D20) or gemini; JUDGE_MODEL; JUDGE_MIN_INTERVAL seconds."""
    provider = os.environ.get("JUDGE_PROVIDER", "groq")
    if provider == "groq":
        model = os.environ.get("JUDGE_MODEL", "qwen/qwen3.8-27b")
        call = groq_call(os.environ["GROQ_API_KEY"], model)
    else:
        model = os.environ.get("JUDGE_MODEL", "gemini-3-flash-preview")
        call = gemini_call(os.environ["GEMINI_API_KEY"], model)
    interval = float(os.environ.get("JUDGE_MIN_INTERVAL", "8"))
    return Judge(call, EVAL_DIR / ".judge_cache", model, min_interval_s=interval), f"{provider}:{model}"


REPO = EVAL_DIR.parent
CONFIGS_DIR = REPO / "configs"


def cmd_sweep(args: argparse.Namespace) -> int:
    from weir.cache.embedder import Embedder
    from weir.cache.entities import Lexicon
    from weir.text import normalize

    from .sweep import THRESHOLDS, build_pairs, choose_threshold, sweep, write_sweep_report

    queries = load_queries(QUERIES)
    vectors = dict(zip([q.id for q in queries],
                       Embedder("BAAI/bge-small-en-v1.5").embed_many([normalize(q.query) for q in queries]),
                       strict=True))
    lexicon = Lexicon.from_yaml(CONFIGS_DIR / "entities.yaml")
    pairs = build_pairs(queries, vectors, lexicon.conflicts)
    results = {(split, guard): sweep([p for p in pairs if split == "all" or p.split == split], THRESHOLDS, guard)
               for split in ("tune", "holdout", "all") for guard in (True, False)}
    # Rule (decision D25): lowest threshold clean on ALL pairs (tune, holdout and pairs spanning both),
    # plus a safety margin above it.
    chosen = choose_threshold(results[("all", True)], args.max_false_hit, args.margin)
    out_dir = EVAL_DIR / "reports" / f"sweep-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    write_sweep_report(out_dir, results, chosen, pairs)
    (EVAL_DIR / "datasets" / "pairs.jsonl").write_text((out_dir / "pairs.jsonl").read_text(encoding="utf-8"),
                                                       encoding="utf-8")
    at = {s: next((r for r in results[(s, True)] if r["threshold"] == chosen), None) for s in ("tune", "holdout", "all")}
    print(f"chosen threshold (all pairs, guard on, margin {args.margin}): {chosen}; at chosen: {at}; report: {out_dir}")
    return 0


async def _features(args: argparse.Namespace) -> int:
    from weir.cache.embedder import Embedder
    from weir.cache.guards import BypassRules
    from weir.config import load_config
    from weir.rag.adapter import RagClient
    from weir.router.features import FeatureExtractor

    from .features import collect_features

    cfg = load_config(CONFIGS_DIR / "weir.yaml")
    embedder = Embedder(cfg.cache.embed_model)
    extractor = FeatureExtractor(embedder.count_tokens, BypassRules(cfg.bypass), cfg.router.reasoning_words)
    rag = RagClient(args.rag_url, cfg.rag.timeout_seconds)
    try:
        rows = await collect_features(load_queries(QUERIES), rag, extractor, cfg.rag.retrieve_k)
    finally:
        await rag.aclose()
    out = EVAL_DIR / "datasets" / "features.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{out}: {len(rows)} questions")
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
    run.add_argument("--no-judge", action="store_true", help="skip judging; grade later with rejudge")
    run.add_argument("--exclude-report", help="skip queries already answered in this report dir")
    run.add_argument("--workload", help="jsonl of {id} lines to replay in order (ignores --split)")
    run.add_argument("--purge-cache", action="store_true", help="empty Weir's cache first (admin key)")
    run.set_defaults(func=lambda a: asyncio.run(_run(a)))
    merge = sub.add_parser("merge-reports", help="combine report dirs (first occurrence of an id wins)")
    merge.add_argument("out")
    merge.add_argument("dirs", nargs="+")
    merge.set_defaults(func=cmd_merge_reports)
    wl = sub.add_parser("make-workload", help="Zipf-skewed replay list")
    wl.add_argument("--n", type=int, default=300)
    wl.add_argument("--seed", type=int, default=7)
    wl.add_argument("--exponent", type=float, default=1.1)
    wl.set_defaults(func=cmd_make_workload)
    sw = sub.add_parser("sweep", help="similarity threshold sweep on paraphrase/trap/hard-negative pairs")
    sw.add_argument("--max-false-hit", type=float, default=0.01)
    sw.add_argument("--margin", type=float, default=0.02, help="safety margin added to the lowest passing threshold")
    sw.set_defaults(func=cmd_sweep)
    rejudge_cmd = sub.add_parser("rejudge", help="re-score rows without a judge verdict; no Weir calls")
    rejudge_cmd.add_argument("report_dir")
    rejudge_cmd.set_defaults(func=lambda a: asyncio.run(_rejudge(a)))
    feat = sub.add_parser("features", help="router features for every question via /retrieve (no LLM)")
    feat.add_argument("--rag-url", default=os.environ.get("RAG_URL", "http://127.0.0.1:8001"))
    feat.set_defaults(func=lambda a: asyncio.run(_features(a)))
    args = parser.parse_args()
    sys.exit(args.func(args))
