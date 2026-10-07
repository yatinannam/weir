import json
from pathlib import Path

import pytest

from weir_eval.loadtest.k6 import (compact_points, failure_phases, parse_summary, percentile, ramp_max_rate,
                                   ramp_steps, spike_recovery_s, window_stats)

FIX = Path(__file__).parent / "fixtures"
T0 = 1_791_288_000_000  # an arbitrary epoch ms


def test_parse_summary_per_path_and_missing_paths():
    s = parse_summary(json.loads((FIX / "k6_summary.json").read_text(encoding="utf-8")))
    assert s["requests"] == 300 and s["achieved_rate"] == 9.98 and s["dropped"] == 2 and s["error_rate"] == 0.0
    assert s["latency"]["all"] == {"p50": 40.0, "p95": 900.0, "p99": 1500.0, "count": 300}
    assert s["latency"]["hit"]["p95"] == 30.0 and s["latency"]["small"] is None   # no small-route requests


def test_compact_points_keeps_traffic_requests_and_drops_only():
    pts = compact_points((FIX / "k6_raw.jsonl").read_text(encoding="utf-8").splitlines())
    assert [(k, v, st) for _, k, v, st in pts] == [("req", 15.5, 200), ("req", 820.0, 503), ("drop", 1.0, 0)]
    assert pts[1][0] - pts[0][0] == 1377                       # 10:00:01.500 - 10:00:00.123(456789) in ms


def req(t_s, ms, status=200):
    return (T0 + int(t_s * 1000), "req", float(ms), status)


def test_percentile_nearest_rank():
    assert percentile([1, 2, 3, 4], 50) == 2 and percentile([], 95) is None


def test_window_stats():
    pts = [req(0, 100), req(1, 200), req(2, 300, 503), (T0 + 2500, "drop", 1.0, 0), req(20, 999)]
    w = window_stats(pts, T0, T0 + 10_000)
    assert w["n"] == 3 and w["p95"] == 300 and w["errors"] == 1 and w["dropped"] == 1
    assert w["error_rate"] == pytest.approx(1 / 3) and w["achieved_rate"] == pytest.approx(0.3)


def test_ramp_steps_and_max_rate():
    pts = [req(i / 5, 500) for i in range(50)]                           # step 1: 5 req/s for 10 s, fast
    pts += [req(10 + i / 10, 900) for i in range(100)]                   # step 2: 10 req/s, fine
    pts += [req(20 + i / 20, 2500) for i in range(200)]                  # step 3: 20 req/s, over budget
    steps = ramp_steps(pts, T0, [5, 10, 20], step_s=10)
    assert [s["rate"] for s in steps] == [5, 10, 20] and steps[2]["p95"] == 2500
    assert ramp_max_rate(steps) == 10


def test_ramp_step_with_dropped_iterations_is_not_ok():  # Review Focus 3
    pts = [req(i / 5, 500) for i in range(50)]
    pts += [req(10 + i / 5, 500) for i in range(50)]                     # target 10 req/s, only 5 achieved
    pts += [(T0 + 10_000 + i * 100, "drop", 1.0, 0) for i in range(50)]
    steps = ramp_steps(pts, T0, [5, 10], step_s=10)
    assert ramp_max_rate(steps) == 5


def test_ramp_max_rate_none_when_first_step_fails_and_stops_at_first_failure():
    assert ramp_max_rate([{"rate": 5, "p95": 3000, "error_rate": 0, "achieved_rate": 5}]) is None
    steps = [{"rate": 5, "p95": 100, "error_rate": 0, "achieved_rate": 5},
             {"rate": 10, "p95": 3000, "error_rate": 0, "achieved_rate": 10},
             {"rate": 20, "p95": 100, "error_rate": 0, "achieved_rate": 20}]   # a lucky later step doesn't count
    assert ramp_max_rate(steps) == 5


def test_spike_recovery():
    burst_end = T0 + 30_000
    pts = [req(30 + i * 0.5, 4000) for i in range(30)]                   # 15 s of slow answers after the burst
    pts += [req(45 + i * 0.5, 300) for i in range(60)]                   # then fast again
    assert spike_recovery_s(pts, burst_end) == 25.0                       # window [45 s, 55 s) is the first all-fast one
    assert spike_recovery_s([req(31, 5000)], burst_end) is None


def test_failure_phases():
    pts = [req(p * 10 + 1, 100 * (p + 1), 503 if p == 2 else 200) for p in range(7)]
    phases = failure_phases(pts, T0, phase_s=10)
    assert [ph["label"] for ph in phases] == ["normal", "normal", "large_rate_limited", "normal_2",
                                              "small_timeout", "db_delay", "recovery"]
    assert phases[2]["errors"] == 1 and phases[5]["p95"] == 600


def test_parse_summary_reports_chaos_failures():
    # a fault switch that silently fails leaves a phase measuring the wrong fault, so the count is surfaced
    base = json.loads((FIX / "k6_summary.json").read_text(encoding="utf-8"))
    assert parse_summary(base)["chaos_failed"] is None                              # not a failure run
    for count in (0, 2):
        base["metrics"]["chaos_failed"] = {"type": "counter", "values": {"count": count, "rate": 0.0}}
        assert parse_summary(base)["chaos_failed"] == count


def test_parse_summary_reports_how_long_k6_really_ran():
    base = json.loads((FIX / "k6_summary.json").read_text(encoding="utf-8"))
    assert parse_summary(base)["duration_ms"] is None
    base["state"] = {"testRunDurationMs": 35012.3}
    assert parse_summary(base)["duration_ms"] == 35012.3


def test_peak_window_p95_finds_the_worst_10_seconds():  # addendum §5: the spike's peak p95
    from weir_eval.loadtest.k6 import peak_window_p95

    pts = [req(i, 300) for i in range(30)] + [req(30 + i * 0.1, 2500) for i in range(50)]
    pts += [req(40 + i, 300) for i in range(20)]
    assert peak_window_p95(pts) == 2500 and peak_window_p95([]) is None


def test_first_and_last_five_minutes_p95():  # addendum §5: the soak's drift
    from weir_eval.loadtest.k6 import first_last_p95

    pts = [req(i, 100) for i in range(300)] + [req(300 + i, 500) for i in range(1200)]
    pts += [req(1500 + i, 200) for i in range(300)]
    assert first_last_p95(pts) == (100, 200) and first_last_p95([]) == (None, None)


def test_spike_that_never_left_the_budget_recovers_in_zero_seconds():  # final review 1
    burst_end = T0 + 30_000
    assert spike_recovery_s([req(i * 0.2, 300) for i in range(300)], burst_end) == 0.0


def test_ramp_step_with_drops_is_over_budget_even_above_95_percent_achieved():  # final review 5, Review Focus 3
    pts = [req(i / 5, 500) for i in range(50)]
    pts += [req(10 + i / 10, 500) for i in range(96)]                    # 9.6 of a 10 req/s target
    pts += [(T0 + 10_000 + i * 1000, "drop", 1.0, 0) for i in range(4)]
    steps = ramp_steps(pts, T0, [5, 10], step_s=10)
    assert steps[1]["achieved_rate"] >= 9.5 and ramp_max_rate(steps) == 5
