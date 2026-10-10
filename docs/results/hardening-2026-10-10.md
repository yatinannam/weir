# Hardening under load (2026-10-10 and 2026-10-11)

Phase 5's load tests left two findings in the backlog:
- **M31:** in 1 of 3 ramps, full Weir collapsed at 100 req/s.
- **M33:** the embedding threads spin-wait at about 600% CPU.

This report covers the fixes (D74–D77) and the before-and-after measurements. The setup matches Phase 5:
- **Harness:** k6 at constant arrival rates, with real retrieval, embeddings, cache and router.
- **Model:** a stub model with delays fitted to Groq, so no quota was spent.
- **Workload:** 3,000 Zipf-skewed requests (94.8% repeats).
- **Machine:** one laptop that also runs k6: Intel Core Ultra 5 225U, 14 threads, 15.5 GB RAM, Windows 11.
- **Power:** the warm runs and the overload ramps ran on battery (65% down to 23%), and the three final ramps on AC.

Raw results are in [`loadtest/results/`](../../loadtest/results/):
- `2026-10-10-m33-before`, `2026-10-10-m33-after`
- `2026-10-10-overload-*`
- `2026-10-11-hardening`

## 1. Embedding threads (M33, D74)

ONNX Runtime's worker threads spin-wait between runs by default. Both services now build their embedding session with spinning off and one intra-op thread.

**Warm cache, 10 req/s, 5 minutes, full Weir:**

| | Before | After |
| :-- | --: | --: |
| Weir CPU, median of samples | 607% | **24%** |
| p50 / p95 / p99 | 10 / 15 / 20 ms | 22 / 40 / 50 ms |
| Errors | 0 | 0 |

The trade-off is per-request time on an idle machine. A spinning thread keeps a core hot, so one paced embedding inside the container takes ~6 ms with spinning and ~15.5 ms without. That holds whatever the thread count; measured at 10/s:

| | Spinning, all threads | Spinning, 2 threads | **No spinning, 1 thread** |
| :-- | --: | --: | --: |
| Embedding p50 | 5.6 ms | 6.7 ms | 15.5 ms |
| Process CPU | 606% | 107% | 15% |

Under load the cores are busy anyway, and the ramps below are faster than before. `cache.embed_spin: true` restores the fast, busy option.

## 2. What happens past capacity (M31, D75)

The overload ramp ran 100, 150, 200, 250 and 300 req/s for 60 s each, full Weir, never aborting on errors (D77). It ran four times as the fix took shape. Each row is one run; "OK/s" counts successful answers per second.

| Run | 200 req/s | 250 req/s | 300 req/s | Requests that fell through to the model path |
| :-- | :-- | :-- | :-- | --: |
| After M33, no shedding | 199/s, p95 89 ms, 0 errors | **collapsed:** 35/s, p95 34 s, 12,397 dropped iterations | 26/s, p95 23 s | 3,314 |
| Shed on embedding timeouts (first design) | 200/s, p95 145 ms | **collapsed:** 30/s, p95 38 s | 25/s, p95 23 s | 3,331 (36 shed) |
| Model-path cap only (64) | 193/s, 45% shed | 217/s answered, **97% shed** | 208/s, 98% shed | 685 |
| **Both limits (final)** | **199/s OK, p95 57 ms** | **221/s OK, 11% shed, p95 158 ms** | **193/s OK, 35% shed, p95 199 ms** | **0** |

The final row comes from the request log. The run's own summary wasn't written because the orchestrator ran the laptop out of memory reading k6's 220 MB raw file, which led to D77. k6's own summary for that run agrees: 59,877 requests, 13.5% errors (all sheds), 22 dropped iterations.

**What the runs showed:**
- **The embedding wasn't the bottleneck after M33.** In the unprotected collapse, 3,226 of 3,314 lookup timeouts came *after* the embedding had finished. At 250 req/s the whole machine saturates, Weir's database lookups slow down too, and the timeout lands in whichever step comes last. A breaker that only counted embedding timeouts therefore shed 36 requests and didn't help.
- **Capping only the model path stopped the fall-through but shed nearly everything.** A request was turned away only after its lookup had already timed out, so every request still paid for an embedding and a vector search, and the cache path stayed overloaded.
- **The front-door limit is what keeps cache hits flowing.** At most 32 lookups run at once, and the excess gets a 503 before any work. The admitted lookups then stay fast, so most requests are still answered from the cache, and the excess gets a quick 503 with `Retry-After: 1`.

**Normal traffic is unaffected.** With a slow cache database at 10 req/s (the Phase 5 failure test, D51), only ~10–25 requests are on the model path, far below 64, so a failed lookup still bypasses the cache as before. The pipeline tests cover both cases.

## 3. The writers that fell behind (D76)

The overload runs showed that above ~200 req/s the background writers dropped work:
- **16,940 request-log rows** were lost. This log is the source of every cost and savings number.
- **15,424 cache jobs** were lost: per-hit UPDATEs, plus the new cache entries queued behind them.

**The fixes:**
- **Hit counts** are summed in memory and written once a second as one statement.
- **The request log** is written with `COPY` in batches of up to 500.
- **The full-queue warning** is logged once per 1,000 dropped rows instead of once per row.

The re-run at up to 300 req/s dropped nothing: `weir_log_rows_dropped_total` and `weir_cache_jobs_dropped_total` stayed at 0, and 60,052 requests were logged.

## 4. The standard ramp, again

Phase 5's ramp was 5, 10, 20, 40, 60, 80 and 100 req/s, 90 s each, with a 2 s p95 budget, at most 1% errors and no dropped iterations. It ran 3 times with the final code, on AC power, against the three Phase 5 runs.

| | Phase 5 (2026-10-07) | After hardening (2026-10-11) |
| :-- | --: | --: |
| Runs holding 100 req/s | 2 of 3 | **3 of 3** |
| p95 at 100 req/s, per run | 60 s (collapsed), 42 ms, 41 ms | **19, 21, 20 ms** |
| Weir peak CPU, per run | 1,346%, 773%, 828% | **145%, 147%, 149%** |
| Errors / dropped iterations at 100 req/s | 5.2% and 7,135 in the collapsed run | **0 / 0 in every run** |

100 req/s is the top of this ramp, not Weir's ceiling. The overload ramp above held 200 req/s with no errors.

## Caveats

- **One laptop, shared with k6.** The ceilings are this machine's.
- **Battery and AC.** The overload ramps ran on battery, which may throttle the CPU; the final ramps ran on AC, as most of Phase 5 did. The before/after pairs (warm M33, the overload runs) shared a power source.
- **Thresholds come from measurement on this machine, not a sweep.** The limits (32 lookups, 64 on the model path) sit well above normal concurrency and well below a collapse. A different machine may want different numbers; both are in `configs/weir.yaml`.
- **Single overload runs.** Each overload configuration ran once (about 6 minutes each), unlike the three repeats of the standard ramp.
