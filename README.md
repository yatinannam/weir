# Weir

**A gateway in front of a RAG service that decides, for every request, whether an LLM call is needed at all, and which model should make it.**

Weir answers repeated questions from a **semantic cache**, will route the rest to the **cheapest model that can handle them** (Phase 3, in progress), and logs **cost and latency for every request** so the savings can be proven. It wraps an existing RAG service; it is not a new retriever, vector database or LLM framework.

> **Status:** Phases 0–2 are done (gateway, baseline, semantic cache). Phase 3 (router) is designed and about to be built. Everything runs on free tiers.

## Results so far

Measured on a fictional hospital FAQ ("Weir General Hospital"), with 158 eval questions including look-alike traps. Costs are at list prices; real spend is $0 on free tiers.

| Configuration | Requests | Cache hit rate | Cost / 1,000 requests | p50 latency | Judge (1–5) | Facts | Wrong cache hits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (no cache, always large model) | 158 | 0% | $0.0980 | 617 ms | 4.90 | 0.981 | — |
| Cache only, cold pass | 158 | 14.6% | $0.0847 | 686 ms | 4.91 | 0.978 | **0** |
| Cache only, warm replay (73.7% repeats) | 300 | **93.3%** | **$0.0050** | **56 ms** | 4.79 | 0.948 | **0** |

- **On repeat-heavy traffic, the cache cuts LLM cost per 1,000 requests by 95% and median latency by 11×, with no quality loss.** On the same 300-request mix, the baseline also scores 4.79 / 0.948.
- **The entity guard is what makes it safe.** At the chosen 0.90 similarity threshold, embedding similarity alone would serve the wrong answer for **37%** of accepted matches ("ICU visiting hours" vs "general ward visiting hours"). With the guard, **0%**.
- Details: [`docs/results/cache-only.md`](docs/results/cache-only.md), [`docs/results/cache-threshold.md`](docs/results/cache-threshold.md), [`docs/results/baseline.md`](docs/results/baseline.md).

## Architecture

```
 client / eval runner / k6
        │  POST /v1/query  (X-API-Key)
        ▼
 ┌──────────────┐   /retrieve  /generate  /info    ┌──────────────────┐
 │  weir :8000  │ ───────────────────────────────▶ │ hospital-rag     │ ──▶ Groq (gpt-oss-20b / 120b)
 │  gateway     │                                  │ :8001 (RAG)      │     or stub mode
 └──────┬───────┘                                  └────────┬─────────┘
        │ weir.cache_entries, weir.request_log              │ rag.documents, rag.chunks
        ▼                                                   ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  Postgres 16 + pgvector 0.8 (HNSW, iterative scan)   127.0.0.1:5432  │
 └─────────────────────────────────────────────────────────────────────┘
```

### Request flow

1. **Auth.** The `X-API-Key` maps to a tenant. A namespace the key isn't allowed returns 403.
2. **Bypass rules.** These requests skip the cache:
   - personalised requests, and the `bypass_cache` option
   - time-sensitive ("now", "today"), clinical, and follow-up questions
   - the kill switch, or a namespace with the cache disabled
   - no known `kb_version`
3. **Embed and look up.** `bge-small-en-v1.5` (local, 384-d) embeds the normalized query. pgvector returns the top 3 entries filtered by `namespace + kb_version + prompt_version` and not expired. The whole step has a 500 ms budget; a timeout means bypass.
4. **Entity guard.** A candidate at or above the threshold (0.90) is only a hit if both questions share the same numbers (including number words and ordinals), negation and lexicon terms: wards, departments, people, vehicles, payment, days, buildings and so on. The lexicon is in [`configs/entities.yaml`](configs/entities.yaml).
5. **Hit:** replay the stored answer and sources. Cost is the embedding cost only. The counterfactual cost (the stored tokens at the large-model price) is logged.
6. **Miss:** hospital-rag `/retrieve` then `/generate`. The answer is stored in the background only if it is eligible: cited, confident retrieval, no "couldn't find", not truncated or partial, no personal data.
7. **Log.** One `weir.request_log` row per request, written off the request path: cache status, similarity, route, tokens, cost, counterfactual cost, per-stage latency.

**Invalidation:**
- TTL (24 h)
- any `kb_version` change (a content hash of the documents; misses pick it up immediately)
- `DELETE /v1/cache` by namespace, source document or entry
- a thumbs-down via `POST /v1/feedback` evicts the entry that served the request

## Stack (all free)

| Layer | Choice |
| --- | --- |
| API | Python 3.12, FastAPI, uvicorn, `uv` |
| Storage and vector search | Postgres 16 + pgvector 0.8, psycopg 3 (async pool) |
| Embeddings | `BAAI/bge-small-en-v1.5` via fastembed (CPU, baked into the images) |
| LLMs | Groq free tier: `openai/gpt-oss-20b` (small), `openai/gpt-oss-120b` (large) |
| Eval judge | `qwen/qwen3.8-27b` on Groq (a different model family from the models under test) |
| Packaging | Docker Compose, GitHub Actions CI (three test suites against pgvector) |
| Planned | Prometheus + Grafana (Phase 4), k6 load tests (Phase 5) |

## Repository layout

```text
services/
  weir/            gateway: pipeline, cache (embedder, store, entity guard, bypass rules, versions),
                   auth, admin API, pricing, async request logger, migrations runner
  hospital-rag/    the RAG service Weir wraps: ingest, /retrieve, /generate (citations, NOT_FOUND), stub LLM
eval/              eval set (158 queries), key-fact checks, LLM judge, runner, threshold sweep,
                   workload replay, reports/ (every raw result is committed)
kb/                fictional hospital knowledge base (40 Markdown docs, public + staff namespaces)
configs/           weir.yaml (all thresholds), ablations/, entities.yaml, tenants.yaml, prices.yaml
db/migrations/     SQL schema (001 init, 002 cache)
docs/              design specs, implementation plans, decision log, progress log, results, backlog
```

## Quick start

**Prerequisites:** Docker Desktop and [uv](https://docs.astral.sh/uv/), plus free API keys from [Groq](https://console.groq.com/keys) (and optionally [Gemini](https://aistudio.google.com/apikey)).

```bash
cp .env.example .env
# fill in GROQ_API_KEY and generate three tenant keys:
uv run python -c "import secrets; print(secrets.token_urlsafe(24))"   # WEIR_KEY_PUBLIC / _STAFF / _ADMIN

docker compose up -d --build            # postgres, migrate, hospital-rag, weir
MSYS_NO_PATHCONV=1 docker compose exec hospital-rag python -m hospital_rag.ingest --kb /app/kb
```

`MSYS_NO_PATHCONV=1` is only needed in Git Bash on Windows.

Ask a question twice. The second time it is a cache hit:

```bash
curl -s localhost:8000/v1/query -H "X-API-Key: $WEIR_KEY_PUBLIC" -H 'content-type: application/json' \
  -d '{"query":"What are the ICU visiting hours?","namespace":"weir-general/en/public"}'
```

Response:

```json
{
  "answer": "The ICU can be visited twice daily: 11 am – 11:30 am and 5 pm – 6 pm…",
  "sources": [{"id": "pub-visiting-hours-icu", "title": "ICU visiting hours"}],
  "meta": {"request_id": "…", "cache_status": "hit", "similarity": 1.0, "route": "none",
           "escalated": false, "model": "openai/gpt-oss-120b", "latency_ms": 7, "cost_usd": 0.0}
}
```

Interactive API docs are at <http://localhost:8000/docs>. Set `LLM_MODE=stub` in `.env` to run without Groq (fixed-latency fake answers, for load tests).

## API

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `POST /v1/query` | tenant key | Answer a question. `{query, namespace, session_id?, personalized?, options: {bypass_cache?, force_model?}}` |
| `POST /v1/feedback` | tenant key | `{request_id, rating: 1 \| -1, comment?}`. A -1 evicts the cache entry that served the request. |
| `DELETE /v1/cache` | admin key | Purge by exactly one of `?namespace=`, `?source_id=`, `?entry_id=` |
| `GET /healthz` | none | DB and RAG health, plus the active `config_label` |

Every response carries `X-Request-ID`, which is also the primary key of its `weir.request_log` row.

## Configuration

Every threshold lives in [`configs/weir.yaml`](configs/weir.yaml): cache threshold, candidates, TTL, lookup budget, bypass keyword lists, models, kill switches, per-namespace policy.

Ablations are overlays selected with `WEIR_ABLATION=<name>`:

| Overlay | Cache | Model |
| --- | --- | --- |
| `baseline` | off | always large |
| `cache_only` | on | always large |

Phase 3 adds `small_only`, `router_only` and `full`.

## Evaluation

The `eval/` package replays questions through Weir and scores every answer two ways:
- **key facts:** canonicalised whole-number matching
- **an LLM judge:** a 1–5 rubric with a disk cache

```bash
cd eval
uv run --env-file ../.env python -m weir_eval validate                          # check the 158-question set against the KB
uv run --env-file ../.env python -m weir_eval run --config baseline --split all --no-judge
uv run --env-file ../.env python -m weir_eval rejudge reports/<run>             # grade later; resumable
uv run python -m weir_eval sweep                                                # threshold sweep (no LLM calls)
uv run python -m weir_eval make-workload --n 300 --seed 7                       # Zipf-skewed replay list
uv run --env-file ../.env python -m weir_eval run --config cache_only --workload datasets/workload-300-seed7.jsonl
```

**The question set:**
- 35 distinct questions
- 13 paraphrase clusters of 5
- 24 look-alike trap pairs
- 10 unanswerable questions

It is split 70/30 by cluster into tune and holdout. Every run's raw `results.jsonl` and `summary.md` is committed under `eval/reports/`.

## Tests

```bash
docker compose up -d postgres                    # DB tests use 127.0.0.1:5432/weir_test
cd services/weir         && uv run pytest -q     # 150 tests
cd services/hospital-rag && uv run pytest -q     #  39 tests
cd eval                  && uv run pytest -q     #  61 tests
```

CI runs all three suites on every push.

## Documentation

| Doc | Contents |
| --- | --- |
| [`docs/weir-original.md`](docs/weir-original.md) | The original vision: goals, risks, evaluation plan |
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | Implementation design and per-phase addenda (cache, router) |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Task-by-task implementation plans |
| [`docs/decisions.md`](docs/decisions.md) | Every decision (D0–D36) with alternatives and reasons |
| [`docs/progress.md`](docs/progress.md) | Phase-by-phase log |
| [`docs/results/`](docs/results/) | Baseline, threshold sweep and cache results |
| [`docs/backlog.md`](docs/backlog.md) | Deferred findings and ideas (for example the demo chat page) |

## Limitations

- **The knowledge base is synthetic** and the eval set is small (158 questions, 24 trap pairs). "Zero wrong hits" is strong evidence for this set, not a guarantee.
- **Hit rate depends on the workload.** The 93% figure is for a 73.7%-repeat replay; a cold pass with only paraphrases repeating hits 15%.
- **Latency numbers are sequential and paced, not load-tested.** That's Phase 5.
- **The cache replays answers exactly as first written,** including any omission the model made. The Phase 3 grounding check targets this.

## Roadmap

| Phase | Work | Status |
| --- | --- | --- |
| 0–1 | Gateway, RAG adapter, request logging, eval set, baseline | ✅ |
| 2 | Semantic cache, entity guard, threshold sweep, cache eval | ✅ |
| 3 | Router: small vs large model, grounding check, escalation, offline-tuned rules | Designed |
| 4 | Prometheus counters, Grafana dashboard, alerts | Planned |
| 5 | k6 load tests (cold/warm, ramp, spike, soak), four-way ablation table | Planned |
| 6 | Polish: demo chat page, write-up, optional learned router | Planned |
