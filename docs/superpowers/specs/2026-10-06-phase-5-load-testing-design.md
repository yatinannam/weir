# Weir Phase 5: Load Testing Design (addendum)

Date: 2026-10-06 · Author: Yatin Annam (with Claude Code)
Status: Draft for review
Builds on:
- [Main design spec](2026-09-30-weir-design.md): §12 (load testing) and §16 (the Phase 5 row).
- [Original spec](../../weir-original.md): "Load testing" (setup, scenarios, what to measure, rigour rules, results template).
- Decisions D10 (k6 `constant-arrival-rate`), D11 (stub model for heavy load) and D16 (the baseline path).
- Phase 3 and 4 results: [`summary.md`](../../results/summary.md) and [`router.md`](../../results/router.md). The stub's timing and the 2 s budget come from these.

This addendum fixes the details the main spec leaves open for Phase 5. Where the two disagree, this document wins for Phase 5.

---

## 1. In plain terms

So far every latency number was measured one request at a time. Phase 5 measures Weir **under concurrent traffic**. It answers five questions:
- How fast is Weir under load?
- At what rate does it get too slow?
- Does it recover from a sudden burst?
- Does it stay healthy over a long run?
- Do failures (a model down, a slow database) stay invisible to users?

These are the p95 numbers the project's claims rest on.

Almost all runs use the **stub model**, a fake model inside hospital-rag that waits a realistic time and answers from the retrieved text. Groq's free tier allows only about 5 large-model requests a minute, so real-model load testing is impossible. The real-model latencies already measured one at a time stay the end-to-end reference.

**User decisions (2026-10-06):**
- **D48, scope (focused):**
  - **Cold cache:** all 4 configurations.
  - **Warm cache:** `cache_only` and `full`, the configurations that have a cache.
  - **Ramp:** `full`, plus `baseline` for comparison.
  - **Spike, soak and failure injection:** `full` only.
  - **Repeats:** 3 per scenario, except the soak (1).
- **D49, stub timing:** realistic and per model. Each delay is drawn from a curve fitted to measured model times.
- **D50, latency budget:** **p95 of 2 s** under load.
- **D51, failure injection:**
  - a stub **fault endpoint** for model rate limits and timeouts
  - **Toxiproxy** on Weir's database link only, for a slow cache database
- **D52, orchestration:** k6 scripts plus a **Python orchestrator** inside the eval tool (`weir_eval loadtest`).
- **D53, the baseline path:** the baseline under load runs through Weir's `baseline` configuration, like the evals. hospital-rag has no single answer endpoint to hit directly. This refines D16.

---

## 2. Components and data flow

```
 weir_eval loadtest (Python orchestrator)
   │ 1. set config, recreate weir        4. read request_log for the run window
   │ 2. empty / pre-fill the cache       5. sample docker stats (CPU, memory)
   │ 3. run k6 ──────────┐               6. write results JSON + report
   ▼                      ▼
 k6 (grafana/k6, Docker) ──POST /v1/query──▶ weir ──▶ hospital-rag (LLM_MODE=stub)
                                              │  └─ toxiproxy ─▶ postgres   (failure runs only)
                                              └─ /metrics ──▶ prometheus ──▶ grafana (live view)
```

| Part | Where | Responsibility |
| --- | --- | --- |
| k6 scripts | `loadtest/scripts/` | One shared helper, plus one script per scenario. Each script tags every response by path (`hit` / `small` / `large`) from `meta.cache_status` and `meta.route`, and flags `fallback` and `escalated`, so the client-side p50/p95/p99 can be reported per path. |
| Request files | `loadtest/workloads/` | JSON arrays of `{query, namespace}` generated from the eval set. **API keys are never written into them**: k6 receives the keys as environment variables at run time. |
| Orchestrator | `eval/src/weir_eval/loadtest/` and the CLI `weir_eval loadtest ...` | Switches configs, purges or pre-fills the cache, warms Weir up, runs k6 in Docker, samples `docker stats` and database connections, and reads the request log for the run window. Writes the results and the report. Reuses the eval tool's workload generator, purge and CLI patterns. |
| Raw results | `loadtest/results/<date>/` | Per run: a small `summary.json`, plus k6's per-request output **gzip-compressed**. The report regenerates from these. |
| k6 | `grafana/k6` (pinned), run on demand | Not a long-running service. |
| Toxiproxy | `ghcr.io/shopify/toxiproxy` (pinned), Compose profile `loadtest` | Proxies `toxiproxy:5433` to `postgres:5432` for Weir only, and only during failure runs (a small Compose override file). Any published ports are localhost-only. |

**Prerequisite (backlog M25):** the dashboard's default refresh goes from 30 s to 5 minutes, and its variable lookups are time-bounded. Watching a run in Grafana must not load the database being measured.

---

## 3. Stub model, fault endpoint and Toxiproxy

### 3.1 Realistic timing (D49)
- **Per-model delays:** each answer's delay is drawn from a **lognormal curve per model**. The curve is fitted to the median and p95 of the request log's measured `latency_llm_ms` from the clean Phase 3 runs, excluding the 2026-10-05 outage run. That is roughly a 0.5 s median for the small model and 0.7 s for the large one; the exact values are fitted in the build and recorded in the report.
- **Seeded,** so repeats see the same sequence.
- **Settings:** new hospital-rag variables select `STUB_TIMING=realistic|fixed` and set each model's median and p95. `fixed` keeps today's single `STUB_LATENCY_MS`.
- **Unknown models** use the large model's timing.

### 3.2 Fault endpoint (D51)
- **The endpoint:** `POST /stub/faults` on hospital-rag, which **exists only in stub mode** (404 otherwise). It is localhost- and Docker-network-only, like the rest of hospital-rag.
- **The request body** is `{"model": "<id>", "mode": "none" | "rate_limit" | "timeout", "delay_ms": 5000}`:
  - `rate_limit` makes that model answer 503 `rate_limited`, so Weir falls back to the other tier.
  - `timeout` makes it answer 504 after `delay_ms`, which also triggers a fallback and shows its latency cost.
  - `none` clears the fault.
- **Faults change mid-run** without a restart.

### 3.3 Toxiproxy (D51)
- **Routing:** for failure runs, Weir's `DATABASE_URL` points at `toxiproxy:5433`, which forwards to `postgres:5432`. hospital-rag keeps its direct connection, so document search is unaffected.
- **The fault:** a 2,000 ms latency on that link makes Weir's cache lookups exceed their 500 ms budget, so requests bypass the cache.

### 3.4 Timing the faults
- **The chaos scenario:** the failure script runs a second k6 scenario alongside the traffic. At fixed offsets it calls the fault endpoint and Toxiproxy's API, and it always restores them at the end, even on abort.
- **Why k6 and not the orchestrator:** faults line up exactly with the traffic, with no timing coordination needed between the orchestrator and k6.

---

## 4. Scenarios

**Shared rules:**
- **The workload:** one fixed list of **3,000 requests** drawn from the 158 eval questions with Zipf-style popularity (the existing generator, seed 11). Its repeat rate is stated in the report. k6 sends the list in order at a **constant arrival rate** (D10). Ramp, spike and soak cycle through the list.
- **Process warm-up:** after each Weir (re)start, the orchestrator sends about 20 throwaway requests. These load the embedding model and open the connection pools. For cold runs, the cache is then emptied.

| Scenario | Configurations | Shape | Repeats |
| --- | --- | --- | --: |
| Cold | baseline, cache_only, router_only, full | Cache emptied, then 10 req/s for 5 min (3,000 requests) | 3 |
| Warm | cache_only, full | Cache pre-filled (each distinct question once, unmeasured), then 10 req/s for 5 min | 3 |
| Ramp | full (warm), baseline | 5, 10, 20, 40, 60, 80 then 100 req/s, 90 s per step. Stops early when errors exceed 5%. | 3 |
| Spike | full (warm) | 5 req/s for 2 min, then 60 req/s for 30 s, then 5 req/s for 3 min | 3 |
| Soak | full (warm) | 10 req/s for 30 min (18,000 requests) | 1 |
| Failure | full (warm), through Toxiproxy | 10 req/s for 7 min, in phases: 0–2 min normal; 2–3 min large model rate-limited; 3–4 min normal; 4–5 min small model times out (5 s); 5–6 min Weir's database link delayed by 2 s; 6–7 min normal | 3 |

**Why some runs are skipped:**
- baseline and router_only have no cache, so their cold run is also their steady state.
- **Total:** about 4.5 hours of unattended machine time, run in chunks.

---

## 5. Measurements

**Per run:**

| Source | Measured |
| --- | --- |
| k6 (client) | p50/p95/p99 overall and per path (hit, small, large); achieved rate vs target and dropped iterations; error and timeout rate |
| Request log (by time window and `config_label`) | Cost per 1,000; hit rate; route mix; fallbacks; **gateway overhead** (embed plus cache-lookup time, mean and p95); Weir-internal p50/p95 |
| `docker stats` (every 5 s) | CPU and memory of `weir`, `hospital-rag` and `postgres` |
| Postgres | Open connections (`pg_stat_activity`), sampled |
| `/metrics` | Lost background work: dropped or failed log rows and cache jobs |

**Repeats** are reported as the **median with the range** (min–max).

**Derived numbers:**
- **Ramp:** the highest step whose p95 is at most 2 s and whose error rate is at most 1%, for full and baseline.
- **Spike:** the peak p95, and the **recovery time** (from the end of the burst until the 10-second-window p95 is back under 2 s).
- **Soak:** p95 and memory in the first 5 minutes vs the last 5.
- **Failure:** errors, p95, fallbacks and cache bypasses per phase.

---

## 6. Report and checks

**The report:** `docs/results/loadtest-<date>.md`, regenerated by `weir_eval loadtest report <results dir>`. It contains:
1. **Setup:** laptop, versions, stub timing parameters, workload repeat rate.
2. **Cold, four-way:** p50/p95/p99, hit rate, cost per 1,000, errors per configuration, plus the warm table for the cache configurations.
3. **Latency per path,** and **gateway overhead**.
4. **Ramp:** a p95-vs-rate chart (PNG) and the maximum sustainable rate, full vs baseline.
5. **Spike:** peak p95 and recovery time.
6. **Soak:** first vs last 5 minutes, connections, memory.
7. **Failure:** a phase-by-phase table.
8. **Limitations.**

**Checks** are reported pass or fail, honestly. A failed check becomes a finding to investigate:

| Claim | Check |
| --- | --- |
| Original spec target | Full Weir's **warm** p95 is at least **30% lower** than the baseline's at 10 req/s |
| Model faults are invisible | **0 errors** in the failure run's model-fault phases |
| Cache outage is invisible | **0 errors** and **p95 at most 2 s** in the database-delay phase |
| No leaks | Soak memory grows less than 10%, and p95 drifts less than 20%, first 5 minutes vs last 5 |
| Nothing lost | 0 dropped or failed log rows and cache jobs, across all runs |

---

## 7. Testing

| Test | Proves |
| --- | --- |
| Stub timing (hospital-rag) | Seeded draws hit each model's median and p95 within a tolerance; unknown models use the large timing; `fixed` mode is unchanged |
| Fault endpoint (hospital-rag) | 404 outside stub mode. `rate_limit` makes only the named model answer 503. `timeout` answers 504 after the delay. `none` resets. |
| Request files | Right size, order and repeat rate; no API keys |
| k6 output parsing | Per-path p50/p95/p99, dropped iterations and errors, from a small saved k6 sample |
| Calculations | Median and range; spike recovery time; ramp maximum under 2 s; failure phase windows; each check's pass/fail |
| Report | Renders from fixture data |
| k6 scripts | `k6 inspect` on every script, in CI |
| Compose | Toxiproxy in profile `loadtest`, pinned, localhost-only. The dashboard refresh and time-bounded variables (M25). |
| Live smoke | Every scenario for about 20 s, before the long runs |

---

## 8. Documentation

- **Results:** `docs/results/loadtest-<date>.md`.
- **README:**
  - an "Under load" part of Results
  - k6 and Toxiproxy in the stack table
  - how to reproduce a run
  - the roadmap set to Done
- **Other docs:**
  - `results/summary.md` with an under-load table
  - `decisions.md` (D48 onwards)
  - `progress.md`
  - `backlog.md`, with M25 resolved
- **Style:** no emojis.

---

## 9. Out of scope

- **Real-model load tests** (free-tier rate limits).
- **A separate machine for k6.** k6 runs on the same laptop, which is recorded as a limitation.
- **Several Weir processes, Kubernetes, distributed k6.**
- **The demo chat page** (Phase 6).
- **The Phase 4 backlog minors (M21–M30)**, except M25.
