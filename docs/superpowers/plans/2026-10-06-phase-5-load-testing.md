# Phase 5 Load Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure Weir under concurrent load with k6: cold/warm four-way, ramp (full vs baseline), spike, soak and failure injection. Use a realistic stub model, and produce a reproducible results report with honest pass/fail checks.

**Architecture:**
- **hospital-rag's stub model** gains realistic per-model latency and a stub-only fault endpoint.
- **Toxiproxy** can sit on Weir's database link.
- **k6 scripts** in `loadtest/scripts/` generate the traffic. They tag latency per path, and a chaos scenario flips the faults.
- **A Python orchestrator in the eval tool** (`weir_eval loadtest ...`) handles each run end to end:
  1. switches the config, prepares the cache and warms Weir up
  2. runs k6 in Docker while sampling `docker stats` and database connections
  3. reads the request log for the run window
  4. writes compact results
- **The report** is rendered from those results files by pure, unit-tested code.

**Tech Stack:** k6 (`grafana/k6:0.54.0`), Toxiproxy (`ghcr.io/shopify/toxiproxy:2.9.0`), Python 3.12, FastAPI, psycopg 3, httpx, matplotlib, pytest, Docker Compose, GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-10-06-phase-5-load-testing-design.md`](../specs/2026-10-06-phase-5-load-testing-design.md) (approved 2026-10-06). Builds on main spec §12 and the original spec's "Load testing" section.

## Global Constraints

- **Free tools only** (D0).
- **Pinned images:** `grafana/k6:0.54.0`, `ghcr.io/shopify/toxiproxy:2.9.0`.
- **Never load-test real models.** The orchestrator refuses to run unless hospital-rag's `/healthz` reports `llm_mode` = `stub`. Load runs must never spend Groq quota.
- **Stub timing (D49):** lognormal per model, seeded (`STUB_SEED=7`):

  | Model | Median | p95 |
  | --- | --: | --: |
  | Small, `openai/gpt-oss-20b` | 553 ms | 830 ms |
  | Large, `openai/gpt-oss-120b` | 748 ms | 1,429 ms |

  These were fitted from 740 clean request-log rows on 2026-10-06. Unknown models use the large model's timing.
- **Latency budget (D50):** p95 at most 2,000 ms. A ramp step is OK when p95 ≤ 2,000 ms, error rate ≤ 1%, and achieved rate ≥ 95% of target.
- **Workload:** 3,000 requests, Zipf exponent 1.1, seed 11, over the 158 eval questions, sent in order at a constant arrival rate.
- **Scenarios and repeats (D48):**

  | Scenario | Configs | Repeats |
  | --- | --- | --: |
  | Cold | baseline, cache_only, router_only, full | 3 |
  | Warm | cache_only, full | 3 |
  | Ramp | full, baseline | 3 |
  | Spike | full | 3 |
  | Failure | full | 3 |
  | Soak | full | 1 |

  - Cold and warm run at 10 req/s for 5 min.
  - The ramp steps through 5, 10, 20, 40, 60, 80 and 100 req/s, 90 s per step, and aborts at 5% errors.
  - The spike runs 5 req/s for 2 min, then 60 req/s for 30 s, then 5 req/s for 3 min.
  - The soak runs 10 req/s for 30 min.
  - The failure run is 10 req/s for 7 one-minute phases: normal, normal, large rate-limited, normal, small timeout (5 s), Weir database link +2 s, normal.
- **API keys are never written to files or command lines.** k6 receives them as `-e WEIR_KEY_PUBLIC -e WEIR_KEY_STAFF`: names only, with the values inherited from the orchestrator's environment.
- **Ports are localhost-only.** Toxiproxy's API is on `127.0.0.1:8474`, its proxy only on the Docker network.
- **Windows host:**
  - Use `127.0.0.1`, never `localhost`.
  - Use `MSYS_NO_PATHCONV=1` with `docker run -v`, and `$(pwd -W)` for mount sources in Git Bash.
  - Never edit files with PowerShell `Set-Content`.
  - Use Python scripts instead of long heredocs.
- **Docs:** no emojis. Times to the user in IST.
- **Workflow:**
  - After each task's tests pass, commit, push and fast-forward main without asking: `git push origin phase-5 && git push origin phase-5:main`.
  - Then pause for the user's go-ahead before the next task.
- **RAM is tight (15.5 GB).**
  - Stop containers when a step is done.
  - k6 `maxVUs` is capped at 500.
  - Don't run the monitoring profile during measured runs unless watching. Grafana refresh is 5 min after Task 1.

## Review Focus

1. **The orchestrator pointed at real models.** If hospital-rag is in `groq` mode, `weir_eval loadtest run` must refuse before sending a single request. Pinned in Task 7 (`test_require_stub_refuses_groq_mode`).
2. **A failure run aborted mid-way leaves a fault switched on.** The next run would then be silently degraded. k6 `teardown` restores faults and toxics, and the orchestrator also resets both before every run. Pinned in Task 7 (`test_reset_calls_cover_faults_and_toxics`), and observed in the Task 7 live smoke.
3. **A ramp step where k6 couldn't keep up** (dropped iterations, achieved rate below target) must count as over budget, not as a fast step. Pinned in Task 6 (`test_ramp_step_with_dropped_iterations_is_not_ok`).
4. **Request-log statistics must belong to this run only.** They are filtered by the run's time window and `config_label`, so rows from a previous run or another config never leak in. Pinned in Task 7 (`test_window_query_filters_by_time_and_config`).
5. **API keys must never reach files or command lines** (request files, the k6 command, results). Pinned in Task 5 (`test_request_file_has_no_keys`) and Task 7 (`test_k6_command_passes_keys_by_name_only`).

---

## File Structure

| File | Create/Modify | Responsibility |
| --- | --- | --- |
| `monitoring/grafana/build_dashboard.py`, `dashboards/weir.json` | Modify | M25: refresh 5 min, time-bounded variable queries |
| `services/hospital-rag/src/hospital_rag/llm.py` | Modify | `FixedTiming`, `LognormalTiming`, `LatencyProfile`; `StubLLM(timing=…)`; stub faults |
| `services/hospital-rag/src/hospital_rag/settings.py`, `main.py` | Modify | Stub timing settings; `POST/GET /stub/faults` |
| `docker-compose.yml`, `docker-compose.loadtest.yml`, `loadtest/toxiproxy.json` | Modify / Create | hospital-rag stub env; Toxiproxy (profile `loadtest`); override routing Weir's DB through Toxiproxy |
| `loadtest/scripts/lib.js`, `steady.js`, `ramp.js`, `spike.js`, `failure.js` | Create | k6 traffic, per-path trends, chaos scenario |
| `loadtest/workloads/requests-3000.json`, `distinct.json` | Create (generated) | Request lists without keys |
| `eval/src/weir_eval/loadtest/__init__.py` | Create | Package |
| `eval/src/weir_eval/loadtest/workload.py` | Create | `make_request_file`, `distinct_requests` |
| `eval/src/weir_eval/loadtest/k6.py` | Create | Parse k6 summaries; compact raw points; window, ramp, spike and phase stats |
| `eval/src/weir_eval/loadtest/orchestrate.py` | Create | `RunSpec`, `suite_runs`, k6 command, stub guard, resets, request-log window query, samplers, `execute` |
| `eval/src/weir_eval/loadtest/report.py` | Create | Aggregate repeats, evaluate checks, render markdown, ramp chart |
| `eval/src/weir_eval/cli.py` | Modify | `loadtest make-workloads`, `run`, `suite`, `report` |
| `services/hospital-rag/tests/test_llm.py`, `test_api.py` | Modify | Timing and fault tests |
| `services/weir/tests/test_compose.py`, `test_dashboard.py` | Modify | Toxiproxy, override, M25 |
| `eval/tests/test_loadtest_*.py` | Create | Workload, k6 parsing, orchestration helpers, report |
| `eval/tests/fixtures/k6_summary.json`, `k6_raw.jsonl` | Create | Small k6 output samples |
| `.github/workflows/tests.yml` | Modify | `k6 inspect` for every script |
| `docs/results/loadtest-<date>.md`, README, `docs/*` | Create / Modify | Results and docs |

---

### Task 1: Dashboard refresh and time-bounded variables (backlog M25)

**Files:**
- Modify: `monitoring/grafana/build_dashboard.py` (the variables at the end of `build()`, and the `"refresh"` key)
- Regenerate: `monitoring/grafana/dashboards/weir.json`
- Test: `services/weir/tests/test_dashboard.py`

**Interfaces:**
- Produces: dashboard `refresh` is `"5m"`; both variable queries use `$__timeFilter(ts)` and `"refresh": 2` (on time-range change).

- [ ] **Step 1: Write the failing test.** Append to `services/weir/tests/test_dashboard.py`:

```python
def test_dashboard_is_light_on_the_database_under_load():  # backlog M25 (Phase 5 prerequisite)
    d = _dashboard()
    assert d["refresh"] == "5m"
    for v in d["templating"]["list"]:
        assert "$__timeFilter(ts)" in v["query"], v["name"]   # no full-table DISTINCT scans
        assert v["refresh"] == 2                                # re-query on time-range change only
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd services/weir && uv run pytest -q tests/test_dashboard.py -k light`

Expected: FAIL (`'30s' == '5m'`).

- [ ] **Step 3: Implement.** In `build_dashboard.py`:

```python
        {"name": "config", "label": "Configuration", "type": "query", "datasource": PG, "refresh": 2,
         "query": "select distinct config_label from weir.request_log where $__timeFilter(ts) "
                  "and config_label is not null order by 1",
```

```python
        {"name": "namespace", "label": "Namespace", "type": "query", "datasource": PG, "refresh": 2,
         "query": "select distinct namespace from weir.request_log where $__timeFilter(ts) order by 1",
```

Change `"refresh": "30s"` to `"refresh": "5m"`. Then regenerate with `python monitoring/grafana/build_dashboard.py`.

- [ ] **Step 4: Run the tests**

```bash
docker compose up -d postgres
cd services/weir && uv run pytest -q tests/test_dashboard.py
```

Expected: all pass. The variable queries still run as `weir_reader`, because the test's `expand()` already handles `$__timeFilter`.

- [ ] **Step 5: Commit and push**

```bash
git add monitoring/grafana/build_dashboard.py monitoring/grafana/dashboards/weir.json services/weir/tests/test_dashboard.py
git commit -m "fix(monitoring): dashboard refresh 5 min and time-bounded variables (M25, before load tests)"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 2: Realistic stub timing (hospital-rag)

**Files:**
- Modify: `services/hospital-rag/src/hospital_rag/llm.py`, `settings.py`, `main.py` (lifespan)
- Modify: `docker-compose.yml` (hospital-rag environment)
- Test: `services/hospital-rag/tests/test_llm.py`

**Interfaces:**
- Produces:
  - `LatencyProfile(median_ms: float, p95_ms: float)` (frozen dataclass)
  - `FixedTiming(ms: float)` with `.delay_ms(model) -> float`
  - `LognormalTiming(profiles: dict[str, LatencyProfile], default_model: str, seed: int)` with `.delay_ms(model) -> float`
  - `StubLLM(latency_ms: int, count_tokens, timing=None)`. With `timing=None` it behaves exactly as today. `LLMResult.latency_ms` is the real delay used.

- [ ] **Step 1: Write the failing tests.** Append to `services/hospital-rag/tests/test_llm.py`:

```python
import statistics  # noqa: E402

from hospital_rag.llm import FixedTiming, LatencyProfile, LognormalTiming  # noqa: E402

PROFILES = {"small": LatencyProfile(553, 830), "large": LatencyProfile(748, 1429)}


def _pct(values, p):
    ordered = sorted(values)
    return ordered[max(1, round(p / 100 * len(ordered))) - 1]


def test_lognormal_timing_matches_each_models_median_and_p95():
    timing = LognormalTiming(PROFILES, default_model="large", seed=7)
    for model, profile in PROFILES.items():
        draws = [timing.delay_ms(model) for _ in range(4000)]
        assert abs(statistics.median(draws) / profile.median_ms - 1) < 0.05, model
        assert abs(_pct(draws, 95) / profile.p95_ms - 1) < 0.08, model


def test_lognormal_timing_is_seeded_and_unknown_models_use_the_default():
    a = [LognormalTiming(PROFILES, "large", seed=7).delay_ms("x") for _ in range(1)]
    b = [LognormalTiming(PROFILES, "large", seed=7).delay_ms("large") for _ in range(1)]
    assert a == b                                               # unknown model -> large profile, same seed


def test_fixed_timing_and_stub_reports_the_delay_it_used():
    assert FixedTiming(800).delay_ms("anything") == 800

    class Tiny:
        def delay_ms(self, model):
            return 3.0

    messages = [{"role": "user", "content": "[c1] Visiting\nOpen 4 pm to 8 pm\n\nQuestion: When?"}]
    result = asyncio.run(StubLLM(latency_ms=800, count_tokens=word_count, timing=Tiny()).complete(messages, "m"))
    assert result.latency_ms == 3
```

(`asyncio`, `StubLLM` and `word_count` are already imported in this file. If `asyncio` isn't, add `import asyncio`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/hospital-rag && uv run pytest -q tests/test_llm.py`

Expected: FAIL with `ImportError: cannot import name 'FixedTiming'`.

- [ ] **Step 3: Implement.** In `llm.py`, add `import math`, `import random` and `from typing import Protocol` (if missing). Add the following above `class StubLLM`:

```python
@dataclass(frozen=True)
class LatencyProfile:
    median_ms: float
    p95_ms: float


class FixedTiming:
    def __init__(self, ms: float):
        self._ms = ms

    def delay_ms(self, model: str) -> float:
        return self._ms


class LognormalTiming:
    """Per-model delays from a lognormal fitted to a measured median and p95 (Phase 5 addendum §3.1)."""

    Z95 = 1.6448536269514722

    def __init__(self, profiles: dict[str, LatencyProfile], default_model: str, seed: int):
        self._profiles = profiles
        self._default = profiles[default_model]
        self._rng = random.Random(seed)

    def delay_ms(self, model: str) -> float:
        p = self._profiles.get(model, self._default)
        sigma = math.log(p.p95_ms / p.median_ms) / self.Z95
        return self._rng.lognormvariate(math.log(p.median_ms), sigma)
```

Change `StubLLM.__init__` and the top of `complete`:

```python
    def __init__(self, latency_ms: int, count_tokens: Callable[[str], int], timing=None):
        self._latency_ms = latency_ms
        self._count = count_tokens
        self._timing = timing or FixedTiming(latency_ms)

    async def complete(self, messages: list[dict], model: str) -> LLMResult:
        delay = self._timing.delay_ms(model)
        await asyncio.sleep(delay / 1000)
```

The final `return` passes `int(delay)` instead of `self._latency_ms`:

```python
        return LLMResult(text, tokens_in, self._count(text), "stop", model, int(delay))
```

In `settings.py`, add:

```python
    stub_timing: Literal["fixed", "realistic"] = "fixed"
    stub_seed: int = 7
    stub_small_model: str = "openai/gpt-oss-20b"
    stub_small_median_ms: float = 553     # fitted 2026-10-06 from 740 clean request-log rows (D49)
    stub_small_p95_ms: float = 830
    stub_large_model: str = "openai/gpt-oss-120b"
    stub_large_median_ms: float = 748
    stub_large_p95_ms: float = 1429
```

In `main.py`'s lifespan, replace the `llm: LLM = (...)` expression:

```python
        if s.llm_mode == "stub":
            timing = (LognormalTiming({s.stub_small_model: LatencyProfile(s.stub_small_median_ms, s.stub_small_p95_ms),
                                       s.stub_large_model: LatencyProfile(s.stub_large_median_ms, s.stub_large_p95_ms)},
                                      s.stub_large_model, s.stub_seed)
                      if s.stub_timing == "realistic" else None)
            llm: LLM = StubLLM(s.stub_latency_ms, embedder.count_tokens, timing)
        else:
            llm = GroqLLM(s.groq_api_key, s.groq_timeout_s, s.max_completion_tokens, s.reasoning_effort)
```

Extend the import to `from .llm import LLM, GroqLLM, LatencyProfile, LLMError, LLMTimeout, LognormalTiming, RateLimited, StubLLM`.

In `docker-compose.yml`, add to the `hospital-rag` `environment`:

```yaml
      STUB_TIMING: ${STUB_TIMING:-realistic}   # used only when LLM_MODE=stub (Phase 5, D49)
```

- [ ] **Step 4: Run the tests**

Run: `cd services/hospital-rag && uv run pytest -q`

Expected: all pass. The DB tests need Postgres running.

- [ ] **Step 5: Commit and push**

```bash
git add services/hospital-rag/src/hospital_rag/llm.py services/hospital-rag/src/hospital_rag/settings.py \
  services/hospital-rag/src/hospital_rag/main.py services/hospital-rag/tests/test_llm.py docker-compose.yml
git commit -m "feat(stub): realistic per-model latency (lognormal fitted to measured model times, seeded)"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 3: Stub fault endpoint (hospital-rag)

**Files:**
- Modify: `services/hospital-rag/src/hospital_rag/llm.py` (`StubLLM`), `main.py` (routes)
- Test: `services/hospital-rag/tests/test_api.py`

**Interfaces:**
- Produces:
  - `StubLLM.set_fault(model: str, mode: str, delay_ms: int) -> None`. Modes are `none`, `rate_limit` and `timeout`. `model="*"` with `mode="none"` clears every fault.
  - `StubLLM.faults -> dict[str, dict]`.
  - `POST /stub/faults` with body `{"model", "mode", "delay_ms"}`, returning `{"faults": {...}}`.
  - `GET /stub/faults`.
  - Both return 404 unless the LLM is a `StubLLM`.
  - `rate_limit` raises `RateLimited(1.0)`, so the endpoint answers 503 `rate_limited`.
  - `timeout` sleeps `delay_ms`, then raises `LLMTimeout`, so the endpoint answers 504.

- [ ] **Step 1: Write the failing tests.** Append to `services/hospital-rag/tests/test_api.py`:

```python
from hospital_rag.llm import StubLLM  # noqa: E402

from .conftest import word_count  # noqa: E402


def stub_client():
    return client_for(Deps(None, FakeEmbedder(), StubLLM(latency_ms=1, count_tokens=word_count), 4, "stub"))


def gen(model):
    return {**GEN_BODY, "model": model}


async def test_rate_limit_fault_hits_only_the_named_model():
    async with stub_client() as c:
        r = await c.post("/stub/faults", json={"model": "large-m", "mode": "rate_limit"})
        assert r.status_code == 200 and r.json()["faults"]["large-m"]["mode"] == "rate_limit"
        bad = await c.post("/generate", json=gen("large-m"))
        ok = await c.post("/generate", json=gen("small-m"))
    assert bad.status_code == 503 and bad.json()["error"] == "rate_limited"
    assert ok.status_code == 200


async def test_timeout_fault_answers_504_after_the_delay():
    import time

    async with stub_client() as c:
        await c.post("/stub/faults", json={"model": "small-m", "mode": "timeout", "delay_ms": 50})
        started = time.perf_counter()
        r = await c.post("/generate", json=gen("small-m"))
    assert r.status_code == 504 and time.perf_counter() - started >= 0.05


async def test_none_clears_a_fault_and_star_clears_all():
    async with stub_client() as c:
        await c.post("/stub/faults", json={"model": "a", "mode": "rate_limit"})
        await c.post("/stub/faults", json={"model": "b", "mode": "rate_limit"})
        await c.post("/stub/faults", json={"model": "a", "mode": "none"})
        assert set((await c.get("/stub/faults")).json()["faults"]) == {"b"}
        await c.post("/stub/faults", json={"model": "*", "mode": "none"})
        assert (await c.get("/stub/faults")).json()["faults"] == {}
        assert (await c.post("/generate", json=gen("b"))).status_code == 200


async def test_fault_endpoint_does_not_exist_outside_stub_mode():
    async with client_for(Deps(None, FakeEmbedder(), FakeLLM(), 4)) as c:
        assert (await c.post("/stub/faults", json={"model": "m", "mode": "rate_limit"})).status_code == 404
        assert (await c.get("/stub/faults")).status_code == 404


async def test_fault_body_is_validated():
    async with stub_client() as c:
        assert (await c.post("/stub/faults", json={"model": "m", "mode": "explode"})).status_code == 422
        assert (await c.post("/stub/faults", json={"model": "m", "mode": "timeout",
                                                    "delay_ms": 999999})).status_code == 422
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/hospital-rag && uv run pytest -q tests/test_api.py -k fault`

Expected: FAIL (404 for `/stub/faults`).

- [ ] **Step 3: Implement.** In `StubLLM.__init__`, add `self._faults: dict[str, dict] = {}`, plus these methods:

```python
    @property
    def faults(self) -> dict[str, dict]:
        return dict(self._faults)

    def set_fault(self, model: str, mode: str, delay_ms: int = 5000) -> None:
        """Load-test fault switch (Phase 5 addendum §3.2). model='*' with mode='none' clears every fault."""
        if mode == "none":
            if model == "*":
                self._faults.clear()
            else:
                self._faults.pop(model, None)
        else:
            self._faults[model] = {"mode": mode, "delay_ms": delay_ms}
```

At the very start of `complete()`, before the delay:

```python
        fault = self._faults.get(model)
        if fault and fault["mode"] == "rate_limit":
            raise RateLimited(1.0)
        if fault and fault["mode"] == "timeout":
            await asyncio.sleep(fault["delay_ms"] / 1000)
            raise LLMTimeout(f"stub timeout fault on {model}")
```

In `main.py`, add `from typing import Literal` and `from pydantic import BaseModel, Field`, then this model above `create_app`:

```python
class FaultIn(BaseModel):
    model: str = Field(min_length=1)
    mode: Literal["none", "rate_limit", "timeout"]
    delay_ms: int = Field(5000, ge=0, le=60000)
```

Add the routes after `/generate`:

```python
    def _stub(request: Request) -> StubLLM:
        llm = request.app.state.deps.llm
        if not isinstance(llm, StubLLM):
            raise HTTPException(status_code=404, detail="faults exist only in stub mode")
        return llm

    @app.post("/stub/faults")
    async def set_fault(body: FaultIn, request: Request):
        llm = _stub(request)
        llm.set_fault(body.model, body.mode, body.delay_ms)
        return {"faults": llm.faults}

    @app.get("/stub/faults")
    async def get_faults(request: Request):
        return {"faults": _stub(request).faults}
```

Import `HTTPException` from `fastapi`.

- [ ] **Step 4: Run the tests**

Run: `cd services/hospital-rag && uv run pytest -q`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```bash
git add services/hospital-rag/src/hospital_rag/llm.py services/hospital-rag/src/hospital_rag/main.py \
  services/hospital-rag/tests/test_api.py
git commit -m "feat(stub): fault endpoint (rate_limit / timeout per model), stub mode only"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 4: Toxiproxy and the failure-run override

**Files:**
- Modify: `docker-compose.yml`
- Create: `docker-compose.loadtest.yml`, `loadtest/toxiproxy.json`
- Test: `services/weir/tests/test_compose.py`

**Interfaces:**
- Produces:
  - **The Toxiproxy service:** `toxiproxy` (profile `loadtest`), with its API on `127.0.0.1:8474`.
  - **The proxy:** `weir-db`, listening on `0.0.0.0:5433` (Docker network only) and forwarding to `postgres:5432`.
  - **The override file** `docker-compose.loadtest.yml` sets Weir's `DATABASE_URL` to `postgresql://weir:weir@toxiproxy:5433/weir`.

- [ ] **Step 1: Write the failing tests.** Append to `services/weir/tests/test_compose.py`:

```python
import json  # noqa: E402


def test_toxiproxy_is_opt_in_pinned_and_only_its_api_is_published_locally():
    toxi = SERVICES["toxiproxy"]
    assert toxi["profiles"] == ["loadtest"] and toxi["image"] == "ghcr.io/shopify/toxiproxy:2.9.0"
    assert toxi["ports"] == ["127.0.0.1:8474:8474"]


def test_toxiproxy_proxies_weir_db_to_postgres():
    [proxy] = json.loads((REPO / "loadtest" / "toxiproxy.json").read_text(encoding="utf-8"))
    assert proxy == {"name": "weir-db", "listen": "0.0.0.0:5433", "upstream": "postgres:5432", "enabled": True}


def test_failure_override_routes_only_weir_through_toxiproxy():
    over = yaml.safe_load((REPO / "docker-compose.loadtest.yml").read_text(encoding="utf-8"))["services"]
    assert set(over) == {"weir"}
    assert over["weir"]["environment"]["DATABASE_URL"] == "postgresql://weir:weir@toxiproxy:5433/weir"


def test_hospital_rag_stub_timing_defaults_to_realistic():
    assert SERVICES["hospital-rag"]["environment"]["STUB_TIMING"] == "${STUB_TIMING:-realistic}"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_compose.py`

Expected: FAIL (`KeyError: 'toxiproxy'`, and the files are missing).

- [ ] **Step 3: Implement.** Add to `docker-compose.yml` after `grafana`:

```yaml
  # Phase 5 load tests: opt-in with `--profile loadtest`; failure runs add -f docker-compose.loadtest.yml.
  toxiproxy:
    image: ghcr.io/shopify/toxiproxy:2.9.0
    profiles: ["loadtest"]
    command: ["-host=0.0.0.0", "-config=/config/toxiproxy.json"]
    volumes: ["./loadtest/toxiproxy.json:/config/toxiproxy.json:ro"]
    ports: ["127.0.0.1:8474:8474"]  # control API, localhost only; the 5433 proxy stays on the Docker network
    depends_on: [postgres]
```

Create `loadtest/toxiproxy.json`:

```json
[
  {"name": "weir-db", "listen": "0.0.0.0:5433", "upstream": "postgres:5432", "enabled": true}
]
```

Create `docker-compose.loadtest.yml`:

```yaml
# Failure-injection runs only (Phase 5 addendum §3.3): Weir reaches Postgres through Toxiproxy, so k6 can slow
# Weir's cache database while hospital-rag's document search keeps its direct connection.
#   docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest up -d toxiproxy weir
services:
  weir:
    environment:
      DATABASE_URL: postgresql://weir:weir@toxiproxy:5433/weir
    depends_on:
      toxiproxy: { condition: service_started }
```

- [ ] **Step 4: Run the tests and a live check**

```bash
cd services/weir && uv run pytest -q tests/test_compose.py
cd ../.. && docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest config -q && echo ok
docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest up -d toxiproxy
curl -s http://127.0.0.1:8474/proxies | python -c "import json,sys; print(list(json.load(sys.stdin)))"
docker compose --profile loadtest stop
```

Expected:
- the tests pass
- `ok`
- `['weir-db']`

- [ ] **Step 5: Commit and push**

```bash
git add docker-compose.yml docker-compose.loadtest.yml loadtest/toxiproxy.json services/weir/tests/test_compose.py
git commit -m "feat(loadtest): Toxiproxy (opt-in profile) and failure-run override for Weir's database link"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 5: Request files and k6 scripts

**Files:**
- Create: `eval/src/weir_eval/loadtest/__init__.py`, `eval/src/weir_eval/loadtest/workload.py`
- Create: `loadtest/scripts/lib.js`, `steady.js`, `ramp.js`, `spike.js`, `failure.js`
- Create (generated): `loadtest/workloads/requests-3000.json`, `loadtest/workloads/distinct.json`
- Modify: `eval/src/weir_eval/cli.py` (`loadtest make-workloads`)
- Modify: `.github/workflows/tests.yml` (`k6 inspect`)
- Test: `eval/tests/test_loadtest_workload.py`

**Interfaces:**
- Consumes: `weir_eval.workload.make_workload`, `repeat_rate`, `weir_eval.dataset.EvalQuery`.
- Produces:
  - `make_request_file(queries: list[EvalQuery], n: int, seed: int, exponent: float = 1.1) -> list[dict]` (`{query, namespace}` only)
  - `distinct_requests(requests: list[dict]) -> list[dict]` (first occurrence order)
  - **k6 metrics:**
    - Trends `latency_all`, `latency_hit`, `latency_small`, `latency_large` (ms)
    - Rate `errors`
    - built-in `dropped_iterations`
  - **k6 scenario name `traffic`** in every script; the failure script adds `chaos`.
  - **The summary** is written to `__ENV.SUMMARY_OUT`.
  - **The environment** each script reads:
    - `WORKLOAD` (all scripts)
    - steady: `RATE`, `DURATION`
    - ramp: `RAMP_STEPS`, `STEP_S`
    - spike: `BASE_S`, `BURST_S`, `AFTER_S`, `BASE_RATE`, `BURST_RATE`
    - failure: `PHASE_S`, `RATE`

- [ ] **Step 1: Write the failing tests.** Create `eval/tests/test_loadtest_workload.py`:

```python
import json

from weir_eval.loadtest.workload import distinct_requests, make_request_file
from weir_eval.workload import repeat_rate

from .conftest import q

QUERIES = [q(f"q-{i:03d}", f"c{i}") for i in range(30)]


def test_request_file_is_sized_ordered_and_deterministic():
    a = make_request_file(QUERIES, 500, seed=11)
    assert len(a) == 500 and a == make_request_file(QUERIES, 500, seed=11)
    assert a != make_request_file(QUERIES, 500, seed=12)
    assert all(set(r) == {"query", "namespace"} for r in a)
    assert repeat_rate([r["query"] for r in a]) > 0.8                     # Zipf-skewed: mostly repeats


def test_request_file_has_no_keys():  # Review Focus 5
    text = json.dumps(make_request_file(QUERIES, 200, seed=11))
    assert "X-API-Key" not in text and "key" not in text.lower()


def test_distinct_keeps_first_occurrence_order():
    reqs = [{"query": "a", "namespace": "n"}, {"query": "b", "namespace": "n"}, {"query": "a", "namespace": "n"}]
    assert distinct_requests(reqs) == reqs[:2]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd eval && uv run pytest -q tests/test_loadtest_workload.py`

Expected: FAIL (`ModuleNotFoundError: weir_eval.loadtest`).

- [ ] **Step 3: Implement the workload module.** Create `eval/src/weir_eval/loadtest/__init__.py` containing `"""Phase 5 load testing (addendum: docs/superpowers/specs/2026-10-06-phase-5-load-testing-design.md)."""`. Then create `eval/src/weir_eval/loadtest/workload.py`:

```python
"""Request lists k6 replays (Phase 5 addendum §4). Questions and namespaces only: keys are never written."""
from ..dataset import EvalQuery
from ..workload import make_workload


def make_request_file(queries: list[EvalQuery], n: int, seed: int, exponent: float = 1.1) -> list[dict]:
    by_id = {q.id: q for q in queries}
    return [{"query": by_id[i].query, "namespace": by_id[i].namespace}
            for i in make_workload(list(by_id), n, seed, exponent)]


def distinct_requests(requests: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in requests:
        key = (r["query"], r["namespace"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out
```

In `eval/src/weir_eval/cli.py`, add the command and register a `loadtest` sub-parser group. Tasks 7 and 8 add more subcommands to this group.

```python
LOADTEST_DIR = REPO / "loadtest"


def cmd_loadtest_make_workloads(args: argparse.Namespace) -> int:
    from .loadtest.workload import distinct_requests, make_request_file
    from .workload import repeat_rate

    reqs = make_request_file(load_queries(QUERIES), args.n, args.seed)
    out = LOADTEST_DIR / "workloads"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"requests-{args.n}.json").write_text(json.dumps(reqs, ensure_ascii=False), encoding="utf-8")
    distinct = distinct_requests(reqs)
    (out / "distinct.json").write_text(json.dumps(distinct, ensure_ascii=False), encoding="utf-8")
    rate = repeat_rate([f"{r['namespace']}|{r['query']}" for r in reqs])
    print(f"{len(reqs)} requests, {len(distinct)} distinct, repeat rate {rate:.1%}")
    return 0
```

```python
    lt = sub.add_parser("loadtest", help="Phase 5 k6 load tests (stub model only)")
    lt_sub = lt.add_subparsers(dest="lt_command", required=True)
    mw = lt_sub.add_parser("make-workloads", help="write loadtest/workloads/*.json (no keys)")
    mw.add_argument("--n", type=int, default=3000)
    mw.add_argument("--seed", type=int, default=11)
    mw.set_defaults(func=cmd_loadtest_make_workloads)
```

- [ ] **Step 4: Write the k6 scripts**

`loadtest/scripts/lib.js`:

```javascript
// Shared k6 helpers (Phase 5 addendum §2). Keys come from the environment, never from files.
import http from 'k6/http';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';
import { Trend, Rate } from 'k6/metrics';

export const WEIR = __ENV.WEIR_URL || 'http://weir:8000';
export const SUMMARY_STATS = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'];
const KEYS = {
  'weir-general/en/public': __ENV.WEIR_KEY_PUBLIC,
  'weir-general/en/staff': __ENV.WEIR_KEY_STAFF,
};
const requests = new SharedArray('requests', () => JSON.parse(open(__ENV.WORKLOAD)));
const all = new Trend('latency_all', true);
const byPath = {
  hit: new Trend('latency_hit', true),
  small: new Trend('latency_small', true),
  large: new Trend('latency_large', true),
};
export const errors = new Rate('errors');

export function ask() {
  const r = requests[exec.scenario.iterationInTest % requests.length];
  const res = http.post(`${WEIR}/v1/query`, JSON.stringify({ query: r.query, namespace: r.namespace }), {
    headers: { 'content-type': 'application/json', 'X-API-Key': KEYS[r.namespace] },
    timeout: '60s',
  });
  const ok = res.status === 200;
  errors.add(!ok);
  all.add(res.timings.duration);
  if (ok) {
    const meta = res.json('meta');
    const path = meta.cache_status === 'hit' ? 'hit' : meta.route;
    if (byPath[path]) byPath[path].add(res.timings.duration);
  }
}

export function summary(data) {
  return { [__ENV.SUMMARY_OUT || '/dev/stdout']: JSON.stringify(data) };
}
```

`loadtest/scripts/steady.js` (cold, warm, soak):

```javascript
import { ask, summary, SUMMARY_STATS } from './lib.js';

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  scenarios: {
    traffic: {
      executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 10), timeUnit: '1s',
      duration: __ENV.DURATION || '5m', preAllocatedVUs: 50, maxVUs: 500, exec: 'traffic',
    },
  },
};
export function traffic() { ask(); }
export function handleSummary(data) { return summary(data); }
```

`loadtest/scripts/ramp.js`:

```javascript
import { ask, summary, SUMMARY_STATS } from './lib.js';

const rates = (__ENV.RAMP_STEPS || '5,10,20,40,60,80,100').split(',').map(Number);
const step = Number(__ENV.STEP_S || 90);
const stages = rates.flatMap((r) => [{ target: r, duration: '1s' }, { target: r, duration: `${step - 1}s` }]);

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  thresholds: { errors: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '20s' }] },
  scenarios: {
    traffic: {
      executor: 'ramping-arrival-rate', startRate: rates[0], timeUnit: '1s',
      preAllocatedVUs: 100, maxVUs: 500, stages, exec: 'traffic',
    },
  },
};
export function traffic() { ask(); }
export function handleSummary(data) { return summary(data); }
```

`loadtest/scripts/spike.js`:

```javascript
import { ask, summary, SUMMARY_STATS } from './lib.js';

const base = Number(__ENV.BASE_RATE || 5);
const burst = Number(__ENV.BURST_RATE || 60);
const s = (name, dflt) => Number(__ENV[name] || dflt);

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  scenarios: {
    traffic: {
      executor: 'ramping-arrival-rate', startRate: base, timeUnit: '1s', preAllocatedVUs: 100, maxVUs: 500,
      exec: 'traffic',
      stages: [
        { target: base, duration: `${s('BASE_S', 120)}s` },
        { target: burst, duration: '1s' }, { target: burst, duration: `${s('BURST_S', 30) - 1}s` },
        { target: base, duration: '1s' }, { target: base, duration: `${s('AFTER_S', 180) - 1}s` },
      ],
    },
  },
};
export function traffic() { ask(); }
export function handleSummary(data) { return summary(data); }
```

`loadtest/scripts/failure.js`:

```javascript
// Failure injection (Phase 5 addendum §3.4): traffic plus a chaos track that flips faults at fixed offsets.
import http from 'k6/http';
import { sleep } from 'k6';
import { ask, summary, SUMMARY_STATS } from './lib.js';

const PHASE = Number(__ENV.PHASE_S || 60);
const RAG = __ENV.RAG_URL || 'http://hospital-rag:8001';
const TOXI = __ENV.TOXI_URL || 'http://toxiproxy:8474';
const SMALL = 'openai/gpt-oss-20b';
const LARGE = 'openai/gpt-oss-120b';
const JSON_HDR = { headers: { 'content-type': 'application/json' }, tags: { name: 'chaos' } };

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  scenarios: {
    traffic: {
      executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 10), timeUnit: '1s',
      duration: `${7 * PHASE}s`, preAllocatedVUs: 50, maxVUs: 500, exec: 'traffic',
    },
    chaos: { executor: 'per-vu-iterations', vus: 1, iterations: 1, maxDuration: `${8 * PHASE}s`, exec: 'chaos' },
  },
};

function fault(model, mode, delayMs) {
  http.post(`${RAG}/stub/faults`, JSON.stringify({ model, mode, delay_ms: delayMs || 5000 }), JSON_HDR);
}
function dbDelay(on) {
  if (on) {
    http.post(`${TOXI}/proxies/weir-db/toxics`, JSON.stringify(
      { name: 'db_latency', type: 'latency', stream: 'downstream', attributes: { latency: 2000 } }), JSON_HDR);
  } else {
    http.del(`${TOXI}/proxies/weir-db/toxics/db_latency`, null, JSON_HDR);
  }
}

export function traffic() { ask(); }
export function chaos() {
  sleep(2 * PHASE); fault(LARGE, 'rate_limit');
  sleep(PHASE); fault(LARGE, 'none');
  sleep(PHASE); fault(SMALL, 'timeout', 5000);
  sleep(PHASE); fault(SMALL, 'none'); dbDelay(true);
  sleep(PHASE); dbDelay(false);
}
export function teardown() { fault('*', 'none'); dbDelay(false); }   // always restore, even after an abort
export function handleSummary(data) { return summary(data); }
```

- [ ] **Step 5: Generate the workloads and inspect the scripts**

```bash
cd eval && uv run python -m weir_eval loadtest make-workloads && uv run pytest -q tests/test_loadtest_workload.py
cd .. && for s in steady ramp spike failure; do MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/loadtest:/loadtest" \
  -e WORKLOAD=/loadtest/workloads/requests-3000.json grafana/k6:0.54.0 inspect /loadtest/scripts/$s.js > /dev/null \
  && echo "$s ok"; done
```

Expected:
- `3000 requests, <N> distinct, repeat rate <x>%`
- the tests pass
- `steady ok`, `ramp ok`, `spike ok`, `failure ok`

Add a CI step to the `monitoring` job:

```yaml
      - name: k6 inspect (load-test scripts)
        run: |
          for s in steady ramp spike failure; do
            docker run --rm -v "$PWD/loadtest:/loadtest" -e WORKLOAD=/loadtest/workloads/requests-3000.json \
              grafana/k6:0.54.0 inspect /loadtest/scripts/$s.js > /dev/null
          done
```

- [ ] **Step 6: Commit and push**

```bash
git add eval/src/weir_eval/loadtest/ eval/src/weir_eval/cli.py eval/tests/test_loadtest_workload.py \
  loadtest/scripts/ loadtest/workloads/ .github/workflows/tests.yml
git commit -m "feat(loadtest): request files (no keys), k6 scripts with per-path trends and a chaos track, k6 inspect in CI"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 6: k6 output parsing and run calculations (pure)

**Files:**
- Create: `eval/src/weir_eval/loadtest/k6.py`
- Create: `eval/tests/fixtures/k6_summary.json`, `eval/tests/fixtures/k6_raw.jsonl`
- Test: `eval/tests/test_loadtest_k6.py`

**Interfaces:**
- Produces:
  - `parse_summary(data: dict) -> dict`, with keys `requests`, `achieved_rate`, `error_rate`, `dropped`, and `latency: {all|hit|small|large: {p50, p95, p99, count} | None}`
  - `compact_points(lines: Iterable[str]) -> list[tuple[int, str, float, int]]` as `(t_ms, kind, value, status)`. `kind` is `"req"` (traffic `http_req_duration`) or `"drop"` (`dropped_iterations`).
  - `percentile(values, p) -> float | None`
  - `window_stats(points, start_ms, end_ms) -> dict`, with `{n, p95, errors, error_rate, dropped, achieved_rate}`
  - `ramp_steps(points, t0_ms, rates, step_s) -> list[dict]`
  - `ramp_max_rate(steps, budget_ms=2000, max_error=0.01, min_achieved=0.95) -> int | None`
  - `spike_recovery_s(points, burst_end_ms, budget_ms=2000, window_s=10) -> float | None`
  - `failure_phases(points, t0_ms, phase_s) -> list[dict]`. The 7 labels are `normal`, `normal`, `large_rate_limited`, `normal_2`, `small_timeout`, `db_delay` and `recovery`.

- [ ] **Step 1: Create the fixtures**

`eval/tests/fixtures/k6_summary.json` is a trimmed real-shape k6 `handleSummary` payload:

```json
{"metrics": {
  "latency_all": {"type": "trend", "values": {"med": 40.0, "p(95)": 900.0, "p(99)": 1500.0, "count": 300}},
  "latency_hit": {"type": "trend", "values": {"med": 15.0, "p(95)": 30.0, "p(99)": 45.0, "count": 270}},
  "latency_large": {"type": "trend", "values": {"med": 780.0, "p(95)": 1400.0, "p(99)": 1600.0, "count": 30}},
  "errors": {"type": "rate", "values": {"rate": 0.0, "passes": 0, "fails": 300}},
  "iterations": {"type": "counter", "values": {"count": 300, "rate": 9.98}},
  "dropped_iterations": {"type": "counter", "values": {"count": 2, "rate": 0.07}}
}}
```

`eval/tests/fixtures/k6_raw.jsonl` holds k6 JSON-output lines. It has two traffic requests, one chaos request (to be ignored), one dropped iteration and one non-point line:

```text
{"type":"Metric","data":{"name":"http_req_duration","type":"trend"},"metric":"http_req_duration"}
{"type":"Point","metric":"http_req_duration","data":{"time":"2026-10-06T10:00:00.123456789Z","value":15.5,"tags":{"scenario":"traffic","status":"200"}}}
{"type":"Point","metric":"http_req_duration","data":{"time":"2026-10-06T10:00:01.5Z","value":820.0,"tags":{"scenario":"traffic","status":"503"}}}
{"type":"Point","metric":"http_req_duration","data":{"time":"2026-10-06T10:00:02Z","value":3.0,"tags":{"scenario":"chaos","status":"200","name":"chaos"}}}
{"type":"Point","metric":"dropped_iterations","data":{"time":"2026-10-06T10:00:03+00:00","value":1,"tags":{"scenario":"traffic"}}}
```

- [ ] **Step 2: Write the failing tests.** Create `eval/tests/test_loadtest_k6.py`:

```python
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
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd eval && uv run pytest -q tests/test_loadtest_k6.py`

Expected: FAIL (`ModuleNotFoundError: weir_eval.loadtest.k6`).

- [ ] **Step 4: Implement.** Create `eval/src/weir_eval/loadtest/k6.py`:

```python
"""k6 output parsing and per-run calculations (Phase 5 addendum §5). Pure functions only."""
import json
import math
import re
from collections.abc import Iterable
from datetime import datetime

PATHS = ("all", "hit", "small", "large")
FAILURE_LABELS = ["normal", "normal", "large_rate_limited", "normal_2", "small_timeout", "db_delay", "recovery"]
_FRACTION = re.compile(r"(\.\d{6})\d+")


def parse_summary(data: dict) -> dict:
    m = data["metrics"]

    def trend(name: str) -> dict | None:
        v = m.get(name, {}).get("values")
        if not v or not v.get("count"):
            return None
        return {"p50": v["med"], "p95": v["p(95)"], "p99": v["p(99)"], "count": int(v["count"])}

    return {
        "requests": int(m["iterations"]["values"]["count"]),
        "achieved_rate": m["iterations"]["values"]["rate"],
        "error_rate": m.get("errors", {}).get("values", {}).get("rate", 0.0),
        "dropped": int(m.get("dropped_iterations", {}).get("values", {}).get("count", 0)),
        "latency": {p: trend(f"latency_{p}") for p in PATHS},
    }


def _ts_ms(text: str) -> int:
    text = _FRACTION.sub(r"\1", text.replace("Z", "+00:00"))
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def compact_points(lines: Iterable[str]) -> list[tuple[int, str, float, int]]:
    out = []
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("type") != "Point":
            continue
        data, tags = rec["data"], rec["data"].get("tags", {})
        if tags.get("scenario") != "traffic":
            continue
        if rec["metric"] == "http_req_duration":
            out.append((_ts_ms(data["time"]), "req", float(data["value"]), int(tags.get("status") or 0)))
        elif rec["metric"] == "dropped_iterations":
            out.append((_ts_ms(data["time"]), "drop", float(data["value"]), 0))
    return sorted(out)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def window_stats(points, start_ms: int, end_ms: int) -> dict:
    reqs = [(v, st) for t, k, v, st in points if k == "req" and start_ms <= t < end_ms]
    dropped = sum(v for t, k, v, _ in points if k == "drop" and start_ms <= t < end_ms)
    errors = sum(1 for _, st in reqs if st != 200)
    seconds = max((end_ms - start_ms) / 1000, 1e-9)
    return {"n": len(reqs), "p95": percentile([v for v, _ in reqs], 95), "errors": errors,
            "error_rate": errors / len(reqs) if reqs else 0.0, "dropped": int(dropped),
            "achieved_rate": len(reqs) / seconds}


def ramp_steps(points, t0_ms: int, rates: list[int], step_s: int) -> list[dict]:
    return [{"rate": r, **window_stats(points, t0_ms + i * step_s * 1000, t0_ms + (i + 1) * step_s * 1000)}
            for i, r in enumerate(rates)]


def _step_ok(step: dict, budget_ms: float, max_error: float, min_achieved: float) -> bool:
    return (step["p95"] is not None and step["p95"] <= budget_ms and step["error_rate"] <= max_error
            and step["achieved_rate"] >= min_achieved * step["rate"])


def ramp_max_rate(steps: list[dict], budget_ms: float = 2000, max_error: float = 0.01,
                  min_achieved: float = 0.95) -> int | None:
    best = None
    for step in steps:  # stop at the first failing step: a lucky later step doesn't count
        if not _step_ok(step, budget_ms, max_error, min_achieved):
            break
        best = step["rate"]
    return best


def spike_recovery_s(points, burst_end_ms: int, budget_ms: float = 2000, window_s: int = 10) -> float | None:
    last = max((t for t, k, _, _ in points if k == "req"), default=burst_end_ms)
    start = burst_end_ms
    while start + window_s * 1000 <= last + 1:
        w = window_stats(points, start, start + window_s * 1000)
        if w["n"] and w["p95"] <= budget_ms:
            return (start + window_s * 1000 - burst_end_ms) / 1000
        start += 1000
    return None


def failure_phases(points, t0_ms: int, phase_s: int) -> list[dict]:
    return [{"label": label, **window_stats(points, t0_ms + i * phase_s * 1000, t0_ms + (i + 1) * phase_s * 1000)}
            for i, label in enumerate(FAILURE_LABELS)]
```

- [ ] **Step 5: Run the tests**

Run: `cd eval && uv run pytest -q tests/test_loadtest_k6.py`

Expected: PASS (10 tests). If a test's expected number disagrees with an obviously correct calculation, fix the test and record a ruling; never fudge the function.

- [ ] **Step 6: Commit and push**

```bash
git add eval/src/weir_eval/loadtest/k6.py eval/tests/test_loadtest_k6.py eval/tests/fixtures/
git commit -m "feat(loadtest): k6 summary parsing, compact points, window/ramp/spike/failure calculations"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 7: Orchestrator and live smoke

**Files:**
- Create: `eval/src/weir_eval/loadtest/orchestrate.py`
- Modify: `eval/src/weir_eval/cli.py` (`loadtest run`, `loadtest suite`)
- Test: `eval/tests/test_loadtest_orchestrate.py`

**Interfaces:**
- Consumes: `parse_summary`, `compact_points`, `ramp_steps`, `failure_phases`, `spike_recovery_s` (Task 6).
- Produces:
  - `RunSpec(scenario, config, repeat, smoke=False)` with `.name`
  - `suite_runs() -> list[RunSpec]` (the D48 matrix)
  - `k6_env(spec) -> dict`
  - `k6_command(spec, host_loadtest_dir, run_rel) -> list[str]`
  - `require_stub(health: dict) -> None`, which raises `RuntimeError`
  - `reset_calls() -> list[tuple[str, str, dict | None]]`, as `(method, url, json)`
  - `window_query(start, end, config) -> tuple[str, tuple]`
  - `execute(spec, results_root, env) -> dict`, which writes `<results_root>/<spec.name>/summary.json` and `requests.csv.gz`

- [ ] **Step 1: Write the failing tests.** Create `eval/tests/test_loadtest_orchestrate.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from weir_eval.loadtest.orchestrate import (RunSpec, k6_command, k6_env, require_stub, reset_calls, suite_runs,
                                            window_query)


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd eval && uv run pytest -q tests/test_loadtest_orchestrate.py`

Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement.** Create `eval/src/weir_eval/loadtest/orchestrate.py`:

```python
"""Phase 5 load-test orchestrator (addendum §2, D52). One run = config switch, cache prep, warm-up, k6, samplers,
request-log window, compact results. Refuses to run against real models."""
import asyncio
import gzip
import json
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg

from .k6 import compact_points, failure_phases, parse_summary, ramp_steps, spike_recovery_s

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


def require_stub(health: dict) -> None:
    if health.get("llm_mode") != "stub":
        raise RuntimeError("hospital-rag is not in stub mode (LLM_MODE=stub); refusing to load-test real models")


def reset_calls() -> list[tuple[str, str, dict | None]]:
    return [("POST", f"{RAG}/stub/faults", {"model": "*", "mode": "none"}),
            ("DELETE", f"{TOXI}/proxies/weir-db/toxics/db_latency", None)]


def window_query(start: datetime, end: datetime, config: str) -> tuple[str, tuple]:
    sql = ("select count(*) as n, coalesce(sum(cost_usd), 0)::float as cost, "
           "avg((cache_status = 'hit')::int)::float as hit_rate, avg((route = 'small')::int)::float as small, "
           "sum((route_reason like '%%fallback')::int) as fallbacks, "
           "sum((bypass_reason = 'error')::int) as cache_errors, sum((status <> 'ok')::int) as errors, "
           "avg(coalesce(latency_embed_ms, 0) + coalesce(latency_cache_ms, 0))::float as overhead_mean, "
           "percentile_cont(0.95) within group (order by coalesce(latency_embed_ms, 0) "
           "+ coalesce(latency_cache_ms, 0))::float as overhead_p95, "
           "percentile_cont(0.5) within group (order by latency_total_ms)::float as internal_p50, "
           "percentile_cont(0.95) within group (order by latency_total_ms)::float as internal_p95 "
           "from weir.request_log where ts >= %s and ts < %s and config_label = %s")
    return sql, (start, end, config)


def _compose(args: list[str], env: dict, failure: bool = False) -> None:
    files = ["-f", "docker-compose.yml", "-f", "docker-compose.loadtest.yml"] if failure else []
    subprocess.run(["docker", "compose", *files, "--profile", "loadtest", *args], env=env, check=True,
                   capture_output=True)


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


class Sampler(threading.Thread):
    """docker stats (CPU, memory) and Postgres connections every 5 s."""

    def __init__(self):
        super().__init__(daemon=True)
        self.samples: list[dict] = []
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            row = {"t": time.time()}
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
            self.samples.append(row)
            self._stop.wait(5)

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=10)


def _lost_work() -> int:
    text = httpx.get(f"{WEIR}/metrics", timeout=5).text
    names = ("weir_log_rows_dropped_total", "weir_log_rows_failed_total",
             "weir_cache_jobs_dropped_total", "weir_cache_jobs_failed_total")
    return int(sum(float(line.split()[-1]) for line in text.splitlines() if line.split(" ")[0] in names))


def execute(spec: RunSpec, results_root: Path, env: dict) -> dict:
    repo = Path(__file__).resolve().parents[4]
    run_dir = results_root / spec.name
    run_dir.mkdir(parents=True, exist_ok=True)
    workload = json.loads((repo / "loadtest" / "workloads" / "requests-3000.json").read_text(encoding="utf-8"))
    distinct = json.loads((repo / "loadtest" / "workloads" / "distinct.json").read_text(encoding="utf-8"))
    with httpx.Client() as client:
        require_stub(client.get(f"{RAG}/healthz", timeout=10).json())
        _reset(client)
        failure = spec.scenario == "failure"
        if failure:
            _compose(["up", "-d", "toxiproxy"], env, failure=True)
        _compose(["up", "-d", "--force-recreate", "weir"], {**env, "WEIR_ABLATION": spec.config}, failure=failure)
        _wait_label(spec.config)
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
    rel = run_dir.relative_to(repo / "loadtest").as_posix()
    proc = subprocess.run(k6_command(spec, repo / "loadtest", rel), env=env, capture_output=True, text=True)
    ended = datetime.now(UTC)
    sampler.stop()
    time.sleep(3)                                                   # request-log rows are written asynchronously
    raw_path = run_dir / "k6-raw.json"
    points = compact_points(raw_path.read_text(encoding="utf-8").splitlines()) if raw_path.exists() else []
    with gzip.open(run_dir / "requests.csv.gz", "wt", encoding="utf-8") as f:
        f.write("t_ms,kind,value,status\n" + "".join(f"{t},{k},{v},{s}\n" for t, k, v, s in points))
    raw_path.unlink(missing_ok=True)
    with psycopg.connect(READER_DB) as conn:
        sql, params = window_query(started, ended, spec.config)
        cur = conn.execute(sql, params)
        log = dict(zip([d.name for d in cur.description], cur.fetchone(), strict=True))
    t0 = points[0][0] if points else int(started.timestamp() * 1000)
    k6sum = run_dir / "k6-summary.json"
    summary = {
        "spec": asdict(spec), "started": started.isoformat(), "ended": ended.isoformat(),
        "k6_exit": proc.returncode, "k6_stderr_tail": proc.stderr[-2000:],
        "k6": parse_summary(json.loads(k6sum.read_text(encoding="utf-8"))) if k6sum.exists() else None,
        "request_log": log, "resources": sampler.samples, "lost_work": _lost_work(),
    }
    if spec.scenario == "ramp":
        env6 = k6_env(spec)
        summary["steps"] = ramp_steps(points, t0, [int(r) for r in env6["RAMP_STEPS"].split(",")],
                                      int(env6["STEP_S"]))
    if spec.scenario == "spike":
        env6 = k6_env(spec)
        burst_end = t0 + (int(env6.get("BASE_S", 120)) + int(env6.get("BURST_S", 30))) * 1000
        summary["recovery_s"] = spike_recovery_s(points, burst_end)
    if spec.scenario == "failure":
        summary["phases"] = failure_phases(points, t0, int(k6_env(spec)["PHASE_S"]))
    with httpx.Client() as client:
        _reset(client)                                              # never leave a fault on for the next run
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary
```

Add to `cli.py`:

```python
def cmd_loadtest_run(args: argparse.Namespace) -> int:
    from .loadtest.orchestrate import RunSpec, execute, suite_runs

    root = LOADTEST_DIR / "results" / (args.out or datetime.now(UTC).strftime("%Y-%m-%d"))
    runs = suite_runs() if args.lt_command == "suite" else [RunSpec(args.scenario, args.config, args.repeat)]
    if args.smoke:
        runs = list({(r.scenario, r.config): RunSpec(r.scenario, r.config, 1, smoke=True) for r in runs}.values())
    for spec in runs:
        if (root / spec.name / "summary.json").exists():
            print(f"skip {spec.name} (done)")
            continue
        print(f"== {datetime.now(UTC):%H:%M:%SZ} {spec.name}", flush=True)
        s = execute(spec, root, dict(os.environ))
        lat = (s["k6"] or {}).get("latency", {}).get("all") or {}
        print(f"   k6 exit {s['k6_exit']}, p95 {lat.get('p95')}, errors {(s['k6'] or {}).get('error_rate')}, "
              f"lost work {s['lost_work']}", flush=True)
    return 0
```

Register:

```python
    for name, helptext in (("run", "one load-test run"), ("suite", "the whole D48 matrix (resumable)")):
        p = lt_sub.add_parser(name, help=helptext)
        if name == "run":
            p.add_argument("scenario", choices=["cold", "warm", "ramp", "spike", "soak", "failure"])
            p.add_argument("--config", required=True, choices=["baseline", "cache_only", "router_only", "full"])
            p.add_argument("--repeat", type=int, default=1)
        p.add_argument("--smoke", action="store_true", help="every scenario for ~20 s, to check the wiring")
        p.add_argument("--out", help="results subfolder name (default: today's date)")
        p.set_defaults(func=cmd_loadtest_run)
```

- [ ] **Step 4: Run the tests**

Run: `cd eval && uv run pytest -q`

Expected: all pass (the 6 new tests included).

- [ ] **Step 5: The live smoke** (stub model only; about 15 min, no Groq quota)

```bash
LLM_MODE=stub docker compose up -d --build postgres migrate hospital-rag weir
curl -s http://127.0.0.1:8001/healthz            # expect "llm_mode":"stub"
set -a && . ./.env && set +a && cd eval && uv run python -m weir_eval loadtest suite --smoke --out smoke
```

Expected: one line per (scenario, config). Each has k6 exit 0, or 99 only if the ramp aborted on errors; errors near 0; and lost work 0. Then check:
- `loadtest/results/smoke/failure-full-r1/summary.json` has 7 `phases`
- `curl -s http://127.0.0.1:8001/stub/faults` is `{"faults":{}}` after the run (Review Focus 2)
- `curl -s http://127.0.0.1:8474/proxies/weir-db/toxics` is `[]`

Then stop everything: `docker compose --profile loadtest --profile monitoring stop`. Fix any wiring issue found here before Task 8, test-first where it's code. Delete `loadtest/results/smoke/`; it is not a result.

- [ ] **Step 6: Commit and push**

```bash
git add eval/src/weir_eval/loadtest/orchestrate.py eval/src/weir_eval/cli.py eval/tests/test_loadtest_orchestrate.py
git commit -m "feat(loadtest): orchestrator (stub guard, resets, cache prep, k6, samplers, request-log window) and CLI"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 8: Report generator (pure)

**Files:**
- Create: `eval/src/weir_eval/loadtest/report.py`
- Modify: `eval/src/weir_eval/cli.py` (`loadtest report`)
- Test: `eval/tests/test_loadtest_report.py`

**Interfaces:**
- Consumes: the `summary.json` shape written by `execute` (Task 7).
- Produces:
  - `load_runs(root: Path) -> list[dict]`
  - `median_range(values) -> tuple[float, float, float] | None`
  - `evaluate_checks(runs) -> list[dict]`, each `{name, passed: bool | None, detail}`. `None` means the input runs are missing.
  - `render(runs, meta) -> str`
  - `ramp_chart(runs, path) -> None`

- [ ] **Step 1: Write the failing tests.** Create `eval/tests/test_loadtest_report.py`:

```python
from weir_eval.loadtest.report import evaluate_checks, median_range, render


def run(scenario, config, repeat, p95, **extra):
    k6 = {"requests": 3000, "achieved_rate": 10.0, "error_rate": 0.0, "dropped": 0,
          "latency": {"all": {"p50": p95 / 3, "p95": p95, "p99": p95 * 1.4, "count": 3000},
                      "hit": None, "small": None, "large": None}}
    log = {"n": 3000, "cost": 0.03, "hit_rate": 0.9, "small": 0.1, "fallbacks": 0, "cache_errors": 0, "errors": 0,
           "overhead_mean": 12.0, "overhead_p95": 25.0, "internal_p50": 15.0, "internal_p95": 700.0}
    return {"spec": {"scenario": scenario, "config": config, "repeat": repeat, "smoke": False},
            "k6": k6, "request_log": log, "resources": [], "lost_work": 0, **extra}


def test_median_range():
    assert median_range([3, 1, 2]) == (2, 1, 3) and median_range([None, 5]) == (5, 5, 5)
    assert median_range([]) is None


def test_checks_pass_on_good_runs():
    runs = [run("cold", "baseline", r, 1100) for r in (1, 2, 3)] + [run("warm", "full", r, 300) for r in (1, 2, 3)]
    phases = [{"label": lbl, "n": 600, "p95": 900, "errors": 0, "error_rate": 0.0, "dropped": 0, "achieved_rate": 10}
              for lbl in ["normal", "normal", "large_rate_limited", "normal_2", "small_timeout", "db_delay", "recovery"]]
    runs += [run("failure", "full", r, 900, phases=phases) for r in (1, 2, 3)]
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


def test_render_contains_every_section():
    runs = [run("cold", c, 1, 900) for c in ("baseline", "cache_only", "router_only", "full")]
    md = render(runs, {"date": "2026-10-07", "machine": "Intel Core Ultra 5 225U, 15.5 GB", "repeat_rate": 0.97})
    for heading in ("## Setup", "## Cold cache: four-way", "## Warm cache", "## Latency per path",
                    "## Gateway overhead", "## Ramp", "## Spike", "## Soak", "## Failure injection", "## Checks",
                    "## Limitations"):
        assert heading in md, heading
    assert "no runs yet" in md          # sections without data say so instead of failing
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd eval && uv run pytest -q tests/test_loadtest_report.py`

Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement.** Create `eval/src/weir_eval/loadtest/report.py`:

```python
"""Load-test report (Phase 5 addendum §6): aggregate repeats, evaluate the checks honestly, render markdown."""
import json
import re
from pathlib import Path
from statistics import median

CONFIGS = ("baseline", "cache_only", "router_only", "full")
BUDGET_MS = 2000
_MEM = re.compile(r"([\d.]+)\s*([KMG]i?B)")
_UNITS = {"KiB": 1 / 1024, "KB": 1 / 1000, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1000}


def load_runs(root: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*/summary.json"))]


def median_range(values) -> tuple | None:
    vals = [v for v in values if v is not None]
    return (median(vals), min(vals), max(vals)) if vals else None


def _sel(runs, scenario, config=None):
    return [r for r in runs if r["spec"]["scenario"] == scenario and (config is None or r["spec"]["config"] == config)
            and r.get("k6")]


def _p95(r):
    return r["k6"]["latency"]["all"]["p95"] if r["k6"]["latency"]["all"] else None


def _mem_mib(text: str) -> float:
    m = _MEM.match(text)
    return float(m.group(1)) * _UNITS[m.group(2)] if m else 0.0


def soak_stats(run: dict) -> dict:
    res = [s for s in run.get("resources", []) if "weir-weir-1" in s]
    if len(res) < 2:
        return {}
    head, tail = res[: max(1, len(res) // 6)], res[-max(1, len(res) // 6):]   # first/last ~5 of 30 minutes
    first = median(_mem_mib(s["weir-weir-1"]["mem"]) for s in head)
    last = median(_mem_mib(s["weir-weir-1"]["mem"]) for s in tail)
    return {"mem_first_mib": first, "mem_last_mib": last, "mem_growth": (last - first) / first if first else 0.0}


def evaluate_checks(runs: list[dict]) -> list[dict]:
    checks = []
    base = median_range(_p95(r) for r in _sel(runs, "cold", "baseline"))
    warm = median_range(_p95(r) for r in _sel(runs, "warm", "full"))
    if base and warm:
        cut = 1 - warm[0] / base[0]
        checks.append({"name": "warm p95 at least 30% below baseline", "passed": cut >= 0.30,
                       "detail": f"full warm p95 {warm[0]:.0f} ms vs baseline {base[0]:.0f} ms ({cut:.0%} lower)"})
    else:
        checks.append({"name": "warm p95 at least 30% below baseline", "passed": None, "detail": "no runs yet"})
    fails = _sel(runs, "failure", "full")
    if fails:
        fault_err = sum(ph["errors"] for r in fails for ph in r["phases"]
                        if ph["label"] in ("large_rate_limited", "small_timeout"))
        db = [ph for r in fails for ph in r["phases"] if ph["label"] == "db_delay"]
        db_err = sum(ph["errors"] for ph in db)
        db_p95 = median_range(ph["p95"] for ph in db)
        checks.append({"name": "0 errors during model faults", "passed": fault_err == 0,
                       "detail": f"{fault_err} errors across {len(fails)} runs"})
        checks.append({"name": "cache outage invisible",
                       "passed": db_err == 0 and db_p95 is not None and db_p95[0] <= BUDGET_MS,
                       "detail": f"{db_err} errors; p95 {db_p95[0]:.0f} ms" if db_p95 else f"{db_err} errors"})
    else:
        checks += [{"name": "0 errors during model faults", "passed": None, "detail": "no runs yet"},
                   {"name": "cache outage invisible", "passed": None, "detail": "no runs yet"}]
    soaks = _sel(runs, "soak", "full")
    if soaks:
        s, st = soaks[0], soak_stats(soaks[0])
        drift = (s["soak"]["last_p95"] / s["soak"]["first_p95"] - 1) if s.get("soak") else None
        ok = st.get("mem_growth", 1) < 0.10 and drift is not None and drift < 0.20
        checks.append({"name": "no leaks over the soak", "passed": ok,
                       "detail": f"memory {st.get('mem_growth', 0):+.0%}, p95 drift "
                                 f"{drift:+.0%}" if drift is not None else "incomplete soak data"})
    else:
        checks.append({"name": "no leaks over the soak", "passed": None, "detail": "no runs yet"})
    lost = sum(r.get("lost_work", 0) for r in runs)
    checks.append({"name": "no lost background work", "passed": lost == 0, "detail": f"{lost} across {len(runs)} runs"})
    return checks


def _fmt(mr, unit=" ms"):
    return "–" if mr is None else (f"{mr[0]:.0f}{unit}" if mr[1] == mr[2] else f"{mr[0]:.0f}{unit} ({mr[1]:.0f}–{mr[2]:.0f})")


def _table(runs, scenario):
    rows = []
    for c in CONFIGS:
        sel = _sel(runs, scenario, c)
        if not sel:
            continue
        lat = lambda key, sel=sel: median_range(r["k6"]["latency"]["all"][key] for r in sel)  # noqa: E731
        cost = median_range(1000 * r["request_log"]["cost"] / max(r["request_log"]["n"], 1) for r in sel)
        hit = median_range(r["request_log"]["hit_rate"] for r in sel)
        err = median_range(r["k6"]["error_rate"] for r in sel)
        rows.append(f"| {c} | {len(sel)} | {_fmt(lat('p50'))} | {_fmt(lat('p95'))} | {_fmt(lat('p99'))} | "
                    f"{hit[0]:.1%} | ${cost[0]:.4f} | {err[0]:.2%} |")
    if not rows:
        return ["no runs yet"]
    return ["| Configuration | Runs | p50 | p95 | p99 | Hit rate | Cost / 1k | Errors |",
            "| :-- | --: | --: | --: | --: | --: | --: | --: |", *rows]


def render(runs: list[dict], meta: dict) -> str:
    out = [f"# Load test results ({meta['date']})", "", "## Setup", "",
           f"- Machine: {meta['machine']}. k6 runs on the same laptop (a recorded limitation).",
           f"- Workload: 3,000 requests, Zipf (seed 11), repeat rate {meta['repeat_rate']:.1%}, constant arrival rate.",
           "- Stub model: lognormal per model (small 553 / 830 ms, large 748 / 1,429 ms median / p95), seeded (D49).",
           "- Latency budget: p95 2 s (D50). Medians of repeats, with the range in brackets.", "",
           "## Cold cache: four-way (10 req/s, 5 min)", "", *_table(runs, "cold"), "",
           "## Warm cache (10 req/s, 5 min)", "", *_table(runs, "warm"), "", "## Latency per path", ""]
    rows = []
    for scenario in ("cold", "warm"):
        for c in CONFIGS:
            sel = _sel(runs, scenario, c)
            if sel:
                cells = [_fmt(median_range((r["k6"]["latency"][p] or {}).get("p95") for r in sel))
                         for p in ("hit", "small", "large")]
                rows.append(f"| {scenario} | {c} | " + " | ".join(cells) + " |")
    out += (["| Scenario | Configuration | Hit p95 | Small p95 | Large p95 |", "| :-- | :-- | --: | --: | --: |", *rows]
            if rows else ["no runs yet"])
    out += ["", "## Gateway overhead", ""]
    ov = [r for r in runs if r.get("request_log", {}).get("overhead_mean") is not None and r["spec"]["config"]
          in ("cache_only", "full")]
    out += ([f"Embed + cache lookup inside Weir: mean {_fmt(median_range(r['request_log']['overhead_mean'] for r in ov))}, "
             f"p95 {_fmt(median_range(r['request_log']['overhead_p95'] for r in ov))} (cache configurations, all runs)."]
            if ov else ["no runs yet"])
    out += ["", "## Ramp", ""]
    ramp_rows = []
    for c in ("full", "baseline"):
        sel = [r for r in _sel(runs, "ramp", c) if r.get("steps")]
        if sel:
            from .k6 import ramp_max_rate
            best = median_range(ramp_max_rate(r["steps"]) for r in sel)
            ramp_rows.append(f"| {c} | {len(sel)} | {_fmt(best, ' req/s')} |")
    out += (["![p95 vs request rate](loadtest-ramp.png)", "",
             "| Configuration | Runs | Highest rate within budget |", "| :-- | --: | --: |", *ramp_rows]
            if ramp_rows else ["no runs yet"])
    out += ["", "## Spike", ""]
    sp = _sel(runs, "spike", "full")
    out += ([f"Recovery after a 60 req/s burst: {_fmt(median_range(r.get('recovery_s') for r in sp), ' s')} until "
             f"10-second p95 is back under 2 s; overall p95 {_fmt(median_range(_p95(r) for r in sp))}."]
            if sp else ["no runs yet"])
    out += ["", "## Soak", ""]
    so = _sel(runs, "soak", "full")
    if so:
        st = soak_stats(so[0])
        out.append(f"30 min at 10 req/s: weir memory {st.get('mem_first_mib', 0):.0f} -> {st.get('mem_last_mib', 0):.0f} "
                   f"MiB; p95 first vs last 5 min: {so[0].get('soak', {}).get('first_p95')} -> "
                   f"{so[0].get('soak', {}).get('last_p95')} ms; errors {so[0]['k6']['error_rate']:.2%}.")
    else:
        out.append("no runs yet")
    out += ["", "## Failure injection", ""]
    fl = _sel(runs, "failure", "full")
    if fl:
        out += ["| Phase | Requests | Errors | p95 |", "| :-- | --: | --: | --: |"]
        for i, label in enumerate(fl[0]["phases"]):
            phs = [r["phases"][i] for r in fl]
            out.append(f"| {label['label']} | {sum(p['n'] for p in phs)} | {sum(p['errors'] for p in phs)} | "
                       f"{_fmt(median_range(p['p95'] for p in phs))} |")
    else:
        out.append("no runs yet")
    out += ["", "## Checks", "", "| Check | Result | Detail |", "| :-- | :-: | :-- |"]
    for c in evaluate_checks(runs):
        result = {True: "pass", False: "FAIL", None: "not run"}[c["passed"]]
        out.append(f"| {c['name']} | {result} | {c['detail']} |")
    out += ["", "## Limitations", "",
            "- The model is a stub with realistic timing, not Groq: answers are real retrieval, generation is simulated.",
            "- k6, Weir, hospital-rag and Postgres share one laptop; one Weir process (no horizontal scaling).",
            "- Rates are modest by design (a free-tier, single-machine project); the ramp finds this machine's limit."]
    return "\n".join(out) + "\n"


def ramp_chart(runs: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    for c, color in (("full", "#2b6cb0"), ("baseline", "#c05621")):
        sel = [r for r in _sel(runs, "ramp", c) if r.get("steps")]
        if not sel:
            continue
        rates = [s["rate"] for s in sel[0]["steps"]]
        p95 = [median([r["steps"][i]["p95"] for r in sel if i < len(r["steps"]) and r["steps"][i]["p95"]] or [0])
               for i in range(len(rates))]
        ax.plot(rates, p95, marker="o", color=color, label=c)
    ax.axhline(BUDGET_MS, color="grey", linestyle=":", label="2 s budget")
    ax.set_xlabel("request rate (req/s)")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title("p95 vs request rate (median of repeats)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
```

Soak first/last p95 comes from the run's compact points. Add this to `execute` (Task 7 code, `soak` branch) when implementing this task:

```python
    if spec.scenario == "soak":
        last_t = points[-1][0] if points else t0
        summary["soak"] = {"first_p95": window_stats(points, t0, t0 + 300_000)["p95"],
                           "last_p95": window_stats(points, last_t - 300_000, last_t + 1)["p95"]}
```

Import `window_stats` there too.

Add the CLI command:

```python
def cmd_loadtest_report(args: argparse.Namespace) -> int:
    import platform

    from .loadtest.report import load_runs, ramp_chart, render
    from .workload import repeat_rate

    root = Path(args.results_dir)
    runs = [r for r in load_runs(root) if not r["spec"].get("smoke")]
    reqs = json.loads((LOADTEST_DIR / "workloads" / "requests-3000.json").read_text(encoding="utf-8"))
    meta = {"date": root.name, "machine": args.machine or platform.processor(),
            "repeat_rate": repeat_rate([f"{r['namespace']}|{r['query']}" for r in reqs])}
    out = REPO / "docs" / "results" / f"loadtest-{root.name}.md"
    out.write_text(render(runs, meta), encoding="utf-8")
    ramp_chart(runs, out.parent / "loadtest-ramp.png")
    print(f"wrote {out} ({len(runs)} runs)")
    return 0
```

```python
    rp = lt_sub.add_parser("report", help="render docs/results/loadtest-<date>.md from a results folder")
    rp.add_argument("results_dir")
    rp.add_argument("--machine", default="Intel Core Ultra 5 225U, 14 threads, 15.5 GB RAM, Windows 11")
    rp.set_defaults(func=cmd_loadtest_report)
```

- [ ] **Step 4: Run the tests**

Run: `cd eval && uv run pytest -q`

Expected: all pass.

- [ ] **Step 5: Commit and push**

```bash
git add eval/src/weir_eval/loadtest/report.py eval/src/weir_eval/loadtest/orchestrate.py eval/src/weir_eval/cli.py \
  eval/tests/test_loadtest_report.py
git commit -m "feat(loadtest): report (four-way, per path, overhead, ramp, spike, soak, failure, honest checks)"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 9: The runs (about 4.5 hours, stub model only)

**Files:**
- Create: `loadtest/results/<date>/` (per-run `summary.json`, `k6-summary.json`, `requests.csv.gz`)
- Modify: `docs/progress.md`

- [ ] **Step 1: Prepare**

```bash
LLM_MODE=stub docker compose up -d --build postgres migrate hospital-rag weir
curl -s http://127.0.0.1:8001/healthz        # "llm_mode":"stub"
```

Stop the monitoring profile unless the user wants to watch. If so, `docker compose --profile monitoring up -d`; the dashboard refresh is 5 min.

- [ ] **Step 2: Run the suite in the background,** in chunks the user is told about in IST. It's resumable: re-running skips finished runs.

```bash
set -a && . ./.env && set +a && cd eval && uv run python -m weir_eval loadtest suite > "$TMP/suite.log" 2>&1
```

Check progress with `tail "$TMP/suite.log"`. If Docker Desktop stops, restart it and re-run the same command.

- [ ] **Step 3: Check the raw results**

Every run should have `summary.json` with `k6_exit` 0, except ramp runs that aborted on errors (99, by design). Spot-check one run of each scenario.

- [ ] **Step 4: Stop everything and commit the raw results**

```bash
docker compose --profile loadtest --profile monitoring stop
git add loadtest/results/<date> docs/progress.md
git commit -m "results: Phase 5 load-test runs (stub model, D48 matrix)"
git push origin phase-5 && git push origin phase-5:main
```

---

### Task 10: Results, docs, final review, close

**Files:**
- Create: `docs/results/loadtest-<date>.md`, `docs/results/loadtest-ramp.png`
- Modify: `README.md`, `docs/results/summary.md`, `docs/decisions.md`, `docs/progress.md`, `docs/backlog.md`, `docs/README.md`

- [ ] **Step 1: Render the report**

Run: `cd eval && uv run python -m weir_eval loadtest report ../loadtest/results/<date>`

Then read it end to end. Add a short "What this shows" paragraph per section by hand, in plain language. Every number stays as rendered. Investigate any FAIL check before writing it up, and record the finding as a decision if it changes the code.

- [ ] **Step 2: Update the README and docs**

- **README Results:** add "Under load (stub model)" with:
  - the cold four-way p95 table
  - warm full vs baseline
  - the ramp's highest rate within budget, full vs baseline
  - the failure checks
  - a link to the report
- **Other README sections:** k6 and Toxiproxy in the stack table, a "Load tests" how-to under Evaluation, and the roadmap Phase 5 set to Done.
- **`docs/results/summary.md`:** add an under-load table.
- **`docs/decisions.md`:** any build decisions, from D54.
- **`docs/backlog.md`:** M25 resolved, plus any new minors.
- **`docs/progress.md`:** a Phase 5 exit entry.
- **`docs/README.md`:** link the report and the plan.

No emojis.

- [ ] **Step 3: Final whole-branch review**

1. Make a code-only diff from the Phase 5 start (`aaaefa9`), covering `services`, `eval/src`, `eval/tests`, `loadtest/scripts`, `docker-compose*`, `.github` and `monitoring`.
2. Dispatch one fresh reviewer on the most capable model, with the plan, the addendum and the Review Focus list.
3. Re-grade the findings by effect.
4. Fix Critical and Important findings test-first, in one pass. Put the Minor ones in the backlog.

- [ ] **Step 4: Commit, push, close**

```bash
git add README.md docs/
git commit -m "docs: Phase 5 load-test results, README under-load section, decisions, progress; Phase 5 closed"
git push origin phase-5 && git push origin phase-5:main
```

Update the memory file `weir-project.md`: Phase 5 done with its date and headline numbers; next is Phase 6 (polish, demo chat page, write-up).

---

## Self-Review Notes

**Spec coverage** (addendum section → task):

| Addendum section | Task(s) |
| --- | --- |
| §1 decisions D48–D53 | already logged |
| §2 components, M25 prerequisite | 1, 4, 5, 7 |
| §3.1 realistic timing | 2 |
| §3.2 fault endpoint | 3 |
| §3.3 Toxiproxy | 4 |
| §3.4 chaos track and teardown | 5 |
| §4 scenarios, workload, warm-up, repeats | 5, 7 |
| §5 measurements | 6, 7 |
| §6 report and checks | 8, 10 |
| §7 testing | 1–8 |
| §8 docs | 10 |
| §9 out of scope | respected |

**Deliberate refinements:**
- **Every run starts from an emptied cache;** warm runs then pre-fill it. This avoids carry-over between runs, which the addendum implies.
- **Raw k6 output is compacted to `requests.csv.gz`** (time, kind, value, status) rather than gzipping k6's full JSON, which is roughly 10x larger.
