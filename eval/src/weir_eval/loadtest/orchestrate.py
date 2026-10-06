"""Phase 5 load-test orchestrator (addendum §2, D52). One run = config switch, cache prep, warm-up, k6, samplers,
request-log window, compact results. Refuses to run against real models."""
import asyncio
import ctypes
import gzip
import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg

from .k6 import FAILURE_LABELS, compact_points, failure_phases, parse_summary, ramp_steps, spike_recovery_s

REPO = Path(__file__).resolve().parents[4]
K6_IMAGE = "grafana/k6:0.54.0"
NETWORK = "weir_default"
WEIR = "http://127.0.0.1:8000"
RAG = "http://127.0.0.1:8001"
TOXI = "http://127.0.0.1:8474"
READER_DB = "postgresql://weir_reader:weir_reader@127.0.0.1:5432/weir"
NAMESPACES = ("weir-general/en/public", "weir-general/en/staff")
CACHE_CONFIGS = ("cache_only", "full")
SCRIPT = {"cold": "steady", "warm": "steady", "soak": "steady", "ramp": "ramp", "spike": "spike", "failure": "failure"}
RAMP_RATES = [5, 10, 20, 40, 60, 80, 100]
CONTAINERS = ["weir-weir-1", "weir-hospital-rag-1", "weir-postgres-1"]
# --no-deps: recreating Weir must never reconcile (and so possibly recreate) hospital-rag or Postgres mid-suite
RECREATE_WEIR = ["up", "-d", "--no-deps", "--force-recreate", "weir"]
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


@dataclass(frozen=True)
class RunSpec:
    scenario: str
    config: str
    repeat: int
    smoke: bool = False

    @property
    def name(self) -> str:
        return f"{self.scenario}-{self.config}-r{self.repeat}"


def suite_runs() -> list[RunSpec]:
    runs = []
    for r in (1, 2, 3):
        runs += [RunSpec("cold", c, r) for c in ("baseline", "cache_only", "router_only", "full")]
        runs += [RunSpec("warm", c, r) for c in CACHE_CONFIGS]
        runs += [RunSpec("ramp", c, r) for c in ("full", "baseline")]
        runs += [RunSpec("spike", "full", r), RunSpec("failure", "full", r)]
    return runs + [RunSpec("soak", "full", 1)]


def k6_env(spec: RunSpec) -> dict[str, str]:
    s = spec.smoke
    if spec.scenario in ("cold", "warm", "soak"):
        return {"RATE": "10", "DURATION": "20s" if s else ("30m" if spec.scenario == "soak" else "5m")}
    if spec.scenario == "ramp":
        return {"RAMP_STEPS": "5,10,20" if s else ",".join(map(str, RAMP_RATES)), "STEP_S": "10" if s else "90"}
    if spec.scenario == "spike":
        return {"BASE_S": "5", "BURST_S": "5", "AFTER_S": "10"} if s else {}
    return {"RATE": "10", "PHASE_S": "5" if s else "60"}


def k6_command(spec: RunSpec, host_loadtest_dir: Path, run_rel: str) -> list[str]:
    cmd = ["docker", "run", "--rm", "--network", NETWORK, "-v", f"{host_loadtest_dir}:/loadtest",
           "-e", "WEIR_KEY_PUBLIC", "-e", "WEIR_KEY_STAFF",          # names only: values come from our env
           "-e", "WORKLOAD=/loadtest/workloads/requests-3000.json",
           "-e", f"SUMMARY_OUT=/loadtest/{run_rel}/k6-summary.json"]
    for k, v in k6_env(spec).items():
        cmd += ["-e", f"{k}={v}"]
    return cmd + [K6_IMAGE, "run", "--quiet", "--out", f"json=/loadtest/{run_rel}/k6-raw.json",
                  f"/loadtest/scripts/{SCRIPT[spec.scenario]}.js"]


def planned_duration_s(spec: RunSpec) -> int:
    e = k6_env(spec)
    if spec.scenario in ("cold", "warm", "soak"):
        return int(e["DURATION"][:-1]) * (60 if e["DURATION"].endswith("m") else 1)
    if spec.scenario == "ramp":
        return len(e["RAMP_STEPS"].split(",")) * int(e["STEP_S"])
    if spec.scenario == "spike":
        return int(e.get("BASE_S", 120)) + int(e.get("BURST_S", 30)) + int(e.get("AFTER_S", 180))
    return len(FAILURE_LABELS) * int(e["PHASE_S"])


def stalled(k6: dict | None, spec: RunSpec, slack_s: int = 60) -> bool:
    """k6 ran far longer than planned: the machine slept or froze mid-run, so its timings are not real."""
    duration = (k6 or {}).get("duration_ms")
    return duration is not None and duration > (planned_duration_s(spec) + slack_s) * 1000


@contextmanager
def keep_awake(setter: Callable[[int], object] | None = None):
    """Ask Windows not to idle-sleep while runs are in progress (it entered Modern Standby mid-run once).
    Closing the lid still sleeps the machine. No-op on other systems."""
    if setter is None:
        if sys.platform != "win32":
            yield
            return
        setter = ctypes.windll.kernel32.SetThreadExecutionState
    setter(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        setter(ES_CONTINUOUS)


def require_stub(health: dict) -> None:
    if health.get("llm_mode") != "stub":
        raise RuntimeError("hospital-rag is not in stub mode (LLM_MODE=stub); refusing to load-test real models")


def compose_env(env: dict, config: str | None = None) -> dict[str, str]:
    """Every compose call pins LLM_MODE=stub: .env says groq, and a recreated hospital-rag must never pick that up."""
    out = {**env, "LLM_MODE": "stub"}
    if config is not None:
        out["WEIR_ABLATION"] = config
    return out


def compose_command(args: list[str], failure: bool = False) -> list[str]:
    files = ["-f", "docker-compose.yml", "-f", "docker-compose.loadtest.yml"] if failure else []
    return ["docker", "compose", *files, "--profile", "loadtest", *args]


def reset_calls() -> list[tuple[str, str, dict | None]]:
    return [("POST", f"{RAG}/stub/faults", {"model": "*", "mode": "none"}),
            ("DELETE", f"{TOXI}/proxies/weir-db/toxics/db_latency", None)]


def window_query(start: datetime, end: datetime, config: str) -> tuple[str, tuple]:
    sql = ("select count(*) as n, coalesce(sum(cost_usd), 0)::float as cost, "
           "avg((cache_status = 'hit')::int)::float as hit_rate, avg((route = 'small')::int)::float as small, "
           # count(*) filter, not sum(cast): cache hits have no route_reason/bypass_reason, and an all-null sum is null
           "count(*) filter (where route_reason like '%%fallback') as fallbacks, "
           "count(*) filter (where bypass_reason = 'error') as cache_errors, "
           "count(*) filter (where status <> 'ok') as errors, "
           "avg(coalesce(latency_embed_ms, 0) + coalesce(latency_cache_ms, 0))::float as overhead_mean, "
           "percentile_cont(0.95) within group (order by coalesce(latency_embed_ms, 0) "
           "+ coalesce(latency_cache_ms, 0))::float as overhead_p95, "
           "percentile_cont(0.5) within group (order by latency_total_ms)::float as internal_p50, "
           "percentile_cont(0.95) within group (order by latency_total_ms)::float as internal_p95 "
           "from weir.request_log where ts >= %s and ts < %s and config_label = %s")
    return sql, (start, end, config)


def phase_windows(t0_ms: int, phase_s: int) -> list[tuple[datetime, datetime]]:
    """The failure run's phases as request-log time windows (fallbacks and cache bypasses per phase, addendum §5)."""
    edges = [datetime.fromtimestamp((t0_ms + i * phase_s * 1000) / 1000, UTC) for i in range(len(FAILURE_LABELS) + 1)]
    return list(zip(edges, edges[1:]))


def _log_window(conn: psycopg.Connection, start: datetime, end: datetime, config: str) -> dict:
    sql, params = window_query(start, end, config)
    cur = conn.execute(sql, params)
    return dict(zip([d.name for d in cur.description], cur.fetchone(), strict=True))


def _compose(args: list[str], env: dict, failure: bool = False) -> None:
    proc = subprocess.run(compose_command(args, failure), env=env, cwd=REPO, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {proc.stderr[-1000:]}")


def _wait_label(config: str, timeout_s: int = 180) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if httpx.get(f"{WEIR}/healthz", timeout=5).json().get("config_label") == config:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError(f"weir did not come up as {config}")


def _reset(client: httpx.Client) -> None:
    for method, url, body in reset_calls():
        try:
            client.request(method, url, json=body, timeout=5)
        except httpx.HTTPError:
            pass  # toxiproxy is only up for failure runs


async def _send(requests: list[dict], env: dict, concurrency: int = 5) -> None:
    keys = {"weir-general/en/public": env["WEIR_KEY_PUBLIC"], "weir-general/en/staff": env["WEIR_KEY_STAFF"]}
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=WEIR, timeout=60) as http:
        async def one(r):
            async with sem:
                await http.post("/v1/query", json=r, headers={"X-API-Key": keys[r["namespace"]]})
        await asyncio.gather(*(one(r) for r in requests))


def _probe() -> dict:
    """One resource sample: docker stats (CPU, memory) for the measured containers and Postgres connections."""
    row: dict = {"t": time.time()}
    out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *CONTAINERS],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        s = json.loads(line)
        row[s["Name"]] = {"cpu": float(s["CPUPerc"].rstrip("%")), "mem": s["MemUsage"].split(" / ")[0]}
    try:
        with psycopg.connect(READER_DB, connect_timeout=3) as conn:
            row["db_connections"] = conn.execute("select count(*) from pg_stat_activity").fetchone()[0]
    except psycopg.Error:
        row["db_connections"] = None
    return row


class Sampler(threading.Thread):
    """Resource samples every interval_s (default 5 s) while k6 runs."""

    def __init__(self, probe: Callable[[], dict] = _probe, interval_s: float = 5):
        super().__init__(daemon=True)
        self.samples: list[dict] = []
        self._probe, self._interval = probe, interval_s
        self._halt = threading.Event()  # not _stop: Thread.join() calls its own _stop()

    def run(self) -> None:
        while not self._halt.is_set():
            self.samples.append(self._probe())
            self._halt.wait(self._interval)

    def stop(self) -> None:
        self._halt.set()
        self.join(timeout=10)


def _lost_work() -> int:
    text = httpx.get(f"{WEIR}/metrics", timeout=5).text
    names = ("weir_log_rows_dropped_total", "weir_log_rows_failed_total",
             "weir_cache_jobs_dropped_total", "weir_cache_jobs_failed_total")
    return int(sum(float(line.split()[-1]) for line in text.splitlines() if line.split(" ")[0] in names))


def execute(spec: RunSpec, results_root: Path, env: dict) -> dict:
    run_dir = results_root / spec.name
    run_dir.mkdir(parents=True, exist_ok=True)
    workload = json.loads((REPO / "loadtest" / "workloads" / "requests-3000.json").read_text(encoding="utf-8"))
    distinct = json.loads((REPO / "loadtest" / "workloads" / "distinct.json").read_text(encoding="utf-8"))
    with httpx.Client() as client:
        require_stub(client.get(f"{RAG}/healthz", timeout=10).json())
        _reset(client)
        failure = spec.scenario == "failure"
        if failure:
            _compose(["up", "-d", "--no-deps", "toxiproxy"], compose_env(env), failure=True)
        _compose(RECREATE_WEIR, compose_env(env, spec.config), failure=failure)
        _wait_label(spec.config)
        require_stub(client.get(f"{RAG}/healthz", timeout=10).json())   # again, after every compose call
        asyncio.run(_send(workload[:20], env))                      # process warm-up, unmeasured
        for ns in NAMESPACES:                                       # every run starts from an empty cache
            client.delete(f"{WEIR}/v1/cache", params={"namespace": ns},
                          headers={"X-API-Key": env["WEIR_KEY_ADMIN"]}, timeout=30)
        if spec.scenario != "cold" and spec.config in CACHE_CONFIGS:
            asyncio.run(_send(distinct, env))                       # pre-fill, unmeasured
            time.sleep(3)                                           # let background cache writes land
    sampler = Sampler()
    sampler.start()
    started = datetime.now(UTC)
    rel = run_dir.relative_to(REPO / "loadtest").as_posix()
    proc = subprocess.run(k6_command(spec, REPO / "loadtest", rel), env=env, capture_output=True, text=True)
    ended = datetime.now(UTC)
    sampler.stop()
    time.sleep(3)                                                   # request-log rows are written asynchronously
    raw_path = run_dir / "k6-raw.json"
    points = compact_points(raw_path.read_text(encoding="utf-8").splitlines()) if raw_path.exists() else []
    with gzip.open(run_dir / "requests.csv.gz", "wt", encoding="utf-8") as f:
        f.write("t_ms,kind,value,status\n" + "".join(f"{t},{k},{v},{s}\n" for t, k, v, s in points))
    raw_path.unlink(missing_ok=True)
    t0 = points[0][0] if points else int(started.timestamp() * 1000)
    with psycopg.connect(READER_DB) as conn:
        log = _log_window(conn, started, ended, spec.config)
        phase_logs = ([_log_window(conn, a, b, spec.config) for a, b in phase_windows(t0, int(k6_env(spec)["PHASE_S"]))]
                      if spec.scenario == "failure" else [])
    k6sum = run_dir / "k6-summary.json"
    summary = {
        "spec": asdict(spec), "started": started.isoformat(), "ended": ended.isoformat(),
        "k6_exit": proc.returncode, "k6_stderr_tail": proc.stderr[-2000:],
        "k6": parse_summary(json.loads(k6sum.read_text(encoding="utf-8"))) if k6sum.exists() else None,
        "request_log": log, "resources": sampler.samples, "lost_work": _lost_work(),
    }
    summary["stalled"] = stalled(summary["k6"], spec)
    if spec.scenario == "ramp":
        env6 = k6_env(spec)
        summary["steps"] = ramp_steps(points, t0, [int(r) for r in env6["RAMP_STEPS"].split(",")],
                                      int(env6["STEP_S"]))
    if spec.scenario == "spike":
        env6 = k6_env(spec)
        burst_end = t0 + (int(env6.get("BASE_S", 120)) + int(env6.get("BURST_S", 30))) * 1000
        summary["recovery_s"] = spike_recovery_s(points, burst_end)
    if spec.scenario == "failure":
        summary["phases"] = [{**ph, "log": pl} for ph, pl in
                             zip(failure_phases(points, t0, int(k6_env(spec)["PHASE_S"])), phase_logs, strict=True)]
    with httpx.Client() as client:
        _reset(client)                                              # never leave a fault on for the next run
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary


def run_once_more_if_stalled(spec: RunSpec, results_root: Path, env: dict,
                             run: Callable[[RunSpec, Path, dict], dict] = execute) -> dict:
    """A stalled run is kept aside as <name>.stalled (not a result) and run once more."""
    summary = run(spec, results_root, env)
    if summary.get("stalled"):
        aside = results_root / f"{spec.name}.stalled"
        shutil.rmtree(aside, ignore_errors=True)
        (results_root / spec.name).rename(aside)
        summary = run(spec, results_root, env)
    return summary
