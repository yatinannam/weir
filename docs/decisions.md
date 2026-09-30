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
