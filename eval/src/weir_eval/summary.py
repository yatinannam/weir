import math
from collections import Counter, defaultdict
from statistics import mean


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _judge_mean(records: list[dict]) -> float | None:
    scores = [r["judge_score"] for r in records if r.get("judge_score") is not None]
    return round(mean(scores), 3) if scores else None


def _group_stats(records: list[dict]) -> dict:
    return {"n": len(records),
            "judge_mean": _judge_mean(records),
            "fact_mean": round(mean(r["fact_score"] for r in records), 3)}


def summarize(records: list[dict]) -> dict:
    ok = [r for r in records if r.get("status_code") == 200]
    summary: dict = {"n": len(records), "ok": len(ok), "errors": len(records) - len(ok)}
    if not ok:
        return summary
    latencies = [r["client_latency_ms"] for r in ok]
    total_cost = sum(r["meta"]["cost_usd"] for r in ok)
    by_group: dict[str, list[dict]] = defaultdict(list)
    by_difficulty: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        by_group[r["group"]].append(r)
        by_difficulty[r["difficulty"]].append(r)
    routes = Counter(r["meta"]["route"] for r in ok)
    hits = sum(1 for r in ok if r["meta"]["cache_status"] == "hit")
    summary.update({
        "cost_usd_total": total_cost,
        "cost_per_1k_usd": total_cost / len(ok) * 1000,
        "latency_ms": {f"p{p}": percentile(latencies, p) for p in (50, 95, 99)},
        "judge_mean": _judge_mean(ok),
        "judge_errors": sum(1 for r in ok if r.get("judge_score") is None),
        "fact_mean": round(mean(r["fact_score"] for r in ok), 3),
        "cache_hit_rate": hits / len(ok),
        "route_mix": {k: v / len(ok) for k, v in routes.items()},
        "by_group": {g: _group_stats(rs) for g, rs in sorted(by_group.items())},
        "by_difficulty": {d: _group_stats(rs) for d, rs in sorted(by_difficulty.items())},
    })
    return summary


def pick_spot_checks(records: list[dict], n: int = 20) -> list[dict]:
    """Human review sample, weighted toward judge vs key-fact disagreement (spec §11.2)."""
    ok = [r for r in records if r.get("status_code") == 200 and r.get("judge_score") is not None]
    return sorted(ok, key=lambda r: abs((r["judge_score"] - 1) / 4 - r["fact_score"]), reverse=True)[:n]


def render_markdown(summary: dict, header: dict, spot_checks: list[dict]) -> str:
    lines = ["# Eval run", ""]
    lines += [f"- **{k}:** {v}" for k, v in header.items()]
    lines += ["", f"Requests: {summary['n']} (ok {summary['ok']}, errors {summary['errors']})", ""]
    if summary.get("ok"):
        lat = summary["latency_ms"]
        lines += [
            "| Metric | Value |", "| --- | --- |",
            f"| Cost per 1,000 requests (USD, list prices) | {summary['cost_per_1k_usd']:.4f} |",
            f"| Latency p50 / p95 / p99 (ms, sequential, client-side) | {lat['p50']} / {lat['p95']} / {lat['p99']} |",
            f"| Judge score mean (1-5) | {summary['judge_mean']} ({summary['judge_errors']} not judged) |",
            f"| Key-fact score mean (0-1) | {summary['fact_mean']} |",
            f"| Cache hit rate | {summary['cache_hit_rate']:.1%} |",
            f"| Route mix | {', '.join(f'{k} {v:.0%}' for k, v in summary['route_mix'].items())} |",
            "", "## By group", "", "| Group | n | Judge | Facts |", "| --- | --- | --- | --- |",
        ]
        lines += [f"| {g} | {s['n']} | {s['judge_mean']} | {s['fact_mean']} |" for g, s in summary["by_group"].items()]
        lines += ["", "## By difficulty", "", "| Difficulty | n | Judge | Facts |", "| --- | --- | --- | --- |"]
        lines += [f"| {d} | {s['n']} | {s['judge_mean']} | {s['fact_mean']} |" for d, s in summary["by_difficulty"].items()]
    if spot_checks:
        lines += ["", "## Human spot check (judge vs key-fact disagreement first)", "",
                  "| id | judge | facts | your verdict |", "| --- | --- | --- | --- |"]
        lines += [f"| {r['id']} | {r['judge_score']} | {r['fact_score']:.2f} |  |" for r in spot_checks]
    return "\n".join(lines) + "\n"
