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
