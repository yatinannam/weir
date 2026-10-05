# Weir results summary (Phases 1–3)

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
| Full Weir (Oct 5)† | 14.6% | 11.4% | $0.0763 (**−23%**) | 788 ms | 7.2 s‡ | 4.89 | 0.975§ | 0 |

**On a cold pass, each technique saves a little, and they add up:**
- the cache saves about 14% (paraphrase hits only)
- the router saves about 7%
- together, about 23%

Quality stays within the D33 bar.

## Replay: 300 requests, Zipf-skewed (seed 7), 73.7% repeats

This is the realistic case: a few questions are asked constantly.

| Configuration | How measured | Cache hits | Cost / 1k | p50 | Judge | Facts | Wrong cache hits |
| :-- | :-- | --: | --: | --: | --: | --: | --: |
| Baseline v4 | derived from baseline v4 per question | 0% | $0.0970 | 747 ms | 4.79 | 0.947 | — |
| Cache only (Oct 3) | live | 93.3% | $0.0050 | 56 ms | 4.79 | 0.948 | 0¶ |
| Router only | derived from the router-only run per question | 0% | $0.0936 (−4%) | 732 ms | 4.79 | 0.947 | — |
| **Full Weir**† | live | **89.7%** | **$0.0090 (−91%)** | **16 ms** | **4.79** | **0.947** | **0** |

**On repeat-heavy traffic, the cache dominates:**
- **Cost:** −91% to −95% per 1,000 requests.
- **Latency:** p50 under 60 ms instead of about 750 ms.
- **Quality:** identical to the baseline on the same request mix.

The router adds little here, because most requests never reach a model.

## Notes

- † **Full Weir here is the clean run with `grounding.min_overlap` 0.6.**
  - Since then, D39 lowered the cut-off to 0.3, so that good large answers it blocked can be cached. That was worth about 10 replay hits.
  - D40 stopped caching fallback-to-small answers.
  - A re-run on 2026-10-05 was hit by a large-model rate-limit outage, so it isn't a clean measurement (see [`router.md`](router.md#outage-run-d39-re-run-degraded)).
  - A clean re-measurement is pending.
- ‡ **The p95 of 7.2 s comes from 20 minutes of Groq errors.** Weir fell back to the small model for 6 requests instead of failing them.
- § **The fact difference is q-150, a question the large model answers inconsistently** (reproduced with the plain baseline configuration).
- ¶ **Phase 2's one flagged hit is not a cache error:** q-141 replayed its own already-incomplete answer.
- **"Derived" rows** reuse each question's measured result for every repeat. That is exact for configurations without a cache, where every request is independent. Their latency is each question's single-request latency.

## Gates

| Phase | Gate | Result |
| --- | --- | --- |
| 2 | Cache: 0 trap matches in the sweep; 0 wrong hits live; cold quality equal to the baseline | ✅ [`cache-only.md`](cache-only.md) |
| 3 | Router: cost lower; judge within 0.1; facts no lower; small route ≥ large; 0 wrong hits (vs same-day baseline) | ✅ with one documented noise exception ([`router.md`](router.md#exit-gate-addendum-76-against-baseline-v4)) |

## Where the detail lives

| Topic | Doc |
| --- | --- |
| Baselines v1–v3 | [`baseline.md`](baseline.md) |
| Cache threshold sweep and the entity guard | [`cache-threshold.md`](cache-threshold.md) |
| Cache results | [`cache-only.md`](cache-only.md) |
| Router tuning (offline simulation) | [`router-tuning.md`](router-tuning.md) |
| Router live results, gate, incidents | [`router.md`](router.md) |
