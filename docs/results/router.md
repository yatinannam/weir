# Router results (Phase 3)

These are live runs from 2026-10-05, with real Groq models, the tuned router (D37) and the always-large baseline re-run the same day (baseline v4).

**Raw data** is in `eval/reports/`:

| Run | Report |
| --- | --- |
| Router only, 158 questions, cold | `20261005T074414Z-router_only-all` |
| **Full Weir, final settings**, 158 cold (cache purged) | `20261006T045749Z-full-all` |
| **Full Weir, final settings**, 300-request replay | `20261006T053129Z-full-workload-300-seed7` |
| Full Weir, cut-off 0.6, 158 cold | `20261005T082403Z-full-all` |
| Full Weir, cut-off 0.6, 300 replay | `20261005T085816Z-full-workload-300-seed7` |
| Baseline v4 (same day) | `20261005T091621Z-baseline-all` |
| Derived replays | `derived-baseline-v4-…`, `derived-router_only-…` (no-cache configs, so each request reuses its question's measured result) |

The final full-Weir runs (2026-10-06) use the shipped settings: `grounding.min_overlap` 0.3 (D39) and no caching of fallback-to-small answers (D40). The earlier runs at cut-off 0.6 are kept for comparison.

## Headline: router only vs the same-day baseline (158 questions, cold, no cache)

| | Router only | Baseline v4 (always large) |
| --- | --: | --: |
| Routed to the small model | **12.7%** (20 questions) | 0% |
| Escalated (small answer failed grounding) | 0 | — |
| Cost per 1,000 requests | **$0.0921 (−7%)** | $0.0988 |
| p50 / p95 latency | 781 ms / 1.5 s | 767 ms / 1.1 s |
| Judge (1–5) | **4.90** | 4.90 |
| Key facts | **0.978** | 0.978 |

- **The router saves 7% with no quality change.**
  - Judge and facts are identical to the same-day baseline.
  - All 20 small-routed questions scored 5/5 with full facts on both models.
- **The saving is modest by design.** The strict "no visible loss" bar (D33, D37) lets the small model take only short, single questions with a very strong retrieval match (≥ 0.86). The looser bar that was declined would have saved about 38% (see [`router-tuning.md`](router-tuning.md)).

## Per-route quality

| Route | Requests | Judge | Facts | Cost / 1k | p50 | p95 |
| --- | --: | --: | --: | --: | --: | --: |
| small (gpt-oss-20b) | 20 | **5.00** | **1.00** | $0.0456 | 663 ms | 1.1 s |
| large (gpt-oss-120b) | 138 | 4.88 | 0.975 | $0.0989 | 791 ms | 1.5 s |

- **On the small route:**
  - A small-routed request costs **54% less** than a large one.
  - Its answers are at least as good as the large model's on those same questions (judge 5.00 vs 5.00).
- **Every quality loss in the run is on the large route.** Two hard questions, q-141 and q-150, are answered partially or not at all by the large model, as they are in the baseline.

## Route reasons

| Config | Route | Reason | Requests | Avg grounding overlap | Avg latency |
| --- | --- | --- | --: | --: | --: |
| router only | large | default_large | 138 | 0.81 | 871 ms |
| router only | small | simple | 20 | 0.92 | 711 ms |
| full | large | default_large | 142 | 0.78 | 1.2 s |
| full | small | simple | 18 | 0.91 | 1.1 s |
| full | large | default_large + fallback | 6 | 0.85 | 16.8 s |

The full-Weir rows count every non-hit request across the cold pass and the replay.

**Rules that never fired on this question set:**
- `clinical`: no clinical questions
- `weak_retrieval`: every top retrieval score is ≥ 0.62
- escalation: every small answer passed grounding

They are covered by unit tests instead.

## Full Weir: cache + router

| | Full Weir (final) | Full Weir, cut-off 0.6 | Baseline v4 |
| --- | --: | --: | --: |
| **Cold, 158 questions** | | | |
| Cache hits / routed small | 14.6% / 11.4% | 14.6% / 11.4% | 0% / 0% |
| Cost per 1,000 | **$0.0786 (−20%)** | $0.0763 (−23%) | $0.0988 |
| p50 / p95 | 876 ms / 1.6 s | 788 ms / 7.2 s | 767 ms / 1.1 s |
| Judge / facts | **4.90 / 0.978** | 4.89 / 0.975* | 4.90 / 0.978 |
| **Replay, 300 requests, 73.7% repeats** | | | |
| Cache hits | **93.0%** | 89.7% | 0% |
| Cost per 1,000 | **$0.0055 (−94%)** | $0.0090 (−91%) | $0.0970 |
| p50 latency | **14 ms** (53× faster) | 16 ms | 747 ms |
| Judge / facts | 4.79 / 0.948 | 4.79 / 0.947 | 4.79 / 0.947 |
| Wrong cache hits | **0** | 0 | — |

- **Lowering the grounding cut-off (D39) did what it was meant to.** The replay hit rate rose from 89.7% to 93.0%, and replay cost fell another 39%, with no quality change.
- **The final cold pass matches the baseline exactly on judge and facts.**

\* The 0.6 run's cold difference is one question, q-150, on the **large** route. The large model flipped it between a half answer and "couldn't find" three times in one minute with the plain baseline configuration, so it is model noise, not Weir.

## Simulated vs live

| | Simulated (D37) | Live, router only |
| --- | --: | --: |
| Routed small | 13% | 12.7% |
| Cost per 1,000 | $0.0917 (−6% vs v3) | $0.0921 (−6% vs v3, −7% vs v4) |
| Small-route judge vs large | 5.00 vs 5.00 | 5.00 vs 5.00 |
| Escalations | 0% | 0% |

The offline simulation predicted the live router almost exactly.

## Exit gate (addendum §7.6), against baseline v4

| Report | Cost lower | Judge within 0.1 | Facts no lower | Small route ≥ large | 0 wrong hits | Result |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| Router only, cold | ✅ −7% | ✅ 4.90 = 4.90 | ✅ 0.978 = 0.978 | ✅ 5.00 = 5.00 | ✅ | **pass** |
| **Full Weir (final), cold** | ✅ −20% | ✅ 4.90 = 4.90 | ✅ 0.978 = 0.978 | ✅ 5.00 = 5.00 | ✅ | **pass** |
| **Full Weir (final), replay** | ✅ −94% | ✅ 4.79 vs 4.79 | ✅ 0.948 vs 0.947 | — | ✅ | **pass** |
| Full Weir (cut-off 0.6), cold | ✅ −23% | ✅ 4.89 vs 4.90 | ⚠️ 0.975 vs 0.978 (q-150, large route, noise) | ✅ 5.00 = 5.00 | ✅ | pass\* |
| Full Weir (cut-off 0.6), replay | ✅ −91% | ✅ 4.79 = 4.79 | ✅ 0.947 = 0.947 | — | ✅ | pass |
| Router only, replay (derived) | ✅ −4% | ✅ 4.79 = 4.79 | ✅ 0.947 = 0.947 | ✅ 5.00 = 5.00 | ✅ | **pass** |

### Why baseline v4

Against baseline v3 (2026-10-03), every report missed "facts no lower" by 0.003–0.006. That traced to the large model itself:
- **q-141 has drifted.** It now gets "couldn't find" every time, including 3 out of 3 with the plain baseline configuration. On Oct 1–3 it half-answered.
- **q-150 is a coin flip.**

The user chose to re-run the baseline the same day, so drift affects both sides equally.

## Resilience: two real large-model incidents

1. **Groq returned errors (HTTP 502) for about 20 minutes** during the full cold pass.
   - Weir fell back to the small model for **6 requests** instead of failing them, and the run had 0 errors.
   - Those requests were slow (16.8 s on average) because hospital-rag retries before giving up. That is what produced the 7.2 s p95.
2. **The large model's free-tier daily allowance ran out** during a later re-run (next section).
   - Weir fell back **113 times** and answered **458 of 458 requests**.

## Outage run (D39 re-run, degraded)

This was the re-measurement after lowering `min_overlap` to 0.3 (D39). Reports: `20261005T095916Z-full-all` and `20261005T104855Z-full-workload-300-seed7`.

**What happened:**
- The large model was rate-limited for most of the run.
- 93 of 117 large-routed cold questions were answered by the small model.
- Cold cost fell to $0.0474. That is the outage, not the router.
- Judge 4.87 (still within 0.1).
- The replay hit 93.0% at $0.0030 / 1k.

**This is not a clean test of D39.** It did, however, expose a design gap: the stand-in small answers were **cached**, including the two known small-model mistakes, and would have been served for 24 hours after the outage. **D40 fixes this:** answers from a fallback down to the small model are no longer cached.

The clean re-run of full Weir with D39 + D40 was done on 2026-10-06, once the quota had reset (see [Full Weir](#full-weir-cache--router)).

## Caveats

- **Small, synthetic benchmark:** 158 questions, 40 documents.
- **The router's saving is limited by its strict quality bar.** That was the user's choice (D37).
- **Grounding is lexical.**
  - It catches unfinished, uncited or "not found" answers.
  - It does **not** catch a fluent answer that omits a detail or invents one using words from the source (q-036, q-154).
  - The strict routing cut-offs, not grounding, keep those questions on the large model.
- **The large model is not stable over time** (q-141 drift, q-150 noise). Every comparison uses a same-day baseline.
- **Latency is sequential and paced, not load-tested.** Load tests are Phase 5.
- **Costs are list prices.** Actual spend was $0.
