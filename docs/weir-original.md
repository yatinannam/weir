# Weir

Sep 30, 2026 · @Yatin Annam

## Overview

Weir is a gateway in front of a RAG service that decides, for every request, whether an LLM call is needed at all and which model should make it.

It does three jobs. It answers repeated questions from a semantic cache, sends each remaining question to the cheapest model that can handle it, and records cost and latency for every request so the savings can be proven.

**Why the name.** A weir is a low dam that controls how much water passes downstream. Weir does the same for queries: most are held back by the cache, and the rest are let through to the right model.

**What it is not.** It is not a new RAG pipeline, a vector database, or an LLM framework. It wraps an existing RAG endpoint and leaves retrieval and prompting as they are.

### Outcomes it targets

The targets below are starting hypotheses. They get replaced by measured numbers after the baseline run in Phase 1.

| Metric | How it is measured | Starting target |
| --- | --- | --- |
| LLM cost per 1,000 requests | Token counts times model price, logged per request | 40% lower than baseline on a repeat-heavy workload |
| p95 end-to-end latency | Load test, full path including cache lookup | 30% lower than baseline |
| Cache hit rate | Hits divided by total requests | 30% or higher on a repeat-heavy workload |
| Answer quality | Eval set, judged against expected answers | Within 2 points of the baseline |
| Wrong cache hits | Manual review of hits on the eval set | Under 1% of hits |

The last two rows are the ones that make the rest credible. A cheaper, faster system that quietly gives worse answers has not improved anything.

## Problem and goals

A RAG product pays for an LLM call on every request, and most of those calls are avoidable or over-powered.

### The three leaks

1. **Repeated questions.** Users ask the same thing in different words. Each paraphrase triggers retrieval, a long prompt, and a full generation, and the answer is the same as last time.
2. **Over-powered models.** A question like "what are visiting hours?" does not need the largest model. Sending everything to one big model pays flagship prices for lookup work.
3. **No visibility.** Without per-request cost and latency logs, nobody can say which queries are expensive, which are slow, or whether a change helped.

Latency follows the same pattern. Retrieval plus a long-context generation from a large model is slow, and the tail (p95) is what users notice.

### Goals

- Cut LLM spend and tail latency on a realistic workload without lowering answer quality.
- Make every saving measurable, with a baseline, an eval set, and a load test behind each claim.
- Keep the gateway small enough to read in an afternoon and run on a single machine.
- Make the cache and router configurable per tenant or per use case, so sensitive domains can turn them off.

### Non-goals

- Building a new retriever, chunking strategy or reranker.
- Training or fine-tuning models.
- Multi-region deployment, autoscaling, or high-availability setups.
- Caching anything that contains personal or patient data.
- Beating a commercial LLM gateway on features. The aim is a clear, correct, well-measured implementation.

## Architecture

Weir sits between the caller and the RAG service, and every request leaves it by one of two paths: a cache hit or a routed miss.

&#91;embedded content: request lifecycle · 1 cache decision, 1 routing decision\]

A hit returns after one embedding and one lookup. A miss retrieves context, is routed to a small or large model, is checked, and is then written back to the cache.

### Components

| Component | Responsibility | Depends on |
| --- | --- | --- |
| Gateway API | Validates the request, maps the API key to a namespace, runs the pipeline | All components below |
| Embedder | Turns the query into a vector | Embedding model |
| Cache store | Similarity search, entry writes, expiry | Postgres with pgvector |
| Guards | Entity guard and never-cache rules | Query text and request flags |
| RAG adapter | Calls retrieve and generate on the existing RAG service | The RAG service |
| Router | Chooses the small or large tier from the request signals | Config, later a trained classifier |
| LLM client | Calls the provider, counts tokens, handles retries and fallback | Model providers |
| Metrics logger | Writes one row per request and updates live counters | Postgres, Prometheus |

### Two paths and their cost

- **Hit path:** embedding plus cache lookup. No retrieval, no generation.
- **Miss path:** embedding, cache lookup, retrieval, generation and the grounding check.

Every request pays for the embedding and the lookup, including misses. That overhead is small next to a model call, but it is why the break-even check in the risks section matters.

### On the request path and off it

| On the request path (the caller waits) | Off the request path (runs after the response) |
| --- | --- |
| Embedding and cache lookup | Writing the new cache entry |
| Retrieval | Writing the request log row |
| Routing and model call | Shadow comparisons against the large model |
| Grounding check and escalation | Audit sampling of cache hits |

Keeping the right-hand column off the request path is what stops the measurement and caching work from adding latency of its own.

## Semantic cache

The cache returns a stored answer when a new question means the same as one already answered. Most of the design work goes into preventing wrong matches, not into finding right ones.

### How a lookup works

1. Normalise the query: trim, collapse whitespace, and build a lowercase copy for matching. Keep the original text for logs.
2. Embed the normalised query with a small embedding model.
3. Search the vector index, inside the correct namespace, for the nearest stored query.
4. If cosine similarity is at or above the threshold, return the stored answer. Otherwise treat it as a miss.
5. After a miss is answered and passes the storage checks, write the query, its embedding, the answer and metadata back to the cache.

### What each entry stores

| Field | Purpose |
| --- | --- |
| query\_text | Original question, kept for debugging and for the eval set |
| embedding | Vector used for similarity search |
| answer | The final response text returned to the user |
| source\_ids | IDs of the documents the answer was built from, used for targeted purging |
| model | Which model produced the answer |
| namespace | Tenant, language and use case the entry belongs to |
| kb\_version | Version of the knowledge base when the answer was made |
| prompt\_version | Version of the prompt template used |
| created\_at, ttl | When it was stored and when it expires |
| hit\_count | How often it has been served, useful for pruning |

### Namespaces

Every entry is keyed by tenant, language, knowledge base version and prompt version. The same question can have a different correct answer for another tenant, another language, or after a document changes. A lookup only searches entries in its own namespace, so cross-contamination cannot happen by construction.

### Choosing the threshold

Start at 0.92 cosine similarity and treat it as a guess. The right value depends on the embedding model and the domain.

1. Build labelled pairs from the eval set: questions that should match, and near-duplicates that should not.
2. Sweep the threshold from 0.80 to 0.98 in steps of 0.01.
3. At each step record the hit rate and the false-hit rate.
4. Pick the lowest threshold where the false-hit rate stays under 1%. Re-run this whenever the embedding model changes.

An optional refinement is a two-band design. Above the high threshold the cache answers directly. In a narrow band just below it, a cheap check decides whether the two questions are equivalent.

### Controls against wrong hits

- **Entity guard.** Extract numbers, names, units and negations from both questions. If they differ ("adult dose" against "child dose", "with" against "without"), treat it as a miss whatever the similarity.
- **Near-band verification.** For scores in the narrow band, ask a small model or cross-encoder whether the two questions have the same answer. This adds latency, so it runs only in the band.
- **Per-namespace overrides.** Sensitive domains can raise the threshold or turn the cache off.
- **Audit sampling.** Log a small random sample of hits with both questions side by side, and review them weekly.

### Invalidation

- **TTL.** Every entry expires. A default of 24 hours is a sensible start, configurable per namespace.
- **Version bump.** Ingesting new or changed documents raises kb\_version. Old entries sit in the old namespace and stop matching, with no scan required.
- **Targeted purge.** Because entries record source\_ids, an admin endpoint can delete every entry that cited a specific document.

### What is never cached

- Requests that depend on user-specific context, such as an account, a patient record or session state.
- Answers that contain personal data.
- Time-sensitive answers ("today", "right now", "current wait time").
- Low-confidence answers, meaning retrieval scores below a floor or a model reply saying it could not find the answer.
- Errors, refusals and truncated outputs.

## Router

The router picks the cheapest model likely to answer well, and escalates when that model turns out to be unsure. Getting it wrong in the cheap direction costs quality; getting it wrong in the expensive direction only costs money, so the defaults lean toward the large model.

### Tiers

| Tier | Model class | Typical queries |
| --- | --- | --- |
| Small | Cheap, fast model | FAQs, single-fact lookups, questions where retrieval clearly contains the answer |
| Large | Strongest available model | Multi-step reasoning, comparisons, ambiguous or long questions, weak retrieval |

The specific models are configuration, not code. Start with two tiers. A middle tier can be added later if the data shows a gap between the two.

### Router v1: rules

v1 uses signals that are available before any generation happens:

- Query length in tokens.
- Reasoning keywords such as compare, why, explain, calculate, steps, or difference.
- Number of separate questions packed into one message.
- Top retrieval score, and the gap between the best chunk and the rest.
- Amount of context retrieved, in tokens.
- Whether the message depends on earlier conversation turns.

```python
def route(q, retrieval):
    if retrieval.top_score < LOW_CONFIDENCE:
        return "large"          # weak retrieval, do not gamble
    if q.tokens <= SHORT and not q.has_reasoning_words and q.num_questions == 1:
        if retrieval.top_score >= HIGH_CONFIDENCE:
            return "small"
    return "large"              # default when unsure
```

The thresholds are tuned on the eval set, not guessed. Anything the rules do not clearly recognise goes to the large model.

### Router v2: learned

v2 replaces the hand-written rules with a small classifier once there is enough logged data.

1. Run every eval query through both tiers and score both answers.
2. Label a query "small is enough" when the small model's score is within a chosen tolerance of the large model's.
3. Train a lightweight classifier (logistic regression or gradient-boosted trees) on the v1 signals plus the query embedding.
4. Route to the small model when the predicted probability of "small is enough" clears a threshold, tuned so quality stays inside the target.
5. Compare v2 to v1 on held-out queries: cost saved at equal quality is the number that matters.

If v2 does not beat v1 by a clear margin, keep v1. A simple router that is understood is better than a learned one that is not.

### Escalation and fallback

- **Escalate on doubt.** If the small model's answer fails a grounding check, cites nothing, or says it cannot find the answer, retry once on the large model and log the request as escalated.
- **Provider failures.** On a timeout or error, fall back to the other tier once, then return a clear error.
- **Retry cap.** No request makes more than two model calls, so a bad day cannot multiply the bill.

### Quality guardrails

- **Per-route scores.** The eval set reports quality separately for the small and large routes. A release is blocked if either falls below its floor.
- **Shadow sampling.** For a small random share of small-model requests, also run the large model offline and compare the answers. This exposes silent quality loss.
- **Kill switch.** One config flag sends everything to the large model, and one turns the cache off, so any incident can be contained in seconds.

## Metrics and dashboard

Every request writes one row of measurements, and the dashboard is a set of queries over those rows. Without this layer the project has no proof, so it is built early, not last.

### Per-request log

| Field | Type | Notes |
| --- | --- | --- |
| request\_id | uuid | Also returned to the caller in a response header |
| ts | timestamp | UTC |
| namespace | text | Tenant, language, use case |
| cache\_status | enum | hit, miss, or bypass |
| similarity | float | Best match score, null on bypass |
| route | enum | none (cache hit), small, or large |
| escalated | bool | True if the small model was retried on the large one |
| model | text | Model that produced the final answer |
| tokens\_in, tokens\_out | int | From the provider response |
| embed\_tokens | int | Tokens spent embedding the query |
| retrieval\_top\_score | float | Best retrieval score for the request |
| latency\_embed\_ms, latency\_cache\_ms, latency\_retrieval\_ms, latency\_llm\_ms | int | Time per stage |
| latency\_total\_ms | int | End to end, as seen by the caller |
| cost\_usd | numeric | Computed at write time from a price table |
| counterfactual\_cost\_usd | numeric | What the request would have cost with no cache and always the large model |
| status | enum | ok, error, or timeout |
| query\_hash | text | Hash of the query. Raw text is stored only where policy allows |

### Cost model

Cost is computed from token counts and a versioned price table, so historical rows stay correct when provider prices change.

```latex
\text{cost} = \frac{t_{in}}{10^{6}}\,p_{in} + \frac{t_{out}}{10^{6}}\,p_{out} + \frac{t_{emb}}{10^{6}}\,p_{emb}
```

The counterfactual column is what makes the savings claim honest. Savings equal counterfactual cost minus actual cost, and the actual cost includes the embedding spend that every request pays.

### Dashboard panels

| Panel | Question it answers | Definition |
| --- | --- | --- |
| Cost per 1,000 requests | Are we cheaper than the baseline? | Sum of cost\_usd divided by request count, times 1,000 |
| Estimated savings | How much did Weir save? | Sum of counterfactual cost minus sum of actual cost |
| Cache hit rate | Is the cache earning its keep? | Hits divided by all requests, per namespace |
| Latency by path | Where does the time go? | p50, p95 and p99 for hit, small and large paths |
| Route mix | Who is handling the traffic? | Share of hit, small and large |
| Escalation rate | Is the small model being over-trusted? | Escalated divided by small-route requests |
| Similarity histogram | Is the threshold set sensibly? | Distribution of similarity scores on hits, and on near misses |
| Errors and timeouts | Is anything failing? | Share of requests with status other than ok |

### Alerts

Thresholds are set after the baseline run, not before.

- p95 latency above the budget for a sustained period.
- Hit rate drops sharply against its trailing average, which often means a version bump or an embedding problem.
- Escalation rate climbs, which means the router is sending hard questions to the small model.
- Cost per 1,000 requests rises above baseline.
- Error or timeout rate rises.

### Implementation notes

- Write log rows asynchronously through an in-process queue, so logging never adds to request latency.
- Expose live counters to Prometheus for the alerts, and keep the full rows in Postgres for analysis and the eval reports.
- Never log raw prompts or answers for namespaces marked sensitive. Log hashes and lengths instead.

## API and data model

The public surface is one main endpoint plus a few for feedback, purging and stats. Callers never need to know whether an answer came from the cache.

### Endpoints

| Method and path | Purpose |
| --- | --- |
| POST /v1/query | Ask a question and get an answer with metadata |
| POST /v1/feedback | Rate an answer by request\_id. Negative feedback evicts the cache entry that served it |
| DELETE /v1/cache | Admin purge by namespace, by source document ID, or by entry ID |
| GET /v1/stats | Summary numbers for the dashboard and for quick checks |
| GET /healthz | Liveness and dependency checks |

Each tenant authenticates with an API key in a header, and the key maps to a namespace and its settings.

### Query request and response

```json
// POST /v1/query
{
  "query": "What are the visiting hours for the cardiology ward?",
  "namespace": "hospital-a/en/faq",
  "session_id": "optional-conversation-id",
  "personalized": false,
  "options": { "bypass_cache": false, "force_model": null }
}

// 200 response
{
  "answer": "...",
  "sources": [{ "id": "doc_142", "title": "Visitor policy" }],
  "meta": {
    "request_id": "8f0c...",
    "cache_status": "hit",
    "similarity": 0.957,
    "route": "none",
    "model": "small-v1",
    "latency_ms": 41,
    "cost_usd": 0.000002
  }
}
```

The `personalized` flag is how the caller says the answer depends on user-specific data. When it is true, the cache is bypassed for both reading and writing.

### Storage

The first version uses one Postgres database with the pgvector extension for both the cache and the logs. This keeps setup to a single service. The schema below is a sketch.

```sql
create table cache_entries (
  id             uuid primary key,
  namespace      text not null,
  kb_version     text not null,
  prompt_version text not null,
  query_text     text not null,
  embedding      vector(384) not null,  -- size depends on the embedding model
  answer         text not null,
  source_ids     text[] not null,
  model          text not null,
  hit_count      int not null default 0,
  created_at     timestamptz not null default now(),
  expires_at     timestamptz not null
);
create index on cache_entries using hnsw (embedding vector_cosine_ops);
create index on cache_entries (namespace, kb_version, prompt_version);

create table model_prices (
  model            text not null,
  usd_per_m_input  numeric not null,
  usd_per_m_output numeric not null,
  effective_from   date not null,
  primary key (model, effective_from)
);
```

The request log follows the field list in the metrics section. Expired entries are removed by a scheduled job, and a lookup also ignores anything past its expiry.

### Error handling

- If the cache or embedding step fails, the request skips the cache and goes straight to the router. A cache outage should never become a user-facing outage.
- If retrieval fails, return an error with the request\_id. Do not guess an answer.
- Every response carries the request\_id, so any answer can be traced back to its log row.

## Tech stack and repo structure

The stack is chosen to keep the whole system runnable with one command and readable by one person. Each choice has a swap-in alternative, so the design does not depend on any single tool.

### Stack

| Layer | Choice | Why | Alternative |
| --- | --- | --- | --- |
| API | FastAPI on uvicorn, async | Typed request models, automatic OpenAPI docs, good async support | Fastify, Flask |
| Cache and vector search | Postgres with pgvector | One service for cache and logs, fast enough at this scale | Redis vector search, Qdrant |
| Embeddings | A small, low-latency embedding model | Cheap and quick, since it runs on every request | A larger model if accuracy is short |
| LLM access | Provider SDKs behind one internal interface | Swap models through config | LiteLLM as a ready-made layer |
| Router | Plain Python, then scikit-learn for v2 | Easy to read and test | Small fine-tuned classifier |
| Metrics | Postgres rows plus Prometheus counters, Grafana on top | Grafana reads Postgres directly | Streamlit for a lighter dashboard |
| Load testing | Locust | Scenarios written in Python | k6 |
| Evaluation | A runner script with pytest checks and an LLM judge | Repeatable, runs in CI | A dedicated eval framework |
| Packaging | Docker Compose | api, postgres and grafana start together | Kubernetes, which is out of scope |

### One requirement on the existing RAG service

The router needs the retrieval score before it picks a model. That means Weir needs the RAG service to expose retrieval and generation as two separate steps: retrieve(query) returns chunks and scores, and generate(query, context, model) returns the answer. If the current service bundles them, splitting them is the first change to make, and it is a small one.

### Repo layout

```text
weir/
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── configs/
│   ├── weir.yaml           # thresholds, tiers, TTLs, per-namespace overrides
│   └── prices.yaml         # model prices with effective dates
├── src/weir/
│   ├── main.py             # FastAPI app and routes
│   ├── pipeline.py         # cache -> router -> llm -> store
│   ├── settings.py
│   ├── cache/
│   │   ├── embedder.py
│   │   ├── store.py        # pgvector reads and writes
│   │   └── guards.py       # entity guard and never-cache rules
│   ├── router/
│   │   ├── features.py
│   │   ├── rules.py        # v1
│   │   └── learned.py      # v2
│   ├── llm/
│   │   ├── client.py       # provider interface
│   │   └── pricing.py
│   ├── rag/
│   │   └── adapter.py      # retrieve() and generate() on the RAG service
│   └── metrics/
│       ├── logger.py       # async log writer
│       └── prometheus.py
├── eval/
│   ├── datasets/           # queries, paraphrase pairs, expected answers
│   ├── run_eval.py
│   ├── sweep_threshold.py
│   └── reports/
├── loadtest/
│   ├── locustfile.py
│   └── scenarios.md
├── dashboards/
│   └── grafana.json
└── tests/
```

### Configuration

Every threshold lives in one YAML file, so experiments change config and not code.

```yaml
cache:
  enabled: true
  threshold: 0.92
  near_band: [0.88, 0.92]
  ttl_hours: 24
  min_retrieval_score: 0.30
router:
  version: rules-v1
  small_model: <configured>
  large_model: <configured>
  short_query_tokens: 20
  high_confidence: 0.75
  low_confidence: 0.40
  max_model_calls: 2
kill_switch:
  force_large: false
  disable_cache: false
```

The numbers shown are placeholders to be replaced by tuned values from the eval runs.

## Evaluation plan

Every claim about cost, latency and quality comes from a fixed eval set and a fixed procedure, run before and after each change. This section is what turns the project from a demo into evidence.

### Step 0: the baseline

Run the existing RAG endpoint with one large model and no cache over the full eval set. Record cost per 1,000 requests, latency percentiles and answer quality. Freeze the baseline settings: model, prompt, retrieval parameters and knowledge base version. Every later number is compared to this run.

### Building the eval set

Aim for 150 to 300 queries in three groups.

| Group | What it is | What it measures | Rough share |
| --- | --- | --- | --- |
| Distinct questions | Unique questions across easy, medium and hard | Quality and routing | 50% |
| Paraphrase clusters | A seed question plus 3 to 5 rewordings | Cache hits | 30% |
| Near-duplicate traps | Questions that look alike but need different answers | False cache hits | 20% |

- Source the queries from anonymised real logs if they exist. Otherwise write them from the knowledge base, and use a model to draft paraphrases that a person then reviews.
- Give every query an expected answer or a list of required facts, plus the source document it should draw on.
- Label difficulty by hand, since the router is judged against it.
- Split the set: 70% for tuning, 30% held out and used once for the final numbers.

### Realistic traffic replay

Real traffic repeats itself unevenly: a few questions are asked constantly and most are asked rarely. For the load test and the hit-rate number, replay queries with a skewed frequency, so a small set of popular questions dominates. State the repeat rate you assumed, because hit rate depends more on the workload than on the cache.

### Scoring quality

- **Key-fact checks.** Automatic test that the required facts appear in the answer.
- **LLM judge.** A judge model compares each answer to the reference on correctness and grounding, using a fixed 1 to 5 rubric. Use a different model from the ones under test where possible.
- **Human spot check.** Review a sample of judge scores, weighted toward disagreements, to calibrate the judge.

### Metrics by component

| Component | Metric | How it is computed |
| --- | --- | --- |
| Cache | Hit rate on paraphrase clusters | Hits divided by paraphrase queries |
| Cache | False-hit rate | Wrong hits divided by all hits, using the trap group |
| Cache | Threshold curve | Hit rate and false-hit rate across the threshold sweep |
| Router | Quality per route | Judge score for small-route and large-route answers separately |
| Router | Share routed small | Small-route requests divided by non-hit requests |
| Router | Cost saved at equal quality | Cost difference against always-large, with quality delta shown beside it |
| System | Cost per 1,000 requests | From the request log |
| System | p50, p95, p99 latency | From the load test |
| System | Quality change against baseline | Mean judge score difference on the held-out set |

### Ablations

Run four configurations on the same held-out set and workload, and report them side by side.

| Configuration | Cache | Router |
| --- | --- | --- |
| Baseline | Off | Always large |
| Cache only | On | Always large |
| Router only | Off | On |
| Weir, full | On | On |

This shows what each part contributes, and it is the first thing a reviewer will ask.

### Reporting honestly

- Give the workload mix and the repeat rate next to every hit-rate and cost number.
- Show quality beside every cost number. A saving without a quality figure is not a result.
- State the sample size. With a small eval set, differences of a point or two are noise.
- List limitations: eval set size, judge bias, and a single domain.
- Keep raw result files in the repo so any number can be reproduced.

## Load testing

Load tests produce the p95 numbers on the resume. To be credible they must use realistic traffic, and they must report cold-cache and warm-cache results separately.

### Setup

- **Two modes.** Run with a stub LLM that has a fixed, known latency to measure the gateway's own overhead. Run with the real models, at lower volume, for end-to-end numbers. Real calls cost money and hit provider rate limits.
- **Same hardware for every configuration.** Record the machine specification with the results.
- **Client on a separate process or machine**, so the load generator does not steal CPU from the gateway.
- **Same workload for baseline and Weir**, replayed from the same query file with the same repeat pattern.

### Scenarios

| Scenario | Setup | Question it answers |
| --- | --- | --- |
| Cold cache | Empty cache, skewed workload | How slow is it before anything is cached? |
| Warm cache | Cache pre-filled with the popular questions | What does steady state look like? |
| Ramp | Arrival rate increased in steps | At what load does p95 start to climb? |
| Spike | Sudden jump in concurrent requests | Does it recover cleanly? |
| Soak | Moderate load for an extended period | Are there memory leaks or exhausted connection pools? |
| Failure injection | LLM timeouts, slow database | Do the fallbacks work, and does the cache outage stay invisible? |

### What to measure

- p50, p95 and p99 latency, measured at the client, for each path: cache hit, small route and large route.
- Throughput at the point where p95 crosses the latency budget.
- Error and timeout rate.
- Gateway overhead: embedding time plus cache lookup time, from the stub-LLM runs.
- CPU, memory and database connection use.
- Cost per 1,000 requests, read from the request log.

### Getting p95 numbers that hold up

1. Send thousands of requests per scenario. A p95 from a few hundred requests is noisy.
2. Discard the warm-up period at the start of each run.
3. Repeat each scenario three times and report the median with the range.
4. Use a fixed arrival rate instead of a fixed number of users where the tool allows it (k6 arrival-rate executors, or Locust with constant throughput). Fixed-user tests slow down when the system slows down, which hides the tail.
5. Always run the baseline under the same load, so the comparison is like for like.

### Results template

Fill this in after the runs, one table per scenario, and keep the raw output next to it.

| Configuration | p50 (ms) | p95 (ms) | p99 (ms) | Cost per 1,000 requests | Quality score | Hit rate |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline |  |  |  |  |  |  |
| Cache only |  |  |  |  |  |  |
| Router only |  |  |  |  |  |  |
| Weir, full |  |  |  |  |  |  |

## Build plan

The build runs in seven phases, ordered so that measurement comes before optimisation. Each phase ends with an exit criterion that must be met before the next one starts.

Effort figures are rough estimates in focused working days for one person, about 20 to 25 days in total. Adjust them after Phase 1.

### Phases

| Phase | Work | Exit criterion | Rough effort |
| --- | --- | --- | --- |
| 0. Foundations | Repo, Docker Compose, FastAPI skeleton, config loading, RAG adapter with retrieve and generate split | POST /v1/query returns an answer through the adapter | 2 days |
| 1. Baseline and logging | Request logger, price table, cost calculation, first 50 eval queries, baseline run | Baseline numbers recorded and frozen | 3 to 4 days |
| 2. Semantic cache | Embedder, pgvector store, namespaces, never-cache rules, TTL, entity guard, threshold sweep | False-hit rate under 1% on the trap group at the chosen threshold | 4 days |
| 3. Router v1 | Feature extraction, rules, escalation, fallback, kill switches, per-route quality report | Lower cost than baseline with quality inside the target | 4 days |
| 4. Dashboard and alerts | Grafana panels, Prometheus counters, alert rules | Every panel populated from real runs | 2 to 3 days |
| 5. Load testing | Locust scenarios, stub LLM, cold and warm runs, ablation table | Results template filled and reproducible | 3 days |
| 6. Polish | README, architecture diagram, demo, write-up. Optional learned router v2 | A stranger can run the project with one command | 2 to 3 days |

### Phase gates that matter most

- **After Phase 1.** No cache or routing code is written until the baseline exists. Without it there is nothing to beat.
- **After Phase 2.** The false-hit rate decides whether the cache is safe to keep on. If the trap group cannot be handled, the threshold rises or the cache stays off for that namespace.
- **After Phase 3.** The router only ships if quality holds. If it does not, keep the cache and the dashboard and drop routing until v2.

### First-week checklist

- [ ] Create the repo and the Docker Compose file with Postgres and pgvector
- [ ] Stand up the FastAPI skeleton with /healthz and /v1/query
- [ ] Split the existing RAG service into retrieve and generate calls
- [ ] Add the request log table and the async logger
- [ ] Add the price table and the cost calculation
- [ ] Write the first 50 eval queries with expected answers
- [ ] Run the baseline and save the results file
- [ ] Decide which embedding model to use and record its vector size

## Risks and mitigations

The biggest risks are quiet ones: answers that are wrong but look fine, and savings that vanish once every cost is counted.

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Wrong cache hits | Similar questions can need different answers, such as adult and child doses | Entity guard, tuned threshold, near-band verification, trap group in the eval set, weekly audit sample |
| Poisoned cache | One bad answer gets stored and served many times | Store only answers that pass the grounding check, evict on negative feedback, keep a purge endpoint |
| Stale answers | Documents change and the cache keeps serving the old answer | TTL, kb\_version in the namespace, purge by source\_id |
| Router under-serves hard queries | The small model answers a question it should not | Conservative defaults, grounding check with escalation, per-route quality gates, shadow sampling |
| Savings smaller than expected | Every request pays for an embedding and a lookup, even misses | Measure break-even, report actual cost including embeddings, disable the cache on low-repeat namespaces |
| Data leaks across tenants or patients | A cache is shared state, and a wrong key exposes someone else's answer | Namespace in every lookup, never cache personalised requests, hashed logs for sensitive namespaces |
| Overfitting to the eval set | Thresholds tuned on the same data used for the result look better than they are | Held-out test set used once, sample size stated with results |
| Judge bias | An LLM judge can favour its own style or longer answers | Different judge model, human spot check, key-fact checks alongside |
| Stale cost numbers | Provider prices and models change | Versioned price table with effective dates |
| Scope creep | Adding features that are not needed to prove the idea | Non-goals list, and the phase gates |

### Break-even for the cache

The cache saves money only when the cost avoided on hits exceeds the cost every request pays for embedding and lookup.

```latex
h \cdot c_{llm} > c_{embed} + c_{lookup}
```

Here h is the hit rate, c\_llm is the average cost of a full LLM answer, and the right side is the per-request cache overhead. On a workload with few repeats, h is small and the inequality can fail. Measuring this on the eval workload is part of the results, and a negative result is worth reporting.

### Privacy rule of thumb

If a question could be answered differently for two different people, or its answer contains information about a person, it does not go in the cache. When in doubt, bypass.

## Fit with HMS and Voice AI

Weir works as a standalone project, and it also drops into a hospital management system or a voice assistant. Each setting adds constraints that are worth designing for from the start.

### Hospital management system

A question-answering assistant for patients, visitors and staff is a natural RAG use case, and much of its traffic is repetitive.

- **Good candidates for the cache:** visiting hours, department directory, admission and discharge process, billing and insurance procedure, general policies, and internal SOPs such as how to register a patient in a module.
- **Two namespaces.** A public one for patients and visitors, and a staff-internal one for SOPs. Each has its own knowledge base version, and a staff answer must never be served to a public caller.
- **Personalised requests bypass Weir's cache.** "My appointment", "my bill" and "my report" go through authenticated data paths, with the personalized flag set to true.
- **No patient identifiers in cached text.** Redact before the prompt is built, and log hashes instead of raw queries for these namespaces.
- **Keep clinical advice out of v1.** Dosage, diagnosis and treatment questions are not cached and are not routed to the small model. Handle them separately with clinical review.
- **Compliance.** Health data is regulated, for example under India's DPDP Act. Confirm the requirements with whoever owns compliance before any real data flows through the system.

### Voice AI

In voice, a pause is heard immediately, so the cache-hit path, which skips retrieval and generation, is worth more than in a text chat.

- **Cache the audio too.** Store a reference to the synthesised speech with each entry. A hit then skips both the LLM and text-to-speech.
- **Stream on misses.** Send tokens to speech synthesis as they arrive. The router should favour the small model when time to first audio matters more than depth.
- **Separate namespace for voice.** Spoken answers are shorter and phrased differently from chat answers, so they use their own prompt\_version and cache entries.
- **Speech recognition noise.** Transcripts contain mistakes, especially on numbers and names. The entity guard matters more here, and a low recognition confidence should bypass the cache.
- **Extra metrics.** Add time to first audio byte and recognition confidence to the request log.

### Recommended path

Build Weir first as a standalone demo over a public FAQ knowledge base, so the repo holds no real patient or company data. Once it works, add the HMS adapter as a second namespace, and treat the voice channel as a third. This keeps the portfolio version clean and the production version careful.

## Presenting the project

The project is only as strong as the numbers and the explanation behind them. Fill every bracket below with a measured result, and delete any line you cannot back up.

### Resume bullets

The generic line in the source image says costs and latency went down while quality held. These versions say by how much, and on what.

- Built Weir, a gateway for a RAG service combining semantic caching and cost-aware model routing, cutting LLM cost per 1,000 requests by \[X\]% and p95 latency from \[A\] ms to \[B\] ms on a replayed workload of \[N\] queries.
- Designed a \[N\]-query eval set with paraphrase clusters and near-duplicate traps, and tuned the cache threshold to a \[Y\]% false-hit rate while keeping answer quality within \[Z\] points of baseline.
- Implemented per-request cost and latency tracking with Postgres and Grafana, including alerts on hit rate, escalation rate and p95 latency.
- Ran ablations (cache only, router only, both) and load tests at fixed arrival rates to isolate what each component contributed.

One or two of these is enough on a resume. The rest belong in the README and in conversation.

### README outline

1. One-paragraph pitch and the architecture diagram
2. Results table: baseline against Weir, with workload and quality shown
3. Quick start: one command to run the stack
4. How the cache works, with the threshold curve chart
5. How the router works, with per-route quality
6. Dashboard screenshots
7. How to reproduce the eval and load tests
8. Limitations and what is not covered
9. Roadmap

### Five-minute demo script

1. Ask a question, showing a miss: retrieval, routing and a full answer, with its latency and cost in the response metadata.
2. Ask a paraphrase of the same question and show the hit, its similarity score, and the near-zero cost.
3. Ask a near-duplicate trap and show that the entity guard forces a miss.
4. Ask an easy question and a hard one, and show them going to different models.
5. Open the dashboard and show hit rate, route mix, latency by path and estimated savings.
6. Flip the kill switch and show everything going to the large model.

### Interview talking points

- **How did you choose the threshold?** From a sweep on labelled pairs, choosing the lowest value that kept the false-hit rate under 1%, then confirming on a held-out set.
- **How do you know quality held?** Fixed eval set, key-fact checks, an LLM judge calibrated with human review, and per-route scores.
- **What went wrong?** Pick a real failure from your runs, such as a trap that slipped through, and explain the guard you added.
- **When would you not use a semantic cache?** Low-repeat traffic, personalised answers, and fast-changing content.
- **What did each part contribute?** Quote the ablation table.
- **What would you do next?** Learned router, cache warming from logs, and a cross-encoder for near-band checks.

## Future work and open questions

### After the first version

- **Learned router.** Train on logged outcomes, and compare it against the rules on cost at equal quality.
- **Cache warming.** Pre-fill the cache from the most frequent questions in past logs.
- **Cross-encoder verification** for the near-threshold band, replacing the small-model check.
- **Prompt-prefix caching** at the provider level, alongside the semantic cache, for long shared contexts.
- **Answer freshness scoring.** Expire entries earlier when their source documents change often.
- **Streaming responses** through the gateway, with cache hits replayed as a stream.
- **Multi-turn awareness.** Include the conversation summary in the cache key so follow-up questions match correctly.

### Open questions to settle early

- [ ] Which knowledge base will the demo use, so the repo contains no private data?
- [ ] Which two models form the small and large tiers, and what do they cost?
- [ ] Which embedding model, and what vector size does it produce?
- [ ] Does the current RAG service already expose retrieval and generation separately?
- [ ] Is there real query traffic to build the eval set from, or must it be written by hand?
- [ ] What p95 latency budget counts as good for the intended use, chat or voice?
- [ ] Will this stay a portfolio project, or is it meant to run inside the HMS later?
