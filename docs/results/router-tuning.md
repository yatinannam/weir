# Router tuning (Phase 3)

The router's settings were tuned on 2026-10-04 by **offline simulation**, without a single extra model call (D34).

**Inputs:**
- **Large model:** baseline v3 (`eval/reports/baseline-v3/`). 158 questions, all answered by gpt-oss-120b, judged.
- **Small model:** the small-model trial (`eval/reports/20261004T171944Z-small_only-all/`).
  - The same 158 questions, all answered by gpt-oss-20b, with no cache, fallback or escalation.
  - Judged by the same Qwen judge with rubric r1.
  - Each answer's grounding result is copied from Weir's request log into `grounding.jsonl`.
- **Router features:** `eval/datasets/features.jsonl`. These are the length, reasoning words, number of questions and retrieval scores, computed by Weir's own feature code on hospital-rag's real retrieval.

**Raw output:**
- `eval/reports/simulate-20261004T184333Z/`: the planned grid, no passing setting
- `eval/reports/simulate-20261004T184336Z/`: the widened grid, the chosen setting

## Result

| Setting | Value | Was |
| --- | --: | --: |
| `router.short_query_tokens` | **16** | 20 |
| `router.high_confidence` | **0.86** | 0.75 |
| `router.low_confidence` | **0.50** | 0.40 |
| `grounding.min_overlap` | **0.6** | 0.5 |

| Split | Questions | Cost / 1k (baseline) | Judge (baseline) | Facts (baseline) | Routed small | Escalated | Small-route judge vs large |
| --- | --: | --- | --- | --- | --: | --: | --- |
| tune | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 |
| **holdout** | 48 | $0.0925 ($0.0973) | 4.92 (4.92) | 0.979 (0.979) | 10% | 0% | 5.00 vs 5.00 |
| all | 158 | $0.0917 ($0.0980) | 4.90 (4.90) | 0.981 (0.981) | 13% | 0% | 5.00 vs 5.00 |

- **Simulated saving: about 6%, with zero quality loss on both tune and holdout.**
- 20 questions go to the small model, and every one of them scored 5/5 from both models.
- **The saving is small,** because the strict bar only allows the small model on questions with a very strong retrieval match (≥ 0.86) and at most 16 tokens.
- Most of Weir's saving still comes from the cache: −95% on repeat-heavy traffic.

## How the small model did on its own

| | Small (gpt-oss-20b) | Large (baseline v3) |
| --- | --: | --: |
| Judge (1–5) | 4.87 | 4.90 |
| Key facts | 0.953 | 0.981 |
| Cost / 1k requests | $0.0467 (**−52%**) | $0.0980 |
| p50 / p95 latency | 561 ms / 754 ms | 617 ms / 3.5 s |

- **By group:**
  - easy questions are nearly identical (judge 4.98 vs 4.99)
  - hard multi-document questions are where the small model loses (4.20 vs 4.33)
  - traps are slightly worse (4.85 vs 4.90)
- It gave up ("not found") on **4 answerable questions**: q-141, q-143, q-150 and q-157. The grounding check catches these, so in live use they escalate to the large model.
- It answered **152 of 158** at 5/5.

### Why the planned grid found nothing (D37)

The addendum's grid capped `high_confidence` at 0.85. All 900 settings failed the same two checks of the D33 bar: facts no lower, and the small route no worse than the large model on its own questions.

Five questions in the tune split had a small answer that **passed grounding** yet scored worse:

| Question | Small | Large | What happened | Real loss? |
| --- | --- | --- | --- | --- |
| q-036 "When is the blood donation camp held?" | judge 3, facts 0.5 | 5, 1.0 | Gave "first Saturday" but **omitted "10 am to 3 pm"** | **Yes** |
| q-154 "Which OPD Block department is on the first floor?" | judge 2 | 4 | Right departments, **invented an extension number** | **Yes** |
| q-151 / q-152 (refund on cancelling 3 days / 1 day before) | judge 5, facts 0 | 5, 1.0 | Wrote "90 %" / "50 %" with a space, which the fact matcher doesn't accept | No: a matcher gap |
| q-129 "Pediatric ward desk extension?" | judge 5, facts 0 | 5, 1.0 | "extension is 2171", while the key wants "ext. 2171" / "extension 2171" | No: a key gap |

**Neither real loss is something a lexical grounding check can catch.** Both answers only use words from the source. q-036 looks as easy as a question gets (8 tokens, top score 0.855), so the planned grid sent it to the small model at every setting.

Widening `high_confidence` to 0.60–0.95 in 0.01 steps (5,400 settings) gave **720 passing settings**. The chosen one is the cheapest on tune; ties go to the most conservative values, which is why it picked the highest `low_confidence` and `min_overlap` among them. `low_confidence` and `min_overlap` don't change the outcome on this question set:
- every question's top score is ≥ 0.62, so weak retrieval never triggers
- no small answer failed on overlap

### The option not taken

A looser bar would have saved **~38%**, with 77% of questions going small. That bar allows judge within 0.1 overall *and* on the small route, and facts within 0.01. The cost would have been:
- overall judge 4.88 vs 4.90
- facts 0.978 vs 0.981
- 2 of 158 answers worse: q-036 and q-154 above

The user chose the strict bar (option A, D37). In a hospital FAQ, an invented phone extension is a real error, and the cache already delivers the large saving.

## Caveats

- **Tuned on 110 questions, checked on 48 holdout questions.** Holdout passed with zero loss, but 48 questions is a small check.
- **The simulation reuses each model's measured answer.** The live runs (router only, full Weir) generate fresh answers, so expect some noise around a saving this small. The live numbers are the ones reported.
- **The fact matcher misses "90 %" with a space, and bare extension numbers.** This doesn't change the chosen setting, because q-129, q-151 and q-152 all score below 0.86 and stay on the large model. It is a separate eval-tool fix.
- **Costs are list prices.** Actual spend was $0.
