# Weir Phase 3: Router Design (addendum)

Date: 2026-10-04 · Author: Yatin Annam (with Claude Code)
Status: Approved 2026-10-04
Builds on:
- [main design spec](2026-09-30-weir-design.md): §7 (router), §8 (cost), §11 (evaluation), §16 (Phase 3 row)
- [Phase 2 addendum](2026-10-02-phase-2-semantic-cache-design.md)
- Phase 2 results: [`cache-only.md`](../../results/cache-only.md) and [`baseline.md`](../../results/baseline.md) (baseline v3, 158 questions)

This addendum fixes the details the main spec leaves open for Phase 3. Where the two disagree, this document wins for Phase 3.

---

## 1. In plain terms

When the cache can't answer a question, Weir picks a model:
- **small** (`gpt-oss-20b`, half the price, faster) for simple, well-documented questions
- **large** (`gpt-oss-120b`) for everything else

Every small-model answer gets checked. If it looks shaky, Weir asks the large model once. The rules are tuned from measured data, so the small model only gets questions it answers as well as the large one.

**Quality bar (user decision, 2026-10-04): no visible loss.** Phase 3 only ships if overall quality stays within 0.1 judge points of the baseline, facts don't drop, and the small route is no worse than the large model on the same questions.

---

## 2. Request flow

```
question ─▶ cache (Phase 2) ─ hit ─▶ replay
              │ miss / bypass
              ▼
           retrieve ─▶ features ─▶ ROUTER ─┬─ small ─▶ generate ─▶ GROUNDING ─┬─ pass ─▶ answer (+ store if eligible)
                                           │                                 └─ fail ─▶ large (escalated) ─▶ answer
                                           └─ large ─▶ generate ─▶ GROUNDING ─▶ answer (+ store if it passed)
```

There are never more than **2 model calls** per request (`router.max_model_calls`).

---

## 3. Components

| Unit | File | Responsibility |
| --- | --- | --- |
| Features | `weir/router/features.py` | `Features` from the query and the retrieval result: `tokens` (bge tokenizer), `has_reasoning_words`, `num_questions`, `top_score`, `score_gap`, `context_tokens`, `is_clinical` |
| Rules v1 | `weir/router/rules.py` | `route(features, cfg) -> (tier, reason)`, following main spec §7.2 with tuned cut-offs. Reasons: `kill_switch`, `force_model`, `router_disabled`, `clinical`, `weak_retrieval`, `simple`, `default_large` |
| Grounding check | `weir/router/grounding.py` | `check(generated, chunks, min_overlap) -> Grounding(passed, reason, overlap)`, following main spec §7.4 |
| Pipeline | `weir/pipeline.py` | Calls the router after retrieval; escalation, fallback and the 2-call cap; grounding result into logs and cache eligibility |

### 3.1 Feature details

- **`num_questions`**: count of `?` plus "and"-joined interrogatives (`and (what|when|where|how|which|who|why|is|are|can|does|do)`), with a minimum of 1.
- **`has_reasoning_words`**: a config list, initially compare, why, explain, difference, steps, calculate, versus, vs, pros and cons, better, which is cheaper, both.
- **`is_clinical`**: reuses the Phase 2 clinical keyword rule. A clinical question always goes to the large model.

### 3.2 Rules v1 (cut-offs tuned in §7)

```python
def route(f, cfg):
    if cfg.kill_switch.force_large:            return "large", "kill_switch"
    if f.forced_tier:                          return f.forced_tier, "force_model"
    if not cfg.router.enabled:                 return cfg.router.default_tier, "router_disabled"
    if f.is_clinical:                          return "large", "clinical"
    if f.top_score < cfg.router.low_confidence: return "large", "weak_retrieval"
    if (f.tokens <= cfg.router.short_query_tokens and not f.has_reasoning_words
            and f.num_questions == 1 and f.top_score >= cfg.router.high_confidence):
        return "small", "simple"
    return "large", "default_large"
```

### 3.3 Grounding check

An answer passes only if all of these hold:
1. not `not_found`;
2. `finish_reason == "stop"`;
3. `cited_chunk_ids` is non-empty, with no invalid citations;
4. no stray `NOT_FOUND` in the text (Phase 2's partial-answer rule);
5. at least `grounding.min_overlap` of the answer's content words (stopwords and citation markers removed, lowercase) appear in the text of the cited chunks.

The result is logged as `grounding_passed`, `grounding_reason` (the first failing rule) and `grounding_overlap` (the measured fraction).

### 3.4 Escalation and fallback

- **Escalation:** a **small** answer that fails grounding is retried once on **large**, with `escalated = true`. The large answer is returned whatever its grounding result. The cost of both calls is counted.
- **Fallback:** if `generate` fails on one tier with a provider error (rate limit, timeout, bad response), Weir tries the other tier once. If that fails too, it returns the error with the `request_id`, as today.
- **Retrieval failure:** no fallback; the error is returned as today.
- **The cap:** never more than `max_model_calls = 2`.

### 3.5 Cache interaction

- **Write-back** additionally requires `grounding_passed`. The other Phase 2 checks stay: low retrieval, personal data.
- **`options.force_model`** requests bypass the cache in both directions, with reason `force_model`. This resolves backlog M9.
- **The cache key doesn't include the tier.** A cached answer, from either model, has passed grounding.

### 3.6 Cost accounting (main spec §8)

| Path | `cost_usd` | `counterfactual_cost_usd` |
| --- | --- | --- |
| small, passed | small call + embedding | the same tokens at the large-model rate |
| escalated | small call + large call + embedding | the large call's tokens at the large-model rate |
| fallback | the calls actually made + embedding | the answering call's tokens at the large-model rate |

---

## 4. Data model: `db/migrations/003_phase3_router.sql`

```sql
alter table weir.request_log add column route_reason text;
alter table weir.request_log add column grounding_reason text;
alter table weir.request_log add column grounding_overlap real;
```

`grounding_passed`, `escalated` and `model_calls` already exist from `001`.

---

## 5. Configuration (`configs/weir.yaml`)

```yaml
router:
  enabled: true
  default_tier: large          # used when the router is disabled
  small_model: openai/gpt-oss-20b
  large_model: openai/gpt-oss-120b
  short_query_tokens: 20       # tuned in §7
  high_confidence: 0.75        # tuned in §7
  low_confidence: 0.40         # tuned in §7
  max_model_calls: 2
  reasoning_words: [compare, why, explain, difference, steps, calculate, versus, vs, "pros and cons", better, both]
grounding:
  min_overlap: 0.5             # tuned in §7
```

New ablation overlays:

| Overlay | Cache | Router | Purpose |
| --- | --- | --- | --- |
| `small_only.yaml` | off | off, `default_tier: small` | Small-model trial run |
| `router_only.yaml` | off | on | Router on its own |
| `full.yaml` | on | on | Full Weir |

`baseline.yaml` and `cache_only.yaml` keep their meaning (always large).

---

## 6. API

`meta.route` is now really `small` or `large` on misses, and `meta.escalated` is real.

There are no new endpoints.

---

## 7. Evaluation

### 7.1 Small-model trial

- **Run:** all 158 questions under `small_only`, cache off, judged and fact-checked like the baseline (report `small-trial`).
- **Labels:** each question gets **small_ok** when the small model's judge score is at least the baseline v3 score for that question **and** its fact score is at least the baseline's.

### 7.2 Offline features and grounding data

- **Features:** `weir_eval features` calls hospital-rag `/retrieve` for every question. This needs no LLM and is free. It computes `Features` with Weir's own `weir.router.features`, giving `datasets/features.jsonl`.
- **Grounding overlap:** for the small-trial answers, it is read from the request log by `request_id`, because Weir logs `grounding_overlap` and `grounding_reason` on every generated answer.

### 7.3 Offline simulation and tuning (`weir_eval simulate`)

For each rule setting in a grid, every question is simulated without calling any model:

| Setting | Values |
| --- | --- |
| `short_query_tokens` | 12, 16, 20, 25, 30, 40 |
| `high_confidence` | 0.60–0.85, step 0.05 |
| `low_confidence` | 0.30–0.50, step 0.05 |
| `min_overlap` | 0.3–0.7, step 0.1 |

For each question:
- **Large route:** the baseline v3 answer.
- **Small route, grounding passes:** the small-trial answer.
- **Small route, grounding fails:** escalated, so the baseline answer at small + large cost.

The simulation computes cost per 1k, overall judge and facts, share routed small, escalation rate, and small-route judge against the large judge on the same questions.

- **Choose:** the setting with the **lowest simulated cost** whose **tune**-split quality meets the bar:
  - judge ≥ baseline − 0.1
  - facts ≥ baseline
  - small-route mean judge ≥ large's mean on those same questions
- **Report** the holdout split at that setting.
- **If none passes:** the router ships disabled, and this is reported.

### 7.4 Live runs

| Run | Ablation | Questions | Report |
| --- | --- | --- | --- |
| Router only | `router_only` | the 158, cold | `router_only-all` |
| Full Weir, cold | `full` | the 158, cache purged | `full-all` |
| Full Weir, replay | `full` | the same 300-request workload | `full-workload` |

All are judged and fact-checked. Simulated and live numbers are compared, and the live numbers are the ones reported.

### 7.5 Results

`docs/results/router.md` contains:
- per-route quality (small vs large)
- share routed small, escalation rate, route reasons
- cost per 1k, p50 and p95 by route

`docs/results/summary.md` contains the **four-way ablation table** (baseline, cache only, router only, full) for both the cold 158 and the 300-request replay, each with its repeat rate stated.

### 7.6 Exit gate

1. Router only and full Weir each have a **lower cost per 1k** than baseline v3 on the same requests.
2. **Overall judge within 0.1** of the baseline, and **facts no lower**, on the same requests.
3. **Small route:** mean judge ≥ the large model's mean on the questions routed small.
4. **Full Weir: 0 wrong cache hits.**

If gate 2 or 3 fails, the router is tuned more conservatively (re-simulated), or it ships disabled, and the reason is reported.

### 7.7 Free-tier budget

| Resource | Usage |
| --- | --- |
| Groq 20b (small trial) | ~158 calls, own quota |
| Groq 120b (live runs) | ~300–400 calls, spread across runs |
| Qwen judge | ~600–700 grades at ~220 a day, so **2–3 days**; every step saves per row and resumes |

---

## 8. Testing

- **Unit tests:**
  - features: tokens, reasoning words, `num_questions` edge cases, clinical
  - rules: each branch and reason, cut-off boundaries
  - grounding: each failure rule, overlap maths, stopwords, citation markers stripped
- **Pipeline tests (fakes):**
  - small pass; small fail → escalated (2 calls, both costs, counterfactual)
  - large path
  - fallback on a 429 from either tier; both tiers failing → 503
  - 2-call cap
  - `force_model` bypasses the cache
  - grounding failure is not cached
  - `route_reason`, `grounding_*` and `escalated` are logged
- **Eval tests:** feature extraction from a `/retrieve` payload, the label rule, simulation maths on a toy table, choosing the setting, and the report.

---

## 9. Out of scope

- Router v2, the learned classifier (Phase 6, optional).
- A middle tier.
- Streaming.
- The demo chat page (backlog, Phase 6).
- Near-band cache verification.
