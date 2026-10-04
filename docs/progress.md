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
- **Next:** Task 5, pipeline integration (route, fallback, escalation, 2-call cap, grounding-gated cache).
