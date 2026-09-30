# Weir: Implementation Design

Date: 2026-09-30 · Author: Yatin Annam (with Claude Code)
Status: Approved 2026-09-30
Source spec: [`docs/weir-original.md`](../../weir-original.md)

This document records how Weir will be built. The original spec says *what* Weir is and *why*. This one records the decisions made during design review, the fixes to gaps found in the original, and the concrete shape of every component. Where the two disagree, this document wins.

---

## 1. In plain terms

Weir is a smart receptionist in front of a help-desk chatbot.

- **It remembers answers.** If a question means the same as one already answered, Weir replies from memory with no AI call. The hard part is not being fooled by look-alike questions ("ICU visiting hours" and "general ward visiting hours").
- **It picks the right-sized AI.** Easy questions go to a small, cheap, fast model and hard ones go to a big one. If the small one looks unsure, the big one gets asked once.
- **It keeps receipts.** Every request logs its time and cost, so we can prove Weir is cheaper and faster without worse answers.

We build a basic chatbot for a fictional hospital, measure it alone (the baseline), then measure it behind Weir. That before-and-after comparison is the deliverable.

---

## 2. Constraints and intent

| Constraint | Source |
| --- | --- |
| **Zero spend.** Every tool, model and service must be free or free-tier. No paid APIs. | User |
| Runs on the user's Windows laptop with Docker Desktop. | User |
| Portfolio project first. Public, fictional data only. May plug into an HMS later. | Original spec, recommended path |
| Everything planned or built is documented in `docs/` for later context. | User |
| Keep the phases and gates of the original spec. | Original spec |

**Success** means the original spec's outcome table, measured under these constraints: a lower cost per 1,000 requests (at list prices), lower p95 latency, a hit rate of at least 30% on a repeat-heavy workload, quality within 2 points of the baseline, and wrong hits under 1% of hits.

---

## 3. Decisions

| # | Decision | Choice | Why |
| --- | --- | --- | --- |
| D1 | LLM provider | **Groq free tier.** One small (~8B Llama-class) and one large (~70B Llama-class) model. Exact IDs chosen from Groq's free model list at setup and kept in config. | Free, very fast (realistic latency), OpenAI-compatible API, and separate rate limits per model, which allows fallback between tiers. |
| D2 | Judge model | **Google Gemini free tier** | A different model family from the models under test, as the original spec asks. Free. |
| D3 | Embeddings | **`BAAI/bge-small-en-v1.5` via `fastembed`**, local CPU, 384 dimensions | Free, offline, fast, and no PyTorch install. |
| D4 | Knowledge base | **Fictional "Weir General Hospital"**, about 40–60 Markdown documents | Fits the HMS story, carries no licensing or privacy risk, gives exact ground truth, and lets us plant trap pairs. The README states that it is synthetic. |
| D5 | Structure | **Two services**: `hospital-rag` (the chatbot) and `weir` (the gateway) | Matches the "gateway in front of an existing service" story. The baseline is simply calling `hospital-rag` directly. |
| D6 | Grounding check | **Rule-based, no LLM**: valid citations, no NOT_FOUND sentinel, not truncated, content overlap with the cited chunks | An LLM check would spend Groq free-tier limits twice on every miss. |
| D7 | Cost reporting | **Priced at the providers' published paid-tier list prices.** Embeddings priced at $0 (local). Judge cost excluded. | Real spend is $0. List prices give an honest "what this would cost in production", stated in the README. |
| D8 | Near-band LLM verification | **Out of v1.** Added only if the threshold sweep shows many true paraphrases just under the threshold. | Saves free-tier calls. YAGNI. |
| D9 | Shadow sampling | **In the eval runner, not live traffic** | Live shadow calls would burn free-tier limits. |
| D10 | Load-test tool | **k6** (Docker image) with `constant-arrival-rate` | Locust's `constant_throughput` still slows down when the server does, which hides the latency tail. |
| D11 | Heavy load tests | **Stub LLM mode** in `hospital-rag` | Free-tier rate limits make heavy real-model load tests impossible. |
| D12 | Repo | `github.com/yatinannam/weir` (public) | User |

---

## 4. Gaps in the original spec and their fixes

| Gap | Fix | Section |
| --- | --- | --- |
| No existing RAG service to wrap | Build a minimal `hospital-rag` with separate `/retrieve` and `/generate` | §5.2 |
| Counterfactual cost unknown on cache hits | Store `tokens_in`/`tokens_out` on each cache entry and price them at the large model's rate on a hit | §8 |
| Follow-up questions could hit the cache wrongly | Detect follow-ups and bypass the cache | §6.1 |
| "Grounding check" undefined | Rule-based check, defined precisely | §7.4 |
| HNSW plus namespace filter can under-return results | `hnsw.iterative_scan = relaxed_order` and top-3 candidates | §6.2 |
| Body `namespace` could spoof another tenant | Reject any namespace not allowed for the API key (403) | §9.1 |
| Feedback cannot find the cache entry that served a request | `cache_entry_id` column on the request log | §10 |
| `hit_count` write on the hot path | Incremented in the background with the log write | §6.3 |
| Train/held-out split could leak paraphrases | Split by paraphrase cluster, never by individual query | §11.1 |
| `model_prices` has no embedding price | Embedding model gets a row with an input price (0 for local) and output price 0 | §10 |

---

## 5. Architecture

```
 caller / eval / k6
        │  POST /v1/query  (X-API-Key)
        ▼
 ┌──────────────┐   /retrieve  /generate  /info   ┌──────────────────┐
 │  weir        │ ──────────────────────────────▶ │  hospital-rag    │ ──▶ Groq API (free)
 │  :8000       │                                 │  :8001           │     (or stub mode)
 └──────┬───────┘                                 └────────┬─────────┘
        │ schema weir: cache, logs, prices                 │ schema rag: documents, chunks
        ▼                                                  ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  postgres 16 + pgvector   (pgvector/pgvector:pg16 image)   :5432    │
 └─────────────────────────────────────────────────────────────────────┘
 weir /metrics ──▶ prometheus :9090 ──▶ grafana :3000 ◀── postgres (SQL panels)
```

All services start with `docker compose up`. The eval runner and k6 run on demand.

### 5.1 Services

| Service | Image or build | Role |
| --- | --- | --- |
| `postgres` | `pgvector/pgvector:pg16` | Stores both schemas. Init SQL creates the extension and the schemas. |
| `hospital-rag` | `./services/hospital-rag` | The chatbot: retrieval, generation, ingest |
| `weir` | `./services/weir` | The gateway |
| `prometheus` | `prom/prometheus` | Scrapes `weir:8000/metrics` |
| `grafana` | `grafana/grafana-oss` | Dashboards, with Postgres and Prometheus datasources provisioned from files |

### 5.2 hospital-rag API

| Endpoint | Request | Response |
| --- | --- | --- |
| `GET /info` | none | `{namespaces: {"weir-general/en/public": {kb_version, prompt_version}, ...}}` |
| `POST /retrieve` | `{query, namespace, k=5}` | `{chunks: [{id, doc_id, title, text, score}], top_score, score_gap, context_tokens, kb_version, latency_ms}` |
| `POST /generate` | `{query, namespace, chunks, model}` | `{answer, cited_chunk_ids, not_found, finish_reason, tokens_in, tokens_out, model, prompt_version, latency_ms}` |
| `GET /healthz` | none | Status of the database and Groq |

- **Prompt contract.** The model is told to cite chunk IDs inline, like `[c3]`, and to reply exactly `NOT_FOUND` when the context does not contain the answer. `/generate` strips the citation markers from `answer` and returns them in `cited_chunk_ids`.
- **Errors.** A Groq 429 becomes HTTP 503 `{error: "rate_limited", retry_after}`. A Groq timeout (20s) becomes 504.
- **Stub mode.** With `LLM_MODE=stub`, `/generate` sleeps for a fixed `STUB_LATENCY_MS` and returns a canned answer built from the top chunk. It reports token counts from the tokenizer and never calls Groq.
- **Ingest.** `python -m hospital_rag.ingest --kb kb/ --kb-version <v>` chunks each Markdown file by heading, at roughly 300 tokens with overlap, embeds the chunks and writes them. A version bump makes Weir's old cache entries stop matching.

### 5.3 Weir request pipeline

1. **Authenticate.** Map `X-API-Key` to a tenant, check that the body `namespace` is allowed for it (403 if not), and load that namespace's settings.
2. **Bypass checks** (§6.1). If any fires, `cache_status = bypass` with a `bypass_reason`.
3. **Embed and look up** (§6.2). A failure becomes `bypass (error)` and the request continues.
4. **On a hit:** return the stored answer and sources, and queue the `hit_count` increment and the log row.
5. **On a miss or bypass:** call `hospital-rag /retrieve`. A retrieval failure returns an error with the `request_id` and no guessed answer.
6. **Route** (§7). Call `/generate` with the chosen model.
7. **Grounding check** (§7.4). Escalate or fall back if needed (§7.3), with at most 2 model calls in total.
8. **Respond.** Queue the cache write (if eligible, §6.3) and the log row. Both happen after the response is sent.

`kb_version` and `prompt_version` per namespace come from `hospital-rag /info`, held in memory and refreshed every 30 seconds, so the cache lookup never waits on a network call.

---

## 6. Semantic cache

### 6.1 Bypass rules (skip both read and write)

| Rule | Detection |
| --- | --- |
| `personalized: true` or `options.bypass_cache` | Request flags |
| Time-sensitive | Keyword list in config: today, now, right now, currently, tonight, this week, wait time, open now, … |
| Follow-up | `session_id` present **and** one of: starts with a continuation phrase ("what about", "and ", "how about", "also", "same for"), or is 6 tokens or fewer and contains a bare pronoun (it, that, those, they, there) |
| Clinical | Keyword list: dose, dosage, mg, symptom, diagnos*, treatment, medication, side effect, … These are also forced to the large model. |
| Kill switch or namespace cache disabled | Config |

### 6.2 Lookup

1. Normalize: trim, collapse whitespace, lowercase. The original text is kept only for logs where policy allows.
2. Embed with bge-small. The vectors are unit-normalized.
3. Query, with `SET LOCAL hnsw.iterative_scan = relaxed_order`:
   ```sql
   select id, query_text, answer, sources, model, tokens_in, tokens_out,
          1 - (embedding <=> $q) as similarity
   from weir.cache_entries
   where namespace = $ns and kb_version = $kb and prompt_version = $pv
     and expires_at > now()
   order by embedding <=> $q
   limit 3;
   ```
4. Go through the candidates with `similarity >= threshold` (0.92 to start, tuned by the sweep). The **first candidate that passes the entity guard** is the hit. Otherwise it's a miss. The best similarity is logged either way.

**Entity guard.** Extract from both normalized questions:
- numbers with any unit,
- negations (no, not, without, except, non-, never),
- terms from the lexicon `configs/entities.yaml`: wards, departments, days, age groups (adult/child/pediatric/senior), visitor types, payment types.

Any difference in any of these sets means a miss.

### 6.3 Write-back eligibility

Write only if **all** of these hold: not bypassed, status ok, grounding passed, `retrieval_top_score >= cache.min_retrieval_score`, not `NOT_FOUND`, `finish_reason != "length"`, no PII pattern (phone, email, 6-plus digit IDs, a "my …" personal reference), and the namespace has the cache enabled.

The entry stores `tokens_in`, `tokens_out` and the `model` of the final answer. `hit_count` increments and entry writes go through the background queue.

### 6.4 Invalidation

- TTL: 24 hours by default, set per namespace.
- `kb_version` or `prompt_version` change: old entries stop matching.
- `DELETE /v1/cache` by namespace, by `source_id`, or by entry ID.
- Negative `POST /v1/feedback` evicts the entry named in that request's log row.
- A scheduled job (an in-process periodic task, hourly) deletes expired rows.

---

## 7. Router

### 7.1 Features (computed after retrieval)

| Feature | How |
| --- | --- |
| `tokens` | bge-small tokenizer (already loaded) |
| `has_reasoning_words` | compare, why, explain, difference, steps, calculate, versus/vs, pros and cons, … |
| `num_questions` | Count of `?` plus "and"-joined interrogatives |
| `top_score`, `score_gap` | From `/retrieve` |
| `context_tokens` | From `/retrieve` |
| `is_followup`, `is_clinical` | From §6.1 |

### 7.2 Rules v1

```python
def route(f, cfg):
    if cfg.kill_switch.force_large or f.is_clinical:
        return "large"
    if f.top_score < cfg.router.low_confidence:
        return "large"
    if (f.tokens <= cfg.router.short_query_tokens and not f.has_reasoning_words
            and f.num_questions == 1 and f.top_score >= cfg.router.high_confidence):
        return "small"
    return "large"
```

`options.force_model` overrides the route. It exists for the eval and the demo.

### 7.3 Escalation and fallback (hard cap: 2 model calls)

- **Small answer fails grounding:** retry once on large and set `escalated = true`.
- **Provider error, 429 or timeout:** try the other tier once. If that also fails, return 503 with the `request_id`.
- The cost of both calls is counted in `cost_usd`.

### 7.4 Grounding check (rule-based)

An answer passes when all of these hold:
1. `not_found` is false.
2. `finish_reason != "length"`.
3. `cited_chunk_ids` is non-empty and every ID was among the chunks provided.
4. At least `grounding.min_overlap` (0.5 to start) of the answer's content words (stopwords removed) appear in the text of the cited chunks.

### 7.5 Router v2

Optional, in Phase 6. A scikit-learn classifier trained on the features plus the query embedding, labeled from eval runs through both tiers. It ships only if it beats v1 on cost at equal quality.

---

## 8. Cost model

`cost = tin/1e6 · p_in(model) + tout/1e6 · p_out(model) + temb/1e6 · p_emb`, where the price is the row with the latest `effective_from <= request date`. Prices come from `configs/prices.yaml` (Groq's published paid-tier prices, with effective dates) and are upserted into `weir.model_prices` at startup. `p_emb = 0` for local bge-small.

**Counterfactual** (always large, no cache):

| Path | Counterfactual |
| --- | --- |
| Cache hit | The entry's stored `tokens_in`/`tokens_out`, priced at the large model's rate |
| Small route | The actual `tokens_in` plus the small model's `tokens_out`, priced at the large model's rate. This is an estimate and is documented as one. |
| Large route | Same as actual, without the embedding cost |
| Escalated | Only the large call's tokens, priced at the large model's rate |

Savings are `sum(counterfactual) - sum(actual)`, where actual includes all calls and the embedding cost.

---

## 9. Weir API

### 9.1 Endpoints

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `POST /v1/query` | tenant key | The question-answering endpoint (request and response as in the original spec, plus `meta.escalated`) |
| `POST /v1/feedback` | tenant key | `{request_id, rating: 1/-1, comment?}`. A -1 evicts the entry that served the request. |
| `DELETE /v1/cache` | admin key | `?namespace=` or `?source_id=` or `?entry_id=` |
| `GET /v1/stats` | admin key | Totals, hit rate, route mix, cost, savings, p50/p95 for a time window |
| `GET /healthz` | none | Status of the database, hospital-rag and the embedder |
| `GET /metrics` | none (internal network) | Prometheus |

Every response carries an `X-Request-ID` header.

**Tenants** are defined in `configs/tenants.yaml` as a tenant name, the name of the environment variable holding its key, its allowed namespaces and its sensitive flag. Keys live only in `.env`. Starting tenants: `public-app` → `weir-general/en/public`, `staff-app` → `weir-general/en/staff` (marked sensitive, so logs keep hashes only).

### 9.2 Configuration

`configs/weir.yaml` holds the original spec's config, plus:

```yaml
cache:
  candidates: 3
  near_band_enabled: false
grounding:
  min_overlap: 0.5
rag:
  base_url: http://hospital-rag:8001
  info_refresh_seconds: 30
  timeout_seconds: 30
namespaces:
  weir-general/en/staff:
    cache: { ttl_hours: 24 }
    sensitive: true
```

Ablation overlays live in `configs/ablations/{baseline,cache_only,router_only,full}.yaml`.

---

## 10. Data model

```sql
create extension if not exists vector;
create schema rag;
create schema weir;

-- hospital-rag
create table rag.documents (
  id text primary key, namespace text not null, title text not null,
  path text not null, kb_version text not null, content_hash text not null,
  ingested_at timestamptz not null default now()
);
create table rag.chunks (
  id text primary key, doc_id text not null references rag.documents(id) on delete cascade,
  namespace text not null, kb_version text not null, chunk_index int not null,
  text text not null, token_count int not null, embedding vector(384) not null
);
create index on rag.chunks using hnsw (embedding vector_cosine_ops);
create index on rag.chunks (namespace, kb_version);

-- weir
create table weir.cache_entries (
  id uuid primary key, namespace text not null, kb_version text not null,
  prompt_version text not null, query_text text not null, embedding vector(384) not null,
  answer text not null, sources jsonb not null,          -- [{id, title}]
  source_ids text[] not null, model text not null,
  tokens_in int not null, tokens_out int not null,
  hit_count int not null default 0,
  created_at timestamptz not null default now(), expires_at timestamptz not null
);
create index on weir.cache_entries using hnsw (embedding vector_cosine_ops);
create index on weir.cache_entries (namespace, kb_version, prompt_version);
create index on weir.cache_entries using gin (source_ids);

create table weir.model_prices (
  model text not null, usd_per_m_input numeric not null, usd_per_m_output numeric not null default 0,
  effective_from date not null, primary key (model, effective_from)
);

create table weir.request_log (
  request_id uuid primary key, ts timestamptz not null, namespace text not null,
  cache_status text not null check (cache_status in ('hit','miss','bypass')),
  bypass_reason text, similarity real, cache_entry_id uuid,
  route text not null check (route in ('none','small','large')),
  escalated boolean not null default false, model_calls smallint not null default 0,
  model text, tokens_in int, tokens_out int, embed_tokens int,
  retrieval_top_score real, grounding_passed boolean,
  latency_embed_ms int, latency_cache_ms int, latency_retrieval_ms int,
  latency_llm_ms int, latency_total_ms int not null,
  cost_usd numeric not null default 0, counterfactual_cost_usd numeric not null default 0,
  status text not null check (status in ('ok','error','timeout')), error_detail text,
  query_hash text not null, query_text text, answer_len int,
  config_label text                                  -- ablation or experiment tag
);
create index on weir.request_log (ts);
create index on weir.request_log (namespace, ts);

create table weir.feedback (
  request_id uuid not null references weir.request_log(request_id),
  rating smallint not null, comment text, ts timestamptz not null default now()
);
```

`query_text` stays null for sensitive namespaces. Schema changes are plain numbered SQL files in `db/migrations/`, applied by a small migration runner at startup.

---

## 11. Evaluation

### 11.1 Eval set

- **Location:** `eval/datasets/queries.jsonl`, with fields `{id, namespace, query, group: distinct|paraphrase|trap, cluster_id, difficulty: easy|medium|hard, required_facts: [...], source_doc, split: tune|holdout}`.
- **Size:** 50 queries in Phase 1, growing to 150–300. The mix is 50% distinct, 30% paraphrase clusters (a seed plus 3–5 rewordings), and 20% traps.
- **Split:** 70/30 by `cluster_id`, so every paraphrase cluster falls wholly in one split. The held-out set is used once, for the final numbers.
- **Authorship:** subagents draft the questions from the knowledge base, and the user reviews a sample.
- **Pairs file:** `eval/datasets/pairs.jsonl`, with fields `{a, b, should_match}`, derived from the clusters and traps for the threshold sweep.

### 11.2 Scoring

1. **Key facts:** normalized substring and regex checks on `required_facts`.
2. **Gemini judge:** a fixed 1–5 rubric on correctness and grounding, using the reference facts and the source document. Results are cached in `eval/.judge_cache/`, keyed by the hash of question, answer and rubric version, so reruns cost nothing.
3. **Human spot check:** the user reviews about 20 answers, weighted toward disagreements between the key-fact check and the judge. Notes go in `docs/results/`.

The runner throttles itself below the free-tier limits.

### 11.3 Runs

- `eval/run_eval.py --config <ablation> --split tune|holdout` writes `eval/reports/<ts>-<config>.jsonl` and `summary.md`.
- `eval/sweep_threshold.py` sweeps 0.80–0.98 in steps of 0.01 over the pairs file, reports hit rate and false-hit rate, and plots the curve.
- `eval/make_workload.py --repeat-rate R --n N --seed S` builds a Zipf-skewed replay stream, recording the repeat rate and seed.
- **Shadow comparison:** for small-route answers, the runner also calls the large model and scores both.
- **Reports:** per-route quality, share routed small, cost saved at equal quality, and the four-way ablation table.

---

## 12. Load testing

- **Tool:** k6 (the `grafana/k6` Docker image) with the `constant-arrival-rate` executor. Scripts live in `loadtest/`.
- **Scenarios:** cold, warm, ramp, spike, soak and failure injection, as in the original spec. Ramp, spike and soak use stub mode. Real-model runs stay low-volume.
- **Procedure:** thousands of requests per scenario, warm-up discarded, 3 repeats, median and range reported, and laptop specs recorded with every result.
- **Gateway overhead:** measured from stub runs as embed time plus cache time.
- **Results:** `docs/results/loadtest-<date>.md`, with raw k6 JSON alongside.

---

## 13. Testing the code

- **Test-first** with pytest.
- **Unit tests:** normalization, bypass rules, follow-up and clinical detection, entity guard, write-back eligibility, router rules, grounding check, cost and counterfactual math, price lookup by date.
- **Pipeline tests:** a fake `hospital-rag` (`httpx` mock transport) and a real Postgres from the compose stack. No Groq calls in tests.
- **hospital-rag tests:** chunking, prompt citation parsing, NOT_FOUND handling, stub mode.
- **CI:** a GitHub Actions workflow (free for public repos) runs unit tests on each push.

---

## 14. Stack

Python 3.12 · `uv` · FastAPI + uvicorn · psycopg 3 (async) + `pgvector` Python package · `fastembed` · `groq` SDK · `google-genai` · `prometheus-client` · `httpx` · `pydantic-settings` + PyYAML · pytest · Docker Compose · Postgres 16 + pgvector · Prometheus · Grafana OSS · k6. All free.

Both API keys (Groq from console.groq.com, Gemini from aistudio.google.com) are free. They go in `.env`, which is gitignored. `.env.example` lists the variable names.

---

## 15. Repo layout

```text
weir/
├── README.md
├── docker-compose.yml
├── .env.example
├── configs/            weir.yaml, prices.yaml, tenants.yaml, entities.yaml, ablations/
├── db/migrations/      001_init.sql, ...
├── kb/                 public/*.md, staff/*.md  (Weir General Hospital)
├── services/
│   ├── hospital-rag/   pyproject.toml, Dockerfile, src/hospital_rag/{main,retrieve,generate,ingest,llm,stub}.py, tests/
│   └── weir/           pyproject.toml, Dockerfile, src/weir/{main,pipeline,settings,auth}.py
│                       src/weir/cache/{embedder,store,guards,entities}.py
│                       src/weir/router/{features,rules,learned}.py
│                       src/weir/rag/adapter.py   src/weir/llm/pricing.py
│                       src/weir/metrics/{logger,prometheus}.py   tests/
├── eval/               datasets/, run_eval.py, sweep_threshold.py, make_workload.py, judge.py, reports/
├── loadtest/           *.js scenarios, scenarios.md
├── dashboards/         grafana provisioning + weir.json
└── docs/               see §17
```

---

## 16. Build plan

| Phase | Work | Exit criterion |
| --- | --- | --- |
| 0. Foundations | Compose stack, migrations, the KB documents (subagent), `hospital-rag` (ingest, retrieve, generate, stub), Weir skeleton passing requests through, tenants and auth | `POST /v1/query` returns a grounded answer via hospital-rag |
| 1. Baseline and logging | Async request logger, prices, cost and counterfactual, first 50 eval queries (subagent), judge, eval runner, baseline run | Baseline numbers written to `docs/results/baseline.md` and frozen |
| 2. Semantic cache | Embedder, store, bypass rules, entity guard, write-back, invalidation, feedback, threshold sweep | False-hit rate under 1% on the trap group at the chosen threshold |
| 3. Router v1 | Features, rules, grounding check, escalation, fallback, kill switches, per-route report, shadow comparison | Lower cost than baseline with quality inside the target |
| 4. Dashboard and alerts | Prometheus counters, Grafana panels (subagent drafts the JSON), alert rules | Every panel populated from real runs |
| 5. Load testing | k6 scenarios (subagent), stub runs, real low-volume runs, ablation table | Results template filled and reproducible |
| 6. Polish | README, diagram, demo script, write-up, optional router v2 | A stranger can run it with one command |

**Gates from the original spec still apply:** no cache or router code before the baseline exists. The cache stays off where traps fail. The router ships only if quality holds.

Each phase gets its own implementation plan in `docs/superpowers/plans/`, written just before that phase starts.

---

## 17. Documentation practice

Everything planned or produced is saved in `docs/` so later sessions have context.

| Path | Contents |
| --- | --- |
| `docs/README.md` | Index of all docs |
| `docs/weir-original.md` | The original spec, unchanged |
| `docs/superpowers/specs/` | Design documents (this file) |
| `docs/superpowers/plans/` | One implementation plan per phase |
| `docs/decisions.md` | A running log of every decision, with date, choice and reason |
| `docs/progress.md` | A phase-by-phase log: what was done, what was learned, what's next |
| `docs/results/` | Baseline, sweeps, ablations and load tests, each with its raw data referenced |

---

## 18. Open items (resolved during the build)

- Exact Groq model IDs and their list prices: confirmed from Groq's docs in Phase 0 and recorded in `prices.yaml` and `decisions.md`.
- Groq and Gemini free-tier rate limits: read from the dashboards at setup, with the eval throttle set to match.
- The p95 latency budget (chat use case): set from the baseline run.
- HMS integration and the voice channel: out of scope for v1 (original spec, "recommended path").
