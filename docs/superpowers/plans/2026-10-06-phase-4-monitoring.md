# Phase 4 Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Weir a live, file-provisioned monitoring stack: a `/metrics` endpoint, Prometheus with 8 tested alert rules, and a Grafana dashboard. The dashboard shows every past and present run, with a configuration filter.

**Architecture:**
- **Metrics:** a `MetricsSink` wraps the existing request-log writer and updates Prometheus counters from the same finished `RequestLogRow` that goes to Postgres. A collector exposes the background queues' loss counters.
- **Monitoring containers:** Prometheus and Grafana run behind a Compose profile. Everything is provisioned from files under `monitoring/`.
- **Postgres access:** Grafana reads the request log through a new read-only `weir_reader` user.
- **Dashboard source:** a small stdlib-only Python builder generates the dashboard JSON, so the SQL stays readable. The JSON is checked by a test that runs every panel query against a seeded database.

**Tech Stack:**
- Python 3.12 with `prometheus-client` (new dependency, Apache-2.0, free)
- FastAPI
- Postgres 16
- `prom/prometheus:v2.55.1` (with `promtool`)
- `grafana/grafana-oss:11.3.0`
- Docker Compose profiles
- Playwright (headless Chromium, free) for screenshots
- pytest and GitHub Actions

**Spec:** [`docs/superpowers/specs/2026-10-06-phase-4-monitoring-design.md`](../specs/2026-10-06-phase-4-monitoring-design.md) (approved 2026-10-06). It builds on main spec §5, §9.1 and §16, and on the original spec's "Metrics and dashboard" section.

## Global Constraints

- **Free tools only** (D0). No paid service or account.
- **Pinned images:** `prom/prometheus:v2.55.1` and `grafana/grafana-oss:11.3.0`.
- **Ports are localhost-only:** Prometheus `127.0.0.1:9090`, Grafana `127.0.0.1:3000`. **Weir moves from `8000:8000` to `127.0.0.1:8000:8000`.**
- **Opt-in:** Prometheus and Grafana run only with `docker compose --profile monitoring up -d`. A plain `docker compose up -d` is unchanged in RAM.
- **Prometheus:**
  - scrape `weir:8000/metrics` every 5 s
  - evaluate rules every 30 s
  - keep 15 days of data
- **Grafana:**
  - admin password from `.env` `GRAFANA_ADMIN_PASSWORD`
  - anonymous access off, sign-up off
  - data sources and the dashboard are provisioned from files only
- **Grafana's Postgres login is `weir_reader` / `weir_reader`.** It is a local-only password, the same approach as `weir/weir`. It may only `SELECT` four tables: `weir.request_log`, `weir.cache_entries`, `weir.model_prices` and `weir.feedback`.
- **Never use as a Prometheus label:** `request_id`, query text, similarity, or model output.
- **Alerts are shown in Grafana and on Prometheus `/alerts` only** (D42). No notifications.
- **The default dashboard time range is "last 30 days."** Answer quality is linked to `docs/results/summary.md`, never shown as a live number.
- **Windows host:**
  - Use `127.0.0.1`, never `localhost`.
  - In Git Bash, prefix `docker` commands that pass container paths with `MSYS_NO_PATHCONV=1`, and use `$(pwd -W)` for bind-mount sources.
  - Never edit files with PowerShell `Set-Content`.
- **Secrets:** never print or commit `.env` values.
- **Docs have no emojis.** Use words ("pass", "Done").
- **Workflow:**
  - After each task's tests pass, commit, push the branch and fast-forward main without asking: `git push origin phase-4 && git push origin phase-4:main`.
  - Then pause for the user's go-ahead before the next task.
  - Give clock times to the user in IST.
- **RAM is tight.** Stop containers when a step no longer needs them (`docker compose --profile monitoring stop`).
- **Rebuild after code changes.** Only `configs/` is mounted into the `weir` container, so code changes need `docker compose up -d --build weir`.

## Review Focus

1. **A metrics failure must never fail a request.** If recording a row raises, the row still reaches the Postgres writer, the request still returns, and `weir_metrics_failed_total` counts the failure. Pinned in Task 1 (`test_metrics_failure_never_blocks_the_log_row`).
2. **Prometheus may scrape before any request has been served.** `/metrics` must still return 200 with `weir_info` and the four loss counters at 0, so `WeirDown` stays quiet and the lost-work panel isn't blank. Pinned in Task 2 (`test_metrics_before_any_request`).
3. **Old rows (Phase 1–2) have NULL `route_reason`, `grounding_*` and `config_label = 'dev'`.** Every panel query must run and return data with such rows present, not error. Pinned in Task 6: the seed includes a Phase-1-style row.
4. **An idle or low-traffic machine must never alert.** The rate alerts need a minimum amount of traffic. Pinned in Task 5: each rate alert has a promtool "low traffic, stays silent" case.
5. **Question text from a sensitive namespace must never reach `/metrics`.** Pinned in Task 1 (`test_no_request_text_or_ids_in_metrics`).

---

## File Structure

| File | Create/Modify | Responsibility |
| --- | --- | --- |
| `services/weir/pyproject.toml`, `uv.lock` | Modify | Add `prometheus-client` |
| `services/weir/src/weir/metrics/prometheus.py` | Create | `WeirMetrics` (series and `record(row)`), `MetricsSink` (wraps a `LogSink`), `LossCollector` (queue loss counters) |
| `services/weir/src/weir/main.py` | Modify | `AppDeps.metrics`, `GET /metrics`, lifespan wiring |
| `db/migrations/004_phase4_monitoring.sql` | Create | Read-only `weir_reader` login |
| `docker-compose.yml`, `.env.example` | Modify | `prometheus` and `grafana` services (profile `monitoring`); Weir on `127.0.0.1`; `GRAFANA_ADMIN_PASSWORD` |
| `monitoring/prometheus/prometheus.yml` | Create | Scrape config and rule file |
| `monitoring/prometheus/alerts.yml`, `alerts_test.yml` | Create | 8 alert rules; promtool unit tests |
| `monitoring/grafana/provisioning/datasources/datasources.yml` | Create | Prometheus (`weir-prom`) and Postgres (`weir-pg`) |
| `monitoring/grafana/provisioning/dashboards/dashboards.yml` | Create | File dashboard provider |
| `monitoring/grafana/build_dashboard.py` | Create | Stdlib-only builder; source of truth for every panel |
| `monitoring/grafana/dashboards/weir.json` | Create (generated) | The dashboard |
| `monitoring/check_panels.py` | Create | Live check: runs every panel through Grafana's query API and reports any empty panel |
| `monitoring/screenshot.py` | Create | Playwright capture of the dashboard into `docs/images/` |
| `.github/workflows/tests.yml` | Modify | New `monitoring` job: `promtool check config` and `test rules` |
| `services/weir/tests/test_prometheus_metrics.py` | Create | Task 1 tests |
| `services/weir/tests/test_api.py` | Modify | `/metrics` endpoint tests |
| `services/weir/tests/test_migrate.py` | Modify | `004`, `weir_reader` privileges |
| `services/weir/tests/test_compose.py` | Create | Compose bindings and profiles |
| `services/weir/tests/test_dashboard.py` | Create | Panel queries run as `weir_reader`; JSON matches the builder; Prometheus expressions only use real metric names |
| `README.md`, `docs/*` | Modify | Monitoring section, diagram, decisions, progress, backlog |

---

### Task 1: Weir metrics module

**Files:**
- Modify: `services/weir/pyproject.toml` (and `uv.lock`, via `uv add`)
- Create: `services/weir/src/weir/metrics/prometheus.py`
- Test: `services/weir/tests/test_prometheus_metrics.py`

**Interfaces:**
- Consumes:
  - `weir.metrics.logger.RequestLogRow` (fields: `namespace`, `cache_status`, `route`, `status`, `latency_total_ms`, `cost_usd`, `counterfactual_cost_usd`, `model_calls`, `escalated`, `route_reason`, `grounding_passed`, `grounding_reason`, `query_text`, `request_id`)
  - `LogSink` (anything with `.submit(row)`)
- Produces:
  - `WeirMetrics(registry: CollectorRegistry, config_label: str)` with `.record(row: RequestLogRow) -> None`, `.registry`, and `.metrics_failed` (Counter)
  - `MetricsSink(writer: LogSink, metrics: WeirMetrics)` with `.submit(row) -> None` (implements `LogSink`)
  - `LossCollector(sources: dict[str, object])`. Each source has int `.dropped` and `.failed`. It exposes `weir_<name>_dropped_total` and `weir_<name>_failed_total`.
  - Exposed names:
    - `weir_requests_total`
    - `weir_request_latency_seconds` (histogram)
    - `weir_cost_usd_total`, `weir_counterfactual_cost_usd_total`
    - `weir_model_calls_total`, `weir_escalations_total`, `weir_fallbacks_total`
    - `weir_grounding_total`, `weir_metrics_failed_total`
    - `weir_info`
    - the `LossCollector` names

- [ ] **Step 1: Add the dependency**

Run: `cd services/weir && uv add "prometheus-client>=0.20"`

Expected: `pyproject.toml` lists `prometheus-client>=0.20` and `uv.lock` updates. The package is free (Apache-2.0).

- [ ] **Step 2: Write the failing tests**

Create `services/weir/tests/test_prometheus_metrics.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from weir.metrics.logger import RequestLogRow
from weir.metrics.prometheus import LossCollector, MetricsSink, WeirMetrics

from .fakes import ListSink

PUB = "weir-general/en/public"


def row(**over):
    base = dict(request_id=uuid4(), ts=datetime.now(UTC), namespace=PUB, cache_status="miss", route="large",
                status="ok", latency_total_ms=800, query_hash="h" * 64, cost_usd=Decimal("0.0001"),
                counterfactual_cost_usd=Decimal("0.0001"), model_calls=1, route_reason="default_large",
                grounding_passed=True, config_label="full")
    return RequestLogRow(**{**base, **over})


def setup():
    registry = CollectorRegistry()
    metrics = WeirMetrics(registry, "full")
    return registry, metrics, MetricsSink(ListSink(), metrics)


def value(registry, name, **labels):
    return registry.get_sample_value(name, labels) or 0.0


def test_large_miss_updates_requests_latency_cost_and_calls():
    registry, metrics, _ = setup()
    metrics.record(row(cost_usd=Decimal("0.0004"), counterfactual_cost_usd=Decimal("0.0004")))
    labels = dict(namespace=PUB, cache_status="miss", route="large", status="ok")
    assert value(registry, "weir_requests_total", **labels) == 1
    assert value(registry, "weir_request_latency_seconds_count", cache_status="miss", route="large") == 1
    assert value(registry, "weir_request_latency_seconds_sum", cache_status="miss", route="large") == 0.8
    assert value(registry, "weir_cost_usd_total", namespace=PUB) == pytest.approx(0.0004)
    assert value(registry, "weir_counterfactual_cost_usd_total", namespace=PUB) == pytest.approx(0.0004)
    assert value(registry, "weir_model_calls_total") == 1


def test_cache_hit_costs_nothing_but_counts_its_counterfactual():
    registry, metrics, _ = setup()
    metrics.record(row(cache_status="hit", route="none", model_calls=0, cost_usd=Decimal(0),
                       counterfactual_cost_usd=Decimal("0.0005"), route_reason=None, grounding_passed=None))
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="hit", route="none", status="ok") == 1
    assert value(registry, "weir_cost_usd_total", namespace=PUB) == 0
    assert value(registry, "weir_counterfactual_cost_usd_total", namespace=PUB) == pytest.approx(0.0005)
    assert value(registry, "weir_grounding_total", passed="true", reason="none") == 0   # hits aren't graded


def test_escalation_fallback_and_grounding():
    registry, metrics, _ = setup()
    metrics.record(row(route="small", escalated=True, model_calls=2, route_reason="simple"))
    metrics.record(row(route="small", model_calls=2, route_reason="simple+fallback"))
    metrics.record(row(route="large", grounding_passed=False, grounding_reason="low_overlap"))
    assert value(registry, "weir_escalations_total") == 1
    assert value(registry, "weir_fallbacks_total", routed_tier="small") == 1
    assert value(registry, "weir_model_calls_total") == 5
    assert value(registry, "weir_grounding_total", passed="true", reason="none") == 2
    assert value(registry, "weir_grounding_total", passed="false", reason="low_overlap") == 1


def test_errors_and_timeouts_are_labelled_by_status():
    registry, metrics, _ = setup()
    metrics.record(row(status="error", grounding_passed=None, model_calls=2))
    metrics.record(row(status="timeout", grounding_passed=None))
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="miss", route="large",
                 status="error") == 1
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="miss", route="large",
                 status="timeout") == 1


def test_sink_records_then_forwards_the_row():
    registry, metrics, sink = setup()
    r = row()
    sink.submit(r)
    assert sink._writer.rows == [r]
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="miss", route="large", status="ok") == 1


def test_metrics_failure_never_blocks_the_log_row():  # Review Focus 1
    registry, metrics, sink = setup()

    def broken(_row):
        raise RuntimeError("boom")

    metrics.record = broken
    r = row()
    sink.submit(r)                                   # must not raise
    assert sink._writer.rows == [r]
    assert value(registry, "weir_metrics_failed_total") == 1


def test_no_request_text_or_ids_in_metrics():  # Review Focus 5
    registry, metrics, _ = setup()
    r = row(namespace="weir-general/en/staff", query_text="patient John Doe 9876543210 room 12")
    metrics.record(r)
    text = generate_latest(registry).decode()
    assert "John Doe" not in text and "9876543210" not in text and str(r.request_id) not in text


def test_info_and_loss_collector():
    class Q:
        dropped, failed = 2, 3

    registry = CollectorRegistry()
    WeirMetrics(registry, "router_only")
    registry.register(LossCollector({"log_rows": Q(), "cache_jobs": Q()}))
    assert value(registry, "weir_info", config_label="router_only") == 1
    assert value(registry, "weir_log_rows_dropped_total") == 2
    assert value(registry, "weir_cache_jobs_failed_total") == 3
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_prometheus_metrics.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'weir.metrics.prometheus'`.

- [ ] **Step 4: Implement**

Create `services/weir/src/weir/metrics/prometheus.py`:

```python
"""Live Prometheus metrics (Phase 4 addendum §3).

Every request metric is derived from the finished RequestLogRow, the same record that goes to Postgres, so the
live and historical numbers can't disagree. Request IDs, question text, similarity and model output are never
labels: they would create unbounded series and could leak text from sensitive namespaces.
"""
import logging

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import CounterMetricFamily
from prometheus_client.registry import Collector

from .logger import LogSink, RequestLogRow

log = logging.getLogger("weir.metrics")

LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0)


class WeirMetrics:
    def __init__(self, registry: CollectorRegistry, config_label: str):
        self.registry = registry
        self.requests = Counter("weir_requests", "Requests handled by Weir",
                                ["namespace", "cache_status", "route", "status"], registry=registry)
        self.latency = Histogram("weir_request_latency_seconds", "End-to-end latency inside Weir",
                                 ["cache_status", "route"], buckets=LATENCY_BUCKETS, registry=registry)
        self.cost = Counter("weir_cost_usd", "Spend at list prices", ["namespace"], registry=registry)
        self.counterfactual = Counter("weir_counterfactual_cost_usd",
                                      "Spend with no cache and always the large model", ["namespace"],
                                      registry=registry)
        self.model_calls = Counter("weir_model_calls", "Model calls attempted", registry=registry)
        self.escalations = Counter("weir_escalations", "Small answers retried on the large model", registry=registry)
        self.fallbacks = Counter("weir_fallbacks", "Requests that switched tier after a provider error",
                                 ["routed_tier"], registry=registry)
        self.grounding = Counter("weir_grounding", "Grounding check results", ["passed", "reason"], registry=registry)
        self.metrics_failed = Counter("weir_metrics_failed", "Rows the metrics layer failed to record",
                                      registry=registry)
        Gauge("weir_info", "Running Weir configuration", ["config_label"], registry=registry).labels(config_label).set(1)

    def record(self, row: RequestLogRow) -> None:
        self.requests.labels(row.namespace, row.cache_status, row.route, row.status).inc()
        self.latency.labels(row.cache_status, row.route).observe(row.latency_total_ms / 1000)
        self.cost.labels(row.namespace).inc(float(row.cost_usd))
        self.counterfactual.labels(row.namespace).inc(float(row.counterfactual_cost_usd))
        if row.model_calls:
            self.model_calls.inc(row.model_calls)
        if row.escalated:
            self.escalations.inc()
        if row.route_reason and row.route_reason.endswith("+fallback"):
            self.fallbacks.labels(row.route).inc()
        if row.grounding_passed is not None:
            self.grounding.labels("true" if row.grounding_passed else "false", row.grounding_reason or "none").inc()


class MetricsSink:
    """A LogSink that records live metrics, then forwards the row to the real writer unchanged."""

    def __init__(self, writer: LogSink, metrics: WeirMetrics):
        self._writer = writer
        self._metrics = metrics

    def submit(self, row: RequestLogRow) -> None:
        try:
            self._metrics.record(row)
        except Exception:  # noqa: BLE001 - monitoring must never fail a request or lose its log row
            self._metrics.metrics_failed.inc()
            log.exception("failed to record metrics for request %s", row.request_id)
        self._writer.submit(row)


class LossCollector(Collector):
    """Exposes the background queues' dropped/failed counts at scrape time (backlog M7)."""

    def __init__(self, sources: dict[str, object]):
        self._sources = sources

    def collect(self):
        for name, source in self._sources.items():
            for attr in ("dropped", "failed"):
                yield CounterMetricFamily(f"weir_{name}_{attr}", f"{name.replace('_', ' ')} {attr}",
                                          value=getattr(source, attr))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd services/weir && uv run pytest -q tests/test_prometheus_metrics.py`

Expected: PASS (8 tests). Then run the whole non-DB suite: `uv run pytest -q -m "not db"`. Expected: PASS.

- [ ] **Step 6: Commit and push**

```bash
git add services/weir/pyproject.toml services/weir/uv.lock services/weir/src/weir/metrics/prometheus.py \
  services/weir/tests/test_prometheus_metrics.py
git commit -m "feat(metrics): Prometheus metrics from the request-log row, loss counters, never-fail sink"
git push origin phase-4 && git push origin phase-4:main
```

---

### Task 2: `GET /metrics` endpoint and app wiring

**Files:**
- Modify: `services/weir/src/weir/main.py` (imports, `AppDeps`, lifespan, routes)
- Test: `services/weir/tests/test_api.py`

**Interfaces:**
- Consumes: `WeirMetrics`, `MetricsSink`, `LossCollector` (Task 1).
- Produces:
  - `AppDeps.metrics: WeirMetrics | None = None`
  - `GET /metrics`: no auth, Prometheus text format (`prometheus_client.CONTENT_TYPE_LATEST`), 404 when metrics are off
  - in the real app, `Pipeline` logs through `MetricsSink(writer, metrics)`, and the registry includes `LossCollector({"log_rows": writer, "cache_jobs": cache_jobs})`

- [ ] **Step 1: Write the failing tests**

In `services/weir/tests/test_api.py`, change `app_client` so it can attach metrics. Add a `metrics=None` parameter and pass it into `AppDeps`:

```python
def app_client(rag=None, health_ok=True, admin=None, metrics=None):
    h = harness(rag or fake_rag())

    async def health():
        return {"db": health_ok, "rag": True}

    deps = AppDeps(h.p, TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", ENV), load_config(CONFIGS / "weir.yaml"),
                   health, admin or FakeAdmin(), feedback_lookup_delay_s=0, metrics=metrics)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://t")
    return client, h.sink
```

Append the tests:

```python
from prometheus_client import CollectorRegistry  # noqa: E402

from weir.metrics.prometheus import LossCollector, WeirMetrics  # noqa: E402


def _metrics():
    class Q:
        dropped = failed = 0

    registry = CollectorRegistry()
    m = WeirMetrics(registry, "dev")
    registry.register(LossCollector({"log_rows": Q(), "cache_jobs": Q()}))
    return m


async def test_metrics_before_any_request():  # Review Focus 2: scrape before traffic
    client, sink = app_client(metrics=_metrics())
    async with client:
        r = await client.get("/metrics")                                  # no API key needed
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert 'weir_info{config_label="dev"} 1.0' in body
    for name in ("weir_log_rows_dropped_total", "weir_log_rows_failed_total",
                 "weir_cache_jobs_dropped_total", "weir_cache_jobs_failed_total"):
        assert f"{name} 0.0" in body
    assert sink.rows == []                                                # scraping isn't a logged request


async def test_metrics_reflect_requests_recorded_by_the_sink():
    m = _metrics()
    client, _ = app_client(metrics=m)
    m.record(_row_for_metrics())
    async with client:
        body = (await client.get("/metrics")).text
    assert 'weir_requests_total{namespace="weir-general/en/public",cache_status="miss",route="large",status="ok"} 1.0' in body


async def test_metrics_off_returns_404():
    client, _ = app_client()
    async with client:
        assert (await client.get("/metrics")).status_code == 404


def _row_for_metrics():
    from datetime import UTC, datetime
    from decimal import Decimal
    from uuid import uuid4

    from weir.metrics.logger import RequestLogRow

    return RequestLogRow(request_id=uuid4(), ts=datetime.now(UTC), namespace=PUBLIC, cache_status="miss",
                         route="large", status="ok", latency_total_ms=500, query_hash="h" * 64,
                         cost_usd=Decimal("0.0001"), counterfactual_cost_usd=Decimal("0.0001"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_api.py -k metrics`

Expected: FAIL with `TypeError: AppDeps.__init__() got an unexpected keyword argument 'metrics'`.

- [ ] **Step 3: Implement**

In `services/weir/src/weir/main.py`:

1. Add the imports:

```python
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from .metrics.prometheus import LossCollector, MetricsSink, WeirMetrics
```

2. Add the last field to `AppDeps`:

```python
    metrics: WeirMetrics | None = None
```

3. In the lifespan, replace the line that builds `app.state.deps = AppDeps(Pipeline(cfg, rag, prices, writer, cache), ...)` with:

```python
        registry = CollectorRegistry()
        metrics = WeirMetrics(registry, cfg.config_label)
        registry.register(LossCollector({"log_rows": writer, "cache_jobs": cache_jobs}))
        app.state.deps = AppDeps(Pipeline(cfg, rag, prices, MetricsSink(writer, metrics), cache), tenants, cfg,
                                 health, AdminService(pool, store), metrics=metrics)
```

4. Add the route after `/healthz`:

```python
    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(request: Request):
        d: AppDeps = request.app.state.deps
        if d.metrics is None:
            raise HTTPException(status_code=404, detail="metrics are off")
        return Response(generate_latest(d.metrics.registry), media_type=CONTENT_TYPE_LATEST)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/weir && uv run pytest -q tests/test_api.py`

Expected: all API tests PASS (the 3 new ones included). Then run the whole suite with Postgres up:

```bash
docker compose up -d postgres
cd services/weir && uv run pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit and push**

```bash
git add services/weir/src/weir/main.py services/weir/tests/test_api.py
git commit -m "feat(metrics): GET /metrics endpoint; pipeline logs through MetricsSink; queue loss counters (M7)"
git push origin phase-4 && git push origin phase-4:main
```

---

### Task 3: Read-only `weir_reader` login (migration 004)

**Files:**
- Create: `db/migrations/004_phase4_monitoring.sql`
- Modify: `services/weir/tests/test_migrate.py`

**Interfaces:**
- Produces:
  - the Postgres role `weir_reader` (password `weir_reader`)
  - `USAGE` on schema `weir`
  - `SELECT` on `weir.request_log`, `weir.cache_entries`, `weir.model_prices` and `weir.feedback`
  - no access to `rag.*` and no writes

- [ ] **Step 1: Write the failing tests**

In `services/weir/tests/test_migrate.py`, extend the expected list in `test_applies_all_then_is_idempotent` with `"004_phase4_monitoring.sql"`, then append:

```python
READ_TABLES = ("weir.request_log", "weir.cache_entries", "weir.model_prices", "weir.feedback")


def _reader(url: str) -> str:
    return url.replace("weir:weir@", "weir_reader:weir_reader@", 1)


def test_weir_reader_can_read_the_four_tables(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(_reader(clean_db_url)) as conn:
        for table in READ_TABLES:
            conn.execute(f"select count(*) from {table}").fetchone()


@pytest.mark.parametrize("statement", [
    "insert into weir.feedback (request_id, rating) values (gen_random_uuid(), 1)",
    "update weir.request_log set status = 'ok'",
    "delete from weir.cache_entries",
    "select count(*) from rag.chunks",
    "create table weir.x (id int)",
])
def test_weir_reader_cannot_write_or_read_rag(clean_db_url, statement):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(_reader(clean_db_url)) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose up -d postgres
cd services/weir && uv run pytest -q tests/test_migrate.py
```

Expected: FAIL. The migration list mismatches, and `connection failed: ... password authentication failed for user "weir_reader"` (or "role does not exist").

- [ ] **Step 3: Implement**

Create `db/migrations/004_phase4_monitoring.sql`:

```sql
-- Phase 4 addendum §2: a read-only login for Grafana. Roles are cluster-wide, so create it only once.
-- Local-only password, like weir/weir: Postgres is bound to 127.0.0.1.
do $$
begin
  if not exists (select from pg_roles where rolname = 'weir_reader') then
    create role weir_reader login password 'weir_reader';
  end if;
end
$$;
grant usage on schema weir to weir_reader;
grant select on weir.request_log, weir.cache_entries, weir.model_prices, weir.feedback to weir_reader;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/weir && uv run pytest -q tests/test_migrate.py`

Expected: PASS. Then run the full suite: `uv run pytest -q`. Expected: PASS.

- [ ] **Step 5: Apply it to the dev database**

Run: `docker compose up -d --build migrate`

Expected: `docker compose logs migrate` shows `applied 1 migration(s): 004_phase4_monitoring.sql`.

- [ ] **Step 6: Commit and push**

```bash
git add db/migrations/004_phase4_monitoring.sql services/weir/tests/test_migrate.py
git commit -m "feat(db): read-only weir_reader login for Grafana (migration 004)"
git push origin phase-4 && git push origin phase-4:main
```

---

### Task 4: Compose services, Prometheus scrape config, Grafana provisioning

**Files:**
- Modify: `docker-compose.yml`, `.env.example`
- Create: `monitoring/prometheus/prometheus.yml`
- Create: `monitoring/grafana/provisioning/datasources/datasources.yml`
- Create: `monitoring/grafana/provisioning/dashboards/dashboards.yml`
- Create: `monitoring/prometheus/alerts.yml`, an empty `groups: []` placeholder that Task 5 fills (needed so `check config` passes)
- Create: `services/weir/tests/test_compose.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Produces:
  - Compose services `prometheus` and `grafana`, both in profile `monitoring`
  - data source UIDs **`weir-prom`** (Prometheus) and **`weir-pg`** (Postgres as `weir_reader`); later tasks reference these exact UIDs
  - dashboards are loaded from `/var/lib/grafana/dashboards` (bind-mounted from `monitoring/grafana/dashboards/`)

- [ ] **Step 1: Write the failing test**

Create `services/weir/tests/test_compose.py`:

```python
"""Compose wiring the monitoring design depends on (Phase 4 addendum §2)."""
import yaml

from .conftest import REPO

COMPOSE = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_every_published_port_is_localhost_only():
    for name, service in SERVICES.items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on every interface"


def test_monitoring_services_are_opt_in_and_pinned():
    assert SERVICES["prometheus"]["profiles"] == ["monitoring"]
    assert SERVICES["grafana"]["profiles"] == ["monitoring"]
    assert SERVICES["prometheus"]["image"] == "prom/prometheus:v2.55.1"
    assert SERVICES["grafana"]["image"] == "grafana/grafana-oss:11.3.0"
    assert all("profiles" not in SERVICES[s] for s in ("postgres", "migrate", "hospital-rag", "weir"))


def test_grafana_has_no_anonymous_access_or_signup():
    env = SERVICES["grafana"]["environment"]
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false" and env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert "GRAFANA_ADMIN_PASSWORD" in env["GF_SECURITY_ADMIN_PASSWORD"]


def test_prometheus_scrapes_weir_every_5s_and_keeps_15_days():
    prom = yaml.safe_load((REPO / "monitoring" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
    assert prom["global"]["scrape_interval"] == "5s" and prom["global"]["evaluation_interval"] == "30s"
    [job] = prom["scrape_configs"]
    assert job["job_name"] == "weir" and job["static_configs"][0]["targets"] == ["weir:8000"]
    assert "--storage.tsdb.retention.time=15d" in SERVICES["prometheus"]["command"]


def test_grafana_datasources_use_the_read_only_login():
    ds = yaml.safe_load((REPO / "monitoring" / "grafana" / "provisioning" / "datasources" / "datasources.yml")
                        .read_text(encoding="utf-8"))["datasources"]
    by_uid = {d["uid"]: d for d in ds}
    assert by_uid["weir-prom"]["url"] == "http://prometheus:9090"
    assert by_uid["weir-pg"]["user"] == "weir_reader" and by_uid["weir-pg"]["jsonData"]["database"] == "weir"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/weir && uv run pytest -q tests/test_compose.py`

Expected: FAIL. `weir publishes 8000:8000 on every interface`, `KeyError: 'prometheus'`, and missing files.

- [ ] **Step 3: Implement**

In `docker-compose.yml`:
- change the `weir` ports line to `ports: ["127.0.0.1:8000:8000"]  # localhost only: /metrics has no auth`
- add these two services before `volumes:`
- add `promdata:` and `grafanadata:` under `volumes:`

```yaml
  prometheus:
    image: prom/prometheus:v2.55.1
    profiles: ["monitoring"]
    command: ["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.retention.time=15d"]
    volumes:
      - ./monitoring/prometheus:/etc/prometheus:ro
      - promdata:/prometheus
    ports: ["127.0.0.1:9090:9090"]  # localhost only
    depends_on: [weir]

  grafana:
    image: grafana/grafana-oss:11.3.0
    profiles: ["monitoring"]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
    volumes:
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafanadata:/var/lib/grafana
    ports: ["127.0.0.1:3000:3000"]  # localhost only
    depends_on: [prometheus, postgres]
```

(`:-admin` rather than `:?`: Compose interpolates every service even when its profile is off, so `:?` would break a plain `docker compose up` for anyone without the variable. Grafana is localhost-only either way.)

Append to `.env.example`:

```bash
# Grafana admin password (Phase 4 monitoring; localhost only). Start with: docker compose --profile monitoring up -d
GRAFANA_ADMIN_PASSWORD=
```

Create `monitoring/prometheus/prometheus.yml`:

```yaml
# Phase 4 addendum §2: scrape Weir every 5 s, evaluate alert rules every 30 s.
global:
  scrape_interval: 5s
  evaluation_interval: 30s
rule_files:
  - /etc/prometheus/alerts.yml
scrape_configs:
  - job_name: weir
    metrics_path: /metrics
    static_configs:
      - targets: ["weir:8000"]
```

Create `monitoring/prometheus/alerts.yml` (filled in Task 5):

```yaml
groups: []
```

Create `monitoring/grafana/provisioning/datasources/datasources.yml`:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    uid: weir-prom
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    jsonData:
      timeInterval: 5s
  - name: Weir request log
    uid: weir-pg
    type: grafana-postgresql-datasource
    access: proxy
    url: postgres:5432
    user: weir_reader
    jsonData:
      database: weir
      sslmode: disable
      postgresVersion: 1600
      timescaledb: false
    secureJsonData:
      password: weir_reader   # local-only read-only login (migration 004)
```

Create `monitoring/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
apiVersion: 1
providers:
  - name: weir
    type: file
    disableDeletion: true
    allowUiUpdates: false
    options:
      path: /var/lib/grafana/dashboards
```

Create an empty `monitoring/grafana/dashboards/.gitkeep`, so the mount target exists until Task 6.

In `.github/workflows/tests.yml`, add a second job under `jobs:`:

```yaml
  monitoring:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: promtool check config
        run: >-
          docker run --rm -v "$PWD/monitoring/prometheus:/etc/prometheus:ro" --entrypoint promtool
          prom/prometheus:v2.55.1 check config /etc/prometheus/prometheus.yml
```

- [ ] **Step 4: Run the tests and the config check**

```bash
cd services/weir && uv run pytest -q tests/test_compose.py
cd ../.. && docker compose --profile monitoring config -q && echo compose-ok
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/monitoring/prometheus:/etc/prometheus:ro" --entrypoint promtool \
  prom/prometheus:v2.55.1 check config /etc/prometheus/prometheus.yml
```

Expected:
- 5 tests PASS
- `compose-ok`
- promtool: `SUCCESS: /etc/prometheus/prometheus.yml is valid prometheus config file syntax`

- [ ] **Step 5: Bring the stack up once and check the wiring**

```bash
docker compose --profile monitoring up -d --build
curl -s http://127.0.0.1:9090/api/v1/targets | python -c "import json,sys; t=json.load(sys.stdin)['data']['activeTargets']; print([(x['labels']['job'], x['health']) for x in t])"
. ./.env; curl -s -u "admin:${GRAFANA_ADMIN_PASSWORD:-admin}" http://127.0.0.1:3000/api/datasources/uid/weir-pg/health
curl -s -u "admin:${GRAFANA_ADMIN_PASSWORD:-admin}" http://127.0.0.1:3000/api/datasources/uid/weir-prom/health
docker compose --profile monitoring stop
```

Expected:
- `[('weir', 'up')]`
- both health calls return `"status":"OK"`

If the Postgres data source type is rejected (an older plugin id), switch `type` to `postgres` and record a ruling.

- [ ] **Step 6: Commit and push**

```bash
git add docker-compose.yml .env.example monitoring/ services/weir/tests/test_compose.py .github/workflows/tests.yml
git commit -m "feat(monitoring): Prometheus and Grafana services (opt-in profile), provisioning, Weir on localhost"
git push origin phase-4 && git push origin phase-4:main
```

---

### Task 5: Alert rules and promtool tests

**Files:**
- Modify: `monitoring/prometheus/alerts.yml`
- Create: `monitoring/prometheus/alerts_test.yml`
- Modify: `.github/workflows/tests.yml` (add the `test rules` step)

**Interfaces:**
- Consumes: the metric names from Task 1.
- Produces: alert names `WeirDown`, `HighErrorRate`, `HighLatencyP95`, `ModelFallbacks`, `HighEscalationRate`, `CacheHitRateDrop`, `CostAboveBaseline` and `BackgroundWorkLost`. Each has a `severity` label and a static `summary` annotation.

- [ ] **Step 1: Write the failing promtool tests**

Create `monitoring/prometheus/alerts_test.yml`:

```yaml
# promtool unit tests for alerts.yml (Phase 4 addendum §6). Run:
#   docker run --rm -v "$PWD/monitoring/prometheus:/etc/prometheus:ro" --entrypoint promtool \
#     prom/prometheus:v2.55.1 test rules /etc/prometheus/alerts_test.yml
rule_files: [alerts.yml]
evaluation_interval: 1m

tests:
  # --- WeirDown ---------------------------------------------------------------------------
  - interval: 1m
    input_series:
      - series: 'up{job="weir", instance="weir:8000"}'
        values: '0x5'
    alert_rule_test:
      - eval_time: 3m
        alertname: WeirDown
        exp_alerts:
          - exp_labels: {severity: critical, job: weir, instance: "weir:8000"}
            exp_annotations: {summary: "Weir is down: Prometheus cannot scrape weir:8000/metrics"}
  - interval: 1m
    input_series:
      - series: 'up{job="weir", instance="weir:8000"}'
        values: '1x5'
    alert_rule_test:
      - {eval_time: 3m, alertname: WeirDown, exp_alerts: []}

  # --- HighErrorRate ----------------------------------------------------------------------
  - interval: 1m
    input_series:   # 10 ok + 2 errors per minute = 17% errors
      - series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}'
        values: '0+10x30'
      - series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="error"}'
        values: '0+2x30'
    alert_rule_test:
      - eval_time: 20m
        alertname: HighErrorRate
        exp_alerts:
          - exp_labels: {severity: critical}
            exp_annotations: {summary: "More than 5% of Weir requests are failing"}
  - interval: 1m
    input_series:   # 50% errors but only ~4 requests per 10 min: below the traffic guard
      - series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}'
        values: '0+0.2x30'
      - series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="error"}'
        values: '0+0.2x30'
    alert_rule_test:
      - {eval_time: 20m, alertname: HighErrorRate, exp_alerts: []}

  # --- HighLatencyP95 ---------------------------------------------------------------------
  - interval: 1m
    input_series:   # every request lands in the (4 s, 8 s] bucket
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="1"}', values: '0x40'}
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="4"}', values: '0x40'}
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="8"}', values: '0+10x40'}
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="+Inf"}', values: '0+10x40'}
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}', values: '0+10x40'}
    alert_rule_test:
      - eval_time: 30m
        alertname: HighLatencyP95
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "Weir p95 latency is above 4 s"}
  - interval: 1m
    input_series:   # every request under 1 s
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="1"}', values: '0+10x40'}
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="4"}', values: '0+10x40'}
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="8"}', values: '0+10x40'}
      - {series: 'weir_request_latency_seconds_bucket{cache_status="miss", route="large", le="+Inf"}', values: '0+10x40'}
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}', values: '0+10x40'}
    alert_rule_test:
      - {eval_time: 30m, alertname: HighLatencyP95, exp_alerts: []}

  # --- ModelFallbacks ---------------------------------------------------------------------
  - interval: 1m
    input_series:
      - series: 'weir_fallbacks_total{routed_tier="large"}'
        values: '0 0 0 1 1 1 1'
    alert_rule_test:
      - eval_time: 4m
        alertname: ModelFallbacks
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "A model tier is failing and Weir is falling back to the other tier"}
  - interval: 1m
    input_series:
      - series: 'weir_fallbacks_total{routed_tier="large"}'
        values: '0x6'
    alert_rule_test:
      - {eval_time: 4m, alertname: ModelFallbacks, exp_alerts: []}

  # --- HighEscalationRate -----------------------------------------------------------------
  - interval: 1m
    input_series:   # 2 small-routed per minute, half escalated
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="small", status="ok"}', values: '0+2x60'}
      - {series: 'weir_escalations_total', values: '0+1x60'}
    alert_rule_test:
      - eval_time: 50m
        alertname: HighEscalationRate
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "More than 20% of small-model answers are being escalated"}
  - interval: 1m
    input_series:   # 50% escalated, but only ~6 small-routed requests per 30 min
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="small", status="ok"}', values: '0+0.2x60'}
      - {series: 'weir_escalations_total', values: '0+0.1x60'}
    alert_rule_test:
      - {eval_time: 50m, alertname: HighEscalationRate, exp_alerts: []}

  # --- CacheHitRateDrop -------------------------------------------------------------------
  - interval: 1m
    input_series:   # 6 h at 90% hits, then 30 min at 10%
      - {series: 'weir_requests_total{namespace="p", cache_status="hit", route="none", status="ok"}', values: '0+9x360 3241+1x30'}
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}', values: '0+1x360 361+9x30'}
    alert_rule_test:
      - eval_time: 390m
        alertname: CacheHitRateDrop
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "Cache hit rate fell below half its 6-hour average"}
  - interval: 1m
    input_series:   # steady 90% hits
      - {series: 'weir_requests_total{namespace="p", cache_status="hit", route="none", status="ok"}', values: '0+9x390'}
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}', values: '0+1x390'}
    alert_rule_test:
      - {eval_time: 390m, alertname: CacheHitRateDrop, exp_alerts: []}

  # --- CostAboveBaseline ------------------------------------------------------------------
  - interval: 1m
    input_series:   # $0.0002 per request vs the $0.0000988 baseline
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}', values: '0+10x120'}
      - {series: 'weir_cost_usd_total{namespace="p"}', values: '0+0.002x120'}
    alert_rule_test:
      - eval_time: 100m
        alertname: CostAboveBaseline
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "Cost per request is above the always-large baseline"}
  - interval: 1m
    input_series:   # $0.00005 per request: well under
      - {series: 'weir_requests_total{namespace="p", cache_status="miss", route="large", status="ok"}', values: '0+10x120'}
      - {series: 'weir_cost_usd_total{namespace="p"}', values: '0+0.0005x120'}
    alert_rule_test:
      - {eval_time: 100m, alertname: CostAboveBaseline, exp_alerts: []}

  # --- BackgroundWorkLost -----------------------------------------------------------------
  - interval: 1m
    input_series:
      - {series: 'weir_log_rows_dropped_total{job="weir"}', values: '0 0 0 5 5 5'}
      - {series: 'weir_cache_jobs_failed_total{job="weir"}', values: '0x5'}
    alert_rule_test:
      - eval_time: 4m
        alertname: BackgroundWorkLost
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "Weir dropped or failed background work (log rows or cache jobs)"}
  - interval: 1m
    input_series:
      - {series: 'weir_log_rows_dropped_total{job="weir"}', values: '0x5'}
      - {series: 'weir_cache_jobs_failed_total{job="weir"}', values: '0x5'}
    alert_rule_test:
      - {eval_time: 4m, alertname: BackgroundWorkLost, exp_alerts: []}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/monitoring/prometheus:/etc/prometheus:ro" --entrypoint promtool \
  prom/prometheus:v2.55.1 test rules /etc/prometheus/alerts_test.yml
```

Expected: FAIL. Each firing case reports `expected ... got []`, because `alerts.yml` has no rules yet.

- [ ] **Step 3: Implement the rules**

Replace `monitoring/prometheus/alerts.yml`:

```yaml
# Weir alert rules (Phase 4 addendum §5). Thresholds come from measured Phase 1-3 runs. Every rate rule has a
# minimum-traffic guard, so an idle machine never alerts. Shown in Grafana and on Prometheus /alerts only (D42).
groups:
  - name: weir
    rules:
      - alert: WeirDown
        expr: up{job="weir"} == 0
        for: 1m
        labels: {severity: critical}
        annotations: {summary: "Weir is down: Prometheus cannot scrape weir:8000/metrics"}

      - alert: HighErrorRate   # every measured run had 0 errors
        expr: |
          sum(increase(weir_requests_total{status!="ok"}[10m])) / sum(increase(weir_requests_total[10m])) > 0.05
          and sum(increase(weir_requests_total[10m])) >= 10
        for: 5m
        labels: {severity: critical}
        annotations: {summary: "More than 5% of Weir requests are failing"}

      - alert: HighLatencyP95   # normal p95 is 1.1-3.5 s; the 2026-10-05 Groq slowdown reached 7.2 s
        expr: |
          histogram_quantile(0.95, sum by (le) (rate(weir_request_latency_seconds_bucket[10m]))) > 4
          and sum(increase(weir_requests_total[10m])) >= 10
        for: 10m
        labels: {severity: warning}
        annotations: {summary: "Weir p95 latency is above 4 s"}

      - alert: ModelFallbacks   # would have caught both 2026-10-05 incidents
        expr: sum(increase(weir_fallbacks_total[5m])) > 0
        labels: {severity: warning}
        annotations: {summary: "A model tier is failing and Weir is falling back to the other tier"}

      - alert: HighEscalationRate   # live rate is 0%
        expr: |
          sum(increase(weir_escalations_total[30m])) / sum(increase(weir_requests_total{route="small"}[30m])) > 0.20
          and sum(increase(weir_requests_total{route="small"}[30m])) >= 10
        for: 10m
        labels: {severity: warning}
        annotations: {summary: "More than 20% of small-model answers are being escalated"}

      - alert: CacheHitRateDrop   # usually a kb_version change or an embedding fault
        expr: |
          (sum(increase(weir_requests_total{cache_status="hit"}[15m])) / sum(increase(weir_requests_total[15m])))
            < 0.5 * (sum(increase(weir_requests_total{cache_status="hit"}[6h])) / sum(increase(weir_requests_total[6h])))
          and sum(increase(weir_requests_total[15m])) >= 20
        for: 15m
        labels: {severity: warning}
        annotations: {summary: "Cache hit rate fell below half its 6-hour average"}

      - alert: CostAboveBaseline   # baseline v4: $0.0988 per 1,000 requests
        expr: |
          sum(increase(weir_cost_usd_total[1h])) / sum(increase(weir_requests_total[1h])) > 0.0000988
          and sum(increase(weir_requests_total[1h])) >= 20
        for: 15m
        labels: {severity: warning}
        annotations: {summary: "Cost per request is above the always-large baseline"}

      - alert: BackgroundWorkLost   # backlog M7: these losses used to be silent
        expr: sum(increase({__name__=~"weir_(log_rows|cache_jobs)_(dropped|failed)_total"}[10m])) > 0
        labels: {severity: warning}
        annotations: {summary: "Weir dropped or failed background work (log rows or cache jobs)"}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the same promtool command as Step 2.

Expected: `SUCCESS`.

If a case fails only on timing (for example `for` not yet satisfied at `eval_time`), move that case's `eval_time` later. Never loosen a rule to make a test pass, and record a ruling for any change. Then re-run `promtool check config` from Task 4. Expected: `SUCCESS` (the rule file is now parsed too).

- [ ] **Step 5: Add the CI step**

Append to the `monitoring` job in `.github/workflows/tests.yml`:

```yaml
      - name: promtool test rules
        run: >-
          docker run --rm -v "$PWD/monitoring/prometheus:/etc/prometheus:ro" --entrypoint promtool
          prom/prometheus:v2.55.1 test rules /etc/prometheus/alerts_test.yml
```

- [ ] **Step 6: Commit and push**

```bash
git add monitoring/prometheus/alerts.yml monitoring/prometheus/alerts_test.yml .github/workflows/tests.yml
git commit -m "feat(monitoring): 8 alert rules from measured thresholds, promtool unit tests in CI"
git push origin phase-4 && git push origin phase-4:main
```

Then check CI: `gh run list --limit 2`. Expected: both jobs succeed.

---

### Task 6: Dashboard (builder, generated JSON, query tests)

**Files:**
- Create: `monitoring/grafana/build_dashboard.py`
- Create (generated): `monitoring/grafana/dashboards/weir.json`, then delete `.gitkeep`
- Create: `services/weir/tests/test_dashboard.py`

**Interfaces:**
- Consumes:
  - data source UIDs `weir-pg` / `weir-prom` (Task 4)
  - metric names (Task 1) and alert names (Task 5)
  - `weir_reader` (Task 3)
- Produces:
  - `build_dashboard.build() -> dict`, and `python monitoring/grafana/build_dashboard.py` writes `weir.json`
  - the dashboard uid is **`weir`** (its URL is `/d/weir/weir`)
  - template variables are `config` and `namespace`
  - **the only Grafana macros used in SQL are `$__timeFilter(<col>)` and `$__timeGroupAlias(<col>, '1h')`; the only variables are `$config` and `$namespace`.** The test's expander and the live check rely on this.

- [ ] **Step 1: Write the failing tests**

Create `services/weir/tests/test_dashboard.py`:

```python
"""The Grafana dashboard's queries (Phase 4 addendum §6). Every Postgres panel query runs as weir_reader against a
seeded database and must return rows; Prometheus expressions may only use metrics Weir really exposes."""
import json
import re
import runpy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from prometheus_client import CollectorRegistry, generate_latest

from weir.metrics.prometheus import LossCollector, WeirMetrics

from .conftest import REPO

DASHBOARD = REPO / "monitoring" / "grafana" / "dashboards" / "weir.json"
BUILDER = REPO / "monitoring" / "grafana" / "build_dashboard.py"
ALERTS = REPO / "monitoring" / "prometheus" / "alerts.yml"


def _dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def _postgres_queries() -> list[tuple[str, str]]:
    d = _dashboard()
    out = [(f"variable {v['name']}", v["query"]) for v in d["templating"]["list"]
           if v.get("datasource", {}).get("uid") == "weir-pg"]
    for panel in d["panels"]:
        for t in panel.get("targets", []):
            if t.get("datasource", {}).get("uid") == "weir-pg":
                out.append((panel["title"], t["rawSql"]))
    return out


def _prometheus_exprs() -> list[str]:
    return [t["expr"] for p in _dashboard()["panels"] for t in p.get("targets", [])
            if t.get("datasource", {}).get("uid") == "weir-prom"]


def expand(sql: str) -> str:
    sql = re.sub(r"\$__timeFilter\(([\w.]+)\)", r"\1 between '2000-01-01' and '2100-01-01'", sql)
    sql = re.sub(r"\$__timeGroupAlias\(([\w.]+),\s*'[^']*'\)", r"date_trunc('hour', \1) as time", sql)
    sql = sql.replace("$config", "'full','baseline','dev'").replace("$namespace", "'weir-general/en/public'")
    assert "$" not in sql, f"unexpanded macro or variable in: {sql}"
    return sql


PUB = "weir-general/en/public"


@pytest.fixture
def seeded_reader(migrated_db_url):
    """Rows covering every panel: hit, small, large, bypass, escalation, fallback, error, a near miss, a Phase-1
    style row with NULL router columns (Review Focus 3), and a thumbs-down."""
    now = datetime.now(UTC)
    rows = [
        # (config, cache_status, route, status, similarity, route_reason, grounding_passed, grounding_reason,
        #  escalated, bypass_reason, cost, counterfactual, latency)
        ("full", "hit", "none", "ok", 0.97, None, None, None, False, None, "0", "0.0004", 20),
        ("full", "miss", "small", "ok", 0.85, "simple", True, None, False, None, "0.0002", "0.0004", 700),
        ("full", "miss", "small", "ok", 0.60, "simple", True, None, True, None, "0.0006", "0.0004", 1500),
        ("full", "miss", "large", "ok", None, "default_large+fallback", True, None, False, None, "0.0004", "0.0004", 900),
        ("full", "bypass", "large", "ok", None, "clinical", False, "low_overlap", False, "clinical", "0.0004", "0.0004", 800),
        ("full", "miss", "large", "error", None, "default_large", None, None, False, None, "0", "0", 3000),
        ("baseline", "bypass", "large", "ok", None, "kill_switch", True, None, False, "cache_disabled", "0.0004", "0.0004", 750),
        ("dev", "miss", "large", "ok", 0.40, None, None, None, False, None, "0.0004", "0.0004", 650),
    ]
    ids = []
    with psycopg.connect(migrated_db_url) as conn:
        for i, (cfg, cs, route, status, sim, rr, gp, gr, esc, br, cost, cf, lat) in enumerate(rows):
            rid = uuid4()
            ids.append(rid)
            conn.execute(
                "insert into weir.request_log (request_id, ts, namespace, cache_status, bypass_reason, similarity, "
                "route, route_reason, escalated, model_calls, grounding_passed, grounding_reason, latency_total_ms, "
                "latency_embed_ms, latency_cache_ms, latency_retrieval_ms, latency_llm_ms, cost_usd, "
                "counterfactual_cost_usd, status, query_hash, config_label) values "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (rid, now - timedelta(hours=i), PUB, cs, br, sim, route, rr, esc, 0 if cs == "hit" else 1, gp, gr,
                 lat, 10, 2, 30, None if cs == "hit" else lat - 50, Decimal(cost), Decimal(cf), status, "h" * 64, cfg))
        conn.execute("insert into weir.feedback (request_id, rating) values (%s, -1)", (ids[1],))
    with psycopg.connect(migrated_db_url.replace("weir:weir@", "weir_reader:weir_reader@", 1)) as reader:
        yield reader


@pytest.mark.db
@pytest.mark.parametrize(("title", "sql"), _postgres_queries())
def test_every_postgres_query_runs_as_weir_reader_and_returns_rows(seeded_reader, title, sql):
    rows = seeded_reader.execute(expand(sql)).fetchall()
    assert rows, f"panel '{title}' returned no rows on the seeded data"


def test_dashboard_json_matches_the_builder():
    built = runpy.run_path(str(BUILDER))["build"]()
    assert built == _dashboard(), "weir.json is stale: run `python monitoring/grafana/build_dashboard.py`"


def test_dashboard_basics():
    d = _dashboard()
    assert d["uid"] == "weir" and d["time"] == {"from": "now-30d", "to": "now"}
    assert [v["name"] for v in d["templating"]["list"]] == ["config", "namespace"]
    assert all(v["multi"] and v["includeAll"] for v in d["templating"]["list"])
    titles = [p["title"] for p in d["panels"]]
    for required in ("Estimated savings", "Configuration comparison", "Similarity: hits and near misses",
                     "Latency by path", "Route mix over time", "Firing alerts", "Answer quality"):
        assert required in titles, required
    assert len(titles) == len(set(titles))


def test_prometheus_queries_only_use_metrics_weir_exposes():
    class Q:
        dropped = failed = 0

    registry = CollectorRegistry()
    WeirMetrics(registry, "dev")
    registry.register(LossCollector({"log_rows": Q(), "cache_jobs": Q()}))
    exposed = set(re.findall(r"^# TYPE (\w+)", generate_latest(registry).decode(), re.M))
    exposed |= {f"{n}_total" for n in exposed} | {f"{n}_bucket" for n in exposed} | {"up", "ALERTS"}
    used = set()
    for text in [*_prometheus_exprs(), ALERTS.read_text(encoding="utf-8")]:
        used |= set(re.findall(r"\b(weir_\w+|up|ALERTS)\b", text))
    regex_names = {"weir_log_rows_dropped_total", "weir_log_rows_failed_total",
                   "weir_cache_jobs_dropped_total", "weir_cache_jobs_failed_total"}
    assert regex_names <= exposed
    unknown = {n for n in used if n not in exposed and not n.startswith("weir_(")}
    assert not unknown, f"queries reference metrics Weir doesn't expose: {sorted(unknown)}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose up -d postgres
cd services/weir && uv run pytest -q tests/test_dashboard.py
```

Expected: an ERROR at collection, `FileNotFoundError: ... weir.json`.

- [ ] **Step 3: Implement the builder**

Create `monitoring/grafana/build_dashboard.py`:

```python
"""Builds monitoring/grafana/dashboards/weir.json (Phase 4 addendum §4). Stdlib only.

This file is the source of truth for every panel: edit it, then run
    python monitoring/grafana/build_dashboard.py
The test suite checks the JSON is up to date and runs every Postgres query as the read-only user.
Only these Grafana macros are used: $__timeFilter(col), $__timeGroupAlias(col, '1h'); variables: $config, $namespace.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards" / "weir.json"
PG = {"type": "grafana-postgresql-datasource", "uid": "weir-pg"}
PROM = {"type": "prometheus", "uid": "weir-prom"}
F = "$__timeFilter(ts) and config_label in ($config) and namespace in ($namespace)"
LOG = "from weir.request_log where " + F

_id = 0


def _next_id() -> int:
    global _id
    _id += 1
    return _id


def _sql(sql: str, fmt: str = "table") -> dict:
    return {"refId": "A", "datasource": PG, "rawSql": " ".join(sql.split()), "format": fmt, "rawQuery": True,
            "editorMode": "code"}


def _prom(expr: str, legend: str = "") -> dict:
    return {"refId": "A", "datasource": PROM, "expr": expr, "legendFormat": legend, "range": True}


def panel(kind: str, title: str, target: dict, x: int, y: int, w: int, h: int, unit: str = "short",
          decimals: int | None = None, options: dict | None = None, overrides: list | None = None,
          time_from: str | None = None, description: str = "") -> dict:
    defaults: dict = {"unit": unit}
    if decimals is not None:
        defaults["decimals"] = decimals
    p = {"id": _next_id(), "type": kind, "title": title, "description": description, "datasource": target["datasource"],
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": [target],
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []}, "options": options or {}}
    if time_from:
        p["timeFrom"] = time_from
    return p


def row(title: str, y: int) -> dict:
    return {"id": _next_id(), "type": "row", "title": title, "collapsed": False, "panels": [],
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}}


STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "none",
        "graphMode": "none", "textMode": "value", "justifyMode": "center"}


def stat(title: str, sql: str, x: int, y: int, unit: str = "short", decimals: int | None = None,
         description: str = "") -> dict:
    return panel("stat", title, _sql(sql), x, y, 3, 4, unit, decimals, STAT, description=description)


def percent_columns(*names: str) -> list:
    return [{"matcher": {"id": "byName", "options": n},
             "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1}]} for n in names]


def build() -> dict:
    global _id
    _id = 0
    panels = [
        row("Headline", 0),
        stat("Requests", f"select count(*) as \"Requests\" {LOG}", 0, 1),
        stat("Cost per 1,000 requests",
             f"select coalesce(1000 * sum(cost_usd) / nullif(count(*), 0), 0) as \"Cost per 1,000\" {LOG}",
             3, 1, "currencyUSD", 4, "List prices; actual spend is $0 on free tiers"),
        stat("Estimated savings",
             f"select coalesce(sum(counterfactual_cost_usd - cost_usd), 0) as \"Saved\" {LOG}", 6, 1,
             "currencyUSD", 4, "Counterfactual (no cache, always the large model) minus actual cost"),
        stat("Savings %",
             f"select coalesce(1 - sum(cost_usd) / nullif(sum(counterfactual_cost_usd), 0), 0) as \"Saved\" {LOG}",
             9, 1, "percentunit", 1),
        stat("Cache hit rate", f"select coalesce(avg((cache_status = 'hit')::int), 0) as \"Hit rate\" {LOG}",
             12, 1, "percentunit", 1),
        stat("Routed small",
             f"select coalesce(sum((route = 'small')::int)::float / nullif(sum((cache_status <> 'hit')::int), 0), 0)"
             f" as \"Routed small\" {LOG}", 15, 1, "percentunit", 1, "Small-model requests / non-hit requests"),
        stat("Escalation rate",
             f"select coalesce(sum(escalated::int)::float / nullif(sum((route = 'small')::int), 0), 0)"
             f" as \"Escalated\" {LOG}", 18, 1, "percentunit", 1, "Escalated / small-routed requests"),
        stat("Error rate", f"select coalesce(avg((status <> 'ok')::int), 0) as \"Errors\" {LOG}",
             21, 1, "percentunit", 2),

        row("Comparison", 5),
        panel("table", "Configuration comparison", _sql(f"""
            select config_label as "Configuration", count(*) as "Requests",
                   avg((cache_status = 'hit')::int) as "Cache hit rate",
                   sum((route = 'small')::int)::float / nullif(sum((cache_status <> 'hit')::int), 0) as "Routed small",
                   1000 * sum(cost_usd) / count(*) as "Cost per 1,000",
                   percentile_cont(0.5) within group (order by latency_total_ms) as "p50 (ms)",
                   percentile_cont(0.95) within group (order by latency_total_ms) as "p95 (ms)",
                   1 - sum(cost_usd) / nullif(sum(counterfactual_cost_usd), 0) as "Saved",
                   avg((status <> 'ok')::int) as "Error rate"
            {LOG} group by config_label order by "Cost per 1,000" desc"""), 0, 6, 24, 7,
              overrides=percent_columns("Cache hit rate", "Routed small", "Saved", "Error rate")
              + [{"matcher": {"id": "byName", "options": "Cost per 1,000"},
                  "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 4}]}],
              description="The four-way ablation, live from the request log"),

        row("Where requests go", 13),
        panel("timeseries", "Route mix over time", _sql(f"""
            select $__timeGroupAlias(ts, '1h'), sum((cache_status = 'hit')::int) as "cache hit",
                   sum((cache_status <> 'hit' and route = 'small')::int) as "small model",
                   sum((cache_status <> 'hit' and route = 'large')::int) as "large model"
            {LOG} group by 1 order by 1""", "time_series"), 0, 14, 12, 8,
              options={"legend": {"displayMode": "list", "placement": "bottom"}},
              overrides=[]),
        panel("piechart", "Cache status",
              _sql(f"select cache_status as \"Status\", count(*) as \"Requests\" {LOG} group by 1 order by 1"),
              12, 14, 6, 8, options={"reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": ""},
                                     "legend": {"displayMode": "list", "placement": "right"}}),
        panel("table", "Top bypass reasons", _sql(f"""
            select coalesce(bypass_reason, '(none)') as "Bypass reason", count(*) as "Requests"
            {LOG} and cache_status = 'bypass' group by 1 order by 2 desc limit 10"""), 18, 14, 6, 8),

        row("Latency", 22),
        panel("table", "Latency by path", _sql(f"""
            select case when cache_status = 'hit' then 'cache hit' else route || ' model' end as "Path",
                   count(*) as "Requests",
                   percentile_cont(0.5) within group (order by latency_total_ms) as "p50 (ms)",
                   percentile_cont(0.95) within group (order by latency_total_ms) as "p95 (ms)",
                   percentile_cont(0.99) within group (order by latency_total_ms) as "p99 (ms)"
            {LOG} and status = 'ok' and (cache_status = 'hit' or route in ('small', 'large'))
            group by 1 order by 1"""), 0, 23, 12, 7),
        panel("bargauge", "Average time per stage (non-hit requests)", _sql(f"""
            select avg(latency_embed_ms) as "Embed", avg(latency_cache_ms) as "Cache lookup",
                   avg(latency_retrieval_ms) as "Retrieval", avg(latency_llm_ms) as "Model"
            {LOG} and cache_status <> 'hit'"""), 12, 23, 12, 7, "ms", 0,
              options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                       "orientation": "horizontal", "displayMode": "basic"}),

        row("Cache and router health", 30),
        panel("barchart", "Similarity: hits and near misses", _sql(f"""
            select to_char(floor(similarity * 100) / 100, 'FM0.00') as "Similarity",
                   sum((cache_status = 'hit')::int) as "hits", sum((cache_status <> 'hit')::int) as "near misses"
            {LOG} and similarity >= 0.80 group by 1 order by 1"""), 0, 31, 12, 8,
              options={"xField": "Similarity", "stacking": "normal", "legend": {"displayMode": "list",
                                                                                 "placement": "bottom"}},
              description="Is the 0.90 threshold sensible? Near misses are lookups that scored 0.80+ but didn't hit"),
        panel("table", "Route reasons", _sql(f"""
            select route_reason as "Route reason", count(*) as "Requests"
            {LOG} and route_reason is not null group by 1 order by 2 desc"""), 12, 31, 6, 8),
        panel("table", "Grounding results", _sql(f"""
            select case when grounding_passed then 'passed' else coalesce(grounding_reason, 'failed') end
                   as "Grounding", count(*) as "Requests"
            {LOG} and grounding_passed is not null group by 1 order by 2 desc"""), 18, 31, 6, 8),
        panel("timeseries", "Fallbacks and escalations over time", _sql(f"""
            select $__timeGroupAlias(ts, '1h'), sum((route_reason like '%+fallback')::int) as "fallbacks",
                   sum(escalated::int) as "escalations"
            {LOG} group by 1 order by 1""", "time_series"), 0, 39, 18, 7),
        panel("stat", "Thumbs down", _sql("""
            select count(*) as "Thumbs down" from weir.feedback f join weir.request_log r on r.request_id = f.request_id
            where f.rating = -1 and $__timeFilter(r.ts) and r.config_label in ($config)
              and r.namespace in ($namespace)"""), 18, 39, 6, 7, options=STAT),

        row("Live (Prometheus, last 15 minutes)", 46),
        panel("timeseries", "Requests per second", _prom("sum(rate(weir_requests_total[1m]))", "requests/s"),
              0, 47, 6, 7, "reqps", time_from="15m"),
        panel("timeseries", "Live p95 latency",
              _prom("histogram_quantile(0.95, sum by (le) (rate(weir_request_latency_seconds_bucket[5m])))", "p95"),
              6, 47, 6, 7, "s", time_from="15m"),
        panel("timeseries", "Errors per second",
              _prom('sum(rate(weir_requests_total{status!="ok"}[1m])) or vector(0)', "errors/s"),
              12, 47, 6, 7, "reqps", time_from="15m"),
        panel("stat", "Lost background work",
              _prom('sum({__name__=~"weir_(log_rows|cache_jobs)_(dropped|failed)_total"}) or vector(0)'),
              18, 47, 3, 7, options=STAT, time_from="15m",
              description="Dropped or failed log rows and cache jobs since Weir started"),
        panel("stat", "Firing alerts", _prom('sum(ALERTS{alertstate="firing"}) or vector(0)'),
              21, 47, 3, 7, options=STAT, time_from="15m"),
        panel("stat", "Running configuration", _prom("weir_info", "{{config_label}}"), 0, 54, 6, 4,
              options={**STAT, "textMode": "name"}, time_from="15m"),
        {"id": _next_id(), "type": "text", "title": "Answer quality", "gridPos": {"x": 6, "y": 54, "w": 18, "h": 4},
         "options": {"mode": "markdown", "content":
                     "Answer quality (judge score, key facts) is measured by the eval suite, not live traffic. "
                     "See [docs/results/summary.md](https://github.com/yatinannam/weir/blob/main/docs/results/"
                     "summary.md) for the four-way ablation with quality."}},
    ]
    variables = [
        {"name": "config", "label": "Configuration", "type": "query", "datasource": PG, "refresh": 1,
         "query": "select distinct config_label from weir.request_log where config_label is not null order by 1",
         "definition": "config_label values", "multi": True, "includeAll": True,
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}},
        {"name": "namespace", "label": "Namespace", "type": "query", "datasource": PG, "refresh": 1,
         "query": "select distinct namespace from weir.request_log order by 1",
         "definition": "namespace values", "multi": True, "includeAll": True,
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]}},
    ]
    return {"uid": "weir", "title": "Weir", "tags": ["weir"], "timezone": "browser", "editable": False,
            "schemaVersion": 39, "refresh": "30s", "time": {"from": "now-30d", "to": "now"},
            "templating": {"list": variables}, "panels": panels}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
```

Generate the JSON and remove the placeholder:

```bash
python monitoring/grafana/build_dashboard.py && rm -f monitoring/grafana/dashboards/.gitkeep
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/weir && uv run pytest -q tests/test_dashboard.py`

Expected: PASS. That's one parametrized case per Postgres query (2 variables + 19 SQL panels), plus 3 other tests.

If a query fails as `weir_reader`, fix the SQL in the builder (never grant more privileges), regenerate, and re-run.

- [ ] **Step 5: Run every suite**

```bash
cd services/weir && uv run pytest -q
cd ../hospital-rag && uv run pytest -q
cd ../../eval && uv run pytest -q
docker compose stop
```

Expected: all pass.

- [ ] **Step 6: Commit and push**

```bash
git add monitoring/grafana/build_dashboard.py monitoring/grafana/dashboards/ services/weir/tests/test_dashboard.py
git commit -m "feat(monitoring): Grafana dashboard (6 rows, config filter) from a tested builder"
git push origin phase-4 && git push origin phase-4:main
```

---

### Task 7: Live verification and screenshots

**Files:**
- Create: `monitoring/check_panels.py`, `monitoring/screenshot.py`
- Create: `docs/images/dashboard.png`, `docs/images/dashboard-headline.png`

**Interfaces:**
- Consumes:
  - the running stack (Tasks 1–6)
  - Grafana's HTTP API (`POST /api/ds/query`, basic auth `admin` / `$GRAFANA_ADMIN_PASSWORD`)
  - the dashboard JSON
- Produces:
  - a pass/fail report of every panel per configuration
  - the README screenshots

- [ ] **Step 1: Write the live check script**

Create `monitoring/check_panels.py`:

```python
"""Live check (Phase 4 addendum §7): run every dashboard panel through Grafana's query API and report empty ones.

Usage (stack up with --profile monitoring):
    GRAFANA_ADMIN_PASSWORD=... python monitoring/check_panels.py
Exit code 1 if any panel is empty for "All". Per-configuration results are printed: cache panels are legitimately
empty for configurations with the cache off (baseline, router_only).
"""
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

GRAFANA = "http://127.0.0.1:3000"
DASHBOARD = json.loads((Path(__file__).resolve().parent / "grafana" / "dashboards" / "weir.json")
                       .read_text(encoding="utf-8"))
AUTH = "Basic " + base64.b64encode(f"admin:{os.environ.get('GRAFANA_ADMIN_PASSWORD') or 'admin'}".encode()).decode()


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(GRAFANA + path, json.dumps(body).encode(),
                                 {"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _quote(values: list[str]) -> str:
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


def rows_for(target: dict, configs: list[str], namespaces: list[str]) -> int:
    q = {"refId": "A", "datasource": target["datasource"]}
    if "rawSql" in target:
        q |= {"rawSql": target["rawSql"].replace("$config", _quote(configs)).replace("$namespace", _quote(namespaces)),
              "format": target["format"], "rawQuery": True}
        span = ("now-30d", "now")
    else:
        q |= {"expr": target["expr"], "instant": True}
        span = ("now-15m", "now")
    frames = _post("/api/ds/query", {"queries": [q], "from": span[0], "to": span[1]})["results"]["A"].get("frames", [])
    return sum(len(f["data"]["values"][0]) if f["data"]["values"] else 0 for f in frames)


def distinct(sql: str) -> list[str]:
    res = _post("/api/ds/query", {"queries": [{"refId": "A", "datasource": {"uid": "weir-pg"}, "rawSql": sql,
                                               "format": "table", "rawQuery": True}], "from": "now-30d", "to": "now"})
    return [v for f in res["results"]["A"]["frames"] for v in f["data"]["values"][0]]


def main() -> int:
    configs = distinct("select distinct config_label from weir.request_log where config_label is not null order by 1")
    namespaces = distinct("select distinct namespace from weir.request_log order by 1")
    views = {"All": configs, **{c: [c] for c in ("baseline", "cache_only", "router_only", "full") if c in configs}}
    panels = [p for p in DASHBOARD["panels"] if p.get("targets")]
    empty_all = []
    print(f"{'panel':48s} " + " ".join(f"{v:>11s}" for v in views))
    for p in panels:
        counts = [rows_for(p["targets"][0], cfgs, namespaces) for cfgs in views.values()]
        print(f"{p['title'][:48]:48s} " + " ".join(f"{c:>11d}" for c in counts))
        if counts[0] == 0:
            empty_all.append(p["title"])
    print("\nempty for All:", empty_all or "none")
    return 1 if empty_all else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Start the stack and run the live replay** (about 80 model calls and 10–15 min; free)

```bash
docker compose --profile monitoring up -d --build
WEIR_ABLATION=full docker compose --profile monitoring up -d --force-recreate weir
cd eval && uv run --env-file ../.env python -m weir_eval run --config full \
  --workload datasets/workload-300-seed7.jsonl --no-judge --weir-url http://127.0.0.1:8000
```

Expected: `errors 0`. The cache may have expired since 2026-10-06 (TTL 24 h), so expect roughly 80 model calls rather than 20. This run is for monitoring only: don't judge it, and don't use it as a result.

- [ ] **Step 3: Check every panel**

```bash
cd .. && set -a && . ./.env && set +a && python monitoring/check_panels.py
curl -s http://127.0.0.1:9090/api/v1/rules | python -c "import json,sys; print([(r['name'], r['state']) for g in json.load(sys.stdin)['data']['groups'] for r in g['rules']])"
```

Expected:
- exit code 0 (no panel empty for All)
- for `baseline` and `router_only`, only the cache panels may show 0 rows ("Similarity", "Cache status" hits)
- all 8 rules listed, each `inactive`

If a panel is empty for All, fix it in the builder (and its test) before continuing.

- [ ] **Step 4: Capture screenshots** (Playwright, free)

Create `monitoring/screenshot.py`:

```python
"""Capture the Weir dashboard into docs/images/ (Phase 4 addendum §7). Free: Playwright's headless Chromium.

    uv run --with playwright python -m playwright install chromium     # once, ~150 MB
    GRAFANA_ADMIN_PASSWORD=... uv run --with playwright python monitoring/screenshot.py
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

GRAFANA = "http://127.0.0.1:3000"
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 2700}, device_scale_factor=1)
        page.goto(f"{GRAFANA}/login")
        page.fill('input[name="user"]', "admin")
        page.fill('input[name="password"]', os.environ.get("GRAFANA_ADMIN_PASSWORD") or "admin")
        page.click('button[type="submit"]')
        page.wait_for_url("**/?orgId=1**", timeout=30_000)
        page.goto(f"{GRAFANA}/d/weir/weir?orgId=1&from=now-30d&to=now&kiosk", wait_until="networkidle")
        page.wait_for_timeout(5_000)                       # let every panel finish rendering
        page.screenshot(path=str(OUT / "dashboard.png"), full_page=True)
        page.screenshot(path=str(OUT / "dashboard-headline.png"), clip={"x": 0, "y": 0, "width": 1600, "height": 560})
        browser.close()
    print(f"wrote {OUT / 'dashboard.png'} and {OUT / 'dashboard-headline.png'}")


if __name__ == "__main__":
    main()
```

Run it:

```bash
uv run --with playwright python -m playwright install chromium
uv run --with playwright python monitoring/screenshot.py
docker compose --profile monitoring stop
```

Then open both PNGs and check them:
- the panels are rendered, not "Loading" or "No data" for All
- there are no login screens
- the text is legible

If panels are still loading, raise the wait and re-run.

- [ ] **Step 5: Commit and push**

```bash
git add monitoring/check_panels.py monitoring/screenshot.py docs/images/dashboard.png docs/images/dashboard-headline.png
git commit -m "feat(monitoring): live panel check and Playwright screenshots of the dashboard"
git push origin phase-4 && git push origin phase-4:main
```

---

### Task 8: Docs, final review, close Phase 4

**Files:**
- Modify: `README.md`, `docs/decisions.md`, `docs/progress.md`, `docs/backlog.md`, `docs/README.md`
- Modify: memory `weir-project.md` (outside the repo)

- [ ] **Step 1: README**

1. **Architecture Mermaid diagram:** add `prometheus` and `grafana` nodes: `gw -- "GET /metrics" --> prometheus`, `prometheus --> grafana`, `pg -- "read-only (weir_reader)" --> grafana`.
2. **New "Monitoring" section after "Router"**, containing:
   - the embedded `docs/images/dashboard-headline.png`
   - one sentence per dashboard row
   - the alert table: name, fires when, severity
   - how to start it: `docker compose --profile monitoring up -d`, then open <http://127.0.0.1:3000> (user `admin`, password from `.env`) and <http://127.0.0.1:9090/alerts>
   - the full screenshot link `docs/images/dashboard.png`
3. **Smaller updates:**
   - Stack table: replace the "Planned" row's Prometheus + Grafana with real entries.
   - API table: add `GET /metrics`.
   - Layout block: add `monitoring/`.
   - Migrations: `001 init · 002 cache · 003 router · 004 monitoring`.
   - Test counts: run each suite and copy the numbers.
   - Status note: Phases 0–4 done; next is Phase 5.
   - Roadmap: Phase 4 `Done`.
   - No emojis.

- [ ] **Step 2: Decisions, backlog, progress, docs index**

- **`decisions.md`:** add rows for any ruling made during the build, numbered from D45.
- **`backlog.md`:** mark M7 resolved ("Phase 4: `weir_*_dropped_total`/`failed_total` on `/metrics`, `BackgroundWorkLost` alert").
- **`progress.md`:** add a "Phase 4 exit" section covering:
  - what was built
  - the live check result
  - the test counts
  - the screenshot paths
- **`docs/README.md`:** link the Phase 4 plan.

- [ ] **Step 3: Final whole-branch review**

1. Create the code-only diff: `git diff <phase-4 start>..HEAD -- services monitoring db docker-compose.yml .github`.
2. Dispatch one fresh reviewer on the most capable model, with this plan, the addendum and the Review Focus list.
3. Re-grade the findings by their effect on the user.
4. Fix Critical and Important findings test-first, one pass. Each fix gets a test that fails, then passes, plus a green suite.
5. Put Minor findings in `backlog.md`.
6. Ask the user about any genuine product decision the review raises.

- [ ] **Step 4: Commit, push, close**

```bash
git add README.md docs/
git commit -m "docs: Phase 4 closed: monitoring section, screenshots, decisions, progress"
git push origin phase-4 && git push origin phase-4:main
```

Then update the memory file `weir-project.md`: Phase 4 done (with its date) and next is Phase 5 (k6 load tests).

---

## Self-Review Notes

**Spec coverage** (addendum section → task):

| Addendum section | Task(s) |
| --- | --- |
| §1 D42–D44 | already logged |
| §2 components, localhost bindings, `weir_reader`, profile | 3, 4 |
| §3.1 `MetricsSink`, never fails, callback loss counters | 1, 2 |
| §3.2 every metric and the forbidden labels | 1 |
| §3 endpoint without auth, not logged | 2 |
| §4 variables, 30-day default, rows 1–6, quality text panel | 6 |
| §5 the 8 alerts with traffic guards | 5 |
| §6 sink, endpoint, migration, dashboard query and promtool tests, config check | 1, 2, 3, 4, 5, 6 |
| §7 live verification and screenshots | 7 |
| §8 docs | 8 |
| §9 out of scope | respected |

**Deliberate refinements of the addendum, to confirm in review:**
- **`weir_metrics_failed_total` is added**, so a metrics failure is visible (Review Focus 1).
- **A "Firing alerts" stat panel is added**, built on Prometheus's `ALERTS` series. It makes alert state visible on the dashboard itself, in addition to Grafana's alert list and Prometheus `/alerts`.
- **The live check requires data for "All" only.** Per-configuration views are printed but not failed, because cache panels are legitimately empty when the cache is off. This refines §7's "every panel ... for each configuration".
- **`GRAFANA_ADMIN_PASSWORD` falls back to `admin`**, because Compose interpolates disabled-profile services too. Grafana stays localhost-only.
