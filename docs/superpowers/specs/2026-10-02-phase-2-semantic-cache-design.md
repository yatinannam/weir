# Weir Phase 2: Semantic Cache Design (addendum)

Date: 2026-10-02 · Author: Yatin Annam (with Claude Code)
Status: Draft, awaiting review
Builds on: [main design spec](2026-09-30-weir-design.md) §6 (semantic cache), §8 (cost), §10 (data model), §11 (evaluation), §16 (Phase 2 row), plus the Phase 1 baseline in [`docs/results/baseline.md`](../../results/baseline.md).

This addendum pins down the Phase 2 details the main spec leaves open. Where the two disagree, this document wins for Phase 2.

---

## 1. In plain terms

Before calling the chatbot, Weir checks whether it has already answered a question that means the same thing, for this namespace, from the current documents. If it has, and nothing important differs, it replays that answer instantly with no AI call. If not, it asks the chatbot as today and may save the answer for next time.

Phase 2 is done when the cache gives wrong answers in under 1% of hits on the look-alike trap questions, and overall quality doesn't drop below the baseline.

---

## 2. Request flow

```
question ─▶ bypass rules ─▶ embed (bge-small) ─▶ look up top-3 in namespace ─▶ entity guard ─▶ HIT: replay stored answer
                │                                                                   │
                └──────────────── BYPASS ──────────────────────────────────── MISS ─┴─▶ retrieve + generate (as Phase 1)
                                                                                         └─▶ save if eligible (background)
```

This replaces the Phase 1 pipeline's "always bypass" step. The router (always the large model, or the `force_model` tier) is unchanged until Phase 3.

---

## 3. Components

| Unit | File | Responsibility |
| --- | --- | --- |
| Embedder | `weir/cache/embedder.py` | `bge-small-en-v1.5` via fastembed, unit-normalized 384-d vectors, token count. Called through `asyncio.to_thread`. The model is baked into the Weir image (about 150 MB of RAM). |
| Version cache | `weir/cache/versions.py` | Holds `{namespace: (kb_version, prompt_version)}` from hospital-rag `/info`, refreshed every `rag.info_refresh_seconds` (30 s) by a background task. A lookup never waits on the network. If no version is known yet, the request bypasses the cache with reason `no_version`. |
| Bypass rules | `weir/cache/guards.py` | Main spec §6.1. Keyword lists live in config. Returns a `bypass_reason` or `None`. |
| Entity guard | `weir/cache/entities.py` | Extracts numbers with units, negations, and lexicon terms (`configs/entities.yaml`, longest match first), then compares two questions. |
| Store | `weir/cache/store.py` | Lookup (top-3 with `hnsw.iterative_scan`), insert, `hit_count` increment, deletes by namespace, `source_id` or entry ID, and expired-row cleanup. |
| Write-back eligibility | `weir/cache/guards.py` | Main spec §6.3 checks, plus personal-data patterns. |
| Background cache writer | `weir/cache/writer.py` | Queue-based, like `LogWriter`. Cache writes and `hit_count` increments happen off the request path. A failure is counted and never raised. |
| Pipeline | `weir/pipeline.py` | Wires the above into the flow in §2. |
| Admin and feedback API | `weir/main.py` | `POST /v1/feedback`, `DELETE /v1/cache`. |

### 3.1 Entity lexicon (`configs/entities.yaml`)

Built from the knowledge base, with each group a list of terms. Matching is case-insensitive on word boundaries, longest term first, so "semi-private" is never read as "private".

- `wards`: ICU, general ward, pediatric ward, maternity ward, private room, semi-private room
- `departments`: cardiology, neurology, orthopedics, pediatrics, radiology, emergency, pharmacy, blood bank, …
- `days`: monday … sunday, weekday(s), weekend(s), public holiday(s)
- `people`: adult, child/children, senior, nurse(s), doctor(s), attendant, visitor, donor
- `vehicles`: car, two-wheeler, bike
- `payment`: cash, self-pay, insurance, cashless, government scheme
- `services`: CT, MRI, X-ray, ultrasound, …

Synonyms map to one canonical term, so "kids" counts as "child" and "intensive care" as "ICU". Two questions conflict when any group's term sets differ, or their numbers or negations differ.

### 3.2 Bypass keyword lists (config)

| List | Examples |
| --- | --- |
| Time-sensitive | today, now, right now, currently, tonight, this week, wait time, open now, at the moment |
| Follow-up | Has a `session_id` **and** either starts with what about / how about / and / also / same for, or is 6 tokens or fewer and contains it / that / those / they / there |
| Clinical | dose, dosage, mg, symptom, diagnos*, treatment, medication, side effect, prescription |

### 3.3 Personal-data patterns (never cached)

- An email address, or a phone-like run of 7 or more digits (spaces and dashes allowed)
- An ID-like run of 6 or more digits
- First-person possessive about personal records: "my appointment", "my bill", "my report", and so on. These normally arrive with `personalized: true` already.

---

## 4. Data model changes: `db/migrations/002_phase2_cache.sql`

- Drop the foreign key from `weir.feedback` to `weir.request_log`. Log rows are written asynchronously, so a fast thumbs-down could arrive before its row exists. `/v1/feedback` looks up the row itself and returns 404 if it doesn't exist after a short retry.
- No other schema change. `weir.cache_entries` and the request-log columns (`similarity`, `cache_entry_id`, `embed_tokens`, `latency_embed_ms`, `latency_cache_ms`) already exist from `001`.

---

## 5. Configuration additions (`configs/weir.yaml`)

```yaml
cache:
  enabled: true
  threshold: 0.92          # replaced by the sweep result
  candidates: 3
  ttl_hours: 24
  min_retrieval_score: 0.30
  cleanup_interval_minutes: 60
rag:
  info_refresh_seconds: 30
namespaces:
  weir-general/en/public: { sensitive: false, cache: { enabled: true } }
  weir-general/en/staff:  { sensitive: true,  cache: { enabled: true } }
```

New ablation overlay: `configs/ablations/cache_only.yaml` (cache on, `force_large: true`). The existing `baseline.yaml` keeps the cache off.

---

## 6. API additions

| Endpoint | Auth | Behaviour |
| --- | --- | --- |
| `POST /v1/feedback` | tenant key (must own the request's namespace) | `{request_id, rating: 1 or -1, comment?}`. Stores feedback. On -1, if the request was a hit or wrote an entry, that entry is deleted. Returns `{evicted: bool}`. |
| `DELETE /v1/cache` | admin key | Exactly one of `?namespace=`, `?source_id=`, `?entry_id=`. Returns `{deleted: n}`. |

`meta.cache_status` and `meta.similarity` are now real values. On a hit: `route = "none"`, `model` = the model that produced the stored answer, `cost_usd` = the embedding cost ($0 for local bge-small), and `counterfactual_cost_usd` = the stored tokens priced at the large model's rate.

To link feedback to entries, the request log records `cache_entry_id` both for hits (the entry that served the request) and for misses that wrote an entry. The entry ID is generated before the background write, so it's known at log time.

---

## 7. Evaluation

### 7.1 Question set grows to about 150

| Add | Count | Group | Notes |
| --- | --- | --- | --- |
| Paraphrase clusters, 5 wordings each | 10 clusters = 50 | `paraphrase` | Realistic repeats, and true pairs for the sweep |
| Trap pairs | 15 pairs = 30 | `trap` | Built from the KB's look-alike facts (new pairs beyond the 8 in `kb/README.md`) |
| Unanswerable | 10 | `unanswerable` (new group) | The KB doesn't contain the answer. The expected answer is the NOT_FOUND message. Key fact: `couldn't find`. Judge rubric `r2` adds: "for unanswerable questions, 5 = clearly says it can't find it; 1 = invents an answer". |
| Harder multi-document questions | 10 | `distinct`, `hard` | Eases the ceiling effect |

- A subagent drafts the new questions. `weir_eval validate` checks them, extended so `unanswerable` items need exactly 1 member per cluster and have no `source_docs` facts.
- Splits are re-assigned only for the new clusters. Existing items keep their split.
- **Baseline extension:** the 100 new questions run under the `baseline` ablation with the same frozen settings and judge. They're reported together with the original 50 as "baseline v2, 150 queries". The original 50 answers are reused, not re-run.
- **Rubric change:** the rubric version bump means the original 50 answers are re-graded under `r2` with `rejudge`. That costs no Weir or Groq-120b calls, only judge calls.

### 7.2 Threshold sweep (`eval/sweep_threshold.py`)

1. Build `eval/datasets/pairs.jsonl` from the question set with three kinds of pair:
   - **positive:** every pair within a paraphrase cluster
   - **negative:** every trap pair
   - **hard negative:** each question's single nearest question from a different cluster, by embedding
2. Embed with the same bge-small model, with no Groq calls.
3. For each threshold from 0.80 to 0.98 in 0.01 steps, both with and without the entity guard, compute:
   - hit rate on positives
   - false-hit rate: negatives accepted, out of all accepted pairs
   - recall
4. **Choose** the lowest threshold where the false-hit rate is under 1% on the tune split, with the guard on. Confirm it on holdout, report both, and put the chosen value in `configs/weir.yaml`.
5. Output a table and a chart (PNG via matplotlib) in `docs/results/cache-threshold.md`.

### 7.3 Cache run (`cache_only` ablation)

- **Cold pass:** all 150 questions once, in file order. The cache starts empty, and paraphrases asked later can hit earlier answers.
- **Realistic replay:** `eval/make_workload.py --n 300 --seed 7`. It draws from the questions with Zipf-skewed popularity (exponent 1.1) and records the realized repeat rate. Replayed after the cold pass, so the cache is warm.
- **Reported** in `docs/results/cache-only.md`:
  - hit rate (overall, and per group)
  - **wrong hits**: a hit whose answer fails its own question's key facts or gets a judge score of 3 or less
  - cost per 1,000 against the baseline
  - latency p50/p95 for hit, miss and bypass
  - bypass reasons
  - quality against baseline v2
- **Groq budget:** only misses call Groq, at about 500 tokens each, which is well within 200K tokens a day.

### 7.4 Exit gate (main spec §16)

1. The false-hit rate is under 1% at the chosen threshold on the trap pairs, on both splits.
2. The cache run's quality is within 0.1 judge points of baseline v2, with no fact-score drop, and there are zero wrong hits on traps.

If (1) fails, the threshold goes up. If no threshold passes, the cache stays off for that namespace and this is reported as a result.

---

## 8. Testing

- **Unit tests:**
  - lexicon extraction (longest match first, synonyms)
  - entity guard (numbers, negations, each lexicon group, and the 8 KB look-alike pairs as fixed cases)
  - bypass rules (each list, follow-up only with `session_id`)
  - write-back eligibility (each rule)
  - personal-data patterns
  - version-cache refresh and `no_version`
  - counterfactual on a hit
- **Store tests (database):** lookup is filtered by namespace and versions, expired rows are ignored, delete by each key, `hit_count` increments, and the iterative scan returns k rows under a selective filter.
- **Pipeline tests (fakes):**
  - hit path makes no hospital-rag calls
  - miss path writes when eligible
  - bypass reasons are recorded
  - an embedder failure becomes `bypass(error)`
  - a guard conflict becomes a miss
  - a sensitive namespace never logs raw text
- **API tests:**
  - feedback evicts on -1
  - feedback for another tenant's request returns 404
  - `DELETE /v1/cache` needs the admin key and exactly one selector
- **Eval tests:** pair building, the sweep math (hit and false-hit rates on a toy set), the workload generator's determinism and repeat rate, the `unanswerable` validation, and the rubric `r2` prompt.

---

## 9. Out of scope for Phase 2

- Near-band LLM verification (decision D8). Revisited only if the sweep shows many true paraphrases just under the threshold.
- The router (Phase 3), dashboards (Phase 4) and load tests (Phase 5).
- Multi-turn cache keys. Follow-ups bypass instead.
