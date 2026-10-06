<div align="center">

# Weir

**A cost-aware gateway for RAG: a semantic cache, a model router and per-request cost accounting.**

[![tests](https://github.com/yatinannam/weir/actions/workflows/tests.yml/badge.svg)](https://github.com/yatinannam/weir/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![postgres](https://img.shields.io/badge/Postgres_16-pgvector_0.8-4169E1?logo=postgresql&logoColor=white)
![cost](https://img.shields.io/badge/infra_cost-%240_(free_tiers)-success)

</div>

Weir sits in front of an existing RAG service and decides, for every request:
1. Does this need an LLM call at all? This is the **semantic cache**.
2. Which model is the cheapest that can answer it well? This is the **router**.

It logs the **cost, counterfactual cost and latency of every request**, so each saving is measured, not assumed. Weir is not a retriever, vector database or LLM framework. It wraps a RAG service it does not own.

> [!NOTE]
> **Status:**
> - **Done:** Phases 0–2 (gateway, baseline, semantic cache).
> - **Phase 3 (router):** built, tuned offline and measured live; every exit-gate check passes. The final whole-branch code review is next.
> - Everything runs on free tiers.

## Contents

[Results](#results) · [Architecture](#architecture) · [Request lifecycle](#request-lifecycle) · [Semantic cache](#semantic-cache) · [Router](#router-phase-3) · [Stack](#stack) · [Quick start](#quick-start) · [API](#api) · [Configuration](#configuration) · [Evaluation](#evaluation) · [Tests](#tests) · [Docs](#documentation) · [Limitations](#limitations) · [Roadmap](#roadmap)

---

## Results

These are measured on *Weir General Hospital*, a fictional hospital FAQ: 40 documents and 158 eval questions, including look-alike trap pairs. The models are real Groq models, graded by a Qwen judge plus key-fact checks. Costs are at provider list prices; actual spend is $0.

**Cold pass** (158 questions, each asked once):

| Configuration | Cache hits | Routed small | Cost / 1k req | p50 | Judge (1–5) | Key facts | Wrong cache hits |
| :-- | --: | --: | --: | --: | --: | --: | --: |
| Baseline: always the large model, no cache | 0% | 0% | $0.0988 | 767 ms | 4.90 | 0.978 | — |
| Cache only | 14.6% | 0% | $0.0847 (−14%) | 686 ms | 4.91 | 0.981 | **0** |
| Router only | 0% | 12.7% | $0.0921 (−7%) | 781 ms | 4.90 | 0.978 | — |
| **Full Weir** (cache + router) | 14.6% | 11.4% | **$0.0786 (−20%)** | 876 ms | **4.90** | **0.978** | **0** |

**Replay** (300 requests, Zipf-skewed, 73.7% repeats):

| Configuration | Cache hits | Cost / 1k req | p50 | Judge (1–5) | Key facts | Wrong cache hits |
| :-- | --: | --: | --: | --: | --: | --: |
| Baseline (derived per question) | 0% | $0.0970 | 747 ms | 4.79 | 0.947 | — |
| Cache only | 93.3% | $0.0050 | 56 ms | 4.79 | 0.948 | **0** |
| **Full Weir** | **93.0%** | **$0.0055 (−94%)** | **14 ms** | **4.79** | **0.948** | **0** |

- **On repeat-heavy traffic, full Weir cuts cost per 1,000 requests by 94% and median latency by about 50× (747 ms → 14 ms), with quality equal to the baseline on the same mix.** On a cold pass, where only paraphrases repeat, it still saves 20% with identical judge and facts.
- **The router adds a modest, safe saving.** It sends 13% of questions to the small model, which answered every one of them at 5/5 with full facts. That cuts router-only cost by 7% with judge and facts unchanged. The strict "no visible loss" bar limits it; a looser bar would have saved ~38% at the cost of 2 wrong answers in 158 ([`router-tuning.md`](docs/results/router-tuning.md)).
- **It degrades gracefully.** When Groq's large model failed (HTTP 502s, then a daily rate limit), Weir fell back to the small model: **0 errors across 1,232 live requests on 2026-10-05**.
- **The entity guard is what makes caching safe.** At the chosen 0.90 threshold, embedding similarity alone would serve the wrong answer for **37%** of accepted matches (for example "ICU visiting hours" vs "general ward visiting hours"). With the guard, that drops to **0%**.

<p align="center">
  <img src="docs/results/cache-threshold.png" alt="Cache threshold sweep: hit rate and false-hit rate with and without the entity guard" width="720">
</p>

Phase 3 rows are compared with baseline v4, re-run on 2026-10-05 because the large model drifted between runs; full Weir was measured on 2026-10-06 with the final settings (D39, D40). Full write-ups:
- [`summary.md`](docs/results/summary.md): the four-way ablation, both workloads
- [`router.md`](docs/results/router.md): live router results, exit gate, the two outage incidents
- [`router-tuning.md`](docs/results/router-tuning.md): offline tuning and the option not taken
- [`cache-only.md`](docs/results/cache-only.md), [`cache-threshold.md`](docs/results/cache-threshold.md), [`baseline.md`](docs/results/baseline.md)

## Architecture

```mermaid
flowchart TB
    client(["Client · eval runner · k6"])

    subgraph gw["weir · gateway :8000"]
        direction LR
        auth["Auth +<br/>tenant policy"] --> bypass["Bypass<br/>rules"] --> cache["Semantic cache<br/>bge-small + entity guard"] --> router["Router<br/>features → rules"] --> ground["Grounding<br/>check"]
    end

    subgraph rag["hospital-rag :8001"]
        direction LR
        retrieve["POST /retrieve<br/>pgvector top-k"] ~~~ generate["POST /generate<br/>cited answer"]
    end

    groq[("Groq<br/>gpt-oss-20b · gpt-oss-120b")]
    pg[("Postgres 16 + pgvector")]

    client -- "POST /v1/query" --> gw
    gw -- "retrieve, then generate with the chosen model" --> rag
    rag -- "LLM call" --> groq
    gw <-- "cache_entries · request_log (async)" --> pg
    rag <-- "documents · chunks" --> pg
```

| Service | Role | Owns |
| :-- | :-- | :-- |
| `weir` | The gateway: auth, cache, router, cost accounting, admin API | `weir.cache_entries`, `weir.request_log`, `weir.feedback`, `weir.model_prices` |
| `hospital-rag` | The RAG service being wrapped: ingest, vector retrieval, cited generation, stub LLM mode | `rag.documents`, `rag.chunks`, `rag.kb_versions` |
| `postgres` | pgvector 0.8 with HNSW and iterative scan; only exposed on `127.0.0.1` | — |

## Request lifecycle

```mermaid
flowchart TD
    A["POST /v1/query"] --> B{"Key allowed<br/>for namespace?"}
    B -- no --> X["403"]
    B -- yes --> C{"Bypass<br/>rule?"}
    C -- yes --> R["Retrieve chunks"]
    C -- no --> D["Embed + top-3 lookup<br/>same namespace · kb_version · prompt_version<br/>500 ms budget"]
    D --> E{"similarity ≥ 0.90<br/>and same entities?"}
    E -- yes --> HIT["Cache hit: replay stored answer"]
    E -- no --> R
    R --> F{"Router"}
    F -- "simple, strong match" --> S["Small model"]
    F -- "otherwise" --> L["Large model"]
    S --> G{"Grounded?"}
    G -- "no: escalate once" --> L
    G -- yes --> OUT["Answer + sources"]
    L --> OUT
    OUT --> W["Store in background<br/>if grounded and eligible"]
    HIT --> LOG[("request_log row:<br/>cost · counterfactual · latency per stage")]
    W --> LOG
```

Every response carries `X-Request-ID`, which is also the primary key of its log row. The log is written off the request path, so a logging failure never fails a request.

## Semantic cache

| Stage | What happens |
| :-- | :-- |
| **Bypass** | Personalised, time-sensitive ("now", "today"), clinical and follow-up questions never touch the cache. Neither do forced-model requests, a disabled namespace or the kill switch. |
| **Lookup** | The normalised query is embedded with local `bge-small-en-v1.5` (384-d). pgvector returns the top 3 entries for the same `namespace + kb_version + prompt_version` that haven't expired. The step has a 500 ms budget; on timeout the request bypasses the cache. |
| **Entity guard** | A candidate at or above the 0.90 threshold is a hit only if both questions share the same numbers (including number words and ordinals), negation and lexicon terms: wards, departments, people, vehicles, payment, days, buildings and more. The lexicon is in [`entities.yaml`](configs/entities.yaml). |
| **Write-back** | An answer is stored in the background only if it is grounded and cited, retrieval was confident, it isn't "couldn't find" and it wasn't truncated, partial or carrying personal data. |
| **Invalidation** | TTL of 24 h. A `kb_version` change (a content hash of the documents) is picked up by the next miss. `DELETE /v1/cache` purges by namespace, source document or entry. A thumbs-down evicts the entry that served it. |

## Router (Phase 3)

```mermaid
flowchart TD
    F["Features<br/>tokens · reasoning words · #questions<br/>top retrieval score · clinical"] --> K{"kill switch?"}
    K -- yes --> L1["large · kill_switch"]
    K -- no --> FM{"force_model?"}
    FM -- yes --> T1["forced tier · force_model"]
    FM -- no --> EN{"router enabled?"}
    EN -- no --> T2["default tier · router_disabled"]
    EN -- yes --> CL{"clinical?"}
    CL -- yes --> L2["large · clinical"]
    CL -- no --> WR{"top score below<br/>low cut-off?"}
    WR -- yes --> L3["large · weak_retrieval"]
    WR -- no --> SM{"short, one question,<br/>no reasoning words,<br/>top score ≥ high cut-off?"}
    SM -- yes --> S1["small · simple"]
    SM -- no --> L4["large · default_large"]
```

- **Grounding check** (rule-based, no extra LLM call). An answer passes only if:
  - it was found and finished
  - it cites at least one chunk, and every citation is valid
  - it didn't give up partway ("NOT_FOUND" mid-answer)
  - at least `min_overlap` of its content words appear in the cited chunks
- **Escalation and fallback:**
  - A small answer that fails grounding is retried once on the large model.
  - A rate-limited or timed-out tier falls back to the other tier.
  - Never more than 2 model calls per request.
  - Forced and disabled routes never adapt.
  - An answer from a fallback down to the small model is never cached, so a stand-in answer can't outlive an outage (D40).
- **Offline tuning.** The cut-offs are tuned without a single model call: the router replays both models' measured answers to all 158 questions over a grid of 5,400 settings. The cheapest setting that meets the quality bar wins. The bar is "no visible loss" (D33):
  - judge within 0.1 of the baseline
  - facts no lower
  - the small route no worse than the large model on the same questions
- **Tuned values** (D37, D39): small only if the question is at most **16 tokens**, a single question with no reasoning words, and its top retrieval score is at least **0.86**; grounding `min_overlap` **0.3**. The live router matched the simulation almost exactly: 12.7% routed small vs 13% predicted, −7% vs −6%.

## Stack

| Layer | Choice | Why |
| :-- | :-- | :-- |
| API | Python 3.12, FastAPI, uvicorn, `uv` | Async I/O, typed request models, fast installs |
| Vector store | Postgres 16 + pgvector 0.8 (HNSW, `iterative_scan = relaxed_order`), psycopg 3 async pool | One database for vectors, cache metadata and logs; filtered ANN without recall loss |
| Embeddings | `BAAI/bge-small-en-v1.5` via fastembed (CPU, baked into images) | Free, offline, no PyTorch |
| LLMs | Groq free tier: `openai/gpt-oss-20b` (small), `openai/gpt-oss-120b` (large) | Fast; separate per-model quotas allow fallback |
| Eval judge | `qwen/qwen3.8-27b` on Groq | A different model family from the models under test |
| Packaging and CI | Docker Compose, GitHub Actions (3 suites against pgvector) | — |
| Planned | Prometheus + Grafana (Phase 4), k6 (Phase 5) | — |

## Repository layout

```text
services/
├── weir/               gateway
│   └── src/weir/
│       ├── pipeline.py     request pipeline: bypass → cache → retrieve → route → generate → log
│       ├── cache/          embedder, pgvector store, entity guard, bypass rules, kb versions
│       ├── router/         features, rules v1, grounding check            (Phase 3)
│       ├── rag/            hospital-rag HTTP adapter
│       ├── metrics/        async request-log writer
│       └── llm/            price table (effective-dated)
└── hospital-rag/       the RAG service Weir wraps: ingest, /retrieve, /generate, stub LLM
eval/                   eval set (158 questions), key-fact checks, LLM judge, runner,
                        threshold sweep, workload replay; reports/ holds every raw result
kb/                     fictional hospital knowledge base (40 Markdown docs, public + staff)
configs/                weir.yaml (every threshold), ablations/, entities.yaml, tenants.yaml, prices.yaml
db/migrations/          001 init · 002 cache · 003 router
docs/                   specs, plans, decision log, progress log, results, backlog
```

## Quick start

**Prerequisites:**
- Docker Desktop and [uv](https://docs.astral.sh/uv/)
- a free [Groq API key](https://console.groq.com/keys)

```bash
cp .env.example .env
# Fill in GROQ_API_KEY, then generate three tenant keys (WEIR_KEY_PUBLIC / _STAFF / _ADMIN):
uv run python -c "import secrets; print(secrets.token_urlsafe(24))"

docker compose up -d --build                     # postgres, migrations, hospital-rag, weir
docker compose exec hospital-rag python -m hospital_rag.ingest --kb /app/kb
```

> [!TIP]
> **On Windows:**
> - In Git Bash, prefix the `exec` command with `MSYS_NO_PATHCONV=1`.
> - Use `127.0.0.1` rather than `localhost`, which can stall on IPv6.

Ask the same question twice. The second time it is a cache hit:

```bash
curl -s http://127.0.0.1:8000/v1/query \
  -H "X-API-Key: $WEIR_KEY_PUBLIC" -H 'content-type: application/json' \
  -d '{"query": "What are the ICU visiting hours?", "namespace": "weir-general/en/public"}'
```

```json
{
  "answer": "The ICU can be visited twice daily: 11 am – 11:30 am and 5 pm – 6 pm…",
  "sources": [{ "id": "pub-visiting-hours-icu", "title": "ICU visiting hours" }],
  "meta": {
    "request_id": "…",
    "cache_status": "hit",
    "similarity": 1.0,
    "route": "none",
    "escalated": false,
    "model": "openai/gpt-oss-120b",
    "latency_ms": 7,
    "cost_usd": 0.0
  }
}
```

Interactive API docs are at <http://127.0.0.1:8000/docs>. Set `LLM_MODE=stub` in `.env` to run without Groq, with fixed-latency fake answers for load tests.

## API

| Endpoint | Auth | Purpose |
| :-- | :-- | :-- |
| `POST /v1/query` | tenant key | Answers a question. Body: `query`, `namespace`, optional `session_id` and `personalized`, `options.bypass_cache`, `options.force_model` (`small` or `large`). |
| `POST /v1/feedback` | tenant key | Body: `request_id`, `rating` (`1` or `-1`), optional `comment`. A `-1` evicts the cache entry that served the request. |
| `DELETE /v1/cache` | admin key | Purges by exactly one of `namespace`, `source_id` or `entry_id`. |
| `GET /healthz` | none | Database and RAG health, plus the active `config_label`. |

Errors carry the `request_id`:
- a provider rate limit → `503` with `Retry-After`
- a timeout → `504`
- a bad upstream response → `502`

## Configuration

Every threshold lives in [`configs/weir.yaml`](configs/weir.yaml), and unknown keys are rejected:
- cache: threshold, candidates, TTL, lookup budget
- bypass keyword lists
- models
- router cut-offs and reasoning words
- grounding `min_overlap`
- kill switches
- per-namespace policy

Experiments change config, not code. Ablations are overlays selected with `WEIR_ABLATION=<name>`:

| Overlay | Cache | Router | Purpose |
| :-- | :-: | :-: | :-- |
| `baseline` | off | forced large | The "before" number |
| `cache_only` | on | forced large | Phase 2 result |
| `small_only` | off | off, small | Small-model trial for offline tuning |
| `router_only` | off | on | Router on its own |
| `full` | on | on | Full Weir |

## Evaluation

Every answer is scored two ways:
- **key facts:** canonicalised whole-number matching against the answer key
- **an LLM judge:** a 1–5 rubric, with a disk cache and resumable grading

```bash
cd eval
uv run --env-file ../.env python -m weir_eval validate                    # check the question set against the KB
uv run --env-file ../.env python -m weir_eval run --config baseline --split all --no-judge \
  --weir-url http://127.0.0.1:8000
uv run --env-file ../.env python -m weir_eval rejudge reports/<run>       # grade later; resumable
uv run python -m weir_eval sweep                                          # threshold sweep, no LLM calls
uv run python -m weir_eval make-workload --n 300 --seed 7                 # Zipf-skewed replay order

# Phase 3 router tuning and checks (no model calls)
uv run python -m weir_eval features                                       # router inputs for every question
uv run python -m weir_eval export-grounding reports/<small-trial>         # grounding results from the request log
uv run python -m weir_eval simulate --small reports/<small-trial>         # replay both models over the rule grid
uv run python -m weir_eval gate reports/<run>                             # exit gate vs baseline v3, same questions
uv run python -m weir_eval derive-workload reports/<run> --workload datasets/workload-300-seed7.jsonl --out reports/<name>
```

| Question group | Count | Purpose |
| :-- | --: | :-- |
| Distinct | 35 | Coverage of the KB |
| Paraphrase clusters (13 × 5) | 65 | Cache recall |
| Look-alike trap pairs (24 pairs) | 48 | Cache safety: same wording, different answer |
| Unanswerable | 10 | "Couldn't find" behaviour, never cached |

The set is split 70/30 by cluster into tune and holdout. Every run's raw `results.jsonl` and `summary.md` is committed under [`eval/reports/`](eval/reports/).

## Tests

```bash
docker compose up -d postgres                       # DB tests use 127.0.0.1:5432/weir_test
cd services/weir         && uv run pytest -q        # 221 tests
cd services/hospital-rag && uv run pytest -q        #  39 tests
cd eval                  && uv run pytest -q        # 105 tests
```

CI runs all three suites against `pgvector/pgvector:0.8.0-pg16` on every push.

## Documentation

| Doc | Contents |
| :-- | :-- |
| [`docs/weir-original.md`](docs/weir-original.md) | The original vision: goals, risks, evaluation plan |
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | Implementation design and the per-phase addenda (cache, router) |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Task-by-task implementation plans |
| [`docs/decisions.md`](docs/decisions.md) | Every decision with its alternatives and the reason (D0–D40) |
| [`docs/progress.md`](docs/progress.md) | Phase-by-phase log |
| [`docs/results/`](docs/results/) | Baselines, threshold sweep, cache, router tuning, router live results, four-way summary |
| [`docs/backlog.md`](docs/backlog.md) | Deferred findings and ideas |

## Limitations

- **Small, synthetic benchmark.** There are 158 questions and 24 trap pairs on a fictional KB. "Zero wrong hits" is strong evidence for this set, not a guarantee.
- **Hit rate depends on the workload.** 93% is for a 73.7%-repeat replay; a cold pass with only paraphrases repeating hits 15%.
- **Latency is measured sequentially, not under load.** Load tests come in Phase 5.
- **Grounding is lexical.** It catches unfinished, uncited and "not found" answers, but not a fluent answer that omits or invents a detail using the source's own words. The strict routing cut-offs, not grounding, keep such questions on the large model.
- **The large model isn't stable over time.** One hard question drifted between runs and another flips between attempts, so every Phase 3 comparison uses a same-day baseline.

## Roadmap

| Phase | Scope | Status |
| :-: | :-- | :-: |
| 0–1 | Gateway, RAG adapter, request logging, eval set, baseline | Done |
| 2 | Semantic cache, entity guard, threshold sweep, cache eval | Done |
| 3 | Router: features, rules, grounding check, escalation and fallback, offline-tuned cut-offs, live ablation | In progress (final review) |
| 4 | Prometheus metrics, Grafana dashboard, alerts | Planned |
| 5 | k6 load tests (cold/warm, ramp, spike, soak), ablation under load | Planned |
| 6 | Demo chat page, write-up, optional learned router | Planned |
