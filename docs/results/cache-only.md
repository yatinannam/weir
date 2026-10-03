# Cache-only results (Phase 2)

Run on 2026-10-03, `config_label = cache_only`: semantic cache on, always the large model (`gpt-oss-120b`), threshold **0.85** (D26). Raw data:
- Cold pass: `eval/reports/20261003T161320Z-cache_only-all/`. 150 questions in file order, cache emptied first.
- Realistic replay: `eval/reports/20261003T164219Z-cache_only-workload-300-seed7/`. 300 requests from `eval/datasets/workload-300-seed7.jsonl`: Zipf-skewed popularity, seed 7, 79 unique questions, **repeat rate 73.7%**. Run right after the cold pass, so the cache was warm.
- The judge is Qwen on Groq (rubric r1) and the facts come from the D28 answer key, both the same as baseline v2.

## Headline

| Configuration | Requests | Cache hit rate | Cost per 1,000 requests | p50 | p95 | Judge (1–5) | Facts | Wrong hits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline v2 (no cache) | 150 | 0% | $0.0972 | 615 ms | 3.5 s | 4.93 | 0.987 | — |
| Cache only, cold pass | 150 | 23.3% | $0.0753 | 606 ms | 1.2 s | **4.93** | **0.987** | **0** |
| Cache only, warm replay | 300 | **93.7%** | **$0.0047** | **53 ms** | 604 ms | 4.79* | 0.948* | **0**† |

- **On repeat-heavy traffic (73.7% repeats), the cache cut cost per 1,000 requests by 95% ($0.0972 → $0.0047) and typical latency by 11× (615 ms → 53 ms), with no quality loss.**
- \* **The replay's quality matches the baseline on the same mix.** Scoring the same 300-request mix with baseline v2's grades gives judge 4.79 and facts 0.948, identical to the cache. The lower average comes from the popularity draw repeating q-143 15 times, a hard two-document question the baseline itself fails.
- † **The one flagged hit isn't a cache error.** The fact check flags one hit, q-141 (judge 2). That is the question replaying its *own* answer from the cold pass (similarity 1.0), which was already incomplete when the model wrote it. Baseline v2 scored q-141 the same way. Wrong answers caused by the cache: **0**.

## Phase 2 exit gate (addendum §7.4)

| Check | Required | Result |
| --- | --- | --- |
| Trap pairs at the chosen threshold (sweep) | 0, false-hit rate under 1% on every split | **0 / 0%** (see `cache-threshold.md`) |
| Wrong hits on trap questions (cache run) | 0 | **0** |
| Cold-pass quality vs baseline v2, same 150 questions | judge within 0.1, facts no lower | **4.93 vs 4.93, facts 0.987 vs 0.987** |

**Passed.** Only one question's grade differed from baseline: q-078 went from 4 to 5. That's normal variation, because the model rewrote the answer on a miss.

## Where the hits came from

Cold pass: the cache started empty, so the first wording of every question had to miss.

| Group | Questions | Hits | Notes |
| --- | --- | --- | --- |
| paraphrase | 65 | 29 | 29 of the 52 wordings that *could* hit (all but each cluster's first) = **56%** |
| trap | 40 | 6 | All 6 correct: each matched an *earlier, different* question with the same answer (for example "How much is a CT scan?" reused "CT scan charge and report time", ₹3,500). **No trap ever received its look-alike partner's answer.** |
| distinct | 35 | 0 | |
| unanswerable | 10 | 0 | "Couldn't find" replies are never stored (D27 / `not_found`) |

Warm replay hit rate by group: paraphrase 100%, trap 100%, distinct 83%, unanswerable 0%.

## Latency by path

| Path | Requests | p50 | p95 |
| --- | --- | --- | --- |
| Cache hit (replay) | 281 | **53 ms** | 57 ms |
| Cache miss (replay) | 19 | 693 ms | 994 ms |
| Cache hit (cold) | 35 | 19 ms | 57 ms |
| Cache miss (cold) | 115 | 652 ms | 1.2 s |

All of these are client-side latencies through Docker on the laptop. Inside Weir, a hit averages **8 ms** (embedding about 5 ms plus lookup 1–2 ms), against **701 ms** for a miss (request log).

## Money (request log, both runs, 450 requests)

| | Requests | Actual cost | Cost without the cache (counterfactual) |
| --- | --- | --- | --- |
| Hits | 316 | $0.00000 | $0.03104 |
| Misses | 134 | $0.01272 | $0.01272 |
| **Total** | 450 | **$0.01272** | **$0.04376** → **71% saved** |

Every request also pays for one embedding, which costs $0 with local bge-small, so the cache breaks even trivially here. With a paid embedding API it would need to be measured.

## Caveats

- **The hit rate depends on the workload.** 73.7% repeats is a repeat-heavy FAQ setting. A low-repeat workload saves much less; the cold pass, with no repeats beyond paraphrases, saved 23%.
- **Latency is sequential and paced, not a load test.** Phase 5 measures p95 under load.
- **The question set is small and the knowledge base is synthetic.** It has 150 questions and 20 trap pairs. "Zero wrong hits" is strong evidence for this set, not a guarantee.
- **The cache replays answers exactly as they were first written.** A miss that produced an incomplete answer, like q-141, is replayed as-is. The partial-answer guard (D27) catches the explicit "NOT_FOUND" case. Silent omissions are a model-quality issue, which Phase 3's grounding check and router address.
- **Costs are list prices.** Real spend was $0.
