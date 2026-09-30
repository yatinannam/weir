# Decision log

Newest at the bottom. Each entry gives the date, the decision, the alternatives considered and the reason. The full context is in the [design spec](superpowers/specs/2026-09-30-weir-design.md).

| Date | # | Decision | Alternatives | Reason |
| --- | --- | --- | --- | --- |
| 2026-09-30 | D0 | Zero spend: only free tools and free tiers | none | User constraint |
| 2026-09-30 | D1 | Groq free tier for the small and large LLMs | Gemini free tier, local Ollama | Free, very fast, OpenAI-compatible, separate rate limits per model allow fallback |
| 2026-09-30 | D2 | Gemini free tier as the eval judge | Groq model as judge | A different model family from the models under test |
| 2026-09-30 | D3 | `bge-small-en-v1.5` via `fastembed`, local, 384 dimensions | Paid embedding API | Free, offline, no PyTorch |
| 2026-09-30 | D4 | Fictional "Weir General Hospital" knowledge base | Govt health scheme FAQs, FastAPI docs | HMS fit, no licensing or privacy risk, exact ground truth, plantable traps |
| 2026-09-30 | D5 | Two services: `hospital-rag` and `weir` | One app, or an open-source RAG app | Honest "gateway in front of a service" story, clean baseline |
| 2026-09-30 | D6 | Rule-based grounding check | LLM grounding check | Saves free-tier calls, adds no latency |
| 2026-09-30 | D7 | Cost priced at published paid-tier list prices, embeddings $0 | Report $0 | Honest "production cost" comparison |
| 2026-09-30 | D8 | Near-band LLM verification out of v1 | Include it | Free-tier budget. Revisit after the threshold sweep. |
| 2026-09-30 | D9 | Shadow sampling runs in the eval runner, not live | Live shadow calls | Free-tier budget |
| 2026-09-30 | D10 | k6 `constant-arrival-rate` for load tests | Locust | Open-model load, so the latency tail isn't hidden |
| 2026-09-30 | D11 | Stub LLM mode for heavy load tests | Real models | Free-tier rate limits |
| 2026-09-30 | D12 | Public GitHub repo `yatinannam/weir` | none | User |
| 2026-09-30 | D13 | Small `openai/gpt-oss-20b`, large `openai/gpt-oss-120b` on Groq; list prices $0.075/$0.30 and $0.15/$0.60 per 1M tokens | Llama 3.1 8B / 3.3 70B | Llama models are not on Groq's free-tier list (checked 2026-09-30). gpt-oss models are free-tier, with published prices. |
| 2026-09-30 | D14 | Chunks of 250 tokens or fewer, retrieve `k = 4`, eval throttled to about 4 requests/min | 300-token chunks, k = 5 | Free tier allows 8K tokens/min and 200K tokens/day per model |
| 2026-09-30 | D15 | Judge model `gemini-2.5-flash` (config value) | Newer Flash versions | Long-standing free-tier model. Can be swapped in config after listing the models available to the key. |
| 2026-09-30 | D16 | Eval baseline runs through Weir with the `baseline` ablation; load-test baseline hits hospital-rag directly | Eval calls hospital-rag directly | One cost/log code path, and a like-for-like gateway hop |
| 2026-09-30 | D17 | `kb_version` is a content hash of each namespace's documents | Manual version flag | Can't forget to bump it |
| 2026-09-30 | D18 | `options.force_model` takes a tier (`small`/`large`), not a model ID; `sensitive` flag lives in `weir.yaml` | Raw model IDs; flag in tenants.yaml | Callers can't pick arbitrary (unpriced) models; one place for namespace policy |
