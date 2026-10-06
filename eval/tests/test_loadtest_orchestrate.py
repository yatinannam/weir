import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from weir_eval.loadtest.orchestrate import (RECREATE_WEIR, RunSpec, Sampler, compose_command, compose_env, k6_command,
                                            k6_env, require_stub, reset_calls, suite_runs, window_query)


def test_suite_matches_the_d48_matrix():
    runs = suite_runs()
    count = lambda sc, cfg: sum(1 for r in runs if r.scenario == sc and r.config == cfg)  # noqa: E731
    for cfg in ("baseline", "cache_only", "router_only", "full"):
        assert count("cold", cfg) == 3
    assert count("warm", "cache_only") == count("warm", "full") == 3 and count("warm", "baseline") == 0
    assert count("ramp", "full") == count("ramp", "baseline") == 3
    assert count("spike", "full") == count("failure", "full") == 3 and count("soak", "full") == 1
    assert len({r.name for r in runs}) == len(runs)


def test_k6_env_per_scenario_and_smoke_is_short():
    assert k6_env(RunSpec("cold", "full", 1)) == {"RATE": "10", "DURATION": "5m"}
    assert k6_env(RunSpec("soak", "full", 1))["DURATION"] == "30m"
    assert k6_env(RunSpec("ramp", "full", 1)) == {"RAMP_STEPS": "5,10,20,40,60,80,100", "STEP_S": "90"}
    assert k6_env(RunSpec("failure", "full", 1)) == {"RATE": "10", "PHASE_S": "60"}
    assert k6_env(RunSpec("cold", "full", 1, smoke=True))["DURATION"] == "20s"
    assert k6_env(RunSpec("failure", "full", 1, smoke=True))["PHASE_S"] == "5"


def test_k6_command_passes_keys_by_name_only():  # Review Focus 5
    cmd = k6_command(RunSpec("cold", "full", 1), Path("C:/x/loadtest"), "results/d/cold-full-r1")
    assert "WEIR_KEY_PUBLIC" in cmd and "WEIR_KEY_STAFF" in cmd
    assert not any("=" in c and c.startswith("WEIR_KEY") for c in cmd)
    assert cmd[cmd.index("--network") + 1] == "weir_default" and "grafana/k6:0.54.0" in cmd
    assert "/loadtest/scripts/steady.js" == cmd[-1]
    assert "SUMMARY_OUT=/loadtest/results/d/cold-full-r1/k6-summary.json" in cmd


def test_require_stub_refuses_groq_mode():  # Review Focus 1
    require_stub({"status": "ok", "llm_mode": "stub"})
    for health in ({"status": "ok", "llm_mode": "groq"}, {"status": "ok"}):
        with pytest.raises(RuntimeError, match="stub"):
            require_stub(health)


def test_reset_calls_cover_faults_and_toxics():  # Review Focus 2
    calls = reset_calls()
    assert ("POST", "http://127.0.0.1:8001/stub/faults", {"model": "*", "mode": "none"}) in calls
    assert ("DELETE", "http://127.0.0.1:8474/proxies/weir-db/toxics/db_latency", None) in calls


def test_window_query_filters_by_time_and_config():  # Review Focus 4
    start, end = datetime(2026, 10, 6, 10, tzinfo=UTC), datetime(2026, 10, 6, 10, 5, tzinfo=UTC)
    sql, params = window_query(start, end, "full")
    assert "ts >= %s and ts < %s and config_label = %s" in sql and params == (start, end, "full")


def test_compose_env_always_pins_the_stub_model():
    # .env says LLM_MODE=groq; a compose call that recreated hospital-rag with it would load-test real models
    env = compose_env({"LLM_MODE": "groq", "WEIR_ABLATION": "", "PATH": "p"}, "full")
    assert env["LLM_MODE"] == "stub" and env["WEIR_ABLATION"] == "full" and env["PATH"] == "p"
    assert compose_env({"PATH": "p"})["LLM_MODE"] == "stub" and "WEIR_ABLATION" not in compose_env({"PATH": "p"})


def test_weir_recreate_leaves_every_other_service_alone():
    assert "--no-deps" in RECREATE_WEIR and RECREATE_WEIR[-1] == "weir"
    plain = compose_command(RECREATE_WEIR)
    assert plain[:2] == ["docker", "compose"] and "docker-compose.loadtest.yml" not in plain
    failure = compose_command(RECREATE_WEIR, failure=True)
    assert failure[failure.index("docker-compose.yml") + 2] == "docker-compose.loadtest.yml"


def test_sampler_records_and_stops_cleanly():
    sampler = Sampler(probe=lambda: {"t": time.time()}, interval_s=0.01)
    sampler.start()
    time.sleep(0.05)
    sampler.stop()
    assert sampler.samples and not sampler.is_alive()


def test_phase_windows_are_contiguous_seven_phases_from_t0():
    from weir_eval.loadtest.orchestrate import phase_windows

    t0 = int(datetime(2026, 10, 6, 10, tzinfo=UTC).timestamp() * 1000)
    w = phase_windows(t0, 60)
    assert len(w) == 7 and w[0][0] == datetime(2026, 10, 6, 10, tzinfo=UTC)
    assert all(a[1] == b[0] for a, b in zip(w, w[1:])) and w[-1][1] == datetime(2026, 10, 6, 10, 7, tzinfo=UTC)


import os  # noqa: E402

import psycopg  # noqa: E402


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
def test_window_counts_are_zero_not_null_when_every_request_is_a_cache_hit():
    # cache hits carry no route_reason or bypass_reason: a sum over all-null casts would report None, not 0
    start, end = datetime(2026, 10, 6, 10, tzinfo=UTC), datetime(2026, 10, 6, 10, 5, tzinfo=UTC)
    sql, params = window_query(start, end, "full")
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], connect_timeout=5) as conn:  # fail fast if Postgres is down
        conn.execute("create temp table request_log (ts timestamptz, config_label text, cost_usd numeric, "
                     "cache_status text, route text, route_reason text, bypass_reason text, status text, "
                     "latency_embed_ms int, latency_cache_ms int, latency_total_ms int)")
        rows = [(datetime(2026, 10, 6, 10, 1, tzinfo=UTC), "full", 0, "hit", "none", None, None, "ok", 5, 3, 12)] * 3
        conn.cursor().executemany("insert into request_log values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        cur = conn.execute(sql.replace("weir.request_log", "pg_temp.request_log"), params)
        log = dict(zip([d.name for d in cur.description], cur.fetchone(), strict=True))
        assert (log["n"], log["fallbacks"], log["cache_errors"], log["errors"], log["model_path"]) == (3, 0, 0, 0, 0)
        conn.execute("insert into request_log values (%s,'full',0,'bypass','large','small+fallback','error',"
                     "'ok',5,3,900)", (datetime(2026, 10, 6, 10, 2, tzinfo=UTC),))
        # D54: a failure run's cache-skipping requests (bypass_reason request_option) always reach the models
        conn.execute("insert into request_log values (%s,'full',0,'bypass','small','small+fallback',"
                     "'request_option','ok',5,0,700)", (datetime(2026, 10, 6, 10, 3, tzinfo=UTC),))
        cur = conn.execute(sql.replace("weir.request_log", "pg_temp.request_log"), params)
        log = dict(zip([d.name for d in cur.description], cur.fetchone(), strict=True))
        assert (log["n"], log["fallbacks"], log["cache_errors"], log["errors"], log["model_path"]) == (5, 2, 1, 0, 1)


def test_planned_duration_per_scenario():
    from weir_eval.loadtest.orchestrate import planned_duration_s

    full = [planned_duration_s(RunSpec(s, "full", 1)) for s in ("cold", "soak", "ramp", "spike", "failure")]
    assert full == [300, 1800, 630, 330, 420]
    assert [planned_duration_s(RunSpec(s, "full", 1, smoke=True)) for s in ("cold", "ramp", "spike", "failure")] \
        == [20, 30, 20, 35]


def test_a_run_that_took_far_longer_than_planned_is_stalled():
    # the machine slept mid-run once (Modern Standby): k6 took 12 min for a 35 s run and its timings are not real
    from weir_eval.loadtest.orchestrate import stalled

    spec = RunSpec("failure", "full", 1, smoke=True)
    assert not stalled({"duration_ms": 35_012}, spec) and not stalled({"duration_ms": 90_000}, spec)
    assert stalled({"duration_ms": 729_546}, spec)
    assert not stalled(None, spec) and not stalled({"duration_ms": None}, spec)   # nothing to judge by


def test_a_stalled_run_is_set_aside_and_run_once_more(tmp_path):
    from weir_eval.loadtest.orchestrate import run_once_more_if_stalled

    outcomes = iter([True, False])
    calls = []

    def fake(spec, root, env):
        calls.append(spec.name)
        (root / spec.name).mkdir(parents=True, exist_ok=True)
        s = {"stalled": next(outcomes)}
        (root / spec.name / "summary.json").write_text(json.dumps(s), encoding="utf-8")
        return s

    s = run_once_more_if_stalled(RunSpec("cold", "full", 1), tmp_path, {}, run=fake)
    assert calls == ["cold-full-r1", "cold-full-r1"] and s == {"stalled": False}
    assert json.loads((tmp_path / "cold-full-r1.stalled" / "summary.json").read_text(encoding="utf-8"))["stalled"]


def test_keep_awake_asks_windows_not_to_sleep_and_releases_it():
    from weir_eval.loadtest.orchestrate import keep_awake

    calls = []
    with keep_awake(setter=calls.append):
        assert calls == [0x80000001]                          # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    assert calls == [0x80000001, 0x80000000]                  # back to ES_CONTINUOUS only
