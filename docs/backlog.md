# Backlog

Ideas and deferred findings that aren't scheduled yet. Each item says where it came from. When one is picked up, move it into that phase's plan and log the decision in `decisions.md`.

## Product ideas

| Idea | Why | Suggested phase |
| --- | --- | --- |
| **Demo chat page** (done in Phase 6A: `uv run demo.py`, `/demo`). A small web page: ask a question and see the answer, plus a badge for "from cache / small model / large model", time and cost | Makes the story visible in a 5-minute demo: slow first answer, instant reworded answer, trap correctly not cached. The FastAPI page at `localhost:8000/docs` works today but is plain. | Phase 6 (polish) |
| **"Asked attribute" guard group.** Time vs place vs price, plus open vs close | The guard can't tell "clinic timings" from "which room" (0.825 similarity). The threshold margin covers it today. Adding this could allow a lower threshold and more hits. | After Phase 3 |

## Deferred minor findings: Phase 2 final review (2026-10-03)

| # | Area | Finding | Suggested fix |
| --- | --- | --- | --- |
| M1 | Sweep | The threshold is chosen on all pairs (including holdout), and the lexicon was tuned after seeing failures, so holdout is not an independent check | State this in the results caveats (done in `cache-threshold.md`). For the final numbers, keep a fresh held-out set the sweep never sees. |
| M2 | Sweep | `choose_threshold` assumes the false-hit rate falls as the threshold rises (it's a ratio, so it can rise again) | Choose the lowest t such that every t' ≥ t passes |
| M3 | Sweep | Hard negatives ignore namespace (some pairs can never meet in the cache) | Restrict `others` to the same namespace |
| M4 | Feedback | The retry window (~0.8 s) is tight against the log flush. An unknown ID takes longer than another tenant's ID. | ~2 s total, and always wait to the same deadline before a 404 |
| M5 | Feedback | A thumbs-down or purge can race a cache insert that is still queued | Re-check after the queue drains, or record purges with a timestamp |
| M6 | Store | `%s = any(source_ids)` can't use the GIN index | `source_ids @> array[%s]::text[]` |
| M7 | Monitoring | The background queue's `failed` / `dropped` counters aren't exposed | **Resolved in Phase 4:** `weir_{log_rows,cache_jobs}_{dropped,failed}_total` on `/metrics`, the `BackgroundWorkLost` alert and a dashboard panel |
| M8 | Startup | If the embedder or lexicon fails to load, the background tasks already started aren't stopped | Start the tasks after loading, or widen the `try` |
| M9 | Router | Answers from `force_model="small"` are cached and served to every caller | **Resolved in Phase 3 (D35):** `force_model` requests bypass the cache |
| M10 | Eval tool | `--exclude-report` and `merge-reports` dedupe by ID, so they would drop repeats on workload reports | Error out when used with `--workload` |
| M11 | Eval tool | `rejudge` re-scores facts but keeps judge grades made against an older answer key | Re-grade the affected clusters, or record the key version on each row |

## Deferred minor findings: Phase 3 final review (2026-10-06)

The review found no Critical issues. The one Important finding (I1, a two-tier failure not marked as a fallback) and M4 (the gate ignored failed requests; graded up to Important) were fixed before merge.

| # | Area | Finding | Suggested fix |
| --- | --- | --- | --- |
| M12 | Router | Clinical questions are a router decision, so when the large model is down they can be answered by the small model (never cached, but not escalated either) | **Decided (D41):** keep as is; revisit if real clinical traffic is added |
| M13 | Logging | `model_calls` counts every failed attempt, including `unavailable` / hospital-rag 4xx/5xx where no provider was reached | Count only `rate_limited` / `timeout`, or document the field as "attempts" |
| M14 | Latency | A timeout followed by a fallback can hold a request for ~2 × `rag.timeout_seconds` (~60 s) | A shorter fallback timeout or a total LLM time budget |
| M15 | Eval tool | The gate's small-route check passes when nothing was routed small, so a silently disabled router would pass under `full` | Report `share_small`; require > 0 when the config has the router on |
| M16 | Eval tool | D38's extension rule makes "ext. 2171" match any standalone 2171 ("Room 2171"), and "ext 4" match "floor 4" | Keep an `ext` token on both sides, or add a test documenting the looseness |
| M17 | Code | The grounding check and `store_block_reason` duplicate their first five rules; the store copies are now dead on the live path | Keep only the extra store checks (retrieval score, personal data), or share one helper |
| M18 | Tests | `test_fallback_down_to_small_is_not_cached` uses `top_score=0.3`, exactly `cache.min_retrieval_score`, so it relies on a strict `<` | Use 0.35 (still below `low_confidence` 0.40) |
| M19 | Eval tool | `simulate` prices an unusable small-trial row's escalation at baseline cost only (`small_cost=0`) | Use the median small cost; no effect on current data |
| M20 | Reporting | `by_route` groups fallback answers under the routed tier, and `meta` has no fallback flag | Group by `meta.model` for outage analysis, or expose the flag in `meta` |

## Deferred minor findings: Phase 4 final review (2026-10-06)

The review found no Critical findings. Three Important ones were fixed before closing (D47):
- first-increment blindness
- `CostAboveBaseline` firing on `baseline` runs
- `HighLatencyP95` blind on cache-heavy traffic

| # | Area | Finding | Suggested fix |
| --- | --- | --- | --- |
| M21 | Dashboard | "Routed small" is small / non-hit requests on the dashboard but small / all requests in `docs/results/` (11.4% vs ~13.3% for the full cold pass) | Rename the column ("Routed small, of non-hit") or align the definition |
| M22 | Metrics | `weir_metrics_failed_total` exists but no panel or alert uses it | Add it to the "Lost work" panel and `BackgroundWorkLost` |
| M23 | Dashboard | Time-series panels draw lines across idle days; the spec asked for a stacked route mix | `$__timeGroupAlias(ts, '1h', 0)` (update the test expander) or stacked bars |
| M24 | Dashboard | Similarity buckets use `floor(real * 100)`, so a 0.90 can land in 0.89; the 1.00 bar (exact repeats) flattens the near misses | Cast to numeric; exclude >= 0.995 or use a log scale |
| M25 | Dashboard | A 30 s refresh re-runs ~17 30-day aggregates plus two full DISTINCT scans against the database the cache uses | **Resolved in Phase 5 (Task 1):** refresh 5 min; variable queries bounded by `$__timeFilter(ts)` and refreshed only on time-range change |
| M26 | Docs | An empty `GRAFANA_ADMIN_PASSWORD` silently means `admin`, and Grafana applies the variable only on first start | Document both, plus a generation command like the tenant keys |
| M27 | Tests | The dashboard query test and `check_panels.py` count rows, but aggregate/`coalesce` stat queries always return one row | Also check for a non-null, non-zero value where data is expected |
| M28 | Tests | The `/metrics` tests build their own registry, so removing the wiring in `main.py` wouldn't fail a test | A shared `build_metrics(...)` used by both `main.py` and the tests |
| M29 | Docs | D45 says promtool can't reproduce the label collision; a `promql_expr_test` on the inner `increase(...)` does | Add that expression test; correct D45's wording |
| M30 | Metrics | prometheus-client adds a `*_created` series for every counter child | `disable_created_metrics()` at startup |
| M31 | Gateway | Under CPU overload (the ramp's 100 req/s step, 1 of 3 runs), cache lookups time out and fall through to retrieval and the model, which adds load until requests time out: the cache's own safety valve amplifies the overload | Shed load or serve stale on lookup timeouts caused by saturation (for example a circuit breaker on the bypass rate) instead of sending more work to the expensive path |
| M32 | Gateway | uvicorn's default 5 s keep-alive is shorter than many clients' idle timeouts, so a reused connection can be reset (2 in about 220,000 load-test requests) | Raise `--timeout-keep-alive` above client and load-balancer idle timeouts (for example 75 s) |
| M33 | Performance | ONNX Runtime's embedding threads spin-wait, so any container that embeds reads about 600% CPU at 10 req/s | Cap intra-op threads and disable spinning; re-measure the ramp ceiling |
| M34 | Load tests | k6 shares the laptop with the system under test, and capacity varied between rounds (a 15 W-class CPU, partly on battery) | Re-run the ramp on dedicated hardware, on AC power, with the load generator on another machine |
| M35 | Load tests | The run window mixes the Windows host clock (start/end) with the Docker VM clock (`request_log.ts`); failure-phase windows start at the first completed request, and k6 phase stats count requests by completion time | Derive windows from k6's points (or Postgres `now()`), start phases at the first request's send time, and flag any run whose request-log count differs from k6's |
| M36 | Load tests | Run preparation and resets aren't verified: a stale `k6-summary.json`/`k6-raw.json` from a crashed attempt can be parsed; the cache purge, warm-up and pre-fill statuses are unchecked (warm-up inserts can race the purge); resets aren't confirmed afterwards | Delete both k6 files at the start of a run; check the purge's status and `deleted` count and the warm-up and pre-fill statuses; wait before purging; assert faults `{}` and toxics `[]` after resetting |
| M37 | Load tests | No timeouts on the k6 subprocess or `docker stats`; the k6 container is unnamed, so a hard-killed orchestrator leaves it sending load; no settle step after a collapsed ramp; chaos switches use relative sleeps and k6's 60 s timeout; `compact_points` reads the whole raw file into memory | `--name weir-k6` with `docker rm -f` before each run; subprocess timeouts (planned duration plus a margin); a settle wait after a collapse; `timeout: '5s'` and absolute offsets for switches; line-by-line compaction |
| M38 | Stub | The seeded delay sequence continues across runs (spec §3.1 says repeats see the same sequence); timing parameters aren't recorded per run, so the report hard-codes them; `set_fault("*", <mode>)` silently stores a key no model matches | Reseed on the `*`/none reset (or correct the spec); expose timing mode and parameters on `/healthz` and store them in `summary.json`; reject `*` with any mode but `none` (422) and cap `model`'s length |
| M39 | Report | The ramp median drops runs with no step within budget while "Runs" still counts them; the gateway-overhead range includes deliberately degraded runs; samples arrive about every 7.1 s but are labelled 5 s; `--machine` defaults to the author's laptop | Count a run with no step as the worst result; show overhead for cold and warm runs only; wait the interval minus the probe time; make `--machine` required or detect it |
| M40 | Tests | Spec §2's per-response fallback/escalated flags were dropped by the plan, so escalations under load are unmeasured; no test pins that `execute` refuses a groq-mode hospital-rag before any compose call, request or k6 run | Add the flags to `lib.js` and the report; a test that patches httpx and subprocess and asserts the refusal comes first |
