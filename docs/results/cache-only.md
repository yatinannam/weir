# Cache-only results (Phase 2)

Run on 2026-10-03, after the final-review fixes, `config_label = cache_only`: semantic cache on, always the large model (`gpt-oss-120b`), threshold **0.90** (D30). The guard reads number words and ordinals (D29), the lookup budget is 500 ms (D31), and a miss updates the `kb_version` straight away (D32).

Raw data:
- **Cold pass:** `eval/reports/20261003T172615Z-cache_only-all/`. 158 questions in file order, cache emptied first.
- **Realistic replay:** `eval/reports/20261003T173739Z-cache_only-workload-300-seed7/`. 300 requests from `eval/datasets/workload-300-seed7.jsonl`: Zipf-skewed popularity, seed 7, 79 unique questions (from the original 150), **repeat rate 73.7%**. Run right after the cold pass, so the cache was warm.
- **Baseline:** `eval/reports/baseline-v3/` (158 questions = baseline v2 plus the 8 new number-word trap questions).
- **Grading:** judge is Qwen on Groq (rubric r1); facts use the D28 answer key.
- **Superseded:** the first cache run at threshold 0.85 (`…161320Z…` and `…164219Z…`) is kept for the record. It came before the final-review fixes.

## Headline

| Configuration | Requests | Cache hit rate | Cost per 1,000 requests | p50 | p95 | Judge (1–5) | Facts | Wrong hits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline v3 (no cache) | 158 | 0% | $0.0980 | 617 ms | 3.5 s | 4.90 | 0.981 | — |
| Cache only, cold pass | 158 | 14.6% | $0.0847 | 686 ms | 1.3 s | **4.91** | 0.981‡ | **0** |
| Cache only, warm replay | 300 | **93.3%** | **$0.0050** | **56 ms** | 579 ms | 4.79* | 0.948* | **0**† |

- **On repeat-heavy traffic (73.7% repeats), the cache cut cost per 1,000 requests by 95% ($0.098 → $0.0050) and typical latency by 11× (617 ms → 56 ms), with no quality loss.**
- \* **The replay's quality matches the baseline on the same mix.** Scoring the same 300-request mix with the baseline's grades gives judge 4.79 and facts 0.948, identical to the cache. The lower average comes from the popularity draw repeating q-143 15 times, a hard two-document question the baseline itself fails.
- † **The one flagged hit isn't a cache error.** The fact check flags one hit, q-141 (judge 2). That is the question replaying its *own* answer from the cold pass (similarity 1.0), which was already incomplete when the model wrote it. The baseline scores q-141 the same way. Wrong answers caused by the cache: **0**.
- ‡ **Facts equal the baseline (0.981) after the fact-matcher fix (D38, 2026-10-05).** As first reported, this was 0.978: on q-019 the model freshly wrote "50 %" with a space, which the matcher then didn't accept, although the answer was correct (judge 5/5). The matcher now treats "50 %", "50%" and "50 percent" alike, and the report was re-scored (no new model calls). Every cache hit kept all of its facts.

## Phase 2 exit gate (addendum §7.4)

| Check | Required | Result |
| --- | --- | --- |
| Trap pairs at the chosen threshold (sweep) | 0, false-hit rate under 1% on every split | **0 of 24 / 0%** (see `cache-threshold.md`) |
| Wrong hits on trap questions (cache run) | 0 | **0** |
| Cold-pass quality vs the baseline, same 158 questions | judge within 0.1, facts no lower | **judge 4.91 vs 4.90; facts 0.981 vs 0.981** (after the D38 matcher fix; 0.978 as first reported, see ‡). The cache itself caused no fact losses. |

**Passed.** Only one question's grade differed from the baseline: q-078 went from 4 to 5, on a miss. That's normal variation.

## Where the hits came from

Cold pass: the cache started empty, so the first wording of every question had to miss.

| Group | Questions | Hits | Notes |
| --- | --- | --- | --- |
| paraphrase | 65 | 19 | 19 of the 52 wordings that could hit = **37%**. At 0.85 it was 56%: that is the price of the safer threshold. |
| trap | 48 | 4 | All 4 correct: each matched an *earlier, different* question with the same answer (for example "How much is an MRI scan?" reused "How much is an MRI scan at the hospital?"). **No trap ever received its look-alike partner's answer**, including the new number-word pairs ("three days" vs "one day before"). |
| distinct | 35 | 0 | |
| unanswerable | 10 | 0 | "Couldn't find" replies are never stored |

Warm replay hit rate by group: paraphrase 99%, trap 100%, distinct 83%, unanswerable 0%. Once a question has been answered, repeats of it hit regardless of the threshold.

## Latency by path

| Path | Requests | p50 | p95 |
| --- | --- | --- | --- |
| Cache hit (replay) | 280 | **56 ms** | 63 ms |
| Cache miss (replay) | 20 | 626 ms | 840 ms |
| Cache hit (cold) | 23 | 43 ms | 77 ms |
| Cache miss (cold) | 135 | 707 ms | 1.3 s |

All of these are client-side latencies through Docker on the laptop. Inside Weir, a hit averages **13 ms** (embedding plus lookup), against **735 ms** for a miss (request log).

## Money (request log, both runs, 458 requests)

| | Requests | Actual cost | Cost without the cache (counterfactual) |
| --- | --- | --- | --- |
| Hits | 303 | $0.00000 | $0.02963 |
| Misses | 155 | $0.01490 | $0.01490 |
| **Total** | 458 | **$0.01490** | **$0.04453** → **67% saved** |

Every request also pays for one embedding, which costs $0 with local bge-small, so the cache breaks even trivially here. With a paid embedding API it would need to be measured.

## Caveats

- **The hit rate depends on the workload.** 73.7% repeats is a repeat-heavy FAQ setting. A workload where few questions repeat saves much less; the cold pass, with only paraphrases repeating, saved 14%.
- **The threshold trades recall for safety.** At 0.90 the cache answers 37% of first-time rewordings, against 56% at 0.85. It gave up that recall to stay clear of wrong answers the final review found ("three days" vs "one day", two-part vs one-part answers).
- **Latency is sequential and paced, not a load test.** Phase 5 measures p95 under load.
- **The question set is small and the knowledge base is synthetic.** It has 158 questions and 24 trap pairs. "Zero wrong hits" is strong evidence for this set, not a guarantee.
- **The cache replays answers exactly as they were first written.** A miss that produced an incomplete answer, like q-141, is replayed as-is. The partial-answer guard (D27) catches the explicit "NOT_FOUND" case. Silent omissions are a model-quality issue, which Phase 3's grounding check and router address.
- **Costs are list prices.** Real spend was $0.
