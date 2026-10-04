# Phase 3 Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the cache can't answer, Weir sends simple, well-documented questions to the small model and everything else to the large one. It checks every answer against its sources, retries a shaky small answer once on the large model, and proves with measured data that this saves money with no visible quality loss.

**Architecture:**
- Three small, pure units under `services/weir/src/weir/router/`:
  - `features.py`: question and retrieval features
  - `rules.py`: picks the tier
  - `grounding.py`: rule-based answer check
- `pipeline.py` calls them after retrieval and owns escalation, fallback and the 2-call cap.
- The cut-offs are tuned offline. The eval package replays both models' measured answers through the *same* `route()` function over a grid of settings, then live runs confirm the result.

**Tech Stack:** Python 3.12, uv, FastAPI, httpx, pydantic 2, psycopg 3, Postgres 16 + pgvector, Groq free tier (gpt-oss-20b / gpt-oss-120b), Qwen judge on Groq, pytest + pytest-asyncio.

**Spec:**
- [`docs/superpowers/specs/2026-10-04-phase-3-router-design.md`](../specs/2026-10-04-phase-3-router-design.md) (approved), referred to below as "the addendum"
- It builds on main spec §7–8: [`2026-09-30-weir-design.md`](../specs/2026-09-30-weir-design.md)
- Decisions D33–D36 in [`docs/decisions.md`](../../decisions.md)

## Global Constraints

- **Free tools and free tiers only** (D0). No paid service, API or dependency.
- **Never more than 2 model calls per request** (`router.max_model_calls`, at most 2).
- **Quality bar (D33):**
  - overall judge ≥ baseline − 0.1
  - facts ≥ baseline
  - small-route mean judge ≥ the large model's mean on the same questions
  - cost per 1k lower than baseline
  - full Weir has 0 wrong cache hits
- **Only grounding-passed answers are cached.** `options.force_model` requests bypass the cache with reason `force_model` (D35).
- **Pricing (D13):** gpt-oss-20b $0.075 in / $0.30 out per 1M tokens; gpt-oss-120b $0.15 / $0.60; embeddings $0.
- **Networking on this Windows machine:**
  - Use `127.0.0.1`, never `localhost`, for Postgres, Weir (:8000) and hospital-rag (:8001).
  - In Git Bash, prefix `docker exec` / `docker compose exec` commands that pass paths with `MSYS_NO_PATHCONV=1`.
- **Editing files:** never use PowerShell `Get-Content`/`Set-Content` on repo files (UTF-8 corruption). Use the editor tools.
- **Secrets:** keys live only in `.env` (gitignored). Never print, paste or commit key values.
- **Commits:** before every commit, tell the user what is in it and wait for their OK. After committing, push the branch and fast-forward `main`:

  ```bash
  git push origin phase-3 && git push origin phase-3:main
  ```

- **Docs:** every plan, decision and result goes in `docs/`: `progress.md`, `decisions.md` (next number is D37), `results/`.
- **Pace:** take it slow. After each task's commit, wait for the user's go-ahead before starting the next task.
- **RAM is tight (15.5 GB):** stop containers when a step is done with them (`docker compose stop`).
- **Judge budget:** Qwen on Groq allows about 220 grades a day. Every judged run uses `--no-judge`, then `rejudge`, which saves each row and resumes after interruptions.
- **Running tests from the repo root:**
  - `cd services/weir && uv run pytest -q`
  - `cd services/hospital-rag && uv run pytest -q`
  - `cd eval && uv run pytest -q`
  - DB tests need `docker compose up -d postgres`.

## Review Focus

1. **A 429 (or timeout) from the small model** should not fail the request when the router chose small. Weir answers from the large model, logs `route_reason = "simple+fallback"` and bills only the call that answered. Pinned in Task 5 (`test_rate_limited_small_falls_back_to_large`).
2. **The escalation call to the large model fails.** The caller still gets the small answer (status 200). The log shows `error_detail = "escalation_failed:<kind>"`, and the answer is not cached. Pinned in Task 5 (`test_failed_escalation_returns_the_small_answer`).
3. **A small route with no chunks** (`finish_reason = "skipped"`) must not escalate: 0 model calls, $0. Pinned in Task 5 (`test_skipped_small_call_never_escalates`).
4. **An answer with no content words** ("It is.", or only citation markers) must fail with `empty_answer`, not divide by zero. Pinned in Task 4 (`test_answer_without_content_words_is_empty_answer`).
5. **A simulated setting that routes nothing to small** trivially "matches the baseline". It must not count as passing, otherwise the tuner "succeeds" by turning the router off. Pinned in Task 8 (`test_bar_requires_some_small_routes`).

---

## File Structure

| File | Create/Modify | Responsibility |
| --- | --- | --- |
| `db/migrations/003_phase3_router.sql` | Create | `route_reason`, `grounding_reason`, `grounding_overlap` columns |
| `configs/weir.yaml` | Modify | `router` cut-offs, reasoning words, `grounding.min_overlap` |
| `configs/ablations/small_only.yaml`, `router_only.yaml`, `full.yaml` | Create | New ablation overlays |
| `services/weir/src/weir/config.py` | Modify | `Tier`, extended `RouterConfig`, `GroundingConfig` |
| `services/weir/src/weir/metrics/logger.py` | Modify | Three new `RequestLogRow` fields |
| `services/weir/src/weir/cache/guards.py` | Modify | `_phrases` → public `phrase_pattern`; `bypass_reason(force_model=...)` |
| `services/weir/src/weir/router/__init__.py` | Create | Package marker |
| `services/weir/src/weir/router/features.py` | Create | `Features`, `FeatureExtractor`, `count_questions` |
| `services/weir/src/weir/router/rules.py` | Create | `route()`, `ROUTER_DECISIONS` |
| `services/weir/src/weir/router/grounding.py` | Create | `Grounding`, `check()`, `overlap()`, `content_words()` |
| `services/weir/src/weir/pipeline.py` | Modify | Router call, `_answer` (fallback, escalation, cap), cost sums, grounding-gated store |
| `services/weir/tests/test_router_features.py`, `test_router_rules.py`, `test_router_grounding.py` | Create | Unit tests |
| `services/weir/tests/test_pipeline.py`, `test_guards.py`, `test_config.py`, `test_migrate.py`, `test_logger.py` | Modify | Updated and new tests |
| `eval/src/weir_eval/features.py` | Create | Features for every eval question via hospital-rag `/retrieve` |
| `eval/src/weir_eval/request_log.py` | Create | Export grounding fields from `weir.request_log` by request id |
| `eval/src/weir_eval/simulate.py` | Create | Offline router simulation, grid, bar, choice, report |
| `eval/src/weir_eval/gate.py` | Create | Exit-gate check of a live report against baseline v3, same ids |
| `eval/src/weir_eval/workload.py` | Modify | `project_onto_workload` (derived replay reports) |
| `eval/src/weir_eval/summary.py` | Modify | `by_route` breakdown (judge, facts, latency, cost per route, escalation rate) |
| `eval/src/weir_eval/cli.py` | Modify | `features`, `export-grounding`, `simulate`, `gate`, `derive-workload` commands |
| `eval/tests/test_features.py`, `test_simulate.py`, `test_gate.py` | Create | Eval tests |
| `eval/tests/test_workload.py`, `test_summary.py`, `test_request_log.py` | Modify/Create | Eval tests |
| `docs/results/router-tuning.md`, `router.md`, `summary.md` | Create | Results |
| `docs/progress.md`, `decisions.md`, `backlog.md`, `README.md` | Modify | Documentation |

**One behaviour rule shared by Tasks 3 and 5:** fallback and escalation happen **only when the router made the decision**. That means `route_reason` is one of `clinical`, `weak_retrieval`, `simple` or `default_large`. Forced routes (`kill_switch`, `force_model`) and a disabled router (`router_disabled`) keep to one tier and one call, exactly like Phase 2. This rule has three consequences:
- The `baseline` and `cache_only` runs stay pure large-model runs.
- The `small_only` trial records the small model's raw answers, never a large-model fallback or escalation.
- A caller who forces a tier gets that tier.

---

### Task 1: Config, migration 003, log fields and overlays

**Files:**
- Create: `db/migrations/003_phase3_router.sql`
- Create: `configs/ablations/small_only.yaml`, `configs/ablations/router_only.yaml`, `configs/ablations/full.yaml`
- Modify: `services/weir/src/weir/config.py` (RouterConfig at lines 19-21, WeirConfig at 58-80)
- Modify: `configs/weir.yaml` (the `router:` block)
- Modify: `services/weir/src/weir/metrics/logger.py` (`RequestLogRow`)
- Test: `services/weir/tests/test_config.py`, `test_migrate.py`, `test_logger.py`

**Interfaces:**
- Produces:
  - `weir.config.Tier = Literal["small", "large"]`
  - `RouterConfig` fields: `enabled: bool`, `default_tier: Tier`, `short_query_tokens: int`, `high_confidence: float`, `low_confidence: float`, `max_model_calls: int` (1–2), `reasoning_words: list[str]`
  - `GroundingConfig(min_overlap: float)` and `WeirConfig.grounding`
  - `RequestLogRow.route_reason: str | None`, `.grounding_reason: str | None`, `.grounding_overlap: float | None`

- [ ] **Step 1: Write the failing tests**

Append to `services/weir/tests/test_config.py`:

```python
def test_phase3_router_and_grounding_config():
    cfg = load_config(CONFIGS / "weir.yaml")
    r = cfg.router
    assert r.enabled is True and r.default_tier == "large" and r.max_model_calls == 2
    assert 0 < r.low_confidence < r.high_confidence <= 1 and r.short_query_tokens > 0
    assert {"why", "compare", "pros and cons"} <= set(r.reasoning_words)
    assert 0 < cfg.grounding.min_overlap <= 1


def test_max_model_calls_is_capped_at_two(tmp_path):
    bad = tmp_path / "w.yaml"
    text = (CONFIGS / "weir.yaml").read_text(encoding="utf-8").replace("max_model_calls: 2", "max_model_calls: 3")
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(bad)


@pytest.mark.parametrize(("overlay", "cache_on", "router_on", "tier", "force_large"), [
    ("baseline", False, True, "large", True),
    ("cache_only", True, True, "large", True),
    ("small_only", False, False, "small", False),
    ("router_only", False, True, "large", False),
    ("full", True, True, "large", False),
])
def test_ablation_overlays(overlay, cache_on, router_on, tier, force_large):
    cfg = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / f"{overlay}.yaml")
    assert cfg.config_label == overlay
    assert cfg.cache.enabled is cache_on and cfg.router.enabled is router_on
    assert cfg.router.default_tier == tier and cfg.kill_switch.force_large is force_large
```

In `services/weir/tests/test_migrate.py`, change the expected list on line 17 and add a column test:

```python
    assert apply_migrations(clean_db_url, MIGRATIONS) == ["001_init.sql", "002_phase2_cache.sql",
                                                          "003_phase3_router.sql"]
```

```python
def test_phase3_router_columns(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(clean_db_url) as conn:
        cols = dict(conn.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'weir' and table_name = 'request_log' "
            "and column_name in ('route_reason', 'grounding_reason', 'grounding_overlap')").fetchall())
    assert cols == {"route_reason": "text", "grounding_reason": "text", "grounding_overlap": "real"}
```

Append to `services/weir/tests/test_logger.py`:

```python
@pytest.mark.db
async def test_router_fields_are_written(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    writer = LogWriter(pool, flush_interval_s=0.05)
    writer.start()
    writer.submit(row(route="small", route_reason="simple", escalated=True, model_calls=2,
                      grounding_passed=False, grounding_reason="low_overlap", grounding_overlap=0.25))
    await writer.stop()
    await pool.close()
    with psycopg.connect(migrated_db_url) as conn:
        got = conn.execute("select route_reason, escalated, model_calls, grounding_passed, grounding_reason, "
                           "grounding_overlap from weir.request_log").fetchone()
    assert got == ("simple", True, 2, False, "low_overlap", 0.25)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_config.py tests/test_migrate.py tests/test_logger.py`

Expected: FAIL:
- `AttributeError: 'RouterConfig' object has no attribute 'enabled'`
- a missing overlay file
- the migration list mismatch
- `TypeError: ... unexpected keyword argument 'route_reason'`

- [ ] **Step 3: Implement**

Create `db/migrations/003_phase3_router.sql`:

```sql
-- Phase 3 router (addendum §4). grounding_passed, escalated and model_calls already exist from 001.
alter table weir.request_log add column route_reason text;
alter table weir.request_log add column grounding_reason text;
alter table weir.request_log add column grounding_overlap real;
```

In `services/weir/src/weir/config.py`:
- Change the pydantic import to `from pydantic import BaseModel, ConfigDict, Field`.
- Add `Tier` under the imports.
- Replace `RouterConfig`.
- Add `GroundingConfig`.
- Add the field to `WeirConfig`.
- Retype `model_for`.

```python
Tier = Literal["small", "large"]
```

```python
class RouterConfig(_Strict):
    small_model: str
    large_model: str
    enabled: bool = False
    default_tier: Tier = "large"            # the tier used when the router is disabled
    short_query_tokens: int = 20            # tuned offline (addendum §7.3)
    high_confidence: float = 0.75           # tuned offline
    low_confidence: float = 0.40            # tuned offline
    max_model_calls: int = Field(2, ge=1, le=2)
    reasoning_words: list[str] = []


class GroundingConfig(_Strict):
    min_overlap: float = 0.5                # share of answer content words found in the cited chunks
```

In `WeirConfig`, add the field after `router: RouterConfig`:

```python
    grounding: GroundingConfig = GroundingConfig()
```

Change `model_for`:

```python
    def model_for(self, tier: Tier) -> str:
```

In `configs/weir.yaml`, replace the `router:` block and add `grounding:` after it:

```yaml
router:                      # Phase 3 addendum §3.2 / §5
  enabled: true
  default_tier: large        # used when the router is disabled
  small_model: openai/gpt-oss-20b
  large_model: openai/gpt-oss-120b
  short_query_tokens: 20     # starting value; tuned offline in Task 10 (addendum §7.3)
  high_confidence: 0.75      # starting value; tuned offline
  low_confidence: 0.40       # starting value; tuned offline
  max_model_calls: 2         # never more than 2 model calls per request
  reasoning_words: [compare, why, explain, difference, steps, calculate, versus, vs, "pros and cons", better, which is cheaper, both]

grounding:
  min_overlap: 0.5           # starting value; tuned offline in Task 10
```

Create `configs/ablations/small_only.yaml`:

```yaml
# Small-model trial (Phase 3 addendum §7.1): no cache, router off, every request to the small model.
# A disabled router never falls back or escalates, so every answer is the small model's own.
config_label: small_only
cache:
  enabled: false
router:
  enabled: false
  default_tier: small
```

Create `configs/ablations/router_only.yaml`:

```yaml
# Router only (Phase 3 addendum §5): no cache, router on.
config_label: router_only
cache:
  enabled: false
router:
  enabled: true
```

Create `configs/ablations/full.yaml`:

```yaml
# Full Weir (Phase 3 addendum §5): semantic cache and router both on.
config_label: full
cache:
  enabled: true
router:
  enabled: true
```

In `services/weir/src/weir/metrics/logger.py`, add these three fields to `RequestLogRow`:
- `route_reason` directly after `bypass_reason`
- the two grounding fields directly after `grounding_passed`

```python
    route_reason: str | None = None
```

```python
    grounding_reason: str | None = None
    grounding_overlap: float | None = None
```

(`COLUMNS` and `INSERT_SQL` are built from the dataclass fields, so the insert picks them up.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
docker compose up -d postgres
cd services/weir && uv run pytest -q
```

Expected: all tests pass (150 existing + 9 new). If `test_pipeline` fails on route or cost assertions, that is wrong at this point: the pipeline still ignores `router.enabled`. Fix before moving on.

- [ ] **Step 5: Commit** (tell the user first)

```bash
git add db/migrations/003_phase3_router.sql configs/weir.yaml configs/ablations/small_only.yaml \
  configs/ablations/router_only.yaml configs/ablations/full.yaml services/weir/src/weir/config.py \
  services/weir/src/weir/metrics/logger.py services/weir/tests/test_config.py \
  services/weir/tests/test_migrate.py services/weir/tests/test_logger.py
git commit -m "feat(router): config, migration 003, log fields and ablation overlays"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 2: Router features

**Files:**
- Create: `services/weir/src/weir/router/__init__.py`, `services/weir/src/weir/router/features.py`
- Modify: `services/weir/src/weir/cache/guards.py:15-26` (rename `_phrases` → `phrase_pattern`)
- Test: `services/weir/tests/test_router_features.py`

**Interfaces:**
- Consumes:
  - `weir.config.Tier`
  - `weir.cache.guards.BypassRules.clinical(text) -> bool`
  - `weir.rag.adapter.RetrieveResult(chunks, top_score, score_gap, context_tokens, kb_version, latency_ms)`
- Produces:
  - `phrase_pattern(terms: list[str]) -> re.Pattern | None`
  - `Features(tokens, has_reasoning_words, num_questions, top_score, score_gap, context_tokens, is_clinical, forced_tier=None)`, a frozen dataclass
  - `count_questions(text: str) -> int`
  - `FeatureExtractor(count_tokens: Callable[[str], int], rules: BypassRules, reasoning_words: list[str])` with `.extract(query: str, retrieved: RetrieveResult, forced_tier: Tier | None = None) -> Features`

- [ ] **Step 1: Write the failing test**

Create `services/weir/tests/test_router_features.py`:

```python
import pytest

from weir.cache.guards import BypassRules
from weir.config import load_config
from weir.rag.adapter import RetrieveResult
from weir.router.features import FeatureExtractor, Features, count_questions

from .conftest import CONFIGS

CFG = load_config(CONFIGS / "weir.yaml")
RETRIEVED = RetrieveResult(chunks=[], top_score=0.82, score_gap=0.11, context_tokens=640, kb_version="v1",
                           latency_ms=3)


def extractor(words=("why", "compare", "pros and cons", "vs")):
    return FeatureExtractor(lambda text: len(text.split()), BypassRules(CFG.bypass), list(words))


def test_extracts_every_feature():
    f = extractor().extract("  When can I   VISIT the ICU? ", RETRIEVED)
    assert f == Features(tokens=6, has_reasoning_words=False, num_questions=1, top_score=0.82, score_gap=0.11,
                         context_tokens=640, is_clinical=False, forced_tier=None)


def test_forced_tier_passes_through():
    assert extractor().extract("q", RETRIEVED, forced_tier="small").forced_tier == "small"


@pytest.mark.parametrize(("query", "expected"), [
    ("Why is the ICU closed on Sundays?", True),
    ("Compare the two parking options", True),
    ("What are the pros and cons of the private ward?", True),
    ("General ward vs private ward price?", True),
    ("Who is Dr Whyte?", False),            # word boundary: "whyte" is not "why"
    ("When can I visit?", False),
])
def test_reasoning_words(query, expected):
    assert extractor().extract(query, RETRIEVED).has_reasoning_words is expected


def test_no_reasoning_words_configured():
    assert extractor(words=()).extract("Why?", RETRIEVED).has_reasoning_words is False


@pytest.mark.parametrize(("query", "expected"), [
    ("When can I visit?", 1),
    ("visiting hours", 1),                                          # no "?" still counts as one
    ("When does it open and when does it close?", 2),
    ("When does it open? And when does it close?", 2),              # "? and when" is not counted twice
    ("What is the MRI price and is parking free?", 2),
    ("Where is it? When is it open? How much is it?", 3),
])
def test_count_questions(query, expected):
    assert count_questions(query) == expected


def test_clinical_uses_the_bypass_keywords():
    assert extractor().extract("What dosage of paracetamol is safe?", RETRIEVED).is_clinical is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/weir && uv run pytest -q tests/test_router_features.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'weir.router'`.

- [ ] **Step 3: Implement**

In `services/weir/src/weir/cache/guards.py`, rename `_phrases` to `phrase_pattern`. That covers the definition and both uses in `BypassRules.__init__`:

```python
def phrase_pattern(terms: list[str]) -> re.Pattern | None:
    """One regex matching any of the phrases as whole words; a trailing "*" means prefix match."""
    parts = []
    for term in terms:
        t = normalize(term)
        parts.append(re.escape(t[:-1]) + r"\w*" if t.endswith("*") else re.escape(t))
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)") if parts else None
```

```python
        self._time = phrase_pattern(cfg.time_sensitive)
        self._clinical = phrase_pattern(cfg.clinical)
```

Create `services/weir/src/weir/router/__init__.py`:

```python
"""Phase 3 model router: features, rules and the grounding check (addendum §3)."""
```

Create `services/weir/src/weir/router/features.py`:

```python
"""Router features from the question and the retrieval result (Phase 3 addendum §3.1)."""
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..cache.guards import BypassRules, phrase_pattern
from ..config import Tier
from ..rag.adapter import RetrieveResult
from ..text import normalize

# "... and when ...": a second question joined by "and". Not counted right after "?" / "." / "!",
# where the "?" already counted it.
AND_QUESTION = re.compile(r"(?<![?.!]) and (?:what|when|where|how|which|who|why|is|are|can|does|do)\b")


@dataclass(frozen=True)
class Features:
    tokens: int
    has_reasoning_words: bool
    num_questions: int
    top_score: float
    score_gap: float
    context_tokens: int
    is_clinical: bool
    forced_tier: Tier | None = None


def count_questions(text: str) -> int:
    t = normalize(text)
    return max(1, t.count("?") + len(AND_QUESTION.findall(t)))


class FeatureExtractor:
    def __init__(self, count_tokens: Callable[[str], int], rules: BypassRules, reasoning_words: list[str]):
        self._count_tokens = count_tokens
        self._rules = rules
        self._reasoning = phrase_pattern(reasoning_words)

    def extract(self, query: str, retrieved: RetrieveResult, forced_tier: Tier | None = None) -> Features:
        t = normalize(query)
        return Features(
            tokens=self._count_tokens(t),
            has_reasoning_words=bool(self._reasoning and self._reasoning.search(t)),
            num_questions=count_questions(t),
            top_score=retrieved.top_score,
            score_gap=retrieved.score_gap,
            context_tokens=retrieved.context_tokens,
            is_clinical=self._rules.clinical(query),
            forced_tier=forced_tier,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/weir && uv run pytest -q tests/test_router_features.py tests/test_guards.py`

Expected: PASS.

- [ ] **Step 5: Commit** (tell the user first)

```bash
git add services/weir/src/weir/router/__init__.py services/weir/src/weir/router/features.py \
  services/weir/src/weir/cache/guards.py services/weir/tests/test_router_features.py
git commit -m "feat(router): question and retrieval features"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 3: Router rules v1

**Files:**
- Create: `services/weir/src/weir/router/rules.py`
- Test: `services/weir/tests/test_router_rules.py`

**Interfaces:**
- Consumes: `Features` (Task 2) and `WeirConfig` (Task 1).
- Produces:
  - `route(f: Features, cfg: WeirConfig) -> tuple[Tier, str]`. The reasons are `kill_switch`, `force_model`, `router_disabled`, `clinical`, `weak_retrieval`, `simple` and `default_large`.
  - `ROUTER_DECISIONS: frozenset[str] = {"clinical", "weak_retrieval", "simple", "default_large"}`. These are the reasons for which the pipeline may fall back or escalate.

- [ ] **Step 1: Write the failing test**

Create `services/weir/tests/test_router_rules.py`:

```python
import pytest

from weir.config import load_config
from weir.router.features import Features
from weir.router.rules import ROUTER_DECISIONS, route

from .conftest import CONFIGS


def cfg(**router):
    c = load_config(CONFIGS / "weir.yaml")
    for k, v in {"enabled": True, "short_query_tokens": 20, "high_confidence": 0.75, "low_confidence": 0.40,
                 **router}.items():
        setattr(c.router, k, v)
    return c


def feats(**over):
    base = dict(tokens=8, has_reasoning_words=False, num_questions=1, top_score=0.9, score_gap=0.1,
                context_tokens=500, is_clinical=False, forced_tier=None)
    return Features(**{**base, **over})


def test_simple_question_goes_small():
    assert route(feats(), cfg()) == ("small", "simple")


@pytest.mark.parametrize(("over", "expected"), [
    ({"tokens": 21}, ("large", "default_large")),
    ({"has_reasoning_words": True}, ("large", "default_large")),
    ({"num_questions": 2}, ("large", "default_large")),
    ({"top_score": 0.74}, ("large", "default_large")),
    ({"top_score": 0.39}, ("large", "weak_retrieval")),
    ({"is_clinical": True}, ("large", "clinical")),
])
def test_each_large_branch(over, expected):
    assert route(feats(**over), cfg()) == expected


def test_boundaries_are_inclusive():
    assert route(feats(tokens=20, top_score=0.75), cfg()) == ("small", "simple")
    assert route(feats(top_score=0.40), cfg(high_confidence=0.40)) == ("small", "simple")  # not weak at exactly low


def test_order_kill_switch_then_force_then_disabled():
    c = cfg(enabled=False)
    c.kill_switch.force_large = True
    assert route(feats(forced_tier="small"), c) == ("large", "kill_switch")
    c.kill_switch.force_large = False
    assert route(feats(forced_tier="small", is_clinical=True), c) == ("small", "force_model")
    assert route(feats(), c) == ("large", "router_disabled")
    c.router.default_tier = "small"
    assert route(feats(is_clinical=True), c) == ("small", "router_disabled")


def test_clinical_beats_weak_retrieval_and_simple():
    assert route(feats(is_clinical=True, top_score=0.1), cfg()) == ("large", "clinical")


def test_router_decisions_exclude_forced_and_disabled():
    assert ROUTER_DECISIONS == {"clinical", "weak_retrieval", "simple", "default_large"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/weir && uv run pytest -q tests/test_router_rules.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'weir.router.rules'`.

- [ ] **Step 3: Implement**

Create `services/weir/src/weir/router/rules.py`:

```python
"""Router rules v1 (main spec §7.2, Phase 3 addendum §3.2). Cut-offs live in configs/weir.yaml, tuned offline."""
from ..config import Tier, WeirConfig
from .features import Features

# Reasons where the router itself chose the tier. Only these may fall back or escalate;
# forced and disabled routes keep to one tier and one call (plan: "one behaviour rule").
ROUTER_DECISIONS = frozenset({"clinical", "weak_retrieval", "simple", "default_large"})


def route(f: Features, cfg: WeirConfig) -> tuple[Tier, str]:
    r = cfg.router
    if cfg.kill_switch.force_large:
        return "large", "kill_switch"
    if f.forced_tier:
        return f.forced_tier, "force_model"
    if not r.enabled:
        return r.default_tier, "router_disabled"
    if f.is_clinical:
        return "large", "clinical"
    if f.top_score < r.low_confidence:
        return "large", "weak_retrieval"
    if (f.tokens <= r.short_query_tokens and not f.has_reasoning_words
            and f.num_questions == 1 and f.top_score >= r.high_confidence):
        return "small", "simple"
    return "large", "default_large"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd services/weir && uv run pytest -q tests/test_router_rules.py`

Expected: PASS (11 tests).

- [ ] **Step 5: Commit** (tell the user first)

```bash
git add services/weir/src/weir/router/rules.py services/weir/tests/test_router_rules.py
git commit -m "feat(router): rules v1 with reasons"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 4: Grounding check

**Files:**
- Create: `services/weir/src/weir/router/grounding.py`
- Test: `services/weir/tests/test_router_grounding.py`

**Interfaces:**
- Consumes:
  - `GenerateResult(answer, cited_chunk_ids, invalid_citations, not_found, finish_reason, tokens_in, tokens_out, model, prompt_version, latency_ms)`
  - `RetrievedChunk(id, doc_id, title, text, score, token_count)`
- Produces:
  - `Grounding(passed: bool, reason: str | None, overlap: float | None)`, a frozen dataclass
  - `check(generated: GenerateResult, chunks: list[RetrievedChunk], min_overlap: float) -> Grounding`
  - `overlap(answer: str, source_text: str) -> float | None`
  - `content_words(text: str) -> list[str]`
  - `STOPWORDS`
- **Logging contract, used by the Task 8 simulator:** `reason` is the first failing rule. `overlap` is measured whenever every cited id is among the chunks and the answer has content words, *even when an earlier rule failed*. So an answer with `reason in (None, "low_overlap")` passes at any `m <= overlap`.

- [ ] **Step 1: Write the failing test**

Create `services/weir/tests/test_router_grounding.py`:

```python
import pytest

from weir.rag.adapter import GenerateResult, RetrievedChunk
from weir.router.grounding import Grounding, check, content_words, overlap

CHUNKS = [
    RetrievedChunk(id="a#0", doc_id="a", title="ICU", text="ICU visiting begins at 11 am.", score=0.9, token_count=8),
    RetrievedChunk(id="b#0", doc_id="b", title="Parking", text="Parking: 50 rupees per day.", score=0.8,
                   token_count=7),
]


def gen(**over):
    base = dict(answer="ICU visiting starts at 11 am 【c1】.", cited_chunk_ids=["a#0"], invalid_citations=0,
                not_found=False, finish_reason="stop", tokens_in=100, tokens_out=20, model="m", prompt_version="p1",
                latency_ms=5)
    return GenerateResult(**{**base, **over})


def test_grounded_answer_passes_with_measured_overlap():
    # content words {icu, visiting, starts, 11}; the chunk has icu, visiting, 11 -> 3/4
    assert check(gen(), CHUNKS, 0.5) == Grounding(True, None, 0.75)


def test_low_overlap_fails_but_keeps_the_measurement():
    assert check(gen(), CHUNKS, 0.8) == Grounding(False, "low_overlap", 0.75)


@pytest.mark.parametrize(("over", "reason"), [
    ({"not_found": True, "answer": "NOT_FOUND", "cited_chunk_ids": []}, "not_found"),
    ({"finish_reason": "length"}, "finish_reason:length"),
    ({"finish_reason": "skipped"}, "finish_reason:skipped"),
    ({"cited_chunk_ids": []}, "no_citations"),
    ({"invalid_citations": 1}, "invalid_citations"),
    ({"answer": "ICU visiting starts at 11 am [c1]. Parking: NOT_FOUND"}, "partial_answer"),
    ({"cited_chunk_ids": ["zz#9"]}, "unknown_citations"),
])
def test_each_failure_rule(over, reason):
    result = check(gen(**over), CHUNKS, 0.5)
    assert result.passed is False and result.reason == reason


def test_first_failing_rule_wins():
    assert check(gen(finish_reason="length", cited_chunk_ids=[]), CHUNKS, 0.5).reason == "finish_reason:length"


def test_answer_without_content_words_is_empty_answer():  # Review Focus 4: no division by zero
    result = check(gen(answer="It is [c1]."), CHUNKS, 0.5)
    assert result == Grounding(False, "empty_answer", None)


def test_citation_markers_and_stopwords_are_not_content_words():
    assert content_words("Parking costs 50 [c1] 【c2†L3-L5】 per the [c1, c2] page.") == ["parking", "costs", "50",
                                                                                     "page"]


def test_overlap_uses_only_the_cited_chunks():
    # cites the parking chunk only, so the ICU words are missing
    result = check(gen(answer="Parking is 50 rupees [c2].", cited_chunk_ids=["b#0"]), CHUNKS, 0.5)
    assert result.passed and result.overlap == 1.0
    assert check(gen(cited_chunk_ids=["b#0"]), CHUNKS, 0.5).reason == "low_overlap"


def test_overlap_counts_each_word_once():
    assert overlap("icu icu icu parking", "icu") == 0.5
    assert overlap("the and of", "anything") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/weir && uv run pytest -q tests/test_router_grounding.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'weir.router.grounding'`.

- [ ] **Step 3: Implement**

Create `services/weir/src/weir/router/grounding.py`:

```python
"""Rule-based grounding check for generated answers (main spec §7.4, addendum §3.3, decision D6).

An answer passes when it is a finished, cited answer whose content words mostly appear in the cited chunks.
"""
import re
from dataclasses import dataclass

from ..rag.adapter import GenerateResult, RetrievedChunk

# [c1], [c1, c3], [c1 and c2] and gpt-oss's 【c1】 / 【c2†L3-L5】 (same shapes hospital-rag parses).
CITATION = re.compile(r"[\[【]\s*c\d+[^\]】]*[\]】]", re.IGNORECASE)
WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset("""
a an the and or but if then than so of to in on at by for from with without about into over under per via
is are was were be been being am do does did done have has had having can could will would shall should may
might must it its this that these those there here they them their you your we our us he she his her i me my
as also only just very more most less any all each up out what when where which who whom whose why how please
""".split())


@dataclass(frozen=True)
class Grounding:
    passed: bool
    reason: str | None       # the first failing rule; None when passed
    overlap: float | None    # share of the answer's content words found in the cited chunks


def content_words(text: str) -> list[str]:
    return [w for w in WORD.findall(CITATION.sub(" ", text).lower()) if w not in STOPWORDS]


def overlap(answer: str, source_text: str) -> float | None:
    words = set(content_words(answer))
    if not words:
        return None
    source = set(WORD.findall(source_text.lower()))
    return len(words & source) / len(words)


def check(generated: GenerateResult, chunks: list[RetrievedChunk], min_overlap: float) -> Grounding:
    by_id = {c.id: c for c in chunks}
    cited = [by_id.get(i) for i in generated.cited_chunk_ids]
    known = bool(cited) and all(c is not None for c in cited)
    measured = overlap(generated.answer, " ".join(c.text for c in cited)) if known else None
    reason = _first_failure(generated, known, measured, min_overlap)
    return Grounding(reason is None, reason, measured)


def _first_failure(g: GenerateResult, known: bool, measured: float | None, min_overlap: float) -> str | None:
    if g.not_found:
        return "not_found"
    if g.finish_reason != "stop":
        return f"finish_reason:{g.finish_reason}"
    if not g.cited_chunk_ids:
        return "no_citations"
    if g.invalid_citations:
        return "invalid_citations"
    if "not_found" in g.answer.lower():  # answered part, then gave up on the rest (D27)
        return "partial_answer"
    if not known:
        return "unknown_citations"
    if measured is None:
        return "empty_answer"
    if measured < min_overlap:
        return "low_overlap"
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd services/weir && uv run pytest -q tests/test_router_grounding.py`

Expected: PASS (14 tests).

- [ ] **Step 5: Commit** (tell the user first)

```bash
git add services/weir/src/weir/router/grounding.py services/weir/tests/test_router_grounding.py
git commit -m "feat(router): rule-based grounding check with overlap measurement"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 5: Pipeline integration (route, fallback, escalation, cap, logging, cache gate)

**Files:**
- Modify: `services/weir/src/weir/cache/guards.py` (`bypass_reason` signature, lines 48-66)
- Modify: `services/weir/src/weir/pipeline.py`
- Modify: `services/weir/tests/test_guards.py`, `services/weir/tests/test_pipeline.py`

**Interfaces:**
- Consumes:
  - `FeatureExtractor.extract` (Task 2)
  - `route`, `ROUTER_DECISIONS` (Task 3)
  - `check`, `Grounding` (Task 4)
  - `cfg.router.max_model_calls`, `cfg.grounding.min_overlap` (Task 1)
- Produces:
  - `bypass_reason(..., force_model: bool = False)`, which returns `"force_model"` right after `request_option`.
  - Every non-hit `RequestLogRow` carries `route`, `route_reason` (with a `+fallback` suffix when a fallback happened), `escalated`, `model_calls`, `grounding_passed`, `grounding_reason` and `grounding_overlap`.
  - `meta.route` is the routed tier, `meta.escalated` is real, and `meta.model` is the model that answered.
- **Cost rules (addendum §3.6):**
  - `cost_usd` = the sum over every call that returned, each at its own model's price, plus the embedding.
  - `counterfactual_cost_usd` = the answering call's tokens at the large-model price.
  - `tokens_in` / `tokens_out` = the sums over all calls that returned.

- [ ] **Step 1: Write the failing tests**

In `services/weir/tests/test_guards.py`:
- Add `force_model=False` to the `reason()` helper and pass it through.
- Add one assertion.

```python
def reason(query="When can I visit?", namespace=PUBLIC, session_id=None, personalized=False, bypass_cache=False,
           config=None, force_model=False):
    c = config or cfg()
    return bypass_reason(query=query, namespace=namespace, session_id=session_id, personalized=personalized,
                         bypass_cache=bypass_cache, cfg=c, rules=BypassRules(c.bypass), force_model=force_model)
```

```python
def test_force_model_bypasses_after_request_option():
    assert reason(force_model=True) == "force_model"
    assert reason(force_model=True, bypass_cache=True) == "request_option"
    assert reason(force_model=True, config=cfg(enabled=False)) == "force_model"
```

In `services/weir/tests/test_pipeline.py`:

(a) Change `CHUNKS` so the default answer `"Answer."` is grounded in them:

```python
CHUNKS = [
    {"id": "pub-a#0", "doc_id": "pub-a", "title": "Visiting", "text": "Answer text", "score": 0.9, "token_count": 3},
    {"id": "pub-a#1", "doc_id": "pub-a", "title": "Visiting", "text": "Answer text", "score": 0.8, "token_count": 3},
    {"id": "pub-b#0", "doc_id": "pub-b", "title": "ICU", "text": "Answer text", "score": 0.7, "token_count": 3},
]
SMALL, LARGE = "openai/gpt-oss-20b", "openai/gpt-oss-120b"
UNGROUNDED = "Something unrelated entirely."
LIMITED = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
# Router on, with cut-offs pinned so offline tuning (Task 10) never changes these tests.
ROUTER_ON = dict(router__enabled=True, router__short_query_tokens=20, router__high_confidence=0.75,
                 router__low_confidence=0.40, router__max_model_calls=2, grounding__min_overlap=0.5)
```

(b) Make `fake_rag` take per-model answers and per-model responses. A response may be an exception, which is raised as a transport error. Replace the whole function:

```python
def fake_rag(generate_response=None, chunks=CHUNKS, seen=None, calls=None, top_score=0.9, cited=None, answer="Answer.",
             answers=None, responses=None):
    def handler(request):
        if calls is not None:
            calls.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path == "/retrieve":
            return httpx.Response(200, json={"chunks": chunks, "top_score": top_score if chunks else 0.0,
                                             "score_gap": 0.1, "context_tokens": 9,
                                             "kb_version": "v1" if chunks else None, "latency_ms": 3})
        if seen is not None:
            seen.append(body)
        per_model = (responses or {}).get(body["model"])
        if isinstance(per_model, Exception):
            raise per_model
        if per_model is not None:  # a fresh copy: one Response object must not be served twice
            return httpx.Response(per_model.status_code, content=per_model.content, headers=per_model.headers)
        if generate_response is not None:
            return generate_response
        has = bool(body["chunks"])
        ids = (["pub-a#1", "pub-b#0", "pub-a#0"] if cited is None else cited) if has else []
        text = (answers or {}).get(body["model"], answer)
        return httpx.Response(200, json={
            "answer": text if has else "Sorry, not found.", "cited_chunk_ids": ids, "invalid_citations": 0,
            "not_found": not has, "finish_reason": "stop" if has else "skipped",
            "tokens_in": 1000 if has else 0, "tokens_out": 500 if has else 0,
            "model": body["model"], "prompt_version": "p1", "latency_ms": 7})
    return RagClient("http://rag", 5, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag"))
```

(c) In `harness`, keep the Phase 2 tests on a disabled router. Add this as the first line of the function body:

```python
    config_overrides.setdefault("router__enabled", False)  # Phase 2 tests; router tests pass ROUTER_ON
```

(d) Update the three existing tests whose meaning changes.

In `test_first_ask_is_a_miss_with_cost_log_and_store`, add after `[row] = h.sink.rows`:

```python
    assert row.route_reason == "router_disabled" and row.model_calls == 1 and row.escalated is False
    assert row.grounding_passed is True and row.grounding_reason is None and row.grounding_overlap == 1.0
```

Replace `test_force_small_is_cheaper_than_counterfactual`:

```python
async def test_force_small_is_cheaper_than_counterfactual_and_bypasses_cache():
    seen = []
    h = harness(fake_rag(seen=seen))
    resp = await h.p.handle(ask("q", options=QueryOptions(force_model="small")))
    assert seen[0]["model"] == SMALL and resp.meta.route == "small"
    row = h.sink.rows[0]
    assert row.cost_usd == Decimal("0.000225") and row.counterfactual_cost_usd == Decimal("0.00045")
    assert row.bypass_reason == "force_model" and row.route_reason == "force_model"
    await h.writer.drain()
    assert h.store.entries == []  # D35: forced answers are never cached (backlog M9)
```

In `test_kill_switch_force_large_beats_force_model`, change the last line to:

```python
    assert h.sink.rows[0].bypass_reason == "force_model" and h.sink.rows[0].route_reason == "kill_switch"
```

(e) Add a router section at the end of `test_pipeline.py`:

```python
# --- router (Phase 3) -------------------------------------------------------------------------

async def test_simple_question_goes_small_and_is_cached():
    seen = []
    h = harness(fake_rag(seen=seen), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL]
    assert resp.meta.route == "small" and resp.meta.model == SMALL and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.route_reason == "simple" and row.model_calls == 1 and row.grounding_passed is True
    assert row.cost_usd == Decimal("0.000225") and row.counterfactual_cost_usd == Decimal("0.00045")
    await h.writer.drain()
    [entry] = h.store.entries
    assert entry.model == SMALL


async def test_ungrounded_small_answer_escalates_to_large():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL, LARGE]
    assert resp.answer == "Answer." and resp.meta.route == "small" and resp.meta.escalated is True
    assert resp.meta.model == LARGE
    row = h.sink.rows[0]
    assert row.route_reason == "simple" and row.escalated is True and row.model_calls == 2
    assert (row.tokens_in, row.tokens_out) == (2000, 1000)
    assert row.cost_usd == Decimal("0.000675")                 # small + large calls
    assert row.counterfactual_cost_usd == Decimal("0.00045")   # the answering (large) call at the large price
    assert row.grounding_passed is True                        # the large answer's check


async def test_answer_that_fails_grounding_is_returned_but_never_cached():
    h = harness(fake_rag(answer=UNGROUNDED), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == UNGROUNDED and resp.meta.escalated is True
    row = h.sink.rows[0]
    assert row.grounding_passed is False and row.grounding_reason == "low_overlap" and row.grounding_overlap == 0.0
    await h.writer.drain()
    assert h.store.entries == [] and row.cache_entry_id is None


@pytest.mark.parametrize("query", [
    "Why are ICU visits limited to two people?",          # reasoning word
    "When can I visit and how much is parking?",          # two questions
])
async def test_harder_questions_go_large(query):
    seen = []
    h = harness(fake_rag(seen=seen), **ROUTER_ON)
    resp = await h.p.handle(ask(query))
    assert [b["model"] for b in seen] == [LARGE] and resp.meta.route == "large"
    assert h.sink.rows[0].route_reason == "default_large"


async def test_weak_retrieval_goes_large():
    h = harness(fake_rag(top_score=0.3), **ROUTER_ON)
    await h.p.handle(ask("When can I visit?"))
    assert h.sink.rows[0].route == "large" and h.sink.rows[0].route_reason == "weak_retrieval"


async def test_clinical_question_goes_large():
    h = harness(fake_rag(), **ROUTER_ON)
    await h.p.handle(ask("What dosage of paracetamol is safe?"))
    row = h.sink.rows[0]
    assert row.route == "large" and row.route_reason == "clinical" and row.bypass_reason == "clinical"


async def test_skipped_small_call_never_escalates():  # Review Focus 3
    calls = []
    h = harness(fake_rag(chunks=[], calls=calls), **{**ROUTER_ON, "router__low_confidence": 0.0,
                                                     "router__high_confidence": 0.0})
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.meta.route == "small" and resp.meta.escalated is False and calls.count("/generate") == 1
    row = h.sink.rows[0]
    assert row.model_calls == 0 and row.cost_usd == 0 and row.grounding_reason == "not_found"


async def test_rate_limited_small_falls_back_to_large():  # Review Focus 1
    seen = []
    h = harness(fake_rag(seen=seen, responses={SMALL: LIMITED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL, LARGE]
    assert resp.answer == "Answer." and resp.meta.model == LARGE and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.route == "small" and row.route_reason == "simple+fallback" and row.model_calls == 2
    assert row.cost_usd == Decimal("0.00045") and row.status == "ok"   # only the answering call is billed


async def test_fallback_to_small_never_makes_a_third_call():
    seen = []
    h = harness(fake_rag(seen=seen, top_score=0.3, responses={LARGE: LIMITED}, answers={SMALL: UNGROUNDED}),
                **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [LARGE, SMALL]          # cap of 2: no escalation after the fallback
    assert resp.answer == UNGROUNDED and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.route_reason == "weak_retrieval+fallback" and row.model_calls == 2
    await h.writer.drain()
    assert h.store.entries == []


async def test_both_tiers_failing_returns_503_with_request_id():
    seen = []
    h = harness(fake_rag(seen=seen, responses={SMALL: LIMITED, LARGE: LIMITED}), **ROUTER_ON)
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("When can I visit?"))
    assert exc.value.status_code == 503 and exc.value.retry_after == 12.0
    assert len(seen) == 2 and exc.value.request_id == str(h.sink.rows[0].request_id)
    assert h.sink.rows[0].status == "error" and h.sink.rows[0].model_calls == 2


async def test_failed_escalation_returns_the_small_answer():  # Review Focus 2
    h = harness(fake_rag(answers={SMALL: UNGROUNDED}, responses={LARGE: LIMITED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == UNGROUNDED and resp.meta.model == SMALL and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.status == "ok" and row.error_detail == "escalation_failed:rate_limited" and row.model_calls == 2
    assert row.cost_usd == Decimal("0.000225")
    await h.writer.drain()
    assert h.store.entries == []


async def test_max_model_calls_one_disables_fallback_and_escalation():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), **{**ROUTER_ON, "router__max_model_calls": 1})
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL] and resp.meta.escalated is False


async def test_unreachable_rag_does_not_fall_back():
    seen = []
    h = harness(fake_rag(seen=seen, responses={SMALL: httpx.ConnectError("down")}), **ROUTER_ON)
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("When can I visit?"))
    assert exc.value.status_code == 502 and len(seen) == 1


async def test_force_model_small_with_router_on_never_escalates():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?", options=QueryOptions(force_model="small")))
    assert [b["model"] for b in seen] == [SMALL] and resp.meta.escalated is False
    assert h.sink.rows[0].route_reason == "force_model" and h.sink.rows[0].bypass_reason == "force_model"


async def test_kill_switch_force_large_never_falls_back():
    seen = []
    h = harness(fake_rag(seen=seen, responses={LARGE: LIMITED}), **{**ROUTER_ON, "kill_switch__force_large": True})
    with pytest.raises(PipelineError):
        await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [LARGE] and h.sink.rows[0].route_reason == "kill_switch"


async def test_disabled_router_uses_default_tier_without_escalation():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), router__default_tier="small")
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL] and resp.answer == UNGROUNDED
    row = h.sink.rows[0]
    assert row.route_reason == "router_disabled" and row.grounding_reason == "low_overlap"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_guards.py tests/test_pipeline.py`

Expected: FAIL:
- `TypeError: bypass_reason() got an unexpected keyword argument 'force_model'`
- route and escalation assertions fail (the pipeline still always uses `_choose_tier`)

- [ ] **Step 3: Implement**

In `services/weir/src/weir/cache/guards.py`, change `bypass_reason`:

```python
def bypass_reason(*, query: str, namespace: str, session_id: str | None, personalized: bool,
                  bypass_cache: bool, cfg: WeirConfig, rules: BypassRules, force_model: bool = False) -> str | None:
    if personalized:
        return "personalized"
    if bypass_cache:
        return "request_option"
    if force_model:  # D35: a forced tier's answer must not be served to other callers (backlog M9)
        return "force_model"
    if cfg.kill_switch.disable_cache:
```

(The rest of the function is unchanged.)

In `services/weir/src/weir/pipeline.py`:

1. Update the module docstring:

```python
"""Request pipeline (main spec §5.3, Phase 2 addendum §2, Phase 3 addendum §2).

bypass rules → embed → cache lookup → entity guard → HIT: replay the stored answer
                                                    → MISS/BYPASS: retrieve → features → route → generate
                                                      → grounding check → (small failed: escalate once to large)
                                                      → store if grounded and eligible
"""
```

2. Imports. Replace the `Tier = Literal[...]` line with an import, and add the router imports:

```python
from .config import Tier, WeirConfig
from .rag.adapter import GenerateResult, RagClient, RagError, RetrievedChunk, RetrieveResult
from .router.features import FeatureExtractor
from .router.grounding import Grounding, check
from .router.rules import ROUTER_DECISIONS, route
```

Remove the old `from .config import WeirConfig` line, the old `from .rag.adapter import RagClient, RagError, RetrievedChunk` line, and `Tier = Literal["small", "large"]`. Keep `Literal` in the `typing` import (QueryMeta uses it). Add a constant under `ERROR_STATUS`:

```python
FALLBACK_KINDS = frozenset({"rate_limited", "timeout", "bad_response"})  # provider trouble; not "unavailable"
```

3. Add the `Outcome` dataclass after `CacheDeps`:

```python
@dataclass
class Outcome:
    generated: GenerateResult                      # the answer returned to the caller
    grounding: Grounding                           # its grounding check
    billed: list[tuple[str, GenerateResult]]       # (requested model, result) for every call that returned
    escalated: bool = False
    fallback: bool = False
```

4. In `Pipeline.__init__`, add:

```python
        self._features = FeatureExtractor(cache.embedder.count_tokens, cache.rules, cfg.router.reasoning_words)
```

5. In `handle`, pass `force_model` to `bypass_reason`:

```python
        reason = bypass_reason(query=req.query, namespace=req.namespace, session_id=req.session_id,
                               personalized=req.personalized, bypass_cache=req.options.bypass_cache,
                               cfg=self._cfg, rules=self._cache.rules,
                               force_model=req.options.force_model is not None)
```

6. Replace the `try:` block (from `t = time.perf_counter()` before retrieve through `row.latency_llm_ms = _ms(t)`) and everything after the two `except` clauses, down to the `return QueryResponse(...)`. The new version:

```python
        try:
            t = time.perf_counter()
            retrieved = await self._rag.retrieve(req.query, req.namespace, self._cfg.rag.retrieve_k)
            row.latency_retrieval_ms = _ms(t)
            row.retrieval_top_score = retrieved.top_score
            features = self._features.extract(req.query, retrieved, req.options.force_model)
            row.route, row.route_reason = route(features, self._cfg)
            outcome = await self._answer(req, retrieved, row)
        except RagError as e:
            row.status = "timeout" if e.kind == "timeout" else "error"
            row.error_detail = str(e)[:500]
            row.latency_total_ms = _ms(started)
            self._log.submit(row)
            raise PipelineError(ERROR_STATUS[e.kind], e.kind, str(row.request_id), e.retry_after) from e
        except Exception as e:  # noqa: BLE001 - any failure still gets a request_id and a log row
            row.status = "error"
            row.error_detail = f"internal: {type(e).__name__}"
            row.latency_total_ms = _ms(started)
            self._log.submit(row)
            raise PipelineError(500, "internal", str(row.request_id)) from e

        generated = outcome.generated
        if retrieved.kb_version and generated.finish_reason != "skipped":
            # A document edit shows up here first: switch the cache key now, not at the next /info refresh.
            self._cache.versions.observe(req.namespace, retrieved.kb_version, generated.prompt_version)
        if outcome.fallback:
            row.route_reason = f"{row.route_reason}+fallback"
        row.escalated = outcome.escalated
        row.model = generated.model
        row.tokens_in = sum(g.tokens_in for _, g in outcome.billed)
        row.tokens_out = sum(g.tokens_out for _, g in outcome.billed)
        row.cost_usd = (sum((self._prices.cost(m, g.tokens_in, g.tokens_out, today) for m, g in outcome.billed),
                            Decimal(0))
                        + self._embed_cost(row, today))
        row.counterfactual_cost_usd = self._prices.cost(
            self._cfg.router.large_model, generated.tokens_in, generated.tokens_out, today)
        row.grounding_passed = outcome.grounding.passed
        row.grounding_reason = outcome.grounding.reason
        row.grounding_overlap = outcome.grounding.overlap
        row.answer_len = len(generated.answer)
        sources = _sources(retrieved.chunks, generated.cited_chunk_ids)
        if row.cache_status == "miss" and outcome.grounding.passed:  # D35: only grounded answers are cached
            row.cache_entry_id = self._maybe_store(req, normalized, vector, versions, retrieved, generated,
                                                   sources, now)
        row.latency_total_ms = _ms(started)
        self._log.submit(row)

        return QueryResponse(
            answer=generated.answer, sources=sources,
            meta=QueryMeta(request_id=str(row.request_id), cache_status=row.cache_status,
                           similarity=row.similarity, route=row.route, escalated=row.escalated, model=row.model,
                           latency_ms=row.latency_total_ms, cost_usd=float(row.cost_usd)),
        )
```

7. Replace `_choose_tier` with three methods:

```python
    async def _answer(self, req: QueryRequest, retrieved: RetrieveResult, row: RequestLogRow) -> Outcome:
        """One call on the routed tier; on provider trouble try the other tier once; a small answer that fails
        grounding is retried once on large. Only router decisions adapt (plan: one behaviour rule)."""
        adaptive = row.route_reason in ROUTER_DECISIONS
        cap = self._cfg.router.max_model_calls
        tier: Tier = row.route  # type: ignore[assignment]
        fallback = False
        try:
            generated = await self._call(req, retrieved, tier, row)
        except RagError as e:
            if not (adaptive and e.kind in FALLBACK_KINDS and row.model_calls < cap):
                raise
            log.warning("%s model failed (%s); falling back to the other tier", tier, e.kind)
            tier, fallback = ("large" if tier == "small" else "small"), True
            generated = await self._call(req, retrieved, tier, row)
        billed = [(self._cfg.model_for(tier), generated)]
        grounding = self._ground(generated, retrieved)
        escalated = False
        if (adaptive and tier == "small" and not grounding.passed and generated.finish_reason != "skipped"
                and row.model_calls < cap):
            try:
                large = await self._call(req, retrieved, "large", row)
            except RagError as e:
                log.warning("escalation to the large model failed (%s); returning the small answer", e.kind)
                row.error_detail = f"escalation_failed:{e.kind}"
            else:
                billed.append((self._cfg.model_for("large"), large))
                generated, grounding, escalated = large, self._ground(large, retrieved), True
        return Outcome(generated, grounding, billed, escalated, fallback)

    async def _call(self, req: QueryRequest, retrieved: RetrieveResult, tier: Tier,
                    row: RequestLogRow) -> GenerateResult:
        t = time.perf_counter()
        try:
            generated = await self._rag.generate(req.query, req.namespace, retrieved.chunks,
                                                 self._cfg.model_for(tier))
        except RagError:
            row.model_calls += 1  # the provider was asked, even though it failed
            raise
        finally:
            row.latency_llm_ms = (row.latency_llm_ms or 0) + _ms(t)
        if generated.finish_reason != "skipped":  # no chunks: hospital-rag answers without calling a model
            row.model_calls += 1
        return generated

    def _ground(self, generated: GenerateResult, retrieved: RetrieveResult) -> Grounding:
        return check(generated, retrieved.chunks, self._cfg.grounding.min_overlap)
```

- [ ] **Step 4: Run the whole weir suite**

Run: `cd services/weir && uv run pytest -q`

Expected: all tests pass, about 218 (150 + 9 from Task 1, 16 features, 11 rules, 14 grounding, 1 guards, 17 router pipeline tests). `test_api.py` uses `harness()`, so its router stays disabled; it must pass unchanged.

- [ ] **Step 5: Lint**

Run: `cd services/weir && uv run ruff check src tests` (skip this step if ruff isn't in the dev group).

Expected: no errors.

- [ ] **Step 6: Commit** (tell the user first)

```bash
git add services/weir/src/weir/pipeline.py services/weir/src/weir/cache/guards.py \
  services/weir/tests/test_guards.py services/weir/tests/test_pipeline.py
git commit -m "feat(router): route after retrieval, fallback, escalation, 2-call cap, grounding-gated cache"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 6: Live smoke test and progress entry

**Files:**
- Modify: `docs/progress.md` (add a Phase 3 section)

**Interfaces:**
- Consumes: Tasks 1–5 running in Docker.
- Produces: migration 003 applied to the dev database, and a verified live small and large route.

- [ ] **Step 1: Start the stack with the new code**

```bash
docker compose up -d --build postgres migrate hospital-rag weir
docker compose logs migrate | tail -5
```

Expected: the migrate log lists `003_phase3_router.sql` as applied. If Docker Desktop is closed, start it first:

```bash
"/c/Program Files/Docker/Docker/Docker Desktop.exe" &
```

Wait until `docker info` succeeds.

- [ ] **Step 2: Check the health label and ask one simple and one hard question** (real Groq calls, 2–3 in total)

```bash
set -a; . ./.env; set +a
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/v1/query -H "X-API-Key: $WEIR_KEY_PUBLIC" -H 'content-type: application/json' \
  -d '{"query":"What are the ICU visiting hours?","namespace":"weir-general/en/public","options":{"bypass_cache":true}}'
curl -s http://127.0.0.1:8000/v1/query -H "X-API-Key: $WEIR_KEY_PUBLIC" -H 'content-type: application/json' \
  -d '{"query":"Compare the general ward and private ward visiting rules, and explain why the ICU differs.","namespace":"weir-general/en/public","options":{"bypass_cache":true}}'
```

Expected:
- `healthz` shows `"config_label":"dev"`.
- The first answer has `"route":"small"`. If retrieval scored below 0.75 it may say `large`; the logged reason explains which.
- The second has `"route":"large"`.

Do not print `.env` contents.

- [ ] **Step 3: Check the log rows**

```bash
MSYS_NO_PATHCONV=1 docker compose exec postgres psql -U weir -d weir -c \
  "select route, route_reason, escalated, model_calls, grounding_passed, grounding_reason, round(grounding_overlap::numeric,2) as overlap, model from weir.request_log order by ts desc limit 2;"
```

Expected:
- two rows with non-null `route_reason`, `grounding_passed` and `grounding_overlap`
- `model_calls` is 1, or 2 if escalated

Note the overlap values; they are the first real data for `min_overlap`.

- [ ] **Step 4: Stop the containers** (RAM)

Run: `docker compose stop`

- [ ] **Step 5: Add a progress entry**

Append to `docs/progress.md` under a new heading `## Phase 3: Router (in progress)`, filling in the real values from Steps 2–3:

```markdown
## Phase 3: Router (in progress)

- 2026-10-04: Design addendum approved (D33–D36). Plan: `docs/superpowers/plans/2026-10-04-phase-3-router.md`.
- <date>: Router built (Tasks 1–5): features, rules v1, grounding check, fallback, escalation, 2-call cap,
  grounding-gated cache, `force_model` bypass, migration 003. Weir suite: <N> tests passing.
- <date>: Live smoke test: "What are the ICU visiting hours?" → <route> (<route_reason>, overlap <x>);
  a compare/explain question → large (default_large). Cut-offs are still the starting guesses; tuning is next.
```

- [ ] **Step 6: Commit** (tell the user first)

```bash
git add docs/progress.md
git commit -m "docs: Phase 3 router built, live smoke test"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 7: Eval `features` command

**Files:**
- Create: `eval/src/weir_eval/features.py`
- Modify: `eval/src/weir_eval/cli.py` (add `cmd_features` and the subparser)
- Test: `eval/tests/test_features.py`

**Interfaces:**
- Consumes:
  - `weir.router.features.FeatureExtractor`, `Features` (Task 2)
  - `weir.rag.adapter.RagClient.retrieve(query, namespace, k) -> RetrieveResult`
  - `weir_eval.dataset.EvalQuery`
- Produces:
  - `features_row(q: EvalQuery, retrieved: RetrieveResult, extractor: FeatureExtractor) -> dict`, with keys `id, split, group, tokens, has_reasoning_words, num_questions, top_score, score_gap, context_tokens, is_clinical`
  - `async collect_features(queries, rag, extractor, k) -> list[dict]`
  - `FEATURE_KEYS: tuple[str, ...]`, the `Features` field names without `forced_tier`
  - CLI `weir_eval features [--rag-url]`, which writes `eval/datasets/features.jsonl`

- [ ] **Step 1: Write the failing test**

Create `eval/tests/test_features.py`:

```python
from pathlib import Path

from weir.cache.guards import BypassRules
from weir.config import load_config
from weir.rag.adapter import RetrieveResult
from weir.router.features import FeatureExtractor, Features

from weir_eval.features import FEATURE_KEYS, collect_features, features_row

from .conftest import q

CFG = load_config(Path(__file__).resolve().parents[2] / "configs" / "weir.yaml")
EXTRACTOR = FeatureExtractor(lambda t: len(t.split()), BypassRules(CFG.bypass), ["why"])


def retrieved(top=0.8):
    return RetrieveResult(chunks=[], top_score=top, score_gap=0.2, context_tokens=300, kb_version="v1", latency_ms=1)


def test_features_row_has_id_split_group_and_every_feature():
    row = features_row(q("q-001", "d-01", split="tune"), retrieved(), EXTRACTOR)
    assert row == {"id": "q-001", "split": "tune", "group": "distinct", "tokens": 2, "has_reasoning_words": False,
                   "num_questions": 1, "top_score": 0.8, "score_gap": 0.2, "context_tokens": 300,
                   "is_clinical": False}
    assert Features(**{k: row[k] for k in FEATURE_KEYS}).tokens == 2  # rows rebuild into Features


class FakeRag:
    def __init__(self):
        self.asked = []

    async def retrieve(self, query, namespace, k):
        self.asked.append((query, namespace, k))
        return retrieved(top=0.5)


async def test_collect_features_retrieves_each_question_once():
    rag = FakeRag()
    rows = await collect_features([q("q-001", "d-01"), q("q-002", "d-02")], rag, EXTRACTOR, 4)
    assert [r["id"] for r in rows] == ["q-001", "q-002"] and all(r["top_score"] == 0.5 for r in rows)
    assert rag.asked == [("question q-001", "weir-general/en/public", 4), ("question q-002", "weir-general/en/public", 4)]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd eval && uv run pytest -q tests/test_features.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'weir_eval.features'`.

- [ ] **Step 3: Implement**

Create `eval/src/weir_eval/features.py`:

```python
"""Router features for every eval question (Phase 3 addendum §7.2).

Uses Weir's own FeatureExtractor on hospital-rag's real /retrieve result, so the offline simulation sees exactly
what the live router sees. No LLM calls.
"""
from dataclasses import asdict, fields

from weir.rag.adapter import RetrieveResult
from weir.router.features import FeatureExtractor, Features

from .dataset import EvalQuery

FEATURE_KEYS = tuple(f.name for f in fields(Features) if f.name != "forced_tier")


def features_row(q: EvalQuery, retrieved: RetrieveResult, extractor: FeatureExtractor) -> dict:
    f = asdict(extractor.extract(q.query, retrieved))
    return {"id": q.id, "split": q.split, "group": q.group, **{k: f[k] for k in FEATURE_KEYS}}


async def collect_features(queries: list[EvalQuery], rag, extractor: FeatureExtractor, k: int) -> list[dict]:
    rows = []
    for q in queries:
        rows.append(features_row(q, await rag.retrieve(q.query, q.namespace, k), extractor))
    return rows
```

In `eval/src/weir_eval/cli.py`, add the command after `cmd_sweep`:

```python
async def _features(args: argparse.Namespace) -> int:
    from weir.cache.embedder import Embedder
    from weir.cache.guards import BypassRules
    from weir.config import load_config
    from weir.rag.adapter import RagClient
    from weir.router.features import FeatureExtractor

    from .features import collect_features

    cfg = load_config(CONFIGS_DIR / "weir.yaml")
    embedder = Embedder(cfg.cache.embed_model)
    extractor = FeatureExtractor(embedder.count_tokens, BypassRules(cfg.bypass), cfg.router.reasoning_words)
    rag = RagClient(args.rag_url, cfg.rag.timeout_seconds)
    try:
        rows = await collect_features(load_queries(QUERIES), rag, extractor, cfg.rag.retrieve_k)
    finally:
        await rag.aclose()
    out = EVAL_DIR / "datasets" / "features.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{out}: {len(rows)} questions")
    return 0
```

Register it in `main()` before `args = parser.parse_args()`:

```python
    feat = sub.add_parser("features", help="router features for every question via hospital-rag /retrieve (no LLM)")
    feat.add_argument("--rag-url", default=os.environ.get("RAG_URL", "http://127.0.0.1:8001"))
    feat.set_defaults(func=lambda a: asyncio.run(_features(a)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd eval && uv run pytest -q`

Expected: all eval tests pass (61 + 2).

- [ ] **Step 5: Commit** (tell the user first)

```bash
git add eval/src/weir_eval/features.py eval/src/weir_eval/cli.py eval/tests/test_features.py
git commit -m "feat(eval): features command, router features for every question"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 8: Eval `export-grounding` and `simulate`

**Files:**
- Create: `eval/src/weir_eval/request_log.py`, `eval/src/weir_eval/simulate.py`
- Modify: `eval/src/weir_eval/cli.py`
- Test: `eval/tests/test_request_log.py`, `eval/tests/test_simulate.py`

**Interfaces:**
- Consumes:
  - `weir.router.rules.route`, `weir.router.features.Features`, `weir.config.load_config`
  - `FEATURE_KEYS` (Task 7)
  - report `results.jsonl` rows: `id`, `status_code`, `judge_score`, `fact_score`, `meta.cost_usd`, `meta.model`, `meta.request_id`
- Produces:
  - `request_log.fetch_grounding(db_url: str, request_ids: list[str]) -> list[dict]`, with keys `request_id, model, route_reason, grounding_passed, grounding_reason, grounding_overlap`
  - `request_log.attach(results: list[dict], log_rows: list[dict]) -> tuple[list[dict], list[str]]`, which returns the grounding rows keyed by result `id`, plus the ids with no log row
  - `simulate.Row`, `simulate.Setting`, `GRID`, `settings()`, `small_passes(row, min_overlap)`, `simulate(rows, setting, cfg) -> list[dict]`, `metrics(sim) -> dict`, `meets_bar(m) -> bool`, `run_grid(rows, cfg) -> list[tuple[Setting, dict[str, dict]]]`, `choose(results) -> tuple[Setting, dict] | None`, `build_rows(queries, features, baseline, small, grounding, small_model) -> list[Row]`, `render(chosen, results, header) -> str`
  - CLI commands:
    - `export-grounding <report_dir> [--db-url]` writes `<report_dir>/grounding.jsonl`
    - `simulate --baseline <dir> --small <dir>` writes `eval/reports/simulate-<stamp>/{simulate.json,summary.md}`

- [ ] **Step 1: Write the failing tests**

Create `eval/tests/test_request_log.py`:

```python
from weir_eval.request_log import attach


def test_attach_maps_log_rows_to_question_ids_and_reports_missing():
    results = [{"id": "q-1", "status_code": 200, "meta": {"request_id": "r1"}},
               {"id": "q-2", "status_code": 200, "meta": {"request_id": "r2"}},
               {"id": "q-3", "status_code": 503}]
    log_rows = [{"request_id": "r1", "model": "s", "route_reason": "router_disabled", "grounding_passed": True,
                 "grounding_reason": None, "grounding_overlap": 0.9}]
    rows, missing = attach(results, log_rows)
    assert rows == [{"id": "q-1", **log_rows[0]}] and missing == ["q-2"]
```

Create `eval/tests/test_simulate.py`:

```python
from pathlib import Path

import pytest

from weir.config import load_config
from weir.router.features import Features

from weir_eval.simulate import (GRID, Row, Setting, build_rows, choose, meets_bar, metrics, render, run_grid,
                                settings, simulate, small_passes)

from .conftest import q

CFG = load_config(Path(__file__).resolve().parents[2] / "configs" / "weir.yaml")
SET = Setting(short_query_tokens=20, high_confidence=0.75, low_confidence=0.40, min_overlap=0.5)


def feats(**over):
    base = dict(tokens=8, has_reasoning_words=False, num_questions=1, top_score=0.9, score_gap=0.1,
                context_tokens=500, is_clinical=False)
    return Features(**{**base, **over})


def row(id="q-1", split="tune", f=None, base=(5, 1.0, 0.0004), small=(5, 1.0, 0.0002), reason=None, overlap=0.9):
    return Row(id=id, split=split, features=f or feats(), base_judge=base[0], base_facts=base[1], base_cost=base[2],
               small_judge=small[0], small_facts=small[1], small_cost=small[2], small_reason=reason,
               small_overlap=overlap)


@pytest.mark.parametrize(("reason", "overlap", "m", "expected"), [
    (None, 0.9, 0.5, True),
    (None, 0.55, 0.6, False),          # passed live at 0.5 but not at a stricter setting
    ("low_overlap", 0.35, 0.3, True),  # failed live at 0.5 but passes at a looser setting
    ("no_citations", 0.9, 0.3, False), # a rule failure fails at every setting
    ("empty_answer", None, 0.3, False),
])
def test_small_passes(reason, overlap, m, expected):
    assert small_passes(row(reason=reason, overlap=overlap), m) is expected


def test_small_without_usable_answer_never_passes():
    assert small_passes(row(small=(None, None, 0.0)), 0.3) is False


def test_simulate_large_small_and_escalated_paths():
    rows = [row("q-1", f=feats(tokens=99)),                              # long -> large
            row("q-2", small=(4, 1.0, 0.0002)),                          # small, grounded
            row("q-3", reason="low_overlap", overlap=0.2)]               # small, fails -> escalated
    sim = {s["id"]: s for s in simulate(rows, SET, CFG)}
    assert sim["q-1"] == {**sim["q-1"], "tier": "large", "reason": "default_large", "escalated": False,
                          "judge": 5, "cost": 0.0004}
    assert sim["q-2"] == {**sim["q-2"], "tier": "small", "escalated": False, "judge": 4, "cost": 0.0002}
    assert sim["q-3"] == {**sim["q-3"], "tier": "small", "escalated": True, "judge": 5,
                          "cost": pytest.approx(0.0006)}


def test_metrics():
    rows = [row("q-1", f=feats(tokens=99)), row("q-2", small=(4, 1.0, 0.0002)),
            row("q-3", reason="low_overlap", overlap=0.2)]
    m = metrics(simulate(rows, SET, CFG))
    assert m["n"] == 3 and m["share_small"] == pytest.approx(2 / 3) and m["escalation_rate"] == 0.5
    assert m["cost_per_1k"] == pytest.approx(0.0012 / 3 * 1000)
    assert m["base_cost_per_1k"] == pytest.approx(0.0012 / 3 * 1000)
    assert m["judge"] == pytest.approx(14 / 3) and m["base_judge"] == 5
    assert m["small_route_judge"] == 4.5 and m["small_route_base_judge"] == 5


def _m(**over):
    base = dict(n=10, share_small=0.3, escalation_rate=0.1, cost_per_1k=0.08, base_cost_per_1k=0.1, judge=4.85,
                base_judge=4.9, facts=0.98, base_facts=0.98, small_route_judge=4.9, small_route_base_judge=4.9)
    return {**base, **over}


def test_bar_passes_within_limits():
    assert meets_bar(_m()) is True


def test_bar_requires_some_small_routes():  # Review Focus 5
    assert meets_bar(_m(share_small=0.0, small_route_judge=None, small_route_base_judge=None,
                        cost_per_1k=0.1)) is False


@pytest.mark.parametrize("over", [
    {"judge": 4.79},                                   # more than 0.1 below baseline
    {"facts": 0.97},                                   # facts dropped
    {"small_route_judge": 4.8},                        # small route worse than large on the same questions
    {"cost_per_1k": 0.1},                              # no saving
])
def test_bar_fails(over):
    assert meets_bar(_m(**over)) is False


def test_grid_and_choice_pick_the_cheapest_passing_setting():
    assert len(settings()) == len(GRID["short_query_tokens"]) * len(GRID["high_confidence"]) * \
        len(GRID["low_confidence"]) * len(GRID["min_overlap"])
    rows = [row("q-1", f=feats(tokens=10)), row("q-2", f=feats(tokens=30)),
            row("q-3", split="holdout", f=feats(tokens=10))]
    results = run_grid(rows, CFG)
    chosen, m = choose(results)
    assert chosen.short_query_tokens >= 30                       # routing both tune questions small is cheapest
    assert m["tune"]["share_small"] == 1.0 and m["holdout"]["n"] == 1


def test_choice_is_none_when_nothing_passes():
    rows = [row("q-1", small=(2, 0.0, 0.0002))]                 # the small model is bad everywhere
    assert choose(run_grid(rows, CFG)) is None


def test_build_rows_joins_reports_and_requires_judging():
    queries = [q("q-1", "d-1", split="tune"), q("q-2", "d-2", split="holdout")]
    features = {i: {"id": i, "tokens": 5, "has_reasoning_words": False, "num_questions": 1, "top_score": 0.9,
                    "score_gap": 0.1, "context_tokens": 100, "is_clinical": False} for i in ("q-1", "q-2")}
    base = {i: {"id": i, "status_code": 200, "judge_score": 5, "fact_score": 1.0, "meta": {"cost_usd": 0.0004}}
            for i in ("q-1", "q-2")}
    small = {"q-1": {"id": "q-1", "status_code": 200, "judge_score": 4, "fact_score": 1.0,
                     "meta": {"cost_usd": 0.0002, "model": "small-m", "request_id": "r1"}},
             "q-2": {"id": "q-2", "status_code": 200, "judge_score": 5, "fact_score": 1.0,
                     "meta": {"cost_usd": 0.0003, "model": "large-m", "request_id": "r2"}}}  # not the small model
    grounding = {"q-1": {"grounding_reason": None, "grounding_overlap": 0.8}}
    rows = {r.id: r for r in build_rows(queries, features, base, small, grounding, "small-m")}
    assert rows["q-1"].small_judge == 4 and rows["q-1"].small_overlap == 0.8 and rows["q-1"].split == "tune"
    assert rows["q-2"].small_judge is None and rows["q-2"].small_reason == "unavailable"
    base["q-1"]["judge_score"] = None
    with pytest.raises(ValueError, match="rejudge"):
        build_rows(queries, features, base, small, grounding, "small-m")


def test_render_reports_the_choice_or_that_none_passed():
    rows = [row("q-1"), row("q-2", split="holdout")]
    results = run_grid(rows, CFG)
    assert "Chosen setting" in render(choose(results), results, {"baseline": "b", "small": "s"})
    assert "router ships disabled" in render(None, results, {"baseline": "b", "small": "s"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd eval && uv run pytest -q tests/test_request_log.py tests/test_simulate.py`

Expected: FAIL with `ModuleNotFoundError` for `weir_eval.request_log` and `weir_eval.simulate`.

- [ ] **Step 3: Implement `request_log.py`**

Create `eval/src/weir_eval/request_log.py`:

```python
"""Read Weir's grounding results for a report's requests from weir.request_log (Phase 3 addendum §7.2)."""
import psycopg

SQL = ("select request_id::text as request_id, model, route_reason, grounding_passed, grounding_reason, "
       "grounding_overlap from weir.request_log where request_id = any(%s::uuid[])")


def fetch_grounding(db_url: str, request_ids: list[str]) -> list[dict]:
    with psycopg.connect(db_url) as conn:
        cur = conn.execute(SQL, (request_ids,))
        names = [d.name for d in cur.description]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def attach(results: list[dict], log_rows: list[dict]) -> tuple[list[dict], list[str]]:
    by_request = {r["request_id"]: r for r in log_rows}
    rows, missing = [], []
    for r in results:
        if r.get("status_code") != 200:
            continue
        found = by_request.get(r["meta"]["request_id"])
        if found is None:
            missing.append(r["id"])
        else:
            rows.append({"id": r["id"], **found})
    return rows, missing
```

- [ ] **Step 4: Implement `simulate.py`**

Create `eval/src/weir_eval/simulate.py`:

```python
"""Offline router simulation and tuning (Phase 3 addendum §7.3). No model calls.

Every question has two measured answers: baseline v3 (large) and the small-model trial. For each rule setting,
Weir's own route() picks a tier per question:
- large -> the baseline answer
- small and the small answer's grounding passes -> the small answer
- small and it fails -> escalated: the baseline answer, paying for both calls
"""
import itertools
from dataclasses import asdict, dataclass
from statistics import mean

from weir.config import WeirConfig
from weir.router.features import Features
from weir.router.rules import route

from .dataset import EvalQuery
from .features import FEATURE_KEYS

GRID = {
    "short_query_tokens": [12, 16, 20, 25, 30, 40],
    "high_confidence": [0.60, 0.65, 0.70, 0.75, 0.80, 0.85],
    "low_confidence": [0.30, 0.35, 0.40, 0.45, 0.50],
    "min_overlap": [0.3, 0.4, 0.5, 0.6, 0.7],
}
EPS = 1e-9
SPLITS = ("tune", "holdout", "all")


@dataclass(frozen=True)
class Row:
    id: str
    split: str
    features: Features
    base_judge: float
    base_facts: float
    base_cost: float
    small_judge: float | None     # None: no usable small answer (error or another model) -> always escalates
    small_facts: float | None
    small_cost: float
    small_reason: str | None      # grounding reason Weir logged for the small answer
    small_overlap: float | None


@dataclass(frozen=True)
class Setting:
    short_query_tokens: int
    high_confidence: float
    low_confidence: float
    min_overlap: float


def settings() -> list[Setting]:
    return [Setting(*values) for values in itertools.product(*GRID.values())]


def small_passes(row: Row, min_overlap: float) -> bool:
    return (row.small_judge is not None and row.small_reason in (None, "low_overlap")
            and row.small_overlap is not None and row.small_overlap >= min_overlap)


def _config_for(setting: Setting, cfg: WeirConfig) -> WeirConfig:
    router = cfg.router.model_copy(update={
        "enabled": True, "short_query_tokens": setting.short_query_tokens,
        "high_confidence": setting.high_confidence, "low_confidence": setting.low_confidence})
    kill = cfg.kill_switch.model_copy(update={"force_large": False})
    return cfg.model_copy(update={"router": router, "kill_switch": kill})


def simulate(rows: list[Row], setting: Setting, cfg: WeirConfig) -> list[dict]:
    rcfg = _config_for(setting, cfg)
    out = []
    for r in rows:
        tier, reason = route(r.features, rcfg)
        base = {"id": r.id, "split": r.split, "tier": tier, "reason": reason, "base_judge": r.base_judge,
                "base_facts": r.base_facts, "base_cost": r.base_cost}
        if tier == "large":
            out.append({**base, "escalated": False, "judge": r.base_judge, "facts": r.base_facts,
                        "cost": r.base_cost})
        elif small_passes(r, setting.min_overlap):
            out.append({**base, "escalated": False, "judge": r.small_judge, "facts": r.small_facts,
                        "cost": r.small_cost})
        else:
            out.append({**base, "escalated": True, "judge": r.base_judge, "facts": r.base_facts,
                        "cost": r.small_cost + r.base_cost})
    return out


def metrics(sim: list[dict]) -> dict:
    small = [s for s in sim if s["tier"] == "small"]
    return {
        "n": len(sim),
        "cost_per_1k": sum(s["cost"] for s in sim) / len(sim) * 1000,
        "base_cost_per_1k": sum(s["base_cost"] for s in sim) / len(sim) * 1000,
        "judge": mean(s["judge"] for s in sim),
        "base_judge": mean(s["base_judge"] for s in sim),
        "facts": mean(s["facts"] for s in sim),
        "base_facts": mean(s["base_facts"] for s in sim),
        "share_small": len(small) / len(sim),
        "escalation_rate": sum(s["escalated"] for s in small) / len(small) if small else 0.0,
        "small_route_judge": mean(s["judge"] for s in small) if small else None,
        "small_route_base_judge": mean(s["base_judge"] for s in small) if small else None,
    }


def meets_bar(m: dict) -> bool:
    """D33, no visible loss. A setting that routes nothing small is not a router (Review Focus 5)."""
    return (m["share_small"] > 0
            and m["cost_per_1k"] < m["base_cost_per_1k"] - EPS
            and m["judge"] >= m["base_judge"] - 0.1 - EPS
            and m["facts"] >= m["base_facts"] - EPS
            and m["small_route_judge"] >= m["small_route_base_judge"] - EPS)


def run_grid(rows: list[Row], cfg: WeirConfig) -> list[tuple[Setting, dict[str, dict]]]:
    results = []
    for setting in settings():
        sim = simulate(rows, setting, cfg)
        by_split = {}
        for split in SPLITS:
            part = [s for s in sim if split == "all" or s["split"] == split]
            if part:
                by_split[split] = metrics(part)
        by_split["_sim"] = sim
        results.append((setting, by_split))
    return results


def choose(results: list[tuple[Setting, dict[str, dict]]]) -> tuple[Setting, dict] | None:
    """Lowest simulated cost on the tune split among settings meeting the bar there.
    Ties go to the more conservative setting."""
    passing = [(s, m) for s, m in results if "tune" in m and meets_bar(m["tune"])]
    if not passing:
        return None
    return min(passing, key=lambda sm: (round(sm[1]["tune"]["cost_per_1k"], 9), -sm[1]["tune"]["judge"],
                                        -sm[0].min_overlap, -sm[0].high_confidence, sm[0].short_query_tokens,
                                        -sm[0].low_confidence))


def build_rows(queries: list[EvalQuery], features: dict[str, dict], baseline: dict[str, dict],
               small: dict[str, dict], grounding: dict[str, dict], small_model: str) -> list[Row]:
    rows = []
    for q in queries:
        b = baseline[q.id]
        if b.get("status_code") != 200 or b.get("judge_score") is None:
            raise ValueError(f"baseline row {q.id} is not judged; run rejudge first")
        s = small.get(q.id)
        g = grounding.get(q.id)
        usable = (s is not None and s.get("status_code") == 200 and s["meta"].get("model") == small_model
                  and g is not None)
        if usable and s.get("judge_score") is None:
            raise ValueError(f"small-trial row {q.id} is not judged; run rejudge first")
        rows.append(Row(
            id=q.id, split=q.split or "tune", features=Features(**{k: features[q.id][k] for k in FEATURE_KEYS}),
            base_judge=b["judge_score"], base_facts=b["fact_score"], base_cost=b["meta"]["cost_usd"],
            small_judge=s["judge_score"] if usable else None, small_facts=s["fact_score"] if usable else None,
            small_cost=s["meta"]["cost_usd"] if usable else 0.0,
            small_reason=g["grounding_reason"] if usable else "unavailable",
            small_overlap=g["grounding_overlap"] if usable else None,
        ))
    return rows


def _fmt(m: dict) -> str:
    srj = "–" if m["small_route_judge"] is None else f"{m['small_route_judge']:.2f} vs {m['small_route_base_judge']:.2f}"
    return (f"| {m['n']} | ${m['cost_per_1k']:.4f} (base ${m['base_cost_per_1k']:.4f}) | "
            f"{m['judge']:.2f} (base {m['base_judge']:.2f}) | {m['facts']:.3f} (base {m['base_facts']:.3f}) | "
            f"{m['share_small']:.0%} | {m['escalation_rate']:.0%} | {srj} | {'yes' if meets_bar(m) else 'no'} |")


HEAD = ("| n | cost / 1k | judge | facts | routed small | escalated | small-route judge vs large | bar |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |")


def render(chosen: tuple[Setting, dict] | None, results: list[tuple[Setting, dict[str, dict]]], header: dict) -> str:
    lines = ["# Router simulation", "", f"Inputs: baseline `{header['baseline']}`, small trial `{header['small']}`. "
             f"{len(results)} settings.", ""]
    if chosen is None:
        lines += ["**No setting meets the bar on the tune split. The router ships disabled (addendum §7.3).**", ""]
    else:
        setting, m = chosen
        lines += ["## Chosen setting", "", f"`{asdict(setting)}`", "", "| split " + HEAD.split("\n")[0][1:],
                  "| --- " + HEAD.split("\n")[1][1:]]
        lines += [f"| {split} " + _fmt(m[split])[1:] for split in SPLITS if split in m]
        small = [s for s in m["_sim"] if s["tier"] == "small"]
        lines += ["", f"## Questions routed small at the chosen setting ({len(small)})", "",
                  "| id | split | escalated | judge (final) | baseline judge |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {s['id']} | {s['split']} | {s['escalated']} | {s['judge']} | {s['base_judge']} |" for s in small]
    passing = sorted(((s, m) for s, m in results if "tune" in m and meets_bar(m["tune"])),
                     key=lambda sm: sm[1]["tune"]["cost_per_1k"])[:10]
    lines += ["", f"## Cheapest passing settings on tune (top {len(passing)})", "",
              "| setting " + HEAD.split("\n")[0][1:], "| --- " + HEAD.split("\n")[1][1:]]
    lines += [f"| `{asdict(s)}` " + _fmt(m["tune"])[1:] for s, m in passing]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 5: Add the CLI commands**

In `eval/src/weir_eval/cli.py`, add after `_features`:

```python
DEFAULT_DB = os.environ.get("WEIR_DB_URL", "postgresql://weir:weir@127.0.0.1:5432/weir")


def cmd_export_grounding(args: argparse.Namespace) -> int:
    from .request_log import attach, fetch_grounding

    out_dir = Path(args.report_dir)
    results = _load_results(out_dir)
    ids = [r["meta"]["request_id"] for r in results if r.get("status_code") == 200]
    rows, missing = attach(results, fetch_grounding(args.db_url, ids))
    (out_dir / "grounding.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{out_dir / 'grounding.jsonl'}: {len(rows)} rows; missing from request_log: {missing or 'none'}")
    return 1 if missing else 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from weir.config import load_config

    from .simulate import build_rows, choose, render, run_grid

    cfg = load_config(CONFIGS_DIR / "weir.yaml")
    first = lambda rows: {r["id"]: r for r in reversed(rows)}  # noqa: E731 - first occurrence wins
    features = first([json.loads(x) for x in (EVAL_DIR / "datasets" / "features.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()])
    grounding = first([json.loads(x) for x in (Path(args.small) / "grounding.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()])
    rows = build_rows(load_queries(QUERIES), features, first(_load_results(Path(args.baseline))),
                      first(_load_results(Path(args.small))), grounding, cfg.router.small_model)
    results = run_grid(rows, cfg)
    chosen = choose(results)
    out_dir = EVAL_DIR / "reports" / f"simulate-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True)
    header = {"baseline": Path(args.baseline).name, "small": Path(args.small).name}
    dump = [{"setting": vars(s), **{k: v for k, v in m.items() if k != "_sim"}} for s, m in results]
    (out_dir / "simulate.json").write_text(json.dumps({"header": header, "results": dump}, indent=1),
                                           encoding="utf-8")
    (out_dir / "summary.md").write_text(render(chosen, results, header), encoding="utf-8")
    print(f"chosen: {vars(chosen[0]) if chosen else None}; report: {out_dir}")
    return 0
```

Register both in `main()`:

```python
    eg = sub.add_parser("export-grounding", help="copy grounding results for a report from weir.request_log")
    eg.add_argument("report_dir")
    eg.add_argument("--db-url", default=DEFAULT_DB)
    eg.set_defaults(func=cmd_export_grounding)
    sim = sub.add_parser("simulate", help="offline router simulation over the rule grid (no model calls)")
    sim.add_argument("--baseline", default=str(EVAL_DIR / "reports" / "baseline-v3"))
    sim.add_argument("--small", required=True, help="small-model trial report dir (with grounding.jsonl)")
    sim.set_defaults(func=cmd_simulate)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd eval && uv run pytest -q`

Expected: all pass (61 + 2 + 1 + about 20).

- [ ] **Step 7: Commit** (tell the user first)

```bash
git add eval/src/weir_eval/request_log.py eval/src/weir_eval/simulate.py eval/src/weir_eval/cli.py \
  eval/tests/test_request_log.py eval/tests/test_simulate.py
git commit -m "feat(eval): export-grounding and offline router simulation with the D33 bar"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 9: Features and small-model trial (live; judging takes about a day)

**Files:**
- Create: `eval/datasets/features.jsonl`
- Create: `eval/reports/<stamp>-small_only-all/` (`results.jsonl`, `grounding.jsonl`, `summary.*`)
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: the `features` (Task 7) and `export-grounding` (Task 8) commands, the `small_only` overlay (Task 1), and the Task 5 pipeline.
- Produces:
  - `datasets/features.jsonl`, one row per question for all 158
  - the small-trial report directory with every row judged, plus its `grounding.jsonl`

- [ ] **Step 1: Start the services under `small_only`**

```bash
docker compose up -d postgres hospital-rag
WEIR_ABLATION=small_only docker compose up -d --force-recreate weir
curl -s http://127.0.0.1:8000/healthz
```

Expected: `"config_label":"small_only"`.

- [ ] **Step 2: Collect features** (no LLM calls)

Run: `cd eval && uv run python -m weir_eval features --rag-url http://127.0.0.1:8001`

Expected: `.../datasets/features.jsonl: 158 questions`. Spot-check a few rows:

```bash
head -3 datasets/features.jsonl
```

Each row should have `top_score` between 0 and 1, and `tokens` > 0.

- [ ] **Step 3: Run the small trial without judging** (158 small-model calls, about 40 min at the default 15 s pacing)

Run it in the background, because the session can be reaped:

```bash
cd eval && uv run --env-file ../.env python -m weir_eval run --config small_only --split all --no-judge \
  --weir-url http://127.0.0.1:8000
```

Expected: `report: reports/<stamp>-small_only-all (errors 0, ...)`.

If there are errors:
1. Re-run with `--exclude-report reports/<stamp>-small_only-all`.
2. Combine the two with `merge-reports reports/<stamp>-small_only-all-merged <first> <second>`.
3. Use the merged directory from here on.

- [ ] **Step 4: Check that every answer came from the small model**

```bash
cd eval && uv run python -c "import json,sys; rows=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]; print({r['meta']['model'] for r in rows if r['status_code']==200}, sum(r['status_code']!=200 for r in rows))" reports/<dir>/results.jsonl
```

Expected: `{'openai/gpt-oss-20b'} 0`.

- [ ] **Step 5: Export grounding from the request log**

Run: `cd eval && uv run python -m weir_eval export-grounding reports/<dir>`

Expected: `158 rows; missing from request_log: none`. If some are missing, wait 2 s for the log flush and re-run.

- [ ] **Step 6: Stop Weir and hospital-rag** (judging needs no containers)

Run: `docker compose stop`

- [ ] **Step 7: Judge the trial** (about 158 grades, roughly a day at the Qwen free quota; resumable)

Run in the background:

```bash
cd eval && uv run --env-file ../.env python -m weir_eval rejudge reports/<dir>
```

If it stops on the daily quota, run the same command again the next day; it continues where it stopped. Done when `not judged 0`.

- [ ] **Step 8: Progress entry and commit** (tell the user first)

Append to the Phase 3 section of `docs/progress.md`, filling in the real numbers from `summary.md`:

```markdown
- <date>: Small-model trial (`reports/<dir>`): 158 questions on gpt-oss-20b, judge <x> (baseline v3 4.90),
  facts <y> (0.981), cost/1k $<z> ($0.0980). Grounding passed on <k>/158 at min_overlap 0.5.
  Features for all 158 questions in `eval/datasets/features.jsonl`.
```

```bash
git add eval/datasets/features.jsonl eval/reports/<dir> docs/progress.md
git commit -m "results: small-model trial (158 questions, judged) and router features"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 10: Simulate, tune and set the cut-offs

**Files:**
- Create: `eval/reports/simulate-<stamp>/`, `docs/results/router-tuning.md`
- Modify: `configs/weir.yaml` (router cut-offs, `grounding.min_overlap`)
- Modify: `services/weir/tests/test_config.py`
- Modify: `docs/decisions.md` (D37), `docs/progress.md`

**Interfaces:**
- Consumes: `simulate` (Task 8), the Task 9 outputs, `reports/baseline-v3`.
- Produces: tuned `router.short_query_tokens`, `high_confidence`, `low_confidence` and `grounding.min_overlap` in `configs/weir.yaml`. These are the values the live runs use.

- [ ] **Step 1: Run the simulation**

Run: `cd eval && uv run python -m weir_eval simulate --small reports/<small-trial-dir>`

Expected: `chosen: {...}; report: reports/simulate-<stamp>`. Read `summary.md`, and compare the holdout row against tune: a holdout that fails the bar is a warning sign.

- [ ] **Step 2: If `chosen` is `None`, stop here and talk to the user**

Per the addendum, the router then ships disabled:
- Set `router.enabled: false` in `configs/weir.yaml`.
- Write the reason into `router-tuning.md` and D37.
- Agree with the user which live runs still make sense, before running Tasks 11–12.

Don't loosen the bar without the user's decision (D33 is theirs).

- [ ] **Step 3: Pin the chosen values in config, test-first**

Add this to `services/weir/tests/test_config.py`, with the chosen numbers filled in:

```python
def test_phase3_tuned_values():  # D37: from the offline router simulation (docs/results/router-tuning.md)
    cfg = load_config(CONFIGS / "weir.yaml")
    assert (cfg.router.short_query_tokens, cfg.router.high_confidence, cfg.router.low_confidence) == (<T>, <H>, <L>)
    assert cfg.grounding.min_overlap == <M>
```

Run: `cd services/weir && uv run pytest -q tests/test_config.py::test_phase3_tuned_values`

Expected: FAIL (still the starting values).

Then edit `configs/weir.yaml`. Replace each `# starting value; tuned offline...` comment with `# tuned offline, D37 (docs/results/router-tuning.md)`, and set the values. Re-run the full weir suite (`uv run pytest -q`). Expected: PASS. The pipeline tests pin their own cut-offs through `ROUTER_ON`.

- [ ] **Step 4: Write `docs/results/router-tuning.md`**

Structure, with real numbers copied from `reports/simulate-<stamp>/summary.md`:

```markdown
# Router tuning (Phase 3)

Offline simulation, <date>.
- Inputs: baseline v3 (large, 158 questions) and the small-model trial `<dir>` (158, judged), plus
  `datasets/features.jsonl`.
- Grid: 900 settings (addendum §7.3).
- Raw data: `eval/reports/simulate-<stamp>/`.

## Chosen setting
short_query_tokens <T>, high_confidence <H>, low_confidence <L>, min_overlap <M> (D37).

| Split | n | Cost / 1k (baseline) | Judge (baseline) | Facts (baseline) | Routed small | Escalated | Small-route judge vs large |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tune | … |
| holdout | … |
| all | … |

## How the small model did
- small-trial overall judge and facts vs baseline
- where it lost points (groups, difficulty, examples)
- grounding overlap distribution: passing vs failing small answers, and how many low-overlap answers were
  actually fine, or wrong

## Caveats
- Tuned on the tune split; holdout is the independent check, but it has only <n> questions.
- Simulated judge and facts reuse each model's measured answer. The live runs (Tasks 11–12) re-generate
  answers, so expect some noise.
- Cost uses list prices; real spend is $0.
```

- [ ] **Step 5: Log D37 and progress**

Append to the `docs/decisions.md` table:

```markdown
| <date> | D37 | Router cut-offs: short_query_tokens <T>, high_confidence <H>, low_confidence <L>; grounding min_overlap <M> | Starting guesses 20 / 0.75 / 0.40 / 0.5; other grid settings | Cheapest setting meeting the D33 bar on the tune split in the offline simulation; holdout <passes/notes> (`docs/results/router-tuning.md`) |
```

Then add one line to the Phase 3 section of `docs/progress.md`.

- [ ] **Step 6: Commit** (tell the user first)

```bash
git add configs/weir.yaml services/weir/tests/test_config.py eval/reports/simulate-<stamp> \
  docs/results/router-tuning.md docs/decisions.md docs/progress.md
git commit -m "results: router tuned by offline simulation (D37)"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 11: Eval reporting for the live runs (route breakdown, gate, derived replays)

**Files:**
- Create: `eval/src/weir_eval/gate.py`
- Modify: `eval/src/weir_eval/summary.py`, `eval/src/weir_eval/workload.py`, `eval/src/weir_eval/cli.py`
- Test: `eval/tests/test_gate.py`, `eval/tests/test_summary.py`, `eval/tests/test_workload.py`

**Interfaces:**
- Consumes: report rows (`meta.route`, `meta.escalated`, `meta.cost_usd`, `client_latency_ms`, `judge_score`, `fact_score`, `meta.cache_status`).
- Produces:
  - `summarize()` gains:
    - `"by_route"`: `{route: {n, judge_mean, fact_mean, cost_per_1k_usd, p50, p95}}`
    - `"escalation_rate"`: escalated requests divided by those routed small, or `None` if none were routed small
  - `render_markdown` prints a "By route" table when there is more than one route.
  - `workload.project_onto_workload(records: list[dict], ids: list[str]) -> list[dict]`
  - `gate.gate(records: list[dict], baseline_by_id: dict[str, dict]) -> dict`, with keys `cost_per_1k, base_cost_per_1k, judge, base_judge, facts, base_facts, small_route_judge, small_route_base_judge, wrong_hits, checks: {cost_lower, judge_within_0_1, facts_no_lower, small_route_ok, zero_wrong_hits}, passed`
  - CLI commands:
    - `gate <report_dir> [--baseline]` prints the gate as JSON; exit 0 if passed, else 1
    - `derive-workload <report_dir> --workload <jsonl> --out <dir>`

- [ ] **Step 1: Write the failing tests**

Append to `eval/tests/test_summary.py` (match its existing record helper if there is one; this test builds its records inline):

```python
def _rec(route, judge, cost, latency, escalated=False, status="miss"):
    return {"id": "q", "group": "distinct", "difficulty": "easy", "status_code": 200, "client_latency_ms": latency,
            "fact_score": 1.0, "judge_score": judge,
            "meta": {"route": route, "escalated": escalated, "cost_usd": cost, "cache_status": status}}


def test_by_route_breakdown_and_escalation_rate():
    import pytest

    from weir_eval.summary import summarize

    s = summarize([_rec("small", 5, 0.0002, 300), _rec("small", 4, 0.0006, 900, escalated=True),
                   _rec("large", 5, 0.0004, 700), _rec("none", 5, 0.0, 50, status="hit")])
    assert s["by_route"]["small"] == pytest.approx({"n": 2, "judge_mean": 4.5, "fact_mean": 1.0,
                                                    "cost_per_1k_usd": 0.4, "p50": 300, "p95": 900})
    assert s["by_route"]["large"]["n"] == 1 and s["by_route"]["none"]["cost_per_1k_usd"] == 0
    assert s["escalation_rate"] == 0.5


def test_escalation_rate_none_without_small_routes():
    from weir_eval.summary import summarize

    assert summarize([_rec("large", 5, 0.0004, 700)])["escalation_rate"] is None
```

Append to `eval/tests/test_workload.py`:

```python
def test_project_onto_workload_keeps_order_and_repeats():
    import pytest

    from weir_eval.workload import project_onto_workload

    records = [{"id": "a", "x": 1}, {"id": "b", "x": 2}, {"id": "a", "x": 9}]  # first occurrence wins
    assert project_onto_workload(records, ["b", "a", "a"]) == [{"id": "b", "x": 2}, {"id": "a", "x": 1},
                                                               {"id": "a", "x": 1}]
    with pytest.raises(KeyError):
        project_onto_workload(records, ["c"])
```

Create `eval/tests/test_gate.py`:

```python
import pytest

from weir_eval.gate import gate


def rec(id, route, judge, facts, cost, status="miss"):
    return {"id": id, "group": "distinct", "difficulty": "easy", "status_code": 200, "client_latency_ms": 100,
            "judge_score": judge, "fact_score": facts,
            "meta": {"route": route, "escalated": False, "cost_usd": cost, "cache_status": status}}


BASE = {"q-1": rec("q-1", "large", 5, 1.0, 0.0004), "q-2": rec("q-2", "large", 5, 1.0, 0.0004)}


def test_gate_passes_when_cheaper_and_no_worse():
    g = gate([rec("q-1", "small", 5, 1.0, 0.0002), rec("q-2", "large", 5, 1.0, 0.0004)], BASE)
    assert g["passed"] is True and g["small_route_judge"] == 5 and g["small_route_base_judge"] == 5
    assert g["cost_per_1k"] == pytest.approx(0.3) and g["base_cost_per_1k"] == pytest.approx(0.4)


def test_gate_compares_repeats_against_the_same_question():
    g = gate([rec("q-1", "none", 5, 1.0, 0.0, status="hit")] * 3, BASE)
    assert g["base_cost_per_1k"] == pytest.approx(0.4) and g["checks"]["cost_lower"] is True


@pytest.mark.parametrize(("records", "failed"), [
    ([rec("q-1", "small", 4, 1.0, 0.0002), rec("q-2", "large", 5, 1.0, 0.0004)], "small_route_ok"),
    ([rec("q-1", "large", 5, 0.5, 0.0003), rec("q-2", "large", 5, 1.0, 0.0003)], "facts_no_lower"),
    ([rec("q-1", "large", 5, 1.0, 0.0005), rec("q-2", "large", 5, 1.0, 0.0004)], "cost_lower"),
    ([rec("q-1", "none", 2, 1.0, 0.0, status="hit"), rec("q-2", "large", 5, 1.0, 0.0001)], "zero_wrong_hits"),
])
def test_gate_failures(records, failed):
    g = gate(records, BASE)
    assert g["checks"][failed] is False and g["passed"] is False


def test_gate_requires_judged_rows():
    with pytest.raises(ValueError, match="rejudge"):
        gate([{**rec("q-1", "large", None, 1.0, 0.0004)}], BASE)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd eval && uv run pytest -q tests/test_summary.py tests/test_workload.py tests/test_gate.py`

Expected: FAIL (`KeyError: 'by_route'`, `ImportError` for `project_onto_workload` and `weir_eval.gate`).

- [ ] **Step 3: Implement**

In `eval/src/weir_eval/summary.py`, add inside `summarize()` before `return summary`:

```python
    by_route: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        by_route[r["meta"]["route"]].append(r)
    small = by_route.get("small", [])
    summary["by_route"] = {
        route: {**_group_stats(rs),
                "cost_per_1k_usd": sum(r["meta"]["cost_usd"] for r in rs) / len(rs) * 1000,
                "p50": percentile([r["client_latency_ms"] for r in rs], 50),
                "p95": percentile([r["client_latency_ms"] for r in rs], 95)}
        for route, rs in sorted(by_route.items())}
    summary["escalation_rate"] = (sum(bool(r["meta"].get("escalated")) for r in small) / len(small)
                                  if small else None)
```

`_group_stats` stays as it is (`n`, `judge_mean`, `fact_mean`); the route breakdown adds cost and latency to it.

In `render_markdown`, after the existing tables, add a section that is emitted only when `len(summary.get("by_route", {})) > 1`:

```python
    if len(summary.get("by_route", {})) > 1:
        lines += ["", "## By route", "", "| Route | n | Judge | Facts | Cost / 1k | p50 | p95 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        lines += [f"| {k} | {v['n']} | {v['judge_mean']} | {v['fact_mean']} | ${v['cost_per_1k_usd']:.4f} | "
                  f"{v['p50']} ms | {v['p95']} ms |" for k, v in summary["by_route"].items()]
        if summary.get("escalation_rate") is not None:
            lines.append(f"\nEscalation rate (of requests routed small): {summary['escalation_rate']:.1%}")
```

(Read `render_markdown` first and use the variable name it already uses for its line list, if that isn't `lines`.)

In `eval/src/weir_eval/workload.py`, add:

```python
def project_onto_workload(records: list[dict], ids: list[str]) -> list[dict]:
    """Per-question results laid onto a replay order (first occurrence of each id wins).
    For configs without a cache every request is independent, so this is the replay's derived result."""
    by_id: dict[str, dict] = {}
    for r in records:
        by_id.setdefault(r["id"], r)
    return [by_id[i] for i in ids]
```

Create `eval/src/weir_eval/gate.py`:

```python
"""Phase 3 exit gate (addendum §7.6): a live report against baseline v3 on the same questions, request by request."""
from statistics import mean

from .summary import summarize

EPS = 1e-9


def gate(records: list[dict], baseline_by_id: dict[str, dict]) -> dict:
    ok = [r for r in records if r.get("status_code") == 200]
    if any(r.get("judge_score") is None for r in ok):
        raise ValueError("report has unjudged rows; run rejudge first")
    base = [baseline_by_id[r["id"]] for r in ok]
    pairs = list(zip(ok, base, strict=True))
    small = [(r, b) for r, b in pairs if r["meta"]["route"] == "small"]
    g = {
        "n": len(ok),
        "cost_per_1k": sum(r["meta"]["cost_usd"] for r in ok) / len(ok) * 1000,
        "base_cost_per_1k": sum(b["meta"]["cost_usd"] for b in base) / len(ok) * 1000,
        "judge": mean(r["judge_score"] for r in ok),
        "base_judge": mean(b["judge_score"] for b in base),
        "facts": mean(r["fact_score"] for r in ok),
        "base_facts": mean(b["fact_score"] for b in base),
        "small_route_judge": mean(r["judge_score"] for r, _ in small) if small else None,
        "small_route_base_judge": mean(b["judge_score"] for _, b in small) if small else None,
        "wrong_hits": summarize(ok).get("wrong_hits", 0),
    }
    g["checks"] = {
        "cost_lower": g["cost_per_1k"] < g["base_cost_per_1k"] - EPS,
        "judge_within_0_1": g["judge"] >= g["base_judge"] - 0.1 - EPS,
        "facts_no_lower": g["facts"] >= g["base_facts"] - EPS,
        "small_route_ok": not small or g["small_route_judge"] >= g["small_route_base_judge"] - EPS,
        "zero_wrong_hits": g["wrong_hits"] == 0,
    }
    g["passed"] = all(g["checks"].values())
    return g
```

In `eval/src/weir_eval/cli.py`, add:

```python
def cmd_gate(args: argparse.Namespace) -> int:
    from .gate import gate

    baseline = {}
    for r in _load_results(Path(args.baseline)):
        baseline.setdefault(r["id"], r)
    g = gate(_load_results(Path(args.report_dir)), baseline)
    print(json.dumps(g, indent=2))
    return 0 if g["passed"] else 1


def cmd_derive_workload(args: argparse.Namespace) -> int:
    from .workload import project_onto_workload

    ids = [json.loads(x)["id"] for x in Path(args.workload).read_text(encoding="utf-8").splitlines() if x.strip()]
    records = project_onto_workload(_load_results(Path(args.report_dir)), ids)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                                           encoding="utf-8")
    _write_report(out_dir, {"derived_from": Path(args.report_dir).name, "workload": Path(args.workload).name,
                            "queries": len(records), "workload_repeat_rate": round(repeat_rate(ids), 3),
                            "note": "derived: each request reuses its question's measured result (no cache)"},
                  records)
    return 0
```

Register them:

```python
    gt = sub.add_parser("gate", help="Phase 3 exit gate: report vs baseline v3 on the same questions")
    gt.add_argument("report_dir")
    gt.add_argument("--baseline", default=str(EVAL_DIR / "reports" / "baseline-v3"))
    gt.set_defaults(func=cmd_gate)
    dw = sub.add_parser("derive-workload", help="lay a per-question report onto a replay order (no-cache configs)")
    dw.add_argument("report_dir")
    dw.add_argument("--workload", required=True)
    dw.add_argument("--out", required=True)
    dw.set_defaults(func=cmd_derive_workload)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd eval && uv run pytest -q`

Expected: all pass.

- [ ] **Step 5: Commit** (tell the user first)

```bash
git add eval/src/weir_eval/gate.py eval/src/weir_eval/summary.py eval/src/weir_eval/workload.py \
  eval/src/weir_eval/cli.py eval/tests/test_gate.py eval/tests/test_summary.py eval/tests/test_workload.py
git commit -m "feat(eval): route breakdown, exit-gate check, derived workload reports"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 12: Live runs: router only, full Weir cold and replay (judging takes 1–2 days)

**Files:**
- Create:
  - `eval/reports/<stamp>-router_only-all/`
  - `eval/reports/<stamp>-full-all/`
  - `eval/reports/<stamp>-full-workload-300-seed7/`
  - `eval/reports/derived-baseline-v3-workload-300-seed7/`
  - `eval/reports/derived-router_only-workload-300-seed7/`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: the tuned config (Task 10) and the reporting commands (Task 11).
- Produces: judged reports for the four-way table and the gate.

- [ ] **Step 1: Router only, cold, 158 questions**

```bash
docker compose up -d postgres hospital-rag
WEIR_ABLATION=router_only docker compose up -d --force-recreate weir
curl -s http://127.0.0.1:8000/healthz        # expect "config_label":"router_only"
cd eval && uv run --env-file ../.env python -m weir_eval run --config router_only --split all --no-judge \
  --weir-url http://127.0.0.1:8000
```

Expected: `errors 0` (re-run with `--exclude-report`, then `merge-reports`, if not). Check `summary.md`: `route_mix` should show a small share close to the simulated one.

- [ ] **Step 2: Full Weir, cold pass with the cache emptied first**

```bash
WEIR_ABLATION=full docker compose up -d --force-recreate weir
curl -s http://127.0.0.1:8000/healthz        # expect "config_label":"full"
cd eval && uv run --env-file ../.env python -m weir_eval run --config full --split all --no-judge --purge-cache \
  --weir-url http://127.0.0.1:8000
```

- [ ] **Step 3: Full Weir, 300-request replay** (run straight after Step 2, so the cache is warm, as in Phase 2)

```bash
cd eval && uv run --env-file ../.env python -m weir_eval run --config full \
  --workload datasets/workload-300-seed7.jsonl --no-judge --weir-url http://127.0.0.1:8000
```

- [ ] **Step 4: Route reasons from the request log, then stop the containers**

```bash
MSYS_NO_PATHCONV=1 docker compose exec postgres psql -U weir -d weir -c \
  "select config_label, route, route_reason, escalated, count(*), round(avg(grounding_overlap)::numeric,2) from weir.request_log where config_label in ('router_only','full') and cache_status <> 'hit' group by 1,2,3,4 order by 1,5 desc;"
docker compose stop
```

Save the output for `router.md`.

- [ ] **Step 5: Judge the three live reports** (resumable; the judge's disk cache reuses grades for identical replayed answers)

```bash
cd eval
uv run --env-file ../.env python -m weir_eval rejudge reports/<router_only-dir>
uv run --env-file ../.env python -m weir_eval rejudge reports/<full-all-dir>
uv run --env-file ../.env python -m weir_eval rejudge reports/<full-workload-dir>
```

Run them in the background, one after another. If the daily quota stops one, re-run it the next day. Every report is done when it shows `not judged 0`.

- [ ] **Step 6: Derived replays for the no-cache configurations** (after judging, so the derived rows carry grades)

```bash
cd eval
uv run python -m weir_eval derive-workload reports/baseline-v3 --workload datasets/workload-300-seed7.jsonl   --out reports/derived-baseline-v3-workload-300-seed7
uv run python -m weir_eval derive-workload reports/<router_only-dir> --workload datasets/workload-300-seed7.jsonl   --out reports/derived-router_only-workload-300-seed7
```

Expected: each `summary.md` shows 300 requests and repeat rate 0.737.

- [ ] **Step 7: Gate checks**

```bash
cd eval
uv run python -m weir_eval gate reports/<router_only-dir>
uv run python -m weir_eval gate reports/<full-all-dir>
uv run python -m weir_eval gate reports/<full-workload-dir>
```

Save the JSON for `router.md`. If a check fails, stop and look at why before Task 13:
- a one-question wording miss like q-019 is explainable noise
- a small-route quality drop is not

Per addendum §7.6, a failure of gate 2 or 3 means one of:
- re-simulate more conservatively (back to Task 10)
- ship the router disabled

Talk to the user first.

- [ ] **Step 8: Progress entry and commit** (tell the user first)

```bash
git add eval/reports/<router_only-dir> eval/reports/<full-all-dir> eval/reports/<full-workload-dir> \
  eval/reports/derived-baseline-v3-workload-300-seed7 eval/reports/derived-router_only-workload-300-seed7 \
  docs/progress.md
git commit -m "results: router-only and full Weir live runs (cold 158 + 300 replay), judged"
git push origin phase-3 && git push origin phase-3:main
```

---

### Task 13: Results write-up, final review, merge

**Files:**
- Create: `docs/results/router.md`, `docs/results/summary.md`
- Modify: `README.md`, `docs/progress.md`, `docs/decisions.md`, `docs/backlog.md`, `docs/README.md` (index)
- Modify: the memory file `weir-project.md` (outside the repo)

**Interfaces:**
- Consumes: every report from Tasks 9–12, plus the Phase 2 reports (`cache_only` cold and replay).
- Produces: the Phase 3 results and the closed phase.

- [ ] **Step 1: Write `docs/results/router.md`**

Match the style of `docs/results/cache-only.md`: a headline table, then bullets, the gate, breakdowns and caveats. Sections:
1. **Setup:** config labels, report directories, tuned values (D37).
2. **Headline:** router only vs baseline v3 on the cold 158 questions: cost per 1k, p50/p95, judge, facts, share routed small, escalation rate.
3. **Per-route quality:** small vs large, from the `By route` table in each report's `summary.md`, plus the gate's small-route judge vs baseline on the same questions.
4. **Route reasons:** the Task 12 Step 4 query output.
5. **Simulated vs live:** the Task 10 chosen-setting row next to the live router-only numbers.
6. **Exit gate (addendum §7.6):** one row per check per report (Task 12 Step 7), with each result and an explanation of any noise.
7. **Caveats:**
   - small eval set
   - the synthetic KB
   - grounding is lexical (it measures word overlap, not meaning)
   - list prices
   - sequential latency (Phase 5 does load)

- [ ] **Step 2: Write `docs/results/summary.md`, the four-way ablation table**

```markdown
# Weir results summary (Phases 1–3)

## Cold pass: 158 questions, each asked once (repeat rate 0%, paraphrases count as distinct)

| Configuration | Cache hits | Routed small | Cost / 1k | p50 | p95 | Judge | Facts | Wrong hits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (always large, no cache) | 0% | 0% | $0.0980 | 617 ms | 3.5 s | 4.90 | 0.981 | — |
| Cache only | 14.6% | 0% | $0.0847 | 686 ms | 1.3 s | 4.91 | 0.978 | 0 |
| Router only | 0% | … | … | … | … | … | … | — |
| Full Weir | … | … | … | … | … | … | … | … |

## Replay: 300 requests, Zipf-skewed, seed 7 (repeat rate 73.7%)

| Configuration | How measured | Cache hits | Cost / 1k | p50 | Judge | Facts | Wrong hits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | derived from baseline v3 per question | 0% | … | … | 4.79 | 0.948 | — |
| Cache only | live (Phase 2) | 93.3% | $0.0050 | 56 ms | 4.79 | 0.948 | 0 |
| Router only | derived from the router-only run per question | 0% | … | … | … | … | — |
| Full Weir | live | … | … | … | … | … | … |
```

Fill it from the `summary.md` of each report:
- `baseline-v3`
- `20261003T172615Z-cache_only-all`
- `20261003T173739Z-cache_only-workload-300-seed7`
- the Task 12 reports
- the two derived reports

Add one paragraph per table saying what the numbers mean. Note the latency caveat for derived rows: their latencies are each question's measured single-request latency.

- [ ] **Step 3: Update the README, decisions, backlog and progress**

- **`README.md`:**
  - status line: Phases 0–3 done
  - results table: add the router-only and full rows, linking `docs/results/summary.md`
  - request flow: add step 6a, "route → generate → grounding check → escalate once"
  - overlay table: add `small_only`, `router_only`, `full`
  - layout: `db/migrations` (001–003) and `weir/router/`
  - test counts (run each suite and copy the numbers)
  - roadmap: Phase 3 ✅
- **`docs/decisions.md`:** add D38, the Phase 3 gate outcome and any judgement calls made in Task 12 Step 7.
- **`docs/backlog.md`:**
  - mark M9 resolved by D35
  - add any deferred final-review findings as M12+
- **`docs/progress.md`:** close the Phase 3 section with the headline numbers.
- **`docs/README.md`:** link `results/router.md`, `results/router-tuning.md` and `results/summary.md`.

- [ ] **Step 4: Run every test suite**

```bash
docker compose up -d postgres
cd services/weir && uv run pytest -q
cd ../hospital-rag && uv run pytest -q
cd ../../eval && uv run pytest -q
docker compose stop
```

Expected: all three suites pass. Put the counts in the README.

- [ ] **Step 5: Final whole-branch review**

Dispatch one fresh reviewer on the most capable model:
- **Scope:** the full `git diff 377af41..HEAD` against this plan and the addendum.
- **Focus:**
  - the five Review Focus items
  - cost accounting (addendum §3.6)
  - the cache gate (D35)
  - the "router decisions only" rule
  - simulator and live agreement
- **Fix list:** fix Critical and Important findings TDD-first. Log Minor ones in `docs/backlog.md`.
- **Results:** if a fix changes behaviour that affects results, say so, and re-run only the affected live run.

- [ ] **Step 6: Commit, push and merge** (tell the user first; summarise the results and the gate)

```bash
git add README.md docs/
git commit -m "docs: Phase 3 results: router tuning, live runs, four-way ablation, exit gate"
git push origin phase-3 && git push origin phase-3:main
```

- [ ] **Step 7: Update the project memory**

Update `weir-project.md` in the memory directory:
- Phase 3 done, with its date
- the headline numbers
- next is Phase 4 (Prometheus and Grafana)

---

## Self-Review Notes

**Spec coverage (addendum section → task):**

| Addendum section | Task |
| --- | --- |
| §2 flow | 5 |
| §3 units | 2, 3, 4, 5 |
| §3.1 features | 2 |
| §3.2 rules | 3 |
| §3.3 grounding | 4 |
| §3.4 escalation and fallback | 5 |
| §3.5 cache interaction (grounded only; `force_model` bypass; no tier in the key) | 5 |
| §3.6 cost | 5 |
| §4 migration | 1 |
| §5 config and overlays | 1 |
| §6 API meta | 5 |
| §7.1 small trial | 9 |
| §7.2 features and grounding data | 7, 8, 9 |
| §7.3 simulation and tuning | 8, 10 |
| §7.4 live runs | 12 |
| §7.5 results | 13 |
| §7.6 gate | 11, 12, 13 |
| §7.7 budget | 9, 12 |
| §8 testing | 1–5, 7, 8, 11 |

**Deliberate choices beyond the addendum, to confirm in review:**
1. Fallback and escalation apply only to router decisions. This keeps the baseline, `cache_only` and `small_only` runs pure.
2. A failed escalation is logged as `error_detail = "escalation_failed:<kind>"` on an `ok` row.
3. Fallback skips `unavailable`: hospital-rag itself is down, so the other tier can't help.
4. Grounding is exported from the request log into the report directory (`grounding.jsonl`), so the simulation is reproducible from committed files.
5. Derived replay rows (baseline, router only) reuse per-question results; they are labelled as derived.
