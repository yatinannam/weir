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
