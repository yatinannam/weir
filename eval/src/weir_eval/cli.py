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


DEFAULT_DB = os.environ.get("WEIR_DB_URL", "postgresql://weir:weir@127.0.0.1:5432/weir")


def _first_by_id(rows: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for r in rows:
        by_id.setdefault(r["id"], r)
    return by_id


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cmd_export_grounding(args: argparse.Namespace) -> int:
    from .request_log import attach, fetch_grounding

    out_dir = Path(args.report_dir)
    results = _load_results(out_dir)
    ids = [r["meta"]["request_id"] for r in results if r.get("status_code") == 200]
    rows, missing = attach(results, fetch_grounding(args.db_url, ids))
    (out_dir / "grounding.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{out_dir / 'grounding.jsonl'}: {len(rows)} rows; missing from request_log: {missing or 'none'}")
    return 1 if missing else 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from weir.config import load_config

    from .simulate import build_rows, choose, dump, render, run_grid

    cfg = load_config(CONFIGS_DIR / "weir.yaml")
    small_dir = Path(args.small)
    rows = build_rows(load_queries(QUERIES), _first_by_id(_read_jsonl(EVAL_DIR / "datasets" / "features.jsonl")),
                      _first_by_id(_load_results(Path(args.baseline))), _first_by_id(_load_results(small_dir)),
                      _first_by_id(_read_jsonl(small_dir / "grounding.jsonl")), cfg.router.small_model)
    results = run_grid(rows, cfg)
    chosen = choose(results)
    out_dir = EVAL_DIR / "reports" / f"simulate-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True)
    header = {"baseline": Path(args.baseline).name, "small": small_dir.name}
    (out_dir / "simulate.json").write_text(json.dumps(dump(results, chosen, header), separators=(",", ":")),
                                           encoding="utf-8")
    (out_dir / "summary.md").write_text(render(chosen, results, header), encoding="utf-8")
    print(f"chosen: {vars(chosen[0]) if chosen else None}; report: {out_dir}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    from .gate import gate

    g = gate(_load_results(Path(args.report_dir)), _first_by_id(_load_results(Path(args.baseline))))
    print(json.dumps(g, indent=2))
    return 0 if g["passed"] else 1


def cmd_derive_workload(args: argparse.Namespace) -> int:
    from .workload import project_onto_workload

    ids = [r["id"] for r in _read_jsonl(Path(args.workload))]
    records = project_onto_workload(_load_results(Path(args.report_dir)), ids)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                                           encoding="utf-8")
    _write_report(out_dir, {"derived_from": Path(args.report_dir).name, "workload": Path(args.workload).name,
                            "queries": len(records), "workload_repeat_rate": round(repeat_rate(ids), 3),
                            "note": "derived: each request reuses its question's measured result (no cache)"},
                  records)
    return 0


LOADTEST_DIR = REPO / "loadtest"


def cmd_loadtest_make_workloads(args: argparse.Namespace) -> int:
    from .loadtest.workload import distinct_requests, make_request_file

    reqs = make_request_file(load_queries(QUERIES), args.n, args.seed)
    out = LOADTEST_DIR / "workloads"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"requests-{args.n}.json").write_text(json.dumps(reqs, ensure_ascii=False), encoding="utf-8")
    distinct = distinct_requests(reqs)
    (out / "distinct.json").write_text(json.dumps(distinct, ensure_ascii=False), encoding="utf-8")
    rate = repeat_rate([f"{r['namespace']}|{r['query']}" for r in reqs])
    print(f"{len(reqs)} requests, {len(distinct)} distinct, repeat rate {rate:.1%}")
    return 0


def cmd_loadtest_run(args: argparse.Namespace) -> int:
    from .loadtest.orchestrate import RunSpec, keep_awake, run_once_more_if_stalled, suite_runs

    root = LOADTEST_DIR / "results" / (args.out or datetime.now(UTC).strftime("%Y-%m-%d"))
    runs = suite_runs() if args.lt_command == "suite" else [RunSpec(args.scenario, args.config, args.repeat)]
    if args.smoke:
        runs = list({(r.scenario, r.config): RunSpec(r.scenario, r.config, 1, smoke=True) for r in runs}.values())
    with keep_awake():
        for spec in runs:
            if (root / spec.name / "summary.json").exists():
                print(f"skip {spec.name} (done)")
                continue
            print(f"== {datetime.now(UTC):%H:%M:%SZ} {spec.name}", flush=True)
            s = run_once_more_if_stalled(spec, root, dict(os.environ))
            lat = (s["k6"] or {}).get("latency", {}).get("all") or {}
            print(f"   k6 exit {s['k6_exit']}, p95 {lat.get('p95')}, errors {(s['k6'] or {}).get('error_rate')}, "
                  f"lost work {s['lost_work']}" + (", STALLED twice" if s["stalled"] else ""), flush=True)
    return 0


def cmd_loadtest_report(args: argparse.Namespace) -> int:
    from .loadtest.report import load_runs, power_by_run, power_line, ramp_chart, render

    root = Path(args.results_dir)
    runs = [r for r in load_runs(root) if not r["spec"].get("smoke")]
    reqs = json.loads((LOADTEST_DIR / "workloads" / "requests-3000.json").read_text(encoding="utf-8"))
    power_log = root / "power.log"
    meta = {"date": root.name, "machine": args.machine,
            "repeat_rate": repeat_rate([f"{r['namespace']}|{r['query']}" for r in reqs]),
            "power": power_line(power_by_run(runs, power_log.read_text(encoding="utf-8")))
            if power_log.exists() else ""}
    out = REPO / "docs" / "results" / f"loadtest-{root.name}.md"
    out.write_text(render(runs, meta), encoding="utf-8")
    ramp_chart(runs, out.parent / "loadtest-ramp.png")
    print(f"wrote {out} ({len(runs)} runs)")
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
    eg = sub.add_parser("export-grounding", help="copy a report's grounding results from weir.request_log")
    eg.add_argument("report_dir")
    eg.add_argument("--db-url", default=DEFAULT_DB)
    eg.set_defaults(func=cmd_export_grounding)
    sim = sub.add_parser("simulate", help="offline router simulation over the rule grid (no model calls)")
    sim.add_argument("--baseline", default=str(EVAL_DIR / "reports" / "baseline-v3"))
    sim.add_argument("--small", required=True, help="small-model trial report dir (with grounding.jsonl)")
    sim.set_defaults(func=cmd_simulate)
    gt = sub.add_parser("gate", help="Phase 3 exit gate: report vs baseline v3 on the same questions")
    gt.add_argument("report_dir")
    gt.add_argument("--baseline", default=str(EVAL_DIR / "reports" / "baseline-v3"))
    gt.set_defaults(func=cmd_gate)
    dw = sub.add_parser("derive-workload", help="lay a per-question report onto a replay order (no-cache configs)")
    dw.add_argument("report_dir")
    dw.add_argument("--workload", required=True)
    dw.add_argument("--out", required=True)
    dw.set_defaults(func=cmd_derive_workload)
    lt = sub.add_parser("loadtest", help="Phase 5 k6 load tests (stub model only)")
    lt_sub = lt.add_subparsers(dest="lt_command", required=True)
    mw = lt_sub.add_parser("make-workloads", help="write loadtest/workloads/*.json (no keys)")
    mw.add_argument("--n", type=int, default=3000)
    mw.add_argument("--seed", type=int, default=11)
    mw.set_defaults(func=cmd_loadtest_make_workloads)
    for name, helptext in (("run", "one load-test run"), ("suite", "the whole D48 matrix (resumable)")):
        p = lt_sub.add_parser(name, help=helptext)
        if name == "run":
            p.add_argument("scenario", choices=["cold", "warm", "ramp", "spike", "soak", "failure"])
            p.add_argument("--config", required=True, choices=["baseline", "cache_only", "router_only", "full"])
            p.add_argument("--repeat", type=int, default=1)
        p.add_argument("--smoke", action="store_true", help="every scenario for ~20 s, to check the wiring")
        p.add_argument("--out", help="results subfolder name (default: today's date)")
        p.set_defaults(func=cmd_loadtest_run)
    rp = lt_sub.add_parser("report", help="render docs/results/loadtest-<date>.md from a results folder")
    rp.add_argument("results_dir")
    rp.add_argument("--machine", default="Intel Core Ultra 5 225U, 14 threads, 15.5 GB RAM, Windows 11")
    rp.set_defaults(func=cmd_loadtest_report)
    args = parser.parse_args()
    sys.exit(args.func(args))
