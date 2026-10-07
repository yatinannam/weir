# Weir results summary (Phases 1–5)

**The four-way ablation:** baseline, cache only, router only and full Weir, each on two workloads.

**Setup:**
- Every run uses the same 158-question eval set on the fictional Weir General Hospital knowledge base.
- The models are real Groq models: gpt-oss-20b (small) and gpt-oss-120b (large).
- The judge is Qwen, using rubric r1.
- Costs are list prices; actual spend is $0.

**Baselines:**
- **Phase 3 rows** are compared with **baseline v4**, run the same day (2026-10-05), because the large model drifted between Oct 3 and Oct 5 (see [`router.md`](router.md)).
- **Phase 2's cache-only rows** were measured on 2026-10-03 against baseline v3. Both baselines are shown.

## Cold pass: 158 questions, each asked once

Only paraphrases repeat here, so this is the hard case for a cache.

| Configuration | Cache hits | Routed small | Cost / 1k | p50 | p95 | Judge | Facts | Wrong cache hits |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: |
| Baseline v3 (Oct 3) | 0% | 0% | $0.0980 | 617 ms | 3.5 s | 4.90 | 0.981 | — |
| Cache only (Oct 3) | 14.6% | 0% | $0.0847 (−14% vs v3) | 686 ms | 1.3 s | 4.91 | 0.981 | 0 |
| **Baseline v4 (Oct 5)** | 0% | 0% | **$0.0988** | 767 ms | 1.1 s | **4.90** | **0.978** | — |
| Router only (Oct 5) | 0% | 12.7% | $0.0921 (**−7%**) | 781 ms | 1.5 s | 4.90 | 0.978 | — |
| **Full Weir (Oct 6)**† | 14.6% | 11.4% | $0.0786 (**−20%**) | 876 ms | 1.6 s | **4.90** | **0.978** | **0** |
| Full Weir, cut-off 0.6 (Oct 5)‡ | 14.6% | 11.4% | $0.0763 (−23%) | 788 ms | 7.2 s | 4.89 | 0.975§ | 0 |

**On a cold pass, each technique saves a little, and they add up:**
- the cache saves about 14% (paraphrase hits only)
- the router saves about 7%
- together, about 20%

Quality is identical to the same-day baseline (judge 4.90, facts 0.978).

## Replay: 300 requests, Zipf-skewed (seed 7), 73.7% repeats

This is the realistic case: a few questions are asked constantly.

| Configuration | How measured | Cache hits | Cost / 1k | p50 | Judge | Facts | Wrong cache hits |
| :-- | :-- | --: | --: | --: | --: | --: | --: |
| Baseline v4 | derived from baseline v4 per question | 0% | $0.0970 | 747 ms | 4.79 | 0.947 | — |
| Cache only (Oct 3) | live | 93.3% | $0.0050 | 56 ms | 4.79 | 0.948 | 0¶ |
| Router only | derived from the router-only run per question | 0% | $0.0936 (−4%) | 732 ms | 4.79 | 0.947 | — |
| **Full Weir**† | live | **93.0%** | **$0.0055 (−94%)** | **14 ms** | **4.79** | **0.948** | **0** |
| Full Weir, cut-off 0.6‡ | live | 89.7% | $0.0090 (−91%) | 16 ms | 4.79 | 0.947 | 0 |

**On repeat-heavy traffic, the cache dominates:**
- **Cost:** −94% to −95% per 1,000 requests.
- **Latency:** p50 under 60 ms instead of about 750 ms.
- **Quality:** identical to the baseline on the same request mix.

The router adds little here, because most requests never reach a model.

## Under load: k6 at a constant arrival rate (Phase 5, stub model)

Retrieval, embeddings, the cache and the router are real; the model is a stub with delays fitted to measured Groq latencies, so costs here use the stub's token counts and compare only within this table. Workload: 3,000 Zipf-skewed requests (94.8% repeats). Medians of 3 runs, range in brackets; full detail in [`loadtest-2026-10-07.md`](loadtest-2026-10-07.md).

| Configuration | Cache | p50 | p95 | Hit rate | Cost / 1k | Errors | Highest rate within the 2 s budget |
| :-- | :-- | --: | --: | --: | --: | --: | --: |
| Baseline | empty at start | 772 ms | 1,439 ms (1,416–1,440) | 0% | $0.0783 | 0% | 60 req/s (60–80) |
| Cache only | empty at start | 10 ms | 41 ms (39–42) | 95.4% | $0.0034 | 0% | — |
| Router only | empty at start | 730 ms | 1,405 ms (1,403–1,442) | 0% | $0.0742 | 0% | — |
| **Full Weir** | empty at start | 10 ms | 33 ms (25–50) | 95.4% | $0.0032 | 0% | **100 req/s (60–100)** |
| Cache only | warm | 10 ms | 14 ms (13–17) | 100% | $0.0000 | 0% | — |
| **Full Weir** | warm | 10 ms | **15 ms** (13–16) | 100% | $0.0000 | 0% | — |

- **Failure injection (full Weir, 3 runs):** 0 errors in every phase. The large-model rate limit caused 541 fallbacks and the small-model timeout 60; a 2 s delay on Weir's database link caused 1,191 cache bypasses with median p95 1,943 ms (1,898–2,068: one run over 2 s).
- **Spike and soak:** a 60 req/s burst kept p95 at 22 ms at its worst, never leaving the budget; 30 minutes at 10 req/s moved p95 from 13.1 to 14.6 ms with 0 errors. Memory held at about 250 MiB for the first 25 minutes, but no samples exist for the last 5, so the no-leak check is incomplete.
- **The overload mode:** in 1 of 3 ramps, full Weir collapsed at 100 req/s when cache lookups timed out under CPU load and the bypassed requests added more load (backlog M31).

## Notes

- † **Full Weir is the final configuration, measured on 2026-10-06:** `grounding.min_overlap` 0.3 (D39) and no caching of fallback-to-small answers (D40). It was a clean run: no fallbacks, no rate limits, every large-routed question answered by the large model. Reports: `20261006T045749Z-full-all`, `20261006T053129Z-full-workload-300-seed7`.
- ‡ **The earlier run with cut-off 0.6 (2026-10-05)** is kept for comparison: lowering the cut-off lifted the replay hit rate from 89.7% to 93.0% and cut replay cost by another 39%, with no quality change. Its 7.2 s p95 came from 20 minutes of Groq errors, during which Weir fell back to the small model for 6 requests instead of failing them. A further re-run that day was hit by a large-model rate-limit outage and is kept only as a resilience record (see [`router.md`](router.md#outage-run-d39-re-run-degraded)).
- § **The fact difference is q-150, a question the large model answers inconsistently** (reproduced with the plain baseline configuration).
- ¶ **Phase 2's one flagged hit is not a cache error:** q-141 replayed its own already-incomplete answer.
- **"Derived" rows** reuse each question's measured result for every repeat. That is exact for configurations without a cache, where every request is independent. Their latency is each question's single-request latency.

## Gates

| Phase | Gate | Result |
| --- | --- | --- |
| 2 | Cache: 0 trap matches in the sweep; 0 wrong hits live; cold quality equal to the baseline | Pass ([`cache-only.md`](cache-only.md)) |
| 3 | Router: cost lower; judge within 0.1; facts no lower; small route ≥ large; 0 wrong hits (vs baseline v4) | Pass, every check, final configuration ([`router.md`](router.md#exit-gate-addendum-76-against-baseline-v4)) |
| 5 | Load: warm p95 at least 30% below baseline; 0 errors during model faults; cache outage invisible (0 errors, p95 at most 2 s); no leaks over the soak; no lost background work | 4 of 5 pass; the soak's no-leak check is incomplete (no memory samples in its last 5 minutes) ([`loadtest-2026-10-07.md`](loadtest-2026-10-07.md#checks)) |

## Where the detail lives

| Topic | Doc |
| --- | --- |
| Baselines v1–v3 | [`baseline.md`](baseline.md) |
| Cache threshold sweep and the entity guard | [`cache-threshold.md`](cache-threshold.md) |
| Cache results | [`cache-only.md`](cache-only.md) |
| Router tuning (offline simulation) | [`router-tuning.md`](router-tuning.md) |
| Router live results, gate, incidents | [`router.md`](router.md) |
| Load tests (Phase 5) | [`loadtest-2026-10-07.md`](loadtest-2026-10-07.md) |
