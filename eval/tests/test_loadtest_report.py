import json

from weir_eval.loadtest.report import evaluate_checks, load_runs, median_range, render

LABELS = ["normal", "normal", "large_rate_limited", "normal_2", "small_timeout", "db_delay", "recovery"]


def run(scenario, config, repeat, p95, **extra):
    k6 = {"requests": 3000, "achieved_rate": 10.0, "error_rate": 0.0, "dropped": 0, "chaos_failed": None,
          "duration_ms": 300_000,
          "latency": {"all": {"p50": p95 / 3, "p95": p95, "p99": p95 * 1.4, "count": 3000},
                      "hit": None, "small": None, "large": None}}
    log = {"n": 3000, "cost": 0.03, "hit_rate": 0.9, "small": 0.1, "fallbacks": 0, "cache_errors": 0, "errors": 0,
           "model_path": 0, "overhead_mean": 12.0, "overhead_p95": 25.0, "internal_p50": 15.0,
           "internal_p95": 700.0}
    return {"spec": {"scenario": scenario, "config": config, "repeat": repeat, "smoke": False},
            "k6": k6, "request_log": log, "resources": [], "lost_work": 0, "stalled": False, **extra}


def phases(model_path=200, errors=0, db_p95=900):
    return [{"label": lbl, "n": 600, "p95": db_p95 if lbl == "db_delay" else 900, "errors": errors,
             "error_rate": 0.0, "dropped": 0, "achieved_rate": 10,
             "log": {"n": 600, "fallbacks": 40 if lbl == "large_rate_limited" else 0,
                     "cache_errors": 300 if lbl == "db_delay" else 0, "model_path": model_path}}
            for lbl in LABELS]


def failure_run(r, **kw):
    out = run("failure", "full", r, 900, phases=phases(**kw))
    out["k6"]["chaos_failed"] = 0
    return out


def test_median_range():
    assert median_range([3, 1, 2]) == (2, 1, 3) and median_range([None, 5]) == (5, 5, 5)
    assert median_range([]) is None


def test_checks_pass_on_good_runs():
    runs = [run("cold", "baseline", r, 1100) for r in (1, 2, 3)] + [run("warm", "full", r, 300) for r in (1, 2, 3)]
    runs += [failure_run(r) for r in (1, 2, 3)]
    res = [{"t": i * 5, "weir-weir-1": {"cpu": 10.0, "mem": "500MiB"}} for i in range(400)]
    runs += [run("soak", "full", 1, 800, resources=res,
                 soak={"first_p95": 800, "last_p95": 820})]
    checks = {c["name"]: c for c in evaluate_checks(runs)}
    assert checks["warm p95 at least 30% below baseline"]["passed"] is True
    assert checks["0 errors during model faults"]["passed"] is True
    assert checks["cache outage invisible"]["passed"] is True
    assert checks["no leaks over the soak"]["passed"] is True
    assert checks["no lost background work"]["passed"] is True


def test_checks_fail_or_are_unknown_honestly():
    runs = [run("cold", "baseline", 1, 1000), run("warm", "full", 1, 900)]        # only 10% better
    runs.append(run("cold", "full", 1, 900, lost_work=3))
    checks = {c["name"]: c for c in evaluate_checks(runs)}
    assert checks["warm p95 at least 30% below baseline"]["passed"] is False
    assert checks["no lost background work"]["passed"] is False
    assert checks["0 errors during model faults"]["passed"] is None                 # no failure runs yet


def test_model_fault_check_is_not_passed_when_no_request_reached_a_model():  # D54
    checks = {c["name"]: c for c in evaluate_checks([failure_run(r, model_path=0) for r in (1, 2, 3)])}
    assert checks["0 errors during model faults"]["passed"] is None
    assert "not tested" in checks["0 errors during model faults"]["detail"]


def test_slow_cache_outage_fails_the_check():
    checks = {c["name"]: c for c in evaluate_checks([failure_run(r, db_p95=3500) for r in (1, 2, 3)])}
    assert checks["cache outage invisible"]["passed"] is False


def test_stalled_runs_and_failed_fault_switches_are_left_out(tmp_path):
    good, slept = run("cold", "baseline", 1, 1000), run("cold", "baseline", 2, 9000, stalled=True)
    broken = failure_run(1, errors=5)
    broken["k6"]["chaos_failed"] = 1                                       # a phase measured the wrong fault
    for name, r in (("cold-baseline-r1", good), ("cold-baseline-r2", slept), ("failure-full-r1", broken),
                    ("cold-baseline-r3.stalled", run("cold", "baseline", 3, 9000, stalled=True))):
        (tmp_path / name).mkdir()
        (tmp_path / name / "summary.json").write_text(json.dumps(r), encoding="utf-8")
    runs = load_runs(tmp_path)
    assert len(runs) == 3                                                  # the set-aside .stalled copy is not a run
    checks = {c["name"]: c for c in evaluate_checks(runs + [run("warm", "full", 1, 300)])}
    assert checks["warm p95 at least 30% below baseline"]["passed"] is True        # 1000 ms baseline, not 9000
    assert checks["0 errors during model faults"]["passed"] is None
    md = render(runs, {"date": "d", "machine": "m", "repeat_rate": 0.9})
    assert "Excluded: 1 stalled run" in md and "1 failure run whose fault switch failed" in md


def test_failure_table_shows_model_path_fallbacks_and_bypasses():
    md = render([failure_run(r) for r in (1, 2, 3)], {"date": "d", "machine": "m", "repeat_rate": 0.9})
    assert "| Phase | Requests | Model path | Errors | p95 | Fallbacks | Cache bypasses |" in md
    assert "| large_rate_limited | 1800 | 600 | 0 | 900 ms | 120 | 0 |" in md
    assert "| db_delay | 1800 | 600 | 0 | 900 ms | 0 | 900 |" in md


def test_render_contains_every_section():
    runs = [run("cold", c, 1, 900) for c in ("baseline", "cache_only", "router_only", "full")]
    md = render(runs, {"date": "2026-10-07", "machine": "Intel Core Ultra 5 225U, 15.5 GB", "repeat_rate": 0.97})
    for heading in ("## Setup", "## Cold cache: four-way", "## Warm cache", "## Latency per path",
                    "## Gateway overhead", "## Ramp", "## Spike", "## Soak", "## Failure injection", "## Checks",
                    "## Limitations"):
        assert heading in md, heading
    assert "no runs yet" in md          # sections without data say so instead of failing
    assert "k6 0.54.0" in md            # versions are part of the setup (addendum §6)


def test_no_runs_means_no_check_passes():
    assert all(c["passed"] is None for c in evaluate_checks([]))          # "0 lost across 0 runs" is not a pass
