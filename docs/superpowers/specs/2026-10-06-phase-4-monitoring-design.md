# Weir Phase 4: Monitoring Design (addendum)

Date: 2026-10-06 · Author: Yatin Annam (with Claude Code)
Status: Draft for review

Builds on:
- [main design spec](2026-09-30-weir-design.md): §5 (architecture: `prometheus`, `grafana`), §9.1 (`GET /metrics`), §16 (Phase 4 row)
- [original spec](../../weir-original.md): "Metrics and dashboard", "Dashboard panels", "Alerts"
- Phase 3 results: [`router.md`](../../results/router.md) and [`summary.md`](../../results/summary.md). Alert thresholds come from these.

This addendum fixes the details the main spec leaves open for Phase 4. Where the two disagree, this document wins for Phase 4.

---

## 1. In plain terms

Weir already writes one row per request, but the only way to see the numbers today is to run a script. Phase 4 adds three things:

1. **A live dashboard** that shows what Weir is doing and saving, past and present.
2. **Alerts** that turn red when something goes wrong.
3. **A `/metrics` page** in Weir, so a standard monitoring tool (Prometheus) can follow it live.

Everything is free and self-hosted in Docker. It is the visual proof of the project: README screenshots and a 5-minute demo.

**User decisions (2026-10-06):**
- **D42:** alerts are shown inside Grafana only. No email, chat or other notifications.
- **D43:** the dashboard shows live traffic *and* every past run, with a configuration filter (`baseline` / `cache_only` / `router_only` / `full`).
- **D44:** data comes from both sources:
  - Postgres (the request log) for history and the configuration filter
  - Prometheus for live counters and alerts

---

## 2. Components and data flow

```
 weir :8000 ── GET /metrics ──▶ prometheus :9090 ──(alert rules)──┐
     │                                                             ▼
     └── request_log rows ──▶ postgres :5432 ──(read-only)──▶ grafana :3000
```

| Service | Image | Role |
| --- | --- | --- |
| `prometheus` | `prom/prometheus` (pinned version) | Scrapes `weir:8000/metrics` every 5 s. Keeps 15 days of data. Evaluates the alert rules every 30 s. |
| `grafana` | `grafana/grafana-oss` (pinned version) | One dashboard. Both data sources and the dashboard are **provisioned from files** in the repo; nothing is configured by clicking. |

**Repository layout** (new top-level `monitoring/` folder, replacing the main spec's `dashboards/` name):

```text
monitoring/
  prometheus/prometheus.yml           scrape config
  prometheus/alerts.yml               alert rules (§5)
  prometheus/alerts_test.yml          promtool unit tests for the rules
  grafana/provisioning/datasources/   Prometheus + Postgres (weir_reader)
  grafana/provisioning/dashboards/    dashboard provider
  grafana/dashboards/weir.json        the dashboard (§4)
```

**Security:**
- **Ports are localhost-only.** Prometheus is on `127.0.0.1:9090` and Grafana on `127.0.0.1:3000`.
- **Weir moves to localhost-only too.** Its port mapping changes from `8000:8000` to `127.0.0.1:8000:8000`, so the unauthenticated `/metrics` page is reachable only from this machine and the Docker network.
- **The Grafana admin password** comes from `.env` (`GRAFANA_ADMIN_PASSWORD`). Anonymous access is off.
- **Grafana reads Postgres as a new read-only user, `weir_reader`.** Migration `004_phase4_monitoring.sql` creates it with `SELECT` only, on:
  - `weir.request_log`
  - `weir.cache_entries`
  - `weir.model_prices`
  - `weir.feedback`

  Its password is local-only, the same approach as the existing `weir/weir` login: Postgres is bound to 127.0.0.1.

**RAM and opt-in:** Prometheus and Grafana together add about 250 MB. They sit behind a Compose profile:
- `docker compose --profile monitoring up -d` starts them
- a plain `docker compose up -d` stays as light as today

---

## 3. Weir metrics (`GET /metrics`)

### 3.1 How they are recorded

**`weir/metrics/prometheus.py`** adds a `MetricsSink` that wraps the existing `LogWriter`:

```python
class MetricsSink:            # implements LogSink
    def __init__(self, writer: LogSink, registry: CollectorRegistry): ...
    def submit(self, row: RequestLogRow) -> None:
        self._record(row)          # update counters from the finished row
        self._writer.submit(row)   # queue for Postgres, unchanged
```

- **Every request metric is derived from the same `RequestLogRow` that goes to Postgres**, so live and historical numbers cannot disagree.
- **Nothing else in the request path changes.**
- **A metrics failure is caught and counted, never raised.** As with the log writer, a monitoring fault must not fail a request.
- **The queue counters are read at scrape time**, through callback gauges on the existing `LogWriter.dropped`/`failed` and the cache `BackgroundQueue.dropped`/`failed` counters.

### 3.2 Metrics

| Metric | Type | Labels | Source |
| --- | --- | --- | --- |
| `weir_requests_total` | counter | `namespace`, `cache_status`, `route`, `status` | every row |
| `weir_request_latency_seconds` | histogram (buckets 0.01 … 30 s) | `cache_status`, `route` | `latency_total_ms` |
| `weir_cost_usd_total` | counter | `namespace` | `cost_usd` |
| `weir_counterfactual_cost_usd_total` | counter | `namespace` | `counterfactual_cost_usd` |
| `weir_model_calls_total` | counter | — | `model_calls` |
| `weir_escalations_total` | counter | — | `escalated` |
| `weir_fallbacks_total` | counter | `routed_tier` | `route_reason` ends in `+fallback` |
| `weir_grounding_total` | counter | `passed`, `reason` | `grounding_*` (non-hit rows that were generated) |
| `weir_log_rows_dropped_total`, `weir_log_rows_failed_total` | gauge (callback) | — | `LogWriter` |
| `weir_cache_jobs_dropped_total`, `weir_cache_jobs_failed_total` | gauge (callback) | — | cache `BackgroundQueue` (resolves backlog M7) |
| `weir_info` | gauge = 1 | `config_label` | config at startup |

**Never used as labels:**
- `request_id`, query text, similarity values and model output.
- **Why:** they would create unbounded series, and could leak text from sensitive namespaces.
- Per-request detail stays in the request log.

**Endpoint:** `GET /metrics` uses the standard Prometheus text format and needs no API key (main spec §9.1). It is exempt from tenant auth and isn't logged as a request.

---

## 4. Dashboard (`monitoring/grafana/dashboards/weir.json`)

**Variables:**
- `config`: multi-select over the distinct `config_label` values in the request log, with "All".
- `namespace`: multi-select.
- Time range: default "last 30 days", so every past run is visible.

**Data sources:**
- Rows 1–5 are **Postgres** SQL panels, filtered by `$config`, `$namespace` and the time range.
- Row 6 is **Prometheus**.

| Row | Panels |
| --- | --- |
| 1. Headline | Requests · cost per 1,000 · **estimated savings** ($ and %, `sum(counterfactual) − sum(cost)`) · cache hit rate · share routed small · escalation rate · error rate |
| 2. Configuration comparison | Table with one row per `config_label`: requests, hit rate, small share, cost per 1,000, p50, p95, savings %, errors. **This is the four-way ablation, live from the request log.** |
| 3. Where requests go | Route mix over time (hit / small / large, stacked) · cache status breakdown · top bypass reasons |
| 4. Latency | p50 / p95 / p99 by path (hit / small / large) · average time per stage (embed, cache, retrieval, LLM) |
| 5. Cache and router health | **Similarity histogram** for hits and near misses (0.80–0.90) · route reasons · grounding results · fallbacks over time · thumbs-down count |
| 6. Live (Prometheus, last 15 min) | Requests per second · live p95 · errors per second · lost background work · running `config_label` |

**Answer quality** (judge scores, key facts) is **not** on the dashboard. It comes from eval runs, not live traffic. A text panel links to `docs/results/summary.md` instead of showing a fake live quality number.

---

## 5. Alerts (`monitoring/prometheus/alerts.yml`)

Thresholds are set from measured Phase 1–3 runs, as the original spec requires. Every rate-based rule has a minimum-traffic guard, so an idle machine never alerts. Alerts appear in Grafana's alert view and on Prometheus's `/alerts` page (D42).

| Alert | Expression (sketch) | For | Severity | Why this threshold |
| --- | --- | --- | --- | --- |
| `WeirDown` | `up{job="weir"} == 0` | 1m | critical | — |
| `HighErrorRate` | errors / requests > 0.05 over 10m, with ≥ 10 requests | 5m | critical | Every measured run had 0 errors |
| `HighLatencyP95` | `histogram_quantile(0.95, …[10m]) > 4` | 10m | warning | Normal p95 is 1.1–3.5 s; the 2026-10-05 Groq slowdown reached 7.2 s |
| `ModelFallbacks` | `increase(weir_fallbacks_total[5m]) > 0` | 0m | warning | A model is failing; this would have caught both 2026-10-05 incidents |
| `HighEscalationRate` | escalations / small-routed requests > 0.20 over 30m, with ≥ 10 small-routed requests | 10m | warning | Live rate is 0%; a rise means the small model is over-trusted |
| `CacheHitRateDrop` | 15m hit rate < 0.5 × 6h hit rate, with ≥ 20 requests in 15m | 15m | warning | Usually a `kb_version` change or an embedding fault |
| `CostAboveBaseline` | 1h cost per request > 0.0000988 (baseline v4: $0.0988 per 1k), with ≥ 20 requests | 15m | warning | Full Weir measured 20–94% below baseline |
| `BackgroundWorkLost` | any increase in dropped or failed log rows or cache jobs over 10m | 0m | warning | Backlog M7: these losses are silent today |

---

## 6. Testing

| Test | What it proves |
| --- | --- |
| `MetricsSink` unit tests | Each row kind updates the right series with the right labels. The row kinds are: hit, small, large, escalated, fallback, grounding failure, error, timeout. The row is still forwarded to the writer. A metrics failure is swallowed and counted. No forbidden labels appear. |
| `/metrics` endpoint test | It serves the text format without an API key, includes the callback gauges and `weir_info`, and isn't logged as a request |
| Migration test | `004` applies. `weir_reader` can `SELECT` the four tables, but `INSERT`/`UPDATE`/`DELETE` and access to `rag.*` are refused. |
| **Dashboard query test** | Extracts every Postgres panel's SQL from `weir.json`, expands the Grafana macros and variables used, and runs each query as `weir_reader` against the seeded test database. A broken query fails CI. |
| **Alert rule tests** | `promtool test rules monitoring/prometheus/alerts_test.yml` checks that each of the 8 alerts fires on a synthetic series that should trigger it, and stays silent on one that shouldn't. It runs in CI through the pinned `prom/prometheus` image. |
| Config check | `promtool check config` on `prometheus.yml`, in CI |

---

## 7. Live verification (exit criterion: "every panel populated from real runs")

1. Start the stack with `--profile monitoring`.
2. Check that Prometheus shows the `weir` target as up, and that both Grafana data sources pass their health checks.
3. Run **one short live replay** under `full`: the 300-request workload.
   - It is mostly cache hits, so about 20 large-model calls (well within the free quota).
   - This fills the live (Prometheus) row.
   - The history rows are already filled from the 2,000+ past rows.
4. Check that **every panel shows data**, for `$config` = each of `baseline`, `cache_only`, `router_only`, `full`, and All. Each alert shows as "inactive" (green).
5. **Capture dashboard screenshots automatically** with Playwright's headless Chromium (free). A repeatable command writes PNGs to `docs/images/`, and the README embeds them.

---

## 8. Documentation

- **README:** a "Monitoring" section (how to start it, where to open it, the screenshot), the architecture diagram updated with Prometheus and Grafana, and the stack table.
- **`decisions.md`:** D42–D44 (above), plus any decisions made during the build.
- **`progress.md`:** a Phase 4 log entry.
- **`backlog.md`:** M7 marked resolved.
- **`docs/results/`:** unchanged. Phase 4 measures nothing new.

---

## 9. Out of scope

- **Alert notifications** (D42).
- **Auth on `/metrics`.** It is localhost/Docker-only instead.
- **Long-term metric storage** beyond 15 days, and **log aggregation** (Loki).
- **Load testing:** Phase 5. Its k6 runs will use this dashboard.
- **The demo chat page:** Phase 6.
- **The Phase 3 backlog minors (M12–M20)**, unless one blocks a panel.
