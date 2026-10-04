from weir_eval.summary import percentile, pick_spot_checks, render_markdown, summarize


def rec(i, latency, cost, judge, fact, group="distinct", status=200, route="large"):
    return {"id": f"q{i}", "group": group, "difficulty": "easy", "status_code": status,
            "client_latency_ms": latency, "meta": {"cost_usd": cost, "cache_status": "bypass", "route": route},
            "judge_score": judge, "fact_score": fact, "query": "q", "answer": "a"}


def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([7], 99) == 7


def test_summarize_numbers():
    records = [rec(1, 100, 0.001, 5, 1.0), rec(2, 300, 0.003, 3, 0.5, group="trap"),
               {"id": "q3", "group": "distinct", "difficulty": "easy", "status_code": 503, "error": "x"}]
    s = summarize(records)
    assert (s["n"], s["ok"], s["errors"]) == (3, 2, 1)
    assert abs(s["cost_per_1k_usd"] - 2.0) < 1e-9  # (0.004 / 2) * 1000
    assert s["judge_mean"] == 4.0 and s["fact_mean"] == 0.75
    assert s["by_group"]["trap"]["n"] == 1
    assert s["route_mix"] == {"large": 1.0}


def test_spot_checks_prefer_disagreement():
    agree = rec(1, 1, 0, 5, 1.0)
    disagree = rec(2, 1, 0, 5, 0.0)  # judge says perfect, facts say nothing
    assert pick_spot_checks([agree, disagree], n=1)[0]["id"] == "q2"


def test_render_markdown_contains_key_numbers():
    s = summarize([rec(1, 100, 0.001, 5, 1.0)])
    md = render_markdown(s, {"config": "baseline", "split": "all"}, [])
    assert "baseline" in md and "Cost per 1,000 requests" in md and "p95" in md


def test_summary_excludes_missing_judge_scores_and_counts_them():
    missing = rec(2, 200, 0.001, None, 0.5)
    s = summarize([rec(1, 100, 0.001, 4, 1.0), missing])
    assert s["judge_mean"] == 4.0 and s["judge_errors"] == 1
    assert s["fact_mean"] == 0.75
    assert [r["id"] for r in pick_spot_checks([missing, rec(1, 1, 0, 5, 1.0)])] == ["q1"]


def test_cache_metrics_and_wrong_hits():
    def r(i, status, fact, judge, group="paraphrase", latency=10):
        x = rec(i, latency, 0.0, judge, fact, group=group)
        x["meta"]["cache_status"] = status
        return x

    s = summarize([r(1, "miss", 1.0, 5, latency=900), r(2, "hit", 1.0, 5), r(3, "hit", 0.0, 5, group="trap"),
                   r(4, "hit", 1.0, 2), r(5, "bypass", 1.0, 5, group="trap")])
    assert s["hits"] == 3 and s["wrong_hits"] == 2
    assert s["hit_rate_by_group"] == {"paraphrase": 2 / 3, "trap": 0.5}
    assert s["latency_by_cache_status"]["hit"]["n"] == 3 and s["latency_by_cache_status"]["miss"]["p50"] == 900


def _rrec(route, judge, cost, latency, escalated=False, status="miss"):
    return {"id": "q", "group": "distinct", "difficulty": "easy", "status_code": 200, "client_latency_ms": latency,
            "fact_score": 1.0, "judge_score": judge,
            "meta": {"route": route, "escalated": escalated, "cost_usd": cost, "cache_status": status}}


def test_by_route_breakdown_and_escalation_rate():
    import pytest

    s = summarize([_rrec("small", 5, 0.0002, 300), _rrec("small", 4, 0.0006, 900, escalated=True),
                   _rrec("large", 5, 0.0004, 700), _rrec("none", 5, 0.0, 50, status="hit")])
    assert s["by_route"]["small"] == pytest.approx({"n": 2, "judge_mean": 4.5, "fact_mean": 1.0,
                                                    "cost_per_1k_usd": 0.4, "p50": 300, "p95": 900})
    assert s["by_route"]["large"]["n"] == 1 and s["by_route"]["none"]["cost_per_1k_usd"] == 0
    assert s["escalation_rate"] == 0.5
    md = render_markdown(s, {}, [])
    assert "## By route" in md and "Escalation rate (of requests routed small): 50.0%" in md


def test_escalation_rate_none_without_small_routes():
    s = summarize([_rrec("large", 5, 0.0004, 700)])
    assert s["escalation_rate"] is None and "## By route" not in render_markdown(s, {}, [])
