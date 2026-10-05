# Progress log

A running log of what was done, what was learned, and what's next. Newest at the bottom.

## 2026-09-30: Design

- Reviewed the original spec (`weir-original.md`) and found 9 gaps. Each is fixed in the design spec, §4.
- Decided the free-tier stack (see `decisions.md`, D0–D12).
- Wrote the implementation design: `superpowers/specs/2026-09-30-weir-design.md`.
- Set up the `docs/` folder and connected the repo to GitHub (`yatinannam/weir`).

- The user approved the design spec.

- Checked the free tiers (2026-09-30): Groq free list has gpt-oss-20b/120b, not Llama, with 8K tokens/min and 200K tokens/day per model. Recorded as decisions D13-D18 and updated the spec.
- Wrote the Phase 0 + 1 plan: `superpowers/plans/2026-09-30-phase-0-1-foundations-baseline.md` (16 tasks).

**Next:** the user reviews the plan and picks an execution method.

**Needed from the user before Phase 0:** a free Groq API key (console.groq.com) and a free Gemini API key (aistudio.google.com).

## 2026-10-01: Phase 0 exit ✅ (built on branch `phase-0-1`)

- Knowledge base: 40 fictional docs (30 public, 10 staff) with 8 planted look-alike pairs.
- hospital-rag: /retrieve, /generate, /info, /healthz. Groq gpt-oss-20b/120b and Gemini gemini-2.5-flash confirmed on the user's free keys.
- Weir pass-through gateway: auth (401/403), /v1/query → retrieve + generate, /healthz. Every request writes a weir.request_log row off the request path, priced at list prices.
- Exit check (real Groq): "ICU visiting hours" → cited answer from pub-visiting-hours-icu, 432 tokens in / 70 out, $0.000107 at list price, ~2 s.
- Whole-branch review: 4 Important findings fixed (malformed-reply handling, eval robustness + `rejudge`, time/number fact matching, localhost-only ports). Real gpt-oss output showed its native 【c1】 citation style, which hid sources; the parser now handles it.
- Learned: on Windows, `localhost` tries IPv6 first; DB URLs use 127.0.0.1. Git Bash rewrites `/app/...` paths in `docker exec` (use `MSYS_NO_PATHCONV=1`). Docker Desktop auto-updated mid-session and stopped containers once.

## 2026-10-01: Phase 1 exit ✅: baseline frozen

- Eval set: 50 queries (25 distinct, 3×5 paraphrase, 5×2 traps), split 33/17 by cluster.
- Baseline (always gpt-oss-120b, no cache): **cost/1k $0.0989**, **p50 853 ms / p95 6.0 s** (sequential), **judge 5.0/5**, **facts 1.00**, 0 errors. Details and frozen settings are in `results/baseline.md`.
- The judge moved Gemini → Qwen on Groq (D19, D20), because Gemini's free tier allows about 20 requests/day. The eval tools gained `rejudge` (re-grade saved answers, no Groq calls), per-row progress saving, and call pacing.
- Learned: the large model aces this set (ceiling effect), so any later drop is a real regression. Harder and unanswerable questions should be added before the final numbers.
- Spot checks: Claude did them at the user's request (2026-10-02). 10 eval questions and 5 graded answers were traced to their source sentences, and all are correct.
- **Gate:** Phase 2 (semantic cache) may start. **Next:** write the Phase 2 plan.

## 2026-10-02: Phase 2 design

- Agreed with the user: eval set grows to about 150 (D21); the threshold comes from a sweep (D22); follow-ups are tested in unit tests (D23); the feedback FK is dropped (D24).
- Wrote the Phase 2 addendum: `superpowers/specs/2026-10-02-phase-2-semantic-cache-design.md`. Work happens on branch `phase-2`.
- The user approved the addendum.
- Wrote the Phase 2 plan: `superpowers/plans/2026-10-02-phase-2-semantic-cache.md` (13 tasks).
- Correction: the Qwen judge is token-bound to about 220 grades/day (200K tokens/day), not 1,000. The plan judges separately and never re-grades.
- **Next:** the user reviews the plan, then it gets executed.

## 2026-10-02: Phase 2, cache live (Tasks 1–8)

- The semantic cache is built and switched on:
  - bypass rules, local bge-small embedder, pgvector lookup (namespace + kb/prompt version)
  - entity guard (lexicon in `configs/entities.yaml`), eligible write-back
  - background writes, version refresh and cleanup
  - `POST /v1/feedback` (thumbs-down evicts) and `DELETE /v1/cache` (admin)
- Live smoke test (real Groq):

  | Question | Result | Similarity | Time |
  | --- | --- | --- | --- |
  | "ICU visiting hours" | miss | — | 787 ms |
  | Same question again | **hit** | 1.0 | 7 ms, $0 |
  | Paraphrase "visit a patient in intensive care" | miss | 0.843, below the starting 0.92 | |
  | General-ward trap | miss | 0.772 | |

  Thumbs-down evicted the entry; the purge deleted 2. The hit row: cost $0, counterfactual $0.000109. Embedding ~5 ms, lookup 1–2 ms.
- Weir tests: 136 passing.
- **Next:** eval tooling, 100 new questions, baseline v2, threshold sweep.

## 2026-10-02: Phase 2, eval set, baseline v2, threshold

- **Eval set:** grew to 150 questions: +10 paraphrase clusters, +15 trap pairs, +10 unanswerable, +10 hard (subagent-drafted; facts traced by script).
- **Baseline v2 (150):** judge 4.93, facts 0.987, $0.0972 per 1k, p50 615 ms. The only misses are 3 hard two-document questions (retrieval k=4).
- **Bug found and fixed (D27):** the model sometimes answers half a question then writes NOT_FOUND. Such answers are never cached.
- **Threshold sweep:** **0.85** (D25 → D26). Zero wrong matches and zero trap pairs on every split. Without the entity guard the same threshold would give a 31% false-hit rate.
  - The sweep found 3 lexicon gaps (buildings, lost/damaged, packages) and 2 labelling bugs, all fixed with tests.
  - It also found one wrong-match type the guard can't see (timings vs room), which the safety margin covers.
- **Next:** cache run (cold pass + 300-request replay, workload repeat rate 73.7%), then results, the final review and merge.

## 2026-10-03: Phase 2 cache measured (superseded by the final-review fixes below)

- **Cold pass** (150 questions, empty cache):
  - 23% hits (56% of the paraphrases that could hit)
  - quality identical to baseline v2 (judge 4.93, facts 0.987)
  - 0 wrong hits; no trap ever got its look-alike's answer
- **Warm replay** (300 requests, 73.7% repeats):
  - **93.7% hits**
  - **cost per 1k $0.0972 → $0.0047 (−95%)**
  - **p50 615 ms → 53 ms**
  - quality equal to baseline on the same mix
- Over both runs, 71% of LLM cost was saved ($0.04376 → $0.01272 at list prices). A hit costs ~8 ms inside Weir against ~700 ms for a miss.
- Full write-up: `results/cache-only.md`.
- **Next:** final whole-branch review, then merge Phase 2 to main. After that, plan Phase 3 (router).

## 2026-10-03: Final review → fixes (Phase 2 not yet closed)

- The whole-branch review (fresh reviewer) found one critical and three important issues; all are fixed test-first:
  - **C1 / D29:** the guard missed numbers written as words or ordinals ("three days" vs "one day" before cancelling, different refunds, matched at 0.966).
  - **I1 / D30:** the sweep counted "two-part vs one-part answer" pairs as safe.
  - **I2 / D31:** a stuck database would stall each request about 30 s. The lookup budget is now 500 ms.
  - **I3 / D32:** a miss now updates the document version immediately after an edit.
- Added 4 number-word trap pairs (158 questions). The re-run sweep chose **0.90** (0 wrong, 0 trap matches on every split).
- 11 minor findings were deferred (listed in the session ledger and the final message).
- **Next:** re-run the cache measurement at 0.90 (cold pass + replay + grading), then update `results/cache-only.md`, then merge.

## 2026-10-03: Phase 2 exit ✅: cache re-measured at 0.90 after the review fixes

- **Baseline v3** (158 questions = v2 + 8 number-word traps): judge 4.90, facts 0.981, $0.098 per 1k, p50 617 ms.
- **Cold pass:**
  - 14.6% hits (37% of the paraphrases that could hit)
  - quality equal to baseline (judge 4.91 vs 4.90)
  - 0 wrong hits; no trap, including "three days" vs "one day", got its look-alike's answer
- **Warm replay** (300 requests, 73.7% repeats):
  - **93.3% hits**
  - **$0.098 → $0.0050 per 1k (−95%)**
  - **p50 617 → 56 ms**
  - quality equal to baseline on the same mix
- Over both runs 67% of LLM cost was saved (list prices). Full write-up: `results/cache-only.md`.
- **Next:** merge Phase 2 to main; then plan Phase 3 (router).

## 2026-10-04: Phase 3 (router) design

- Agreed with the user:
  - quality bar "no visible loss" (D33)
  - measure-first tuning via a small-model trial and offline simulation (D34)
  - only grounded answers cached; `force_model` bypasses the cache (D35)
  - demo chat page deferred to Phase 6; Grafana is the metrics display in Phase 4 (D36)
- Wrote the Phase 3 addendum: `superpowers/specs/2026-10-04-phase-3-router-design.md`. Added `backlog.md` (product ideas + the 11 deferred Phase 2 review findings). Work is on branch `phase-3`.
- The user approved the addendum.
- **Next:** write the Phase 3 implementation plan.

## 2026-10-04: Phase 3 (router) build, in progress

- Plan written and approved: `superpowers/plans/2026-10-04-phase-3-router.md` (13 tasks). Executed in-session, with a commit after each task once the user approves it.
- **Task 1:** router and grounding settings in `configs/weir.yaml` (starting values 20 tokens / 0.75 / 0.40 / overlap 0.5; at most 2 model calls, enforced by config validation). Migration `003_phase3_router.sql` (`route_reason`, `grounding_reason`, `grounding_overlap`). New overlays `small_only`, `router_only`, `full`.
- **Task 2:** `weir/router/features.py`: tokens, reasoning words (whole-word match), number of questions ("? and when" is not double-counted), retrieval scores, clinical flag.
- **Task 3:** `weir/router/rules.py`: `route()` with reasons kill_switch → force_model → router_disabled → clinical → weak_retrieval → simple → default_large. Only the last four ("router decisions") may fall back or escalate.
- **Task 4:** `weir/router/grounding.py`: rule-based check (not found, unfinished, no/invalid/unknown citations, partial answer, no content words, low overlap). The overlap is logged even on failure, so tuning can replay other cut-offs offline.
- **Audit before Task 5:** all suites green (weir 200, hospital-rag 39, eval 61), CI green on `phase-3` and `main`, lint clean on new code. hospital-rag accepts both model names and already strips citation markers, so grounding's marker stripping is only a safety net. No defects found.
- README rewritten: Mermaid architecture, request-lifecycle and router diagrams (replacing ASCII art that misaligned on GitHub), badges, the threshold-sweep chart, cleaner tables.
- **Task 5:** the pipeline routes every non-cached question after retrieval. A small answer that fails grounding is retried once on large; a rate-limited or timed-out tier falls back to the other; at most 2 model calls; cost is summed over every call; only grounded answers are cached; `force_model` requests bypass the cache (resolves backlog M9). Weir suite: 218 tests.
- **Task 6, live smoke test** (real Groq, `config_label = dev`, starting cut-offs, migration 003 applied to the dev DB):

  | Question | Route (reason) | Model | Top retrieval score | Grounding overlap | Latency | Cost |
  | --- | --- | --- | --: | --: | --: | --: |
  | "What are the ICU visiting hours?" | small (simple) | gpt-oss-20b | 0.911 | 0.89 ✓ | 694 ms | $0.000055 |
  | "Compare the general ward and private ward visiting rules, and explain why the ICU differs." | large (default_large) | gpt-oss-120b | 0.769 | 0.59 ✓ | 704 ms | $0.000194 |

  Both answers were correct and grounded, and `route_reason`, `grounding_*` and `model_calls` were logged. Note: the longer, reworded large answer scored 0.59 overlap, close to the 0.5 starting cut-off, so tuning `min_overlap` on real data (Tasks 9–10) matters.
- **Task 7:** `weir_eval features` asks hospital-rag `/retrieve` for every question and records the router's inputs with Weir's own `FeatureExtractor` (same tokenizer, reasoning words and clinical list as live), into `eval/datasets/features.jsonl`. No LLM calls. Eval suite: 63 tests.
- **Task 8:** `weir_eval export-grounding <report>` copies each answer's logged grounding result (reason, overlap) from `weir.request_log` into the report folder (`grounding.jsonl`), so tuning is reproducible from committed files. `weir_eval simulate` replays both models' measured answers through Weir's real `route()` over a 900-setting grid (no model calls, ~0.5 s) and picks the cheapest setting meeting the D33 bar on the tune split; a setting that routes nothing small never passes. Smoke-checked on the real baseline-v3 rows with stand-in data. Eval suite: 82 tests.
- **Task 9, features:** `eval/datasets/features.jsonl` for all 158 questions (110 tune, 48 holdout). Tokens 4–32 (median 13); top retrieval score 0.62–0.93 (median 0.81); 1 question with a reasoning word, 0 clinical, a few two-part questions. Since every top score is ≥ 0.62, the `weak_retrieval` rule (cut-offs 0.30–0.50) never fires on this set: tuning comes down to question length, the "simple" score cut-off and grounding overlap.
- **Task 9, small-model trial** (`eval/reports/20261004T171944Z-small_only-all`, gpt-oss-20b on all 158, cache off, no fallback/escalation): 0 errors, every answer from the small model. Facts **0.953** (baseline v3 0.981), cost **$0.0467 / 1k** (baseline $0.0980, −52%). Grounding at min_overlap 0.5: 144 passed, 14 `not_found` (the 10 unanswerable + 4 answerable questions the small model gave up on: q-141, q-143, q-150, q-157, which escalation would send to the large model). No `low_overlap` failures (overlap median 0.86, minimum 0.50). 4 answers missed a key fact yet passed grounding (q-036, q-129, q-151, q-152): grounding can't catch these, so the simulation relies on the judge grades to keep such questions off the small route. Judged: **judge 4.87** (baseline 4.90), 152/158 at 5/5, p95 754 ms (baseline 3.5 s).
- **Task 10, tuning** (`docs/results/router-tuning.md`):
  - The planned 900-setting grid had **no passing setting**. Every setting routed q-036 small (8 tokens, top score 0.855), and the small model omitted half its answer. q-154 (an invented extension number) also passed grounding.
  - 3 other "failures" were fact-matcher gaps ("90 %" with a space, a bare "2171"; judge 5/5), to be fixed separately.
  - The user chose **option A**: keep the strict bar and widen `high_confidence` to 0.60–0.95.
  - Result: 720/5,400 settings pass. Chosen: 16 tokens / 0.86 / 0.50 / overlap 0.6.
  - Simulated −6% cost, 13% routed small, zero quality loss on tune *and* holdout.
  - The rejected option B (looser bar) would have saved ~38% with 2 answers worse. Decision D37.
- **Fact-matcher fix (D38, user chose to fix it before the live runs):**
  - The key-fact matcher now treats "90 %", "90%", "90 percent" and "90 per cent" alike.
  - It reads "ext. 2171", "extension 2171", "extension is 2171" and "Extension number: 2171" as the number 2171. Whole-number matching still applies, so 2172 and 21710 don't match.
  - Facts were re-scored, with no model calls, on baseline v3 (unchanged, 0.981), the Phase 2 cache runs (cold pass 0.978 → **0.981**, now equal to baseline: q-019 "50 %"; replay unchanged) and the small trial (0.953 → **0.972**: q-129, q-151, q-152).
  - The cache sweep labels are unchanged (threshold still 0.90). The router simulation is identical (same 720 passing settings, same choice).
- **Task 11, live-run reporting:** every report's `summary.md` now has a **By route** table (judge, facts, cost per 1k, p50/p95 per route) and the escalation rate. `weir_eval gate <report>` checks a run against baseline v3 question by question (cost lower, judge within 0.1, facts no lower, small route ≥ large on its questions, 0 wrong cache hits). `weir_eval derive-workload` lays a per-question report onto the 300-request replay order, for the no-cache configs. Sanity checks on real data: the gate passes the Phase 2 cache cold run; the derived baseline replay reproduces the published 4.79 / 0.948 (repeat rate 73.7%). Eval suite: 105 tests.
- **Task 12, live runs** (2026-10-05, tuned config D37, real Groq; 616 requests, **0 errors**):

  | Run | Report | Cache hits | Routed small | Cost / 1k | p50 / p95 | Judge | Facts |
  | --- | --- | --: | --: | --: | --: | --: | --: |
  | Router only, 158 cold | `20261005T074414Z-router_only-all` | 0% | 12.7% | $0.0921 (−6%) | 781 ms / 1.5 s | 4.90 | 0.978 |
  | Full Weir, 158 cold (cache purged) | `20261005T082403Z-full-all` | 14.6% | 11.4% | $0.0763 (−22%) | 788 ms / 7.2 s | 4.89 | 0.975 |
  | Full Weir, 300 replay (73.7% repeats) | `20261005T085816Z-full-workload-300-seed7` | 89.7% | — | $0.0090 (−91%) | 16 ms / 709 ms | 4.79 | 0.947 |

  - **Simulation matched live:** router-only cost $0.0921 vs $0.0917 simulated, 12.7% vs 13% routed small. All 20 small-route answers scored 5/5 with full facts; 0 escalations.
  - **Fallback fired for real:** Groq's large model returned errors (HTTP 502) and slowed down for about 20 minutes during the full cold pass. 6 requests fell back to the small model instead of failing, which explains the 7.2 s p95.
  - **Replay hits 89.7% vs 93.3% in Phase 2:** 31 misses = 15× q-143 (the large model now says "couldn't find", which is never cached) + 10 from 8 large answers whose grounding overlap (0.38–0.57) was below `min_overlap` 0.6, so they weren't cached, although all 8 were judged 4–5/5 with full facts + 6 one-offs. The simulation tuned `min_overlap` for routing only; it didn't model that the same cut-off gates which large answers are cached.
  - **Gate vs baseline v3:** cost, judge, small route and 0 wrong hits all pass; "facts no lower" misses by 0.003–0.006. Every drop is on the large route (q-141, q-150). Re-asking with the plain baseline config showed it is the large model, not Weir: q-141 now gets "couldn't find" 3/3 times (it half-answered on Oct 1–3: drift), and q-150 flipped half-answer / couldn't find / half-answer within a minute (noise). Derived replays: `derived-baseline-v3-…` and `derived-router_only-…`.
  - **User decision:** run a same-day baseline (v4) and gate against it, so model drift affects both sides equally.
- **Baseline v4** (`20261005T091621Z-baseline-all`, same day, always large, no cache): judge 4.90, facts **0.978** (v3 0.981: q-141 drift confirmed), cost $0.0988 / 1k, p50/p95 767 ms / 1.1 s. Derived replay: `derived-baseline-v4-workload-300-seed7`.
- **Exit gate vs baseline v4:**

  | Report | Cost | Judge | Facts | Small route vs large | Wrong hits | Gate |
  | --- | --- | --- | --- | --- | --: | --- |
  | Router only, cold | −7% | 4.90 = 4.90 | 0.978 = 0.978 | 5.00 = 5.00 | 0 | pass |
  | Full Weir, cold | −23% | 4.89 vs 4.90 | 0.975 vs 0.978 | 5.00 = 5.00 | 0 | pass* |
  | Full Weir, 300 replay | −91% | 4.79 = 4.79 | 0.947 = 0.947 | — | 0 | pass |
  | Router only, replay (derived) | −4% | 4.79 = 4.79 | 0.947 = 0.947 | 5.00 = 5.00 | 0 | pass |

  \* The only difference is q-150 on the **large** route (judge 2 → 1), which the large model flipped 3 times in a minute with the plain baseline config: model noise, not Weir (same rule as q-019 in Phase 2).
- **D39:** `grounding.min_overlap` lowered 0.6 → 0.3 (user chose option A): 0.6 kept 8 good large answers out of the cache. Re-measuring full Weir (cold + 300 replay) with 0.3.
- **D39 re-run, degraded** (`20261005T095916Z-full-all`, `20261005T104855Z-full-workload-300-seed7`, min_overlap 0.3): Groq **rate-limited the large model 113 times** (the free-tier daily allowance for gpt-oss-120b ran out after ~600 large calls today). Weir **fell back to the small model** each time: **0 errors in 458 requests**; cold judge 4.87 (v4 4.90), replay 93.0% hits, $0.0030 / 1k, judge 4.79 = baseline. But 93 of 117 large-routed cold questions were answered by the small model (cost −52% is the outage, not the router), the two known small-model mistakes (q-036, q-154) came through on fallback, and the cache filled with small answers. **Not a clean measurement of D39**; kept as an outage/resilience record. Design gap found: fallback answers are cached, so degraded answers outlive the outage by the cache TTL.
