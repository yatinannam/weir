"""Phase 3 exit gate (addendum §7.6): a live report against baseline v3 on the same questions, request by request."""
from statistics import mean

from .summary import summarize

EPS = 1e-9


def gate(records: list[dict], baseline_by_id: dict[str, dict]) -> dict:
    ok = [r for r in records if r.get("status_code") == 200]
    if any(r.get("judge_score") is None for r in ok):
        raise ValueError("report has unjudged rows; run rejudge first")
    base = [baseline_by_id[r["id"]] for r in ok]
    pairs = list(zip(ok, base, strict=True))
    small = [(r, b) for r, b in pairs if r["meta"]["route"] == "small"]
    g = {
        "n": len(ok),
        "cost_per_1k": sum(r["meta"]["cost_usd"] for r in ok) / len(ok) * 1000,
        "base_cost_per_1k": sum(b["meta"]["cost_usd"] for b in base) / len(ok) * 1000,
        "judge": mean(r["judge_score"] for r in ok),
        "base_judge": mean(b["judge_score"] for b in base),
        "facts": mean(r["fact_score"] for r in ok),
        "base_facts": mean(b["fact_score"] for b in base),
        "small_route_judge": mean(r["judge_score"] for r, _ in small) if small else None,
        "small_route_base_judge": mean(b["judge_score"] for _, b in small) if small else None,
        "wrong_hits": summarize(ok).get("wrong_hits", 0),
    }
    g["checks"] = {
        "cost_lower": g["cost_per_1k"] < g["base_cost_per_1k"] - EPS,
        "judge_within_0_1": g["judge"] >= g["base_judge"] - 0.1 - EPS,
        "facts_no_lower": g["facts"] >= g["base_facts"] - EPS,
        "small_route_ok": not small or g["small_route_judge"] >= g["small_route_base_judge"] - EPS,
        "zero_wrong_hits": g["wrong_hits"] == 0,
    }
    g["passed"] = all(g["checks"].values())
    return g
