# Baseline: hospital-rag behind Weir, no cache, always the large model

Run on 2026-10-01. This is the number every later phase has to beat.

Raw data:
- `eval/reports/20261001T124959Z-baseline-all/results.jsonl`: every answer, with fact and judge scores
- `summary.json` and `summary.md` in the same folder

## Results

50 queries, both splits (`--split all`), `config_label = baseline`.

| Metric | Value |
| --- | --- |
| Requests answered | 50 / 50, no errors |
| Cost per 1,000 requests | **$0.0989** at list prices (real spend: $0, Groq free tier) |
| Latency p50 / p95 / p99 | **853 ms / 6.0 s / 9.2 s** (client-side, sequential, one request every 15 s) |
| Judge score (1–5, Qwen) | **5.0**, all 50 answers |
| Key-fact score (0–1) | **1.00**, every required fact present in every answer |
| Route mix | 100% large (`openai/gpt-oss-120b`) |
| Cache hit rate | 0% (cache not built yet) |

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 25 | 5.0 | 1.00 |
| paraphrase | 15 | 5.0 | 1.00 |
| trap | 10 | 5.0 | 1.00 |

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 33 | 5.0 | 1.00 |
| medium | 12 | 5.0 | 1.00 |
| hard | 5 | 5.0 | 1.00 |

I read all 10 trap answers by hand. Each one gives its own side's fact: ICU vs general-ward hours, ₹600 vs ₹700 OPD fees, ₹200 vs ₹50 parking, adult vs child vaccination hours, and the nurse 9 pm vs doctor 12 midnight night shift. A real request through Weir costs about 430 input and 70 output tokens.

## Frozen baseline settings

| Setting | Value |
| --- | --- |
| Large model | `openai/gpt-oss-120b` on Groq, `reasoning_effort=low`, `temperature=0`, `max_completion_tokens=700` |
| Prompt | `p1` (cite `[cN]`, reply `NOT_FOUND` when the context lacks the answer) |
| Retrieval | `bge-small-en-v1.5`, chunks ≤ 250 tokens, `k = 4`, pgvector HNSW |
| Knowledge base | `weir-general/en/public` kb_version `f3588241e9c7` (30 docs, 175 chunks); `weir-general/en/staff` kb_version `5dc09499ad35` (10 docs, 61 chunks) |
| Eval set | 50 queries: 25 distinct, 3×5 paraphrase, 5×2 traps; split 33 tune / 17 holdout by cluster |
| Judge | `groq:qwen/qwen3.8-27b`, rubric `r1`, temperature 0, JSON output (decision D20) |
| Prices | `configs/prices.yaml`: gpt-oss-120b $0.15 in / $0.60 out per 1M tokens |
| Code | answers produced at git commit `a61ce0b`; graded with the judge code in `3b2cf88` |
| Machine | Intel Core Ultra 5 225U (12 cores / 14 threads), 15.5 GB RAM, Windows 11 Home build 26300, Docker Desktop (server 29.8.1) |

## What this means for the next phases

The large model gets every question right. Any drop from 5.0 or 1.00 in a later configuration is a real regression:
- a wrong cache hit (Phase 2), or
- the small model failing a question (Phase 3).

The trap group is the sharpest test, because a cache that confuses "ICU" with "general ward" will now fail visibly.

The flip side is a **ceiling effect**: this set can't show the large model getting *better*, and it may miss subtle quality loss. Recommended additions before the final numbers:
- harder multi-document questions
- questions the knowledge base can't answer, to test the `NOT_FOUND` path
- follow-up questions (to test the cache bypass)

## Caveats

- **Latency is not a load test.** Requests were sent one at a time, 15 s apart, to stay under Groq's free-tier limits. The p95 and p99 come from a few slow Groq calls in a sample of 50, so they're noisy. Phase 5 measures p95 under load.
- **50 queries is small.** A judge difference of about 0.2 points is noise.
- **The knowledge base is synthetic** (fictional Weir General Hospital), so real hospital documents would be messier.
- **Costs are list prices.** Actual spend was $0.
- **Judge history.** The first judge choice, `gemini-2.5-flash`, refuses new accounts. Gemini's free tier then allowed only about 20 grades per model per day. The baseline was graded with Qwen on Groq instead (D19 → D20). The answers were saved first, so no question was sent to Groq twice.

## Human spot checks

- **Eval set:** the user checked 10 random questions against the knowledge base. *Pending.*
- **Judge agreement:** the judge and the key-fact check agree on all 50 answers (5 and 1.00 everywhere), so there are no disagreements to review. The user checked 5 random graded answers. *Pending.*
