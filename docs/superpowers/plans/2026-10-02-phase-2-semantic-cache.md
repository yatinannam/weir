# Weir Phase 2 (Semantic Cache) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe semantic cache to Weir (bypass rules, embedding lookup, entity guard, eligible write-back, invalidation, feedback and purge APIs), grow the eval set to about 150 questions, tune the similarity threshold with a sweep, and measure the cache against baseline v2.

**Architecture:**
- **Pipeline:** Weir's pipeline gains a cache step before retrieval: bypass rules → bge-small embedding → top-3 lookup in `weir.cache_entries` (filtered by namespace, `kb_version` and `prompt_version`) → entity guard → hit (replay) or miss/bypass (Phase 1 path).
- **Background work:** cache writes, hit counters, version refresh and expired-row cleanup all run off the request path.
- **Eval package:** reuses Weir's own embedder, normalizer and entity guard (path dependency), so the sweep tests exactly what production runs.

**Tech Stack:** Existing stack plus fastembed and tokenizers in Weir; matplotlib in eval (chart). All free.

**Spec:**
- `docs/superpowers/specs/2026-10-02-phase-2-semantic-cache-design.md` (Phase 2 addendum, binding)
- builds on `docs/superpowers/specs/2026-09-30-weir-design.md` §6, §8, §10, §11, §16

## Global Constraints

- **Zero spend.** Free tools and tiers only.
- Python `>=3.12,<3.13`, uv, one `uv.lock` per package. LF line endings, UTF-8. Never edit files with PowerShell `Set-Content`.
- **Push every commit** to `origin phase-2` right after committing (user instruction 2026-10-02). Fast-forward `main` at the end of Phase 2.
- Branch: `phase-2` (exists; the addendum is already committed there).
- Postgres URLs use `127.0.0.1`, never `localhost` (Windows IPv6 stall). Git Bash `docker compose exec` with container paths needs `MSYS_NO_PATHCONV=1`.
- Embeddings: `BAAI/bge-small-en-v1.5`, 384-d, unit-normalized, computed on `weir.text.normalize(query)`.
- **Cache key:** namespace + `kb_version` + `prompt_version`. Starting threshold 0.92 (the sweep replaces it), candidates 3, TTL 24 h, `min_retrieval_score` 0.30.
- **On a hit:**
  - `route="none"` and `model_calls=0`
  - `cost_usd` = embedding cost ($0 for local bge-small)
  - `counterfactual_cost_usd` = the stored entry's tokens priced at the large model's rate
- **Free-tier budgets:**
  - **Groq gpt-oss-120b:** 8K tokens/min and 200K tokens/day, at about 500 tokens per request. Use `--min-interval 5` for eval runs.
  - **Qwen judge:** 30 requests/min, 8K tokens/min and 200K tokens/day, at about 900 tokens per grade, so about 220 grades a day. Judge separately (`--no-judge`, then `rejudge`, which can resume). Never re-grade rows that already have a score.
- Rubric stays `r1`. Unanswerable questions get an extra note in the prompt, and only their cache key changes, so the 50 existing grades stay valid (this refines addendum §7.1's "r2 + re-grade 50").
- Containers: stop them (`docker compose stop`) when a task doesn't need them, because RAM is tight. Long eval steps run in the foreground in chunks under 10 minutes (`run` and `rejudge` save after every row).

## Review Focus

1. **The version cache is empty** (Weir just started, or hospital-rag `/info` is down). Requests must still be answered, with `cache_status=bypass` and `bypass_reason=no_version`. A failed refresh keeps the last known versions. Tests: Task 7 `test_no_version_bypasses_cache`, Task 6 `test_refresh_failure_keeps_old_versions`.
2. **The same question is asked in another namespace.** It must never be served from the other namespace's entries. Test: Task 5 `test_lookup_is_isolated_by_namespace`.
3. **A document is edited, so `kb_version` changes.** Old entries must stop matching immediately, with no scan. Tests: Task 5 `test_lookup_filters_versions_and_expiry`, Task 7 `test_version_change_misses`.
4. **Cache infrastructure fails** (embedder error, lookup error, insert error). The user still gets an answer (`bypass_reason=error`), and a failed write is counted, never raised. Tests: Task 7 `test_embedder_failure_bypasses`, `test_lookup_failure_bypasses`; Task 6 `test_queue_counts_failures_and_continues`.
5. **Feedback arrives before the asynchronously written log row**, or comes from another tenant. The first case must wait briefly and succeed. The second must return 404 without leaking anything. Tests: Task 8 `test_feedback_waits_for_log_row`, `test_feedback_unknown_or_other_tenant_404`.

---

## File map

```text
db/migrations/002_phase2_cache.sql           drop feedback FK, add indexes (T1)
configs/weir.yaml                            cache/bypass/namespace settings (T1; cache flipped on in T7)
configs/ablations/cache_only.yaml            cache on + always large (T1)
configs/entities.yaml                        entity-guard lexicon (T2)

services/weir/src/weir/
  config.py                                  + RagConfig.info_refresh_seconds, CacheConfig fields, BypassConfig, NamespaceCacheConfig (T1)
  settings.py                                + embed_cache_dir (T4)
  background.py                              BackgroundQueue, Periodic (T6)
  admin.py                                   AdminService, RequestRef (T8)
  pipeline.py                                CacheDeps + cache flow (T7)
  main.py                                    feedback + purge endpoints, lifespan wiring (T8)
  rag/adapter.py                             + RagClient.info() (T6)
  cache/__init__.py
  cache/entities.py                          Lexicon, Entities (T2)
  cache/guards.py                            BypassRules, bypass_reason, contains_personal_data, store_block_reason (T3)
  cache/embedder.py                          Embedder (T4)
  cache/store.py                             CacheEntry, Candidate, CacheStore (T5)
  cache/versions.py                          VersionCache (T6)
services/weir/Dockerfile                     bake bge-small (T4)
services/weir/tests/
  fakes.py                                   ListSink, FakeEmbedder, FakeStore, InlineQueue, FakeAdmin, make_entry (T5/T7/T8)
  test_config.py, test_migrate.py            (T1)
  test_entities.py (T2), test_guards.py (T3), test_embedder.py (T4), test_cache_store.py (T5)
  test_background.py, test_versions.py, test_adapter.py (T6)
  test_pipeline.py (rewritten T7), test_api.py (rewritten T8), test_admin.py (T8)

eval/
  pyproject.toml                             + weir (path dep), matplotlib (T9)
  src/weir_eval/dataset.py                   unanswerable group, split preservation (T9)
  src/weir_eval/kb.py, judge.py, runner.py, summary.py, cli.py   (T9)
  src/weir_eval/workload.py                  Zipf workload (T9)
  src/weir_eval/sweep.py                     pairs, sweep, threshold choice, report (T12)
  datasets/queries.jsonl                     +100 queries (T10)
  datasets/pairs.jsonl                       (T12)
  datasets/workload-300-seed7.jsonl          (T13)
  tests/test_dataset.py, test_judge.py, test_runner.py, test_summary.py, test_workload.py (T9), test_sweep.py (T12)

docs/results/baseline.md (v2, T11), cache-threshold.md (T12), cache-only.md (T13); docs/progress.md, decisions.md
```

---

### Task 1: Config schema, Phase 2 configs, migration 002

**Files:**
- Modify: `services/weir/src/weir/config.py`, `configs/weir.yaml`, `services/weir/tests/test_config.py`, `services/weir/tests/test_migrate.py`
- Create: `configs/ablations/cache_only.yaml`, `db/migrations/002_phase2_cache.sql`

**Interfaces:**
- Produces:
  - `RagConfig.info_refresh_seconds: float`
  - `CacheConfig` fields: `enabled`, `threshold`, `candidates`, `ttl_hours`, `min_retrieval_score`, `cleanup_interval_minutes`, `embed_model`
  - `BypassConfig` fields: `time_sensitive`, `clinical`, `followup_prefixes`, `followup_pronouns`, `followup_max_words`
  - `NamespaceConfig.cache: NamespaceCacheConfig(enabled: bool = True, ttl_hours: float | None = None)`
  - `WeirConfig.bypass`, `WeirConfig.cache_enabled_for(namespace) -> bool` (unknown → False), `WeirConfig.ttl_hours_for(namespace) -> float`
- Migration `002_phase2_cache.sql`.

- [ ] **Step 1: Failing tests.** Append to `services/weir/tests/test_config.py`:

```python
def test_phase2_config_fields():
    cfg = load_config(CONFIGS / "weir.yaml")
    assert cfg.cache.threshold == 0.92 and cfg.cache.candidates == 3
    assert cfg.cache.embed_model == "BAAI/bge-small-en-v1.5" and cfg.cache.ttl_hours == 24
    assert cfg.rag.info_refresh_seconds == 30
    assert cfg.cache_enabled_for("weir-general/en/public") is True
    assert cfg.cache_enabled_for("unknown/ns") is False
    assert cfg.ttl_hours_for("weir-general/en/staff") == 24
    assert "now" in cfg.bypass.time_sensitive and "diagnos*" in cfg.bypass.clinical
    assert cfg.bypass.followup_max_words == 6


def test_cache_only_overlay():
    cfg = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / "cache_only.yaml")
    assert cfg.config_label == "cache_only"
    assert cfg.cache.enabled is True and cfg.kill_switch.force_large is True


def test_namespace_ttl_override(tmp_path):
    import yaml

    data = yaml.safe_load((CONFIGS / "weir.yaml").read_text(encoding="utf-8"))
    data["namespaces"]["weir-general/en/staff"]["cache"]["ttl_hours"] = 2
    path = tmp_path / "w.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert load_config(path).ttl_hours_for("weir-general/en/staff") == 2
```

In `services/weir/tests/test_migrate.py`, change the first test's expectation and add an FK test:

```python
def test_applies_all_then_is_idempotent(clean_db_url):
    assert apply_migrations(clean_db_url, MIGRATIONS) == ["001_init.sql", "002_phase2_cache.sql"]
    assert apply_migrations(clean_db_url, MIGRATIONS) == []


def test_feedback_fk_dropped(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(clean_db_url) as conn:
        fks = conn.execute(
            "select count(*) from pg_constraint where conrelid = 'weir.feedback'::regclass and contype = 'f'"
        ).fetchone()[0]
    assert fks == 0
```

- [ ] **Step 2: Run and confirm failure.** `docker compose up -d postgres`, then `cd services/weir && uv run pytest tests/test_config.py tests/test_migrate.py -q`.
Expected: failures (`AttributeError ... threshold`, missing overlay file, migration list mismatch).

- [ ] **Step 3: Implement.**

`db/migrations/002_phase2_cache.sql`:
```sql
-- Phase 2 addendum §4. Feedback can arrive before its asynchronously written request_log row,
-- so the API checks existence itself instead of relying on a foreign key.
alter table weir.feedback drop constraint if exists feedback_request_id_fkey;
create index if not exists feedback_request_id_idx on weir.feedback (request_id);
create index if not exists cache_entries_expires_at_idx on weir.cache_entries (expires_at);
```

`services/weir/src/weir/config.py`: replace `RagConfig`, `CacheConfig` and `NamespaceConfig`, add `BypassConfig`, and extend `WeirConfig`:
```python
class RagConfig(_Strict):
    base_url: str
    timeout_seconds: float = 30.0
    retrieve_k: int = 4
    info_refresh_seconds: float = 30.0


class CacheConfig(_Strict):
    enabled: bool = False
    threshold: float = 0.92
    candidates: int = 3
    ttl_hours: float = 24.0
    min_retrieval_score: float = 0.30
    cleanup_interval_minutes: float = 60.0
    embed_model: str = "BAAI/bge-small-en-v1.5"


class BypassConfig(_Strict):
    time_sensitive: list[str] = []
    clinical: list[str] = []          # a trailing "*" means prefix match ("diagnos*")
    followup_prefixes: list[str] = []
    followup_pronouns: list[str] = []
    followup_max_words: int = 6


class NamespaceCacheConfig(_Strict):
    enabled: bool = True
    ttl_hours: float | None = None


class NamespaceConfig(_Strict):
    sensitive: bool = False
    cache: NamespaceCacheConfig = NamespaceCacheConfig()
```
In `WeirConfig`, add the field `bypass: BypassConfig = BypassConfig()` and these methods:
```python
    def cache_enabled_for(self, namespace: str) -> bool:
        ns = self.namespaces.get(namespace)
        return ns is not None and ns.cache.enabled  # unknown namespace: never cache

    def ttl_hours_for(self, namespace: str) -> float:
        ns = self.namespaces.get(namespace)
        return ns.cache.ttl_hours if ns is not None and ns.cache.ttl_hours is not None else self.cache.ttl_hours
```

`configs/weir.yaml` (full replacement; the cache stays **off** until Task 7):
```yaml
# Weir gateway configuration. Every threshold lives here; experiments change config, not code.
# Sections are added phase by phase (see docs/superpowers/plans/). Unknown keys are rejected.
config_label: dev

rag:
  base_url: http://hospital-rag:8001
  timeout_seconds: 30
  retrieve_k: 4
  info_refresh_seconds: 30   # how often kb/prompt versions are refreshed from hospital-rag /info

router:
  small_model: openai/gpt-oss-20b
  large_model: openai/gpt-oss-120b

cache:
  enabled: false             # switched on in Phase 2 Task 7
  threshold: 0.92            # replaced by the threshold sweep (docs/results/cache-threshold.md)
  candidates: 3
  ttl_hours: 24
  min_retrieval_score: 0.30  # never cache answers built on weak retrieval
  cleanup_interval_minutes: 60
  embed_model: BAAI/bge-small-en-v1.5

bypass:                      # questions that never read or write the cache (addendum §3.2)
  time_sensitive: [today, tonight, now, right now, currently, at the moment, this week, wait time, waiting time, open now]
  clinical: [dose, dosage, mg, "symptom*", "diagnos*", "treatment*", "medication*", "side effect*", "prescri*"]
  followup_prefixes: [what about, how about, and, also, same for, what if]
  followup_pronouns: [it, that, those, they, there, them, this]
  followup_max_words: 6

kill_switch:
  force_large: false         # send every request to the large model
  disable_cache: false       # skip the cache entirely

namespaces:
  weir-general/en/public:
    sensitive: false
    cache:
      enabled: true
  weir-general/en/staff:
    sensitive: true          # logs keep only hashes, never raw query text
    cache:
      enabled: true
```

`configs/ablations/cache_only.yaml`:
```yaml
# Cache only: semantic cache on, always the large model (Phase 2 addendum §5).
config_label: cache_only
cache:
  enabled: true
kill_switch:
  force_large: true
```

- [ ] **Step 4: Run the full Weir suite.** `uv run pytest -q`.
Expected: all pass, 51 existing plus 4 new = 55. The Phase 1 pipeline tests still pass because the cache is off.

- [ ] **Step 5: Commit and push.**
```bash
git add db/migrations/002_phase2_cache.sql configs services/weir
git commit -m "feat(weir): Phase 2 config schema, cache_only ablation, migration 002"
git push
```

---

### Task 2: Entity lexicon and guard

**Files:**
- Create: `configs/entities.yaml`, `services/weir/src/weir/cache/__init__.py`, `services/weir/src/weir/cache/entities.py`
- Test: `services/weir/tests/test_entities.py`

**Interfaces:**
- Produces:
  - `Entities(numbers: frozenset[str], negated: bool, terms: frozenset[str])`, where terms look like `"group:canonical"`
  - `Lexicon(groups: dict[str, dict[str, list[str]]])` and `Lexicon.from_yaml(path)`
  - `Lexicon.extract(text) -> Entities`
  - `Lexicon.conflicts(a_text, b_text) -> bool` (True when the entities differ in any way)
  - The constructor raises `ValueError` when one phrase maps to two terms.

- [ ] **Step 1: Write the lexicon.** `configs/entities.yaml`:
```yaml
# Entity guard lexicon (Phase 2 addendum §3.1).
# Two questions may share a cached answer only if they mention the same terms below, the same
# numbers and the same negation. Format: group -> canonical term -> synonyms. Matching is
# case-insensitive on whole words, longest phrase first ("semi-private room" before "private room").
# Every phrase may appear only once in this file. Built from kb/ (Weir General Hospital).
groups:
  wards:
    icu: [intensive care unit, intensive care, critical care]
    general ward: [general wards]
    pediatric ward: [paediatric ward, children's ward, childrens ward, kids ward]
    maternity ward: [maternity, labour ward, labor ward, delivery ward]
    private room: [private rooms, private]
    semi-private room: [semi-private rooms, semi-private, semi private room, semi private]
  departments:
    cardiology: [cardiac, heart]
    neurology: [neuro, neurologist]
    orthopedics: [orthopaedics, ortho, orthopedic, bone]
    pediatrics: [paediatrics, pediatric opd, paediatric opd, pediatrician]
    radiology: [imaging]
    emergency: [casualty, emergency department, er]
    blood bank: [blood donation, donate blood, donation camp]
    laboratory: [lab, labs, lab report, lab reports]
    medical records: [records department]
    cafeteria: [visitor cafeteria]
    staff canteen: [canteen]
    main pharmacy: [24-hour pharmacy, 24 hour pharmacy]
    opd pharmacy: [outpatient pharmacy]
  services:
    ct scan: [ct, ct scans, cat scan]
    mri: [mri scan, mri scans]
    x-ray: [x-rays, xray, x ray]
    ultrasound: [sonography, usg]
    health checkup: [health check-up, health check, checkup package]
    vaccination: [vaccine, vaccines, immunisation, immunization]
  people:
    adult: [adults]
    child: [children, kid, kids, baby, babies, infant, infants]
    senior: [seniors, senior citizen, senior citizens, elderly]
    nurse: [nurses, nursing]
    doctor: [doctors, physician, consultant]
    attendant: [attendants]
    visitor: [visitors]
  vehicles:
    car: [cars, four-wheeler, four wheeler]
    two-wheeler: [two wheeler, two-wheelers, bike, bikes, motorcycle, scooter]
  payment:
    self-pay: [self pay, cash, out of pocket]
    insurance: [insured, cashless, tpa]
    government scheme: [govt scheme, government health scheme]
  days:
    monday: [mondays]
    tuesday: [tuesdays]
    wednesday: [wednesdays]
    thursday: [thursdays]
    friday: [fridays]
    saturday: [saturdays]
    sunday: [sundays]
    weekday: [weekdays, monday to friday]
    weekend: [weekends, saturday and sunday]
    public holiday: [public holidays, holiday, holidays]
  time_of_day:
    morning: [mornings]
    afternoon: [afternoons]
    evening: [evenings]
    night: [nights, night shift, overnight]
  copies:
    first copy: [first]
    additional copy: [additional, duplicate, extra copy, another copy]
```

- [ ] **Step 2: Failing tests.** `services/weir/tests/test_entities.py`:
```python
import pytest

from weir.cache.entities import Lexicon

from .conftest import CONFIGS

LEX = Lexicon.from_yaml(CONFIGS / "entities.yaml")


@pytest.mark.parametrize(("a", "b"), [
    ("What are the ICU visiting hours?", "What are the general ward visiting hours?"),
    ("When is the Cardiology OPD open?", "When is the Neurology OPD open?"),
    ("How much is parking for a car?", "How much is parking for a two-wheeler?"),
    ("When is the adult vaccination clinic?", "When is the child vaccination clinic?"),
    ("When does the night shift start for nurses?", "When does the night shift start for doctors?"),
    ("What is the deposit for cashless insurance admission?", "What is the deposit for self-pay admission?"),
    ("What is the private room tariff?", "What is the semi-private room tariff?"),
    ("What are the main pharmacy hours?", "What are the OPD pharmacy hours?"),
    ("Is parking free on weekdays?", "Is parking free on weekends?"),
    ("Can I visit for 2 hours?", "Can I visit for 3 hours?"),
    ("Is there parking on Sunday?", "Is there no parking on Sunday?"),
    ("Can kids visit the ICU?", "Can adults visit the ICU?"),
])
def test_kb_look_alike_pairs_conflict(a, b):
    assert LEX.conflicts(a, b)


@pytest.mark.parametrize(("a", "b"), [
    ("What are the ICU visiting hours?", "When can I visit someone in intensive care?"),
    ("How much does a CT scan cost?", "What is the charge for a CT?"),
    ("What is the standard discharge time?", "When do patients usually get discharged?"),
    ("Parking fee for a bike?", "How much do two-wheelers pay for parking?"),
])
def test_paraphrases_do_not_conflict(a, b):
    assert not LEX.conflicts(a, b)


def test_longest_phrase_wins():
    assert LEX.extract("semi-private room tariff").terms == frozenset({"wards:semi-private room"})
    assert LEX.extract("intensive care unit hours").terms == frozenset({"wards:icu"})


def test_numbers_and_units_are_normalised():
    assert LEX.extract("Rs 1,200 for 2 hours at 4pm").numbers == frozenset({"1200", "2 hour", "4 pm"})


def test_negation_forms():
    assert LEX.extract("I can't visit").negated and LEX.extract("non-veg thali").negated
    assert not LEX.extract("I can visit").negated


def test_duplicate_phrase_rejected():
    with pytest.raises(ValueError, match="two terms"):
        Lexicon({"a": {"x": ["shared"]}, "b": {"y": ["shared"]}})
```

- [ ] **Step 3: Confirm failure.** `uv run pytest tests/test_entities.py -q` → `ModuleNotFoundError: weir.cache`.

- [ ] **Step 4: Implement.** `services/weir/src/weir/cache/__init__.py`:
```python
"""Semantic cache (Phase 2 addendum)."""
```
`services/weir/src/weir/cache/entities.py`:
```python
"""Entity guard (Phase 2 addendum §3.1).

Two questions may share a cached answer only if they mention the same numbers, the same
negation and the same lexicon terms. Embedding similarity alone can't tell "ICU visiting
hours" from "general ward visiting hours"; this guard can.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..text import normalize

UNIT_CANON = {
    "am": "am", "pm": "pm", "km": "km", "%": "%", "percent": "%",
    "hour": "hour", "hours": "hour", "hr": "hour", "hrs": "hour",
    "day": "day", "days": "day", "minute": "minute", "minutes": "minute", "min": "minute", "mins": "minute",
    "week": "week", "weeks": "week", "month": "month", "months": "month", "year": "year", "years": "year",
    "bed": "bed", "beds": "bed",
}
_UNITS = "|".join(sorted((re.escape(u) for u in UNIT_CANON), key=len, reverse=True))
NUMBER = re.compile(rf"(?<![\w.])(\d+(?:[.,:]\d+)*)(?:\s*({_UNITS}))?(?!\w)")
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
NEGATIONS = frozenset({"no", "not", "without", "except", "non", "never", "cannot", "none", "neither", "nor"})


@dataclass(frozen=True)
class Entities:
    numbers: frozenset[str]
    negated: bool
    terms: frozenset[str]


class Lexicon:
    def __init__(self, groups: dict[str, dict[str, list[str]]]):
        self._term_of: dict[str, str] = {}
        for group, entries in groups.items():
            for canonical, synonyms in entries.items():
                term = f"{group}:{canonical}"
                for phrase in [canonical, *synonyms]:
                    key = normalize(phrase)
                    if self._term_of.get(key, term) != term:
                        raise ValueError(f"lexicon phrase {phrase!r} maps to two terms: {self._term_of[key]} and {term}")
                    self._term_of[key] = term
        phrases = sorted(self._term_of, key=len, reverse=True)
        self._pattern = (re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in phrases) + r")(?!\w)")
                         if phrases else None)

    @classmethod
    def from_yaml(cls, path: Path) -> "Lexicon":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8"))["groups"])

    def extract(self, text: str) -> Entities:
        text = normalize(text).replace("’", "'")
        numbers = frozenset(_number_key(m) for m in NUMBER.finditer(text))
        negated = any(w in NEGATIONS or w.endswith("n't") for w in WORD.findall(text))
        terms = (frozenset(self._term_of[m.group(0)] for m in self._pattern.finditer(text))
                 if self._pattern else frozenset())
        return Entities(numbers, negated, terms)

    def conflicts(self, a_text: str, b_text: str) -> bool:
        return self.extract(a_text) != self.extract(b_text)


def _number_key(match: re.Match) -> str:
    value = match.group(1).replace(",", "")
    unit = UNIT_CANON.get(match.group(2) or "", "")
    return f"{value} {unit}".strip()
```

- [ ] **Step 5: Run.** `uv run pytest tests/test_entities.py -q` → 20 passed. If a paraphrase case conflicts, or a look-alike case doesn't, fix **the lexicon** (not the test) and record a ledger ruling.

- [ ] **Step 6: Commit and push.**
```bash
git add configs/entities.yaml services/weir
git commit -m "feat(weir): entity guard lexicon built from the KB"
git push
```

---

### Task 3: Bypass rules, personal-data check, write-back eligibility

**Files:**
- Create: `services/weir/src/weir/cache/guards.py`
- Test: `services/weir/tests/test_guards.py`

**Interfaces:**
- Consumes: `BypassConfig`, `WeirConfig` (Task 1); `GenerateResult` (weir.rag.adapter); `normalize`.
- Produces:
  - `BypassRules(cfg: BypassConfig)` with `.time_sensitive(text) -> bool`, `.clinical(text) -> bool` and `.followup(text, session_id) -> bool`
  - `bypass_reason(*, query, namespace, session_id, personalized, bypass_cache, cfg, rules) -> str | None`. Reasons, checked in this order: `personalized`, `request_option`, `kill_switch`, `cache_disabled`, `namespace_disabled`, `clinical`, `time_sensitive`, `followup`.
  - `contains_personal_data(text) -> bool`
  - `store_block_reason(*, generated, top_score, query, min_retrieval_score) -> str | None`. Reasons: `not_found`, `finish_reason:<x>`, `no_citations`, `invalid_citations`, `low_retrieval`, `personal_data`.

- [ ] **Step 1: Failing tests.** `services/weir/tests/test_guards.py`:
```python
import pytest

from weir.cache.guards import BypassRules, bypass_reason, contains_personal_data, store_block_reason
from weir.config import load_config
from weir.rag.adapter import GenerateResult

from .conftest import CONFIGS

PUBLIC = "weir-general/en/public"


def cfg(**cache):
    c = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / "cache_only.yaml")
    for k, v in cache.items():
        setattr(c.cache, k, v)
    return c


def reason(query="When can I visit?", namespace=PUBLIC, session_id=None, personalized=False, bypass_cache=False, config=None):
    c = config or cfg()
    return bypass_reason(query=query, namespace=namespace, session_id=session_id, personalized=personalized,
                         bypass_cache=bypass_cache, cfg=c, rules=BypassRules(c.bypass))


def test_plain_question_is_cacheable():
    assert reason() is None


def test_reason_order_and_each_rule():
    assert reason(personalized=True, bypass_cache=True) == "personalized"
    assert reason(bypass_cache=True) == "request_option"
    c = cfg(); c.kill_switch.disable_cache = True
    assert reason(config=c) == "kill_switch"
    assert reason(config=cfg(enabled=False)) == "cache_disabled"
    assert reason(namespace="unknown/ns") == "namespace_disabled"
    assert reason(query="What dosage of paracetamol is safe?") == "clinical"
    assert reason(query="Is the pharmacy open now?") == "time_sensitive"
    assert reason(query="what about weekends?", session_id="s1") == "followup"


@pytest.mark.parametrize("query", [
    "What does a diagnosis report cost?", "Who gives the treatment plan?", "Any side effects of the vaccine?",
])
def test_clinical_prefix_terms(query):
    assert reason(query=query) == "clinical"


def test_word_boundaries():
    assert reason(query="Do you know the visiting hours?") is None      # "know" is not "now"
    assert reason(query="Android app for appointments?", session_id="s1") is None  # "and" only as a whole leading word


def test_followup_needs_session_and_short_pronoun_or_prefix():
    assert reason(query="what about weekends?") is None                  # no session: a fresh question
    assert reason(query="is it open?", session_id="s1") == "followup"
    assert reason(query="Is the main pharmacy open on Sundays and public holidays?", session_id="s1") is None


@pytest.mark.parametrize(("text", "personal"), [
    ("Mail me at ravi@example.com", True),
    ("Call 98765 43210", True),
    ("My patient ID is 4471209", True),
    ("When is my appointment?", True),
    ("Call ext. 2140 for cardiology", False),
    ("The deposit is ₹25,000", False),
    ("Visiting is 4 pm to 7 pm", False),
])
def test_personal_data(text, personal):
    assert contains_personal_data(text) is personal


def gen(**over):
    base = dict(answer="Open 4 pm to 7 pm.", cited_chunk_ids=["pub-a#0"], invalid_citations=0, not_found=False,
                finish_reason="stop", tokens_in=500, tokens_out=60, model="m", prompt_version="p1", latency_ms=5)
    return GenerateResult(**{**base, **over})


@pytest.mark.parametrize(("over", "top", "query", "expected"), [
    ({}, 0.9, "When can I visit?", None),
    ({"not_found": True}, 0.9, "q", "not_found"),
    ({"finish_reason": "length"}, 0.9, "q", "finish_reason:length"),
    ({"cited_chunk_ids": []}, 0.9, "q", "no_citations"),
    ({"invalid_citations": 1}, 0.9, "q", "invalid_citations"),
    ({}, 0.1, "q", "low_retrieval"),
    ({"answer": "Call 98765 43210."}, 0.9, "q", "personal_data"),
    ({}, 0.9, "When is my bill due?", "personal_data"),
])
def test_store_block_reason(over, top, query, expected):
    assert store_block_reason(generated=gen(**over), top_score=top, query=query, min_retrieval_score=0.3) == expected
```

- [ ] **Step 2: Confirm failure.** `uv run pytest tests/test_guards.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement.** `services/weir/src/weir/cache/guards.py`:
```python
"""Which questions may use the cache (main spec §6.1) and which answers may be stored (§6.3)."""
import re

from ..config import BypassConfig, WeirConfig
from ..rag.adapter import GenerateResult
from ..text import normalize

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)(?:\d[ -]?){7,}(?!\d)")
LONG_ID = re.compile(r"(?<![\d,])\d{6,}(?![\d,])")
MY_RECORD = re.compile(
    r"\bmy (?:appointment|bill|report|result|record|prescription|admission|account|booking|payment|claim)s?\b")


def _phrases(terms: list[str]) -> re.Pattern | None:
    parts = []
    for term in terms:
        t = normalize(term)
        parts.append(re.escape(t[:-1]) + r"\w*" if t.endswith("*") else re.escape(t))
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)") if parts else None


class BypassRules:
    def __init__(self, cfg: BypassConfig):
        self._time = _phrases(cfg.time_sensitive)
        self._clinical = _phrases(cfg.clinical)
        prefixes = [re.escape(normalize(p)) for p in cfg.followup_prefixes]
        self._prefix = re.compile(r"^(?:" + "|".join(prefixes) + r")(?!\w)") if prefixes else None
        self._pronouns = frozenset(normalize(p) for p in cfg.followup_pronouns)
        self._max_words = cfg.followup_max_words

    def time_sensitive(self, text: str) -> bool:
        return bool(self._time and self._time.search(normalize(text)))

    def clinical(self, text: str) -> bool:
        return bool(self._clinical and self._clinical.search(normalize(text)))

    def followup(self, text: str, session_id: str | None) -> bool:
        if not session_id:
            return False
        t = normalize(text)
        if self._prefix and self._prefix.search(t):
            return True
        words = re.findall(r"[a-z']+", t)
        return len(words) <= self._max_words and any(w in self._pronouns for w in words)


def bypass_reason(*, query: str, namespace: str, session_id: str | None, personalized: bool,
                  bypass_cache: bool, cfg: WeirConfig, rules: BypassRules) -> str | None:
    if personalized:
        return "personalized"
    if bypass_cache:
        return "request_option"
    if cfg.kill_switch.disable_cache:
        return "kill_switch"
    if not cfg.cache.enabled:
        return "cache_disabled"
    if not cfg.cache_enabled_for(namespace):
        return "namespace_disabled"
    if rules.clinical(query):
        return "clinical"
    if rules.time_sensitive(query):
        return "time_sensitive"
    if rules.followup(query, session_id):
        return "followup"
    return None


def contains_personal_data(text: str) -> bool:
    t = normalize(text)
    return bool(EMAIL.search(t) or PHONE.search(t) or LONG_ID.search(t) or MY_RECORD.search(t))


def store_block_reason(*, generated: GenerateResult, top_score: float, query: str,
                       min_retrieval_score: float) -> str | None:
    if generated.not_found:
        return "not_found"
    if generated.finish_reason != "stop":
        return f"finish_reason:{generated.finish_reason}"
    if not generated.cited_chunk_ids:
        return "no_citations"
    if generated.invalid_citations:
        return "invalid_citations"
    if top_score < min_retrieval_score:
        return "low_retrieval"
    if contains_personal_data(query) or contains_personal_data(generated.answer):
        return "personal_data"
    return None
```

- [ ] **Step 4: Run.** `uv run pytest tests/test_guards.py -q` → 22 passed.

- [ ] **Step 5: Commit and push.**
```bash
git add services/weir
git commit -m "feat(weir): cache bypass rules, personal-data check, write-back eligibility"
git push
```

---

### Task 4: Weir embedder and image

**Files:**
- Modify: `services/weir/pyproject.toml` (add `"fastembed>=0.4"` and `"tokenizers>=0.19"` to dependencies), `services/weir/src/weir/settings.py`, `services/weir/Dockerfile`
- Create: `services/weir/src/weir/cache/embedder.py`
- Test: `services/weir/tests/test_embedder.py`

**Interfaces:**
- Produces:
  - `Embedder(model_name: str, cache_dir: str | None = None)` with `.embed(text) -> np.ndarray` (float32, (384,), unit norm), `.embed_many(texts) -> list[np.ndarray]` and `.count_tokens(text) -> int`
  - `Settings.embed_cache_dir: str | None`

- [ ] **Step 1: Failing test.** `services/weir/tests/test_embedder.py`:
```python
import numpy as np
import pytest

from weir.cache.embedder import Embedder


@pytest.fixture(scope="module")
def embedder():
    return Embedder("BAAI/bge-small-en-v1.5")


def test_single_and_batch_agree_and_are_unit_norm(embedder):
    one = embedder.embed("icu visiting hours")
    [batch] = embedder.embed_many(["icu visiting hours"])
    assert one.shape == (384,) and one.dtype == np.float32
    assert abs(float(np.linalg.norm(one)) - 1.0) < 1e-5
    assert float(one @ batch) == pytest.approx(1.0, abs=1e-5)


def test_paraphrase_closer_than_look_alike_topic_shift(embedder):
    a, b, c = embedder.embed_many(["when can i visit the icu?", "what are icu visiting hours?",
                                   "how much is car parking?"])
    assert float(a @ b) > float(a @ c)
    assert embedder.count_tokens("icu visiting hours") >= 3
```

- [ ] **Step 2: Add the dependencies and confirm failure.** Add the two dependencies, run `uv lock && uv sync`, then `uv run pytest tests/test_embedder.py -q` → `ModuleNotFoundError: weir.cache.embedder`.

- [ ] **Step 3: Implement.** `services/weir/src/weir/cache/embedder.py`:
```python
import numpy as np
from fastembed import TextEmbedding
from tokenizers import Tokenizer


class Embedder:
    """Local bge-small embeddings (free, CPU), the same model hospital-rag uses for retrieval."""

    dim = 384

    def __init__(self, model_name: str, cache_dir: str | None = None):
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self._tokenizer = Tokenizer.from_pretrained(model_name)

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        vectors = []
        for raw in self._model.embed(texts):
            v = np.asarray(raw, dtype=np.float32)
            vectors.append(v / np.linalg.norm(v))
        return vectors

    def embed(self, text: str) -> np.ndarray:
        return self.embed_many([text])[0]

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
```
In `settings.py`, add the field `embed_cache_dir: str | None = None`.

In `services/weir/Dockerfile`:
- Change the `ENV` block to also set `EMBED_CACHE_DIR=/models/fastembed` and `HF_HOME=/models/hf`.
- After `RUN uv sync --frozen --no-dev --no-install-project`, add:
```dockerfile
# Bake the embedding model and tokenizer so startup needs no download (same model as hospital-rag).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models/fastembed'); from tokenizers import Tokenizer; Tokenizer.from_pretrained('BAAI/bge-small-en-v1.5')"
```

- [ ] **Step 4: Run.** `uv run pytest -q` → all pass (55 + 20 + 22 + 2 = 99). `docker compose build weir` → succeeds.

- [ ] **Step 5: Commit and push.**
```bash
git add services/weir
git commit -m "feat(weir): local bge-small embedder baked into the image"
git push
```

---

### Task 5: Cache store

**Files:**
- Create: `services/weir/src/weir/cache/store.py`, `services/weir/tests/fakes.py`
- Test: `services/weir/tests/test_cache_store.py`

**Interfaces:**
- Produces:
  - `CacheEntry(id, namespace, kb_version, prompt_version, query_text, embedding, answer, sources: list[dict], source_ids: list[str], model, tokens_in, tokens_out, expires_at: datetime)`
  - `Candidate(id, query_text, answer, sources, model, tokens_in, tokens_out, similarity: float)`
  - `CacheStore(pool)` with:
    - `async lookup(namespace, kb_version, prompt_version, embedding, k) -> list[Candidate]` (sorted by similarity, descending)
    - `async insert(entry)`
    - `async increment_hits(entry_id)`
    - `async delete(*, namespace=None, source_id=None, entry_id=None) -> int` (exactly one selector, otherwise `ValueError`)
    - `async delete_expired() -> int`
  - `tests/fakes.py`: `unit(i)` (a one-hot 384-d vector) and `make_entry(**overrides) -> CacheEntry`. Later tasks add to this file.

- [ ] **Step 1: Test helpers and failing tests.** `services/weir/tests/fakes.py`:
```python
"""Test doubles shared by the cache, pipeline and API tests."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np

from weir.cache.store import CacheEntry


def unit(i: int) -> np.ndarray:
    v = np.zeros(384, dtype=np.float32)
    v[i] = 1.0
    return v


def make_entry(**over) -> CacheEntry:
    base = dict(id=uuid4(), namespace="weir-general/en/public", kb_version="v1", prompt_version="p1",
                query_text="when can i visit?", embedding=unit(0), answer="Answer.",
                sources=[{"id": "pub-a", "title": "Visiting"}], source_ids=["pub-a"], model="openai/gpt-oss-120b",
                tokens_in=1000, tokens_out=500, expires_at=datetime.now(UTC) + timedelta(hours=24))
    return CacheEntry(**{**base, **over})
```
`services/weir/tests/test_cache_store.py`:
```python
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from weir.cache.store import CacheStore
from weir.db import open_pool

from .fakes import make_entry, unit

pytestmark = pytest.mark.db
PUBLIC, STAFF = "weir-general/en/public", "weir-general/en/staff"


@pytest.fixture
async def store(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    yield CacheStore(pool)
    await pool.close()


async def test_insert_then_lookup_returns_best_first(store):
    near, far = make_entry(embedding=unit(0)), make_entry(embedding=unit(1), query_text="other")
    await store.insert(near)
    await store.insert(far)
    found = await store.lookup(PUBLIC, "v1", "p1", unit(0), 3)
    assert [c.id for c in found][0] == near.id
    assert found[0].similarity == pytest.approx(1.0) and found[0].sources == [{"id": "pub-a", "title": "Visiting"}]
    assert found[0].tokens_in == 1000 and found[0].model == "openai/gpt-oss-120b"


async def test_lookup_is_isolated_by_namespace(store):
    await store.insert(make_entry(namespace=STAFF))
    assert await store.lookup(PUBLIC, "v1", "p1", unit(0), 3) == []


async def test_lookup_filters_versions_and_expiry(store):
    await store.insert(make_entry(kb_version="v0"))
    await store.insert(make_entry(prompt_version="p0"))
    await store.insert(make_entry(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert await store.lookup(PUBLIC, "v1", "p1", unit(0), 3) == []


async def test_iterative_scan_fills_k_under_selective_filter(store):
    for i in range(40):  # many closer rows in another namespace
        await store.insert(make_entry(namespace=STAFF, embedding=unit(0)))
    for i in range(3):
        await store.insert(make_entry(embedding=unit(1 + i)))
    assert len(await store.lookup(PUBLIC, "v1", "p1", unit(0), 3)) == 3


async def test_increment_and_deletes(store, migrated_db_url):
    a = make_entry(source_ids=["pub-a", "pub-x"])
    b = make_entry(source_ids=["pub-b"])
    c = make_entry(namespace=STAFF, source_ids=["staff-c"])
    old = make_entry(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    for e in (a, b, c, old):
        await store.insert(e)
    await store.increment_hits(a.id)
    await store.increment_hits(a.id)
    with psycopg.connect(migrated_db_url) as conn:
        assert conn.execute("select hit_count from weir.cache_entries where id = %s", (a.id,)).fetchone()[0] == 2
    assert await store.delete_expired() == 1
    assert await store.delete(source_id="pub-x") == 1
    assert await store.delete(entry_id=b.id) == 1
    assert await store.delete(namespace=STAFF) == 1
    with pytest.raises(ValueError, match="exactly one"):
        await store.delete(namespace=PUBLIC, entry_id=b.id)
    with pytest.raises(ValueError, match="exactly one"):
        await store.delete()
```

- [ ] **Step 2: Confirm failure.** `uv run pytest tests/test_cache_store.py -q` → `ModuleNotFoundError: weir.cache.store`.

- [ ] **Step 3: Implement.** `services/weir/src/weir/cache/store.py`:
```python
"""weir.cache_entries reads and writes (main spec §6.2, §10)."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import numpy as np
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class CacheEntry:
    id: UUID
    namespace: str
    kb_version: str
    prompt_version: str
    query_text: str
    embedding: np.ndarray
    answer: str
    sources: list[dict]
    source_ids: list[str]
    model: str
    tokens_in: int
    tokens_out: int
    expires_at: datetime


@dataclass(frozen=True)
class Candidate:
    id: UUID
    query_text: str
    answer: str
    sources: list[dict]
    model: str
    tokens_in: int
    tokens_out: int
    similarity: float


DELETE_SQL = {
    "namespace": "delete from weir.cache_entries where namespace = %s",
    "source_id": "delete from weir.cache_entries where %s = any(source_ids)",
    "entry_id": "delete from weir.cache_entries where id = %s",
}


class CacheStore:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def lookup(self, namespace: str, kb_version: str, prompt_version: str,
                     embedding: np.ndarray, k: int) -> list[Candidate]:
        async with self._pool.connection() as conn, conn.transaction():
            # Filtered HNSW can under-return; iterative scan keeps going until k rows match.
            await conn.execute("set local hnsw.iterative_scan = relaxed_order")
            rows = await (await conn.execute(
                "select id, query_text, answer, sources, model, tokens_in, tokens_out,"
                " 1 - (embedding <=> %s) as similarity"
                " from weir.cache_entries"
                " where namespace = %s and kb_version = %s and prompt_version = %s and expires_at > now()"
                " order by embedding <=> %s limit %s",
                (embedding, namespace, kb_version, prompt_version, embedding, k),
            )).fetchall()
        found = [Candidate(r[0], r[1], r[2], r[3], r[4], r[5], r[6], float(r[7])) for r in rows]
        return sorted(found, key=lambda c: c.similarity, reverse=True)  # relaxed_order may be unordered

    async def insert(self, e: CacheEntry) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "insert into weir.cache_entries (id, namespace, kb_version, prompt_version, query_text, embedding,"
                " answer, sources, source_ids, model, tokens_in, tokens_out, expires_at)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (e.id, e.namespace, e.kb_version, e.prompt_version, e.query_text, e.embedding, e.answer,
                 Jsonb(e.sources), e.source_ids, e.model, e.tokens_in, e.tokens_out, e.expires_at),
            )

    async def increment_hits(self, entry_id: UUID) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("update weir.cache_entries set hit_count = hit_count + 1 where id = %s", (entry_id,))

    async def delete(self, *, namespace: str | None = None, source_id: str | None = None,
                     entry_id: UUID | None = None) -> int:
        given = [(k, v) for k, v in (("namespace", namespace), ("source_id", source_id), ("entry_id", entry_id))
                 if v is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of namespace, source_id, entry_id")
        column, value = given[0]
        async with self._pool.connection() as conn:
            return (await conn.execute(DELETE_SQL[column], (value,))).rowcount

    async def delete_expired(self) -> int:
        async with self._pool.connection() as conn:
            return (await conn.execute("delete from weir.cache_entries where expires_at <= now()")).rowcount
```

- [ ] **Step 4: Run.** `uv run pytest tests/test_cache_store.py -q` → 5 passed, then `uv run pytest -q` → all green.

- [ ] **Step 5: Commit and push.**
```bash
git add services/weir
git commit -m "feat(weir): pgvector cache store with namespace/version filters and deletes"
git push
```

---

### Task 6: Background jobs, version cache, RagClient.info

**Files:**
- Create: `services/weir/src/weir/background.py`, `services/weir/src/weir/cache/versions.py`
- Modify: `services/weir/src/weir/rag/adapter.py` (add `info()`)
- Test: `services/weir/tests/test_background.py`, `services/weir/tests/test_versions.py`, append to `services/weir/tests/test_adapter.py`

**Interfaces:**
- Produces:
  - `BackgroundQueue(name, max_queue=10_000)` with `.start()`, `.submit(job: Callable[[], Awaitable])`, `async .stop(timeout_s=5.0)` and the counters `.dropped`, `.failed`
  - `Periodic(fn, interval_s, name)` with `.start()`, `async .stop()` and the counters `.runs`, `.failed`. It runs `fn` immediately, then every `interval_s`.
  - `VersionCache(fetch, initial=None)` with `.get(namespace) -> tuple[str, str] | None` and `async .refresh()`. A failed refresh raises and keeps the old values.
  - `RagClient.info() -> dict[str, tuple[str, str]]`, raising `RagError`.

- [ ] **Step 1: Failing tests.** `services/weir/tests/test_background.py`:
```python
import asyncio

from weir.background import BackgroundQueue, Periodic


async def test_queue_runs_jobs_in_order():
    done = []
    q = BackgroundQueue("t")
    q.start()
    for i in range(3):
        q.submit(lambda i=i: _append(done, i))
    await q.stop()
    assert done == [0, 1, 2]


async def _append(target, value):
    target.append(value)


async def test_queue_counts_failures_and_continues():
    done = []

    async def boom():
        raise RuntimeError("db down")

    q = BackgroundQueue("t")
    q.start()
    q.submit(boom)
    q.submit(lambda: _append(done, "after"))
    await q.stop()
    assert q.failed == 1 and done == ["after"]


async def test_queue_full_drops():
    q = BackgroundQueue("t", max_queue=1)  # not started
    q.submit(lambda: _append([], 1))
    q.submit(lambda: _append([], 2))
    assert q.dropped == 1


async def test_periodic_runs_repeatedly_and_survives_errors():
    calls = []

    async def tick():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("flaky")

    p = Periodic(tick, 0.01, "t")
    p.start()
    await asyncio.sleep(0.08)
    await p.stop()
    assert len(calls) >= 3 and p.failed == 1 and p.runs == len(calls) - 1
```
`services/weir/tests/test_versions.py`:
```python
import pytest

from weir.cache.versions import VersionCache


async def test_refresh_replaces_versions():
    vc = VersionCache(fetch=_returns({"ns": ("v2", "p1")}), initial={"ns": ("v1", "p1")})
    assert vc.get("ns") == ("v1", "p1")
    await vc.refresh()
    assert vc.get("ns") == ("v2", "p1") and vc.get("other") is None


async def test_refresh_failure_keeps_old_versions():
    async def down():
        raise RuntimeError("rag down")

    vc = VersionCache(fetch=down, initial={"ns": ("v1", "p1")})
    with pytest.raises(RuntimeError):
        await vc.refresh()
    assert vc.get("ns") == ("v1", "p1")


def _returns(value):
    async def fetch():
        return value
    return fetch
```
Append to `services/weir/tests/test_adapter.py`:
```python
async def test_info_parses_versions():
    body = {"namespaces": {"ns": {"kb_version": "v1", "prompt_version": "p1"}}}
    assert await client(lambda r: httpx.Response(200, json=body)).info() == {"ns": ("v1", "p1")}


@pytest.mark.parametrize("response", [httpx.Response(500, text="x"), httpx.Response(200, json={"oops": 1})])
async def test_info_errors_are_rag_errors(response):
    with pytest.raises(RagError):
        await client(lambda r: response).info()
```

- [ ] **Step 2: Confirm failure.** `uv run pytest tests/test_background.py tests/test_versions.py tests/test_adapter.py -q` → import errors, and `AttributeError: info`.

- [ ] **Step 3: Implement.** `services/weir/src/weir/background.py`:
```python
"""Off-request-path work: a job queue (cache writes, hit counters) and periodic tasks
(version refresh, expired-entry cleanup). Failures are counted and logged, never raised."""
import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("weir.background")
Job = Callable[[], Awaitable[object]]


class BackgroundQueue:
    def __init__(self, name: str, max_queue: int = 10_000):
        self._name = name
        self._queue: asyncio.Queue[Job] = asyncio.Queue(max_queue)
        self._task: asyncio.Task | None = None
        self.dropped = 0
        self.failed = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def submit(self, job: Job) -> None:
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            self.dropped += 1
            log.warning("%s queue full; dropped a job", self._name)

    async def stop(self, timeout_s: float = 5.0) -> None:
        if self._task is None:
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._queue.join(), timeout_s)
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await job()
            except Exception:  # noqa: BLE001 - background work must never break requests
                self.failed += 1
                log.exception("%s job failed", self._name)
            finally:
                self._queue.task_done()


class Periodic:
    def __init__(self, fn: Job, interval_s: float, name: str):
        self._fn = fn
        self._interval_s = interval_s
        self._name = name
        self._task: asyncio.Task | None = None
        self.runs = 0
        self.failed = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self._fn()
                self.runs += 1
            except Exception:  # noqa: BLE001
                self.failed += 1
                log.exception("%s failed", self._name)
            await asyncio.sleep(self._interval_s)
```
`services/weir/src/weir/cache/versions.py`:
```python
from collections.abc import Awaitable, Callable

Versions = dict[str, tuple[str, str]]


class VersionCache:
    """Latest (kb_version, prompt_version) per namespace from hospital-rag /info, held in memory
    so a cache lookup never waits on the network (main spec §5.3)."""

    def __init__(self, fetch: Callable[[], Awaitable[Versions]] | None, initial: Versions | None = None):
        self._fetch = fetch
        self._versions: Versions = dict(initial or {})

    def get(self, namespace: str) -> tuple[str, str] | None:
        return self._versions.get(namespace)

    async def refresh(self) -> None:
        if self._fetch is None:
            return
        self._versions = dict(await self._fetch())  # on failure the exception propagates; old values stay
```
In `services/weir/src/weir/rag/adapter.py`, add to `RagClient`:
```python
    async def info(self) -> dict[str, tuple[str, str]]:
        try:
            response = await self._client.get("/info")
        except httpx.TimeoutException as e:
            raise RagError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise RagError("unavailable", str(e)) from e
        body = _json_or_none(response) if response.status_code == 200 else None
        try:
            return {ns: (v["kb_version"], v["prompt_version"]) for ns, v in body["namespaces"].items()}
        except (TypeError, KeyError, AttributeError) as e:
            raise RagError("bad_response", f"/info {response.status_code}: {response.text[:200]}") from e
```

- [ ] **Step 4: Run.** `uv run pytest -q` → all green (9 new tests).

- [ ] **Step 5: Commit and push.**
```bash
git add services/weir
git commit -m "feat(weir): background job queue, periodic tasks, kb/prompt version cache"
git push
```

---

### Task 7: Cache in the pipeline (switch the cache on)

**Files:**
- Modify: `services/weir/src/weir/pipeline.py`, `configs/weir.yaml` (`cache.enabled: true`), `services/weir/tests/fakes.py`
- Rewrite: `services/weir/tests/test_pipeline.py`; update the `app_client` helper in `services/weir/tests/test_api.py` (Step 3)

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces:
  - `CacheDeps(embedder, versions, store, writer, lexicon, rules)`
  - `Pipeline(cfg, rag, prices, log, cache: CacheDeps, now=...)`. **The `cache` argument is now required.**
  - Fakes: `ListSink`, `FakeEmbedder(aliases=None)` (with `.fail`), `FakeStore(now)` (with `.fail_lookup`, `.entries`, `.hits`), `InlineQueue` (with `async .drain()`)
- Behaviour (addendum §2, §6):
  - A **hit** returns the stored answer and sources with `route="none"` and `model_calls=0`. `cost_usd` is the embedding cost, `counterfactual_cost_usd` is the stored tokens at the large model's price, `cache_entry_id` and `similarity` are logged, and a `hit_count` increment is queued.
  - A **miss** runs the Phase 1 path. If `store_block_reason` returns `None`, it queues an insert and logs the new entry's ID in `cache_entry_id`.
  - A **bypass** logs `bypass_reason`, which is one of the Task 3 reasons or `no_version` / `error`.

- [ ] **Step 1: Extend the fakes.** Append to `services/weir/tests/fakes.py`:
```python
import hashlib  # noqa: E402

from weir.cache.store import Candidate  # noqa: E402
from weir.text import normalize  # noqa: E402


class ListSink:
    def __init__(self):
        self.rows = []

    def submit(self, row):
        self.rows.append(row)


class FakeEmbedder:
    """Deterministic pseudo-random unit vectors per text; `aliases` make two texts embed identically."""

    def __init__(self, aliases: dict[str, str] | None = None):
        self.aliases = {normalize(k): normalize(v) for k, v in (aliases or {}).items()}
        self.fail = False

    def embed(self, text: str) -> np.ndarray:
        if self.fail:
            raise RuntimeError("embedder down")
        text = self.aliases.get(text, text)
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).standard_normal(384).astype(np.float32)
        return v / np.linalg.norm(v)

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeStore:
    def __init__(self, now):
        self._now = now
        self.entries = []
        self.hits = {}
        self.fail_lookup = False

    async def lookup(self, namespace, kb_version, prompt_version, embedding, k):
        if self.fail_lookup:
            raise RuntimeError("db down")
        found = [Candidate(e.id, e.query_text, e.answer, e.sources, e.model, e.tokens_in, e.tokens_out,
                           float(e.embedding @ embedding))
                 for e in self.entries
                 if (e.namespace, e.kb_version, e.prompt_version) == (namespace, kb_version, prompt_version)
                 and e.expires_at > self._now()]
        return sorted(found, key=lambda c: c.similarity, reverse=True)[:k]

    async def insert(self, entry):
        self.entries.append(entry)

    async def increment_hits(self, entry_id):
        self.hits[entry_id] = self.hits.get(entry_id, 0) + 1

    async def delete(self, *, namespace=None, source_id=None, entry_id=None):
        before = len(self.entries)
        self.entries = [e for e in self.entries if not (
            e.namespace == namespace or source_id in e.source_ids or e.id == entry_id)]
        return before - len(self.entries)


class InlineQueue:
    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)

    async def drain(self):
        while self.jobs:
            await self.jobs.pop(0)()
```

- [ ] **Step 2: Rewrite the pipeline tests (failing).** Replace `services/weir/tests/test_pipeline.py` with:
```python
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from weir.cache.entities import Lexicon
from weir.cache.guards import BypassRules
from weir.cache.versions import VersionCache
from weir.config import WeirConfig, load_config
from weir.llm.pricing import PriceTable
from weir.pipeline import CacheDeps, Pipeline, PipelineError, QueryOptions, QueryRequest
from weir.rag.adapter import RagClient

from .conftest import CONFIGS
from .fakes import FakeEmbedder, FakeStore, InlineQueue, ListSink

PUBLIC = "weir-general/en/public"
STAFF = "weir-general/en/staff"
CHUNKS = [
    {"id": "pub-a#0", "doc_id": "pub-a", "title": "Visiting", "text": "t", "score": 0.9, "token_count": 3},
    {"id": "pub-a#1", "doc_id": "pub-a", "title": "Visiting", "text": "t", "score": 0.8, "token_count": 3},
    {"id": "pub-b#0", "doc_id": "pub-b", "title": "ICU", "text": "t", "score": 0.7, "token_count": 3},
]
VERSIONS = {PUBLIC: ("v1", "p1"), STAFF: ("v1", "p1")}
FIXED_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def fake_rag(generate_response=None, chunks=CHUNKS, seen=None, calls=None, top_score=0.9, cited=None, answer="Answer."):
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
        if generate_response is not None:
            return generate_response
        has = bool(body["chunks"])
        ids = (["pub-a#1", "pub-b#0", "pub-a#0"] if cited is None else cited) if has else []
        return httpx.Response(200, json={
            "answer": answer if has else "Sorry, not found.", "cited_chunk_ids": ids, "invalid_citations": 0,
            "not_found": not has, "finish_reason": "stop" if has else "skipped",
            "tokens_in": 1000 if has else 0, "tokens_out": 500 if has else 0,
            "model": body["model"], "prompt_version": "p1", "latency_ms": 7})
    return RagClient("http://rag", 5, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag"))


@dataclass
class Harness:
    p: Pipeline
    sink: ListSink
    store: FakeStore
    writer: InlineQueue
    embedder: FakeEmbedder
    cfg: WeirConfig


def harness(rag, overlay=None, versions=VERSIONS, aliases=None, **config_overrides) -> Harness:
    cfg = load_config(CONFIGS / "weir.yaml", overlay)
    for path, value in config_overrides.items():
        section, key = path.split("__")
        setattr(getattr(cfg, section), key, value)
    sink, store, writer, embedder = ListSink(), FakeStore(now=lambda: FIXED_NOW), InlineQueue(), FakeEmbedder(aliases)
    cache = CacheDeps(embedder=embedder, versions=VersionCache(fetch=None, initial=versions), store=store,
                      writer=writer, lexicon=Lexicon.from_yaml(CONFIGS / "entities.yaml"), rules=BypassRules(cfg.bypass))
    p = Pipeline(cfg, rag, PriceTable.from_yaml(CONFIGS / "prices.yaml"), sink, cache, now=lambda: FIXED_NOW)
    return Harness(p, sink, store, writer, embedder, cfg)


def ask(query, namespace=PUBLIC, **kwargs):
    return QueryRequest(query=query, namespace=namespace, **kwargs)


# --- miss / hit -------------------------------------------------------------------------------

async def test_first_ask_is_a_miss_with_cost_log_and_store():
    h = harness(fake_rag())
    resp = await h.p.handle(ask("  When can I visit? "))
    assert resp.answer == "Answer." and [s.id for s in resp.sources] == ["pub-a", "pub-b"]
    assert resp.meta.cache_status == "miss" and resp.meta.route == "large"
    [row] = h.sink.rows
    assert row.bypass_reason is None and row.status == "ok" and row.embed_tokens == 4
    assert row.cost_usd == Decimal("0.00045") == row.counterfactual_cost_usd
    assert row.query_text == "When can I visit?" and row.config_label == "dev"
    await h.writer.drain()
    [entry] = h.store.entries
    assert row.cache_entry_id == entry.id and entry.query_text == "when can i visit?"
    assert entry.source_ids == ["pub-a", "pub-b"] and (entry.tokens_in, entry.tokens_out) == (1000, 500)
    assert entry.kb_version == "v1" and entry.prompt_version == "p1"


async def test_identical_question_hits_without_calling_rag():
    calls = []
    h = harness(fake_rag(calls=calls))
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    resp = await h.p.handle(ask("when can i VISIT?"))
    assert resp.meta.cache_status == "hit" and resp.meta.route == "none" and resp.answer == "Answer."
    assert resp.meta.similarity == pytest.approx(1.0) and [s.id for s in resp.sources] == ["pub-a", "pub-b"]
    assert calls.count("/retrieve") == 1 and calls.count("/generate") == 1
    hit = h.sink.rows[1]
    assert hit.cost_usd == 0 and hit.counterfactual_cost_usd == Decimal("0.00045")
    assert hit.model_calls == 0 and hit.cache_entry_id == h.store.entries[0].id
    await h.writer.drain()
    assert h.store.hits == {h.store.entries[0].id: 1}


async def test_paraphrase_with_same_entities_hits():
    h = harness(fake_rag(), aliases={"what are the visiting hours?": "when can i visit?"})
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    assert (await h.p.handle(ask("What are the visiting hours?"))).meta.cache_status == "hit"


async def test_look_alike_with_different_entities_misses():
    calls = []
    h = harness(fake_rag(calls=calls),
                aliases={"what are the icu visiting hours?": "what are the general ward visiting hours?"})
    await h.p.handle(ask("What are the general ward visiting hours?"))
    await h.writer.drain()
    resp = await h.p.handle(ask("What are the ICU visiting hours?"))
    assert resp.meta.cache_status == "miss" and calls.count("/generate") == 2
    assert h.sink.rows[1].similarity == pytest.approx(1.0)  # embedding said "same"; the guard said no


async def test_below_threshold_misses_and_logs_similarity():
    h = harness(fake_rag())
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    resp = await h.p.handle(ask("How much is parking?"))
    assert resp.meta.cache_status == "miss" and h.sink.rows[1].similarity < 0.5


async def test_version_change_misses():
    h = harness(fake_rag())
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    h.p._cache.versions = VersionCache(fetch=None, initial={PUBLIC: ("v2", "p1")})
    assert (await h.p.handle(ask("When can I visit?"))).meta.cache_status == "miss"


async def test_sensitive_namespace_hit_logs_no_query_text():
    h = harness(fake_rag())
    await h.p.handle(ask("How do I register a patient?", namespace=STAFF))
    await h.writer.drain()
    await h.p.handle(ask("How do I register a patient?", namespace=STAFF))
    assert [r.cache_status for r in h.sink.rows] == ["miss", "hit"]
    assert all(r.query_text is None and len(r.query_hash) == 64 for r in h.sink.rows)


# --- bypass -----------------------------------------------------------------------------------

@pytest.mark.parametrize(("request_kwargs", "overrides", "reason"), [
    ({"personalized": True}, {}, "personalized"),
    ({"options": QueryOptions(bypass_cache=True)}, {}, "request_option"),
    ({}, {"kill_switch__disable_cache": True}, "kill_switch"),
    ({}, {"cache__enabled": False}, "cache_disabled"),
])
async def test_bypass_reasons_from_request_and_config(request_kwargs, overrides, reason):
    h = harness(fake_rag(), **overrides)
    resp = await h.p.handle(ask("When can I visit?", **request_kwargs))
    assert resp.meta.cache_status == "bypass" and h.sink.rows[0].bypass_reason == reason
    await h.writer.drain()
    assert h.store.entries == []


@pytest.mark.parametrize(("query", "kwargs", "reason"), [
    ("What dosage of paracetamol is safe?", {}, "clinical"),
    ("Is the pharmacy open now?", {}, "time_sensitive"),
    ("what about weekends?", {"session_id": "s1"}, "followup"),
])
async def test_bypass_reasons_from_question_text(query, kwargs, reason):
    h = harness(fake_rag())
    await h.p.handle(ask(query, **kwargs))
    assert h.sink.rows[0].bypass_reason == reason


async def test_namespace_disabled():
    h = harness(fake_rag())
    h.cfg.namespaces[PUBLIC].cache.enabled = False
    await h.p.handle(ask("When can I visit?"))
    assert h.sink.rows[0].bypass_reason == "namespace_disabled"


async def test_no_version_bypasses_cache():
    h = harness(fake_rag(), versions={})
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and h.sink.rows[0].bypass_reason == "no_version"


async def test_embedder_failure_bypasses():
    h = harness(fake_rag())
    h.embedder.fail = True
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and h.sink.rows[0].bypass_reason == "error"


async def test_lookup_failure_bypasses():
    h = harness(fake_rag())
    h.store.fail_lookup = True
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and h.sink.rows[0].bypass_reason == "error"


# --- write-back eligibility -------------------------------------------------------------------

@pytest.mark.parametrize("rag_kwargs", [
    {"chunks": []},                       # not found
    {"cited": []},                        # no citations
    {"top_score": 0.1},                   # weak retrieval
    {"answer": "Call 98765 43210."},      # personal data
])
async def test_ineligible_answers_are_not_stored(rag_kwargs):
    h = harness(fake_rag(**rag_kwargs))
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    assert h.store.entries == [] and h.sink.rows[0].cache_entry_id is None


# --- Phase 1 behaviour kept -------------------------------------------------------------------

async def test_force_small_is_cheaper_than_counterfactual():
    seen = []
    h = harness(fake_rag(seen=seen))
    resp = await h.p.handle(ask("q", options=QueryOptions(force_model="small")))
    assert seen[0]["model"] == "openai/gpt-oss-20b" and resp.meta.route == "small"
    assert h.sink.rows[0].cost_usd == Decimal("0.000225") and h.sink.rows[0].counterfactual_cost_usd == Decimal("0.00045")


async def test_kill_switch_force_large_beats_force_model():
    seen = []
    h = harness(fake_rag(seen=seen), overlay=CONFIGS / "ablations" / "baseline.yaml")
    resp = await h.p.handle(ask("q", options=QueryOptions(force_model="small")))
    assert resp.meta.route == "large" and seen[0]["model"] == "openai/gpt-oss-120b"
    assert h.sink.rows[0].bypass_reason == "cache_disabled"


async def test_no_chunks_returns_not_found_answer():
    h = harness(fake_rag(chunks=[]))
    resp = await h.p.handle(ask("q"))
    assert resp.sources == [] and resp.answer == "Sorry, not found."
    assert h.sink.rows[0].model_calls == 0 and h.sink.rows[0].cost_usd == 0


async def test_rate_limited_generate_raises_503_and_logs_error():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    h = harness(fake_rag(generate_response=limited))
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("q"))
    assert exc.value.status_code == 503 and exc.value.retry_after == 12.0
    assert exc.value.request_id == str(h.sink.rows[0].request_id)
    assert h.sink.rows[0].status == "error" and "rate_limited" in h.sink.rows[0].error_detail


async def test_timeout_maps_to_504_and_status_timeout():
    h = harness(fake_rag(generate_response=httpx.Response(504, json={"error": "timeout"})))
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("q"))
    assert exc.value.status_code == 504 and h.sink.rows[0].status == "timeout"


class ExplodingRag:
    async def retrieve(self, *args):
        raise RuntimeError("boom")


async def test_unexpected_error_returns_500_with_request_id_and_logs():
    h = harness(ExplodingRag())
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("q"))
    assert exc.value.status_code == 500 and exc.value.error == "internal"
    [row] = h.sink.rows
    assert row.status == "error" and row.error_detail == "internal: RuntimeError"


def test_blank_query_rejected():
    with pytest.raises(ValueError):
        QueryRequest(query="   ", namespace=PUBLIC)
```

- [ ] **Step 3: Point the API tests at the harness.** In `services/weir/tests/test_api.py`, replace the import line `from .test_pipeline import PUBLIC, STAFF, fake_rag, pipeline` with `from .test_pipeline import PUBLIC, STAFF, fake_rag, harness`, and replace the first two lines of `app_client`:
```python
def app_client(rag=None, health_ok=True):
    h = harness(rag or fake_rag())
    p, sink = h.p, h.sink
```
(The rest of `app_client` stays as is. Task 8 rewrites this file.)

- [ ] **Step 4: Confirm failure.** `uv run pytest tests/test_pipeline.py -q` → `ImportError: cannot import name 'CacheDeps'`.

- [ ] **Step 5: Implement.** In `services/weir/src/weir/pipeline.py`:
- Keep the request/response models, `ERROR_STATUS`, `PipelineError`, `_ms` and `_sources` unchanged.
- Add these imports:
```python
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from .cache.entities import Lexicon
from .cache.guards import BypassRules, bypass_reason, store_block_reason
from .cache.store import CacheEntry, Candidate
from .cache.versions import VersionCache
from .text import normalize, query_hash  # replaces the old `from .text import query_hash`

log = logging.getLogger("weir.pipeline")
```
- Update the module docstring:
```python
"""Request pipeline (main spec §5.3, Phase 2 addendum §2).

bypass rules → embed → cache lookup → entity guard → HIT: replay the stored answer
                                                    → MISS/BYPASS: retrieve → generate → store if eligible
Phase 3 replaces _choose_tier with the router.
"""
```
- Add `CacheDeps`, and replace the `Pipeline` class with:
```python
@dataclass
class CacheDeps:
    embedder: Any          # .embed(text) -> np.ndarray, .count_tokens(text) -> int
    versions: VersionCache
    store: Any             # CacheStore or a test double
    writer: Any            # .submit(job)
    lexicon: Lexicon
    rules: BypassRules


class Pipeline:
    def __init__(self, cfg: WeirConfig, rag: RagClient, prices: PriceTable, log: LogSink, cache: CacheDeps,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._cfg = cfg
        self._rag = rag
        self._prices = prices
        self._log = log
        self._cache = cache
        self._now = now

    async def handle(self, req: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        now = self._now()
        today = now.date()
        normalized = normalize(req.query)
        row = RequestLogRow(
            request_id=uuid4(), ts=now, namespace=req.namespace,
            cache_status="bypass", route="none", status="ok", latency_total_ms=0,
            query_hash=query_hash(req.query),
            query_text=None if self._cfg.is_sensitive(req.namespace) else req.query,
            config_label=self._cfg.config_label,
        )
        reason = bypass_reason(query=req.query, namespace=req.namespace, session_id=req.session_id,
                               personalized=req.personalized, bypass_cache=req.options.bypass_cache,
                               cfg=self._cfg, rules=self._cache.rules)
        versions = None
        if reason is None:
            versions = self._cache.versions.get(req.namespace)
            if versions is None:
                reason = "no_version"
        vector = None
        if reason is None:
            try:
                hit, vector = await self._lookup(req.namespace, normalized, versions, row)
            except Exception:  # noqa: BLE001 - a cache outage must never become a user outage
                log.exception("cache lookup failed; bypassing the cache")
                reason = "error"
            else:
                if hit is not None:
                    return self._serve_hit(hit, row, started, today)
                row.cache_status = "miss"
        row.bypass_reason = reason

        try:
            t = time.perf_counter()
            retrieved = await self._rag.retrieve(req.query, req.namespace, self._cfg.rag.retrieve_k)
            row.latency_retrieval_ms = _ms(t)
            row.retrieval_top_score = retrieved.top_score
            tier = self._choose_tier(req)
            model = self._cfg.model_for(tier)
            row.route = tier
            t = time.perf_counter()
            generated = await self._rag.generate(req.query, req.namespace, retrieved.chunks, model)
            row.latency_llm_ms = _ms(t)
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

        row.model = generated.model
        row.model_calls = 0 if generated.finish_reason == "skipped" else 1
        row.tokens_in, row.tokens_out = generated.tokens_in, generated.tokens_out
        row.cost_usd = (self._prices.cost(model, generated.tokens_in, generated.tokens_out, today)
                        + self._embed_cost(row, today))
        row.counterfactual_cost_usd = self._prices.cost(
            self._cfg.router.large_model, generated.tokens_in, generated.tokens_out, today)
        row.answer_len = len(generated.answer)
        sources = _sources(retrieved.chunks, generated.cited_chunk_ids)
        if row.cache_status == "miss":
            row.cache_entry_id = self._maybe_store(req, normalized, vector, versions, retrieved, generated,
                                                   sources, now)
        row.latency_total_ms = _ms(started)
        self._log.submit(row)

        return QueryResponse(
            answer=generated.answer, sources=sources,
            meta=QueryMeta(request_id=str(row.request_id), cache_status=row.cache_status,
                           similarity=row.similarity, route=row.route, escalated=False, model=row.model,
                           latency_ms=row.latency_total_ms, cost_usd=float(row.cost_usd)),
        )

    async def _lookup(self, namespace: str, normalized: str, versions: tuple[str, str],
                      row: RequestLogRow) -> tuple[Candidate | None, Any]:
        kb_version, prompt_version = versions
        t = time.perf_counter()
        vector = await asyncio.to_thread(self._cache.embedder.embed, normalized)
        row.latency_embed_ms = _ms(t)
        row.embed_tokens = self._cache.embedder.count_tokens(normalized)
        t = time.perf_counter()
        candidates = await self._cache.store.lookup(namespace, kb_version, prompt_version, vector,
                                                    self._cfg.cache.candidates)
        row.latency_cache_ms = _ms(t)
        if candidates:
            row.similarity = candidates[0].similarity
        wanted = self._cache.lexicon.extract(normalized)
        for candidate in candidates:  # best first
            if candidate.similarity < self._cfg.cache.threshold:
                break
            if self._cache.lexicon.extract(candidate.query_text) == wanted:
                return candidate, vector
        return None, vector

    def _serve_hit(self, hit: Candidate, row: RequestLogRow, started: float, today) -> QueryResponse:
        row.cache_status = "hit"
        row.similarity = hit.similarity
        row.cache_entry_id = hit.id
        row.route = "none"
        row.model = hit.model
        row.model_calls = 0
        row.cost_usd = self._embed_cost(row, today)
        row.counterfactual_cost_usd = self._prices.cost(self._cfg.router.large_model, hit.tokens_in,
                                                        hit.tokens_out, today)
        row.answer_len = len(hit.answer)
        row.latency_total_ms = _ms(started)
        store, entry_id = self._cache.store, hit.id
        self._cache.writer.submit(lambda: store.increment_hits(entry_id))
        self._log.submit(row)
        return QueryResponse(
            answer=hit.answer, sources=[Source(**s) for s in hit.sources],
            meta=QueryMeta(request_id=str(row.request_id), cache_status="hit", similarity=hit.similarity,
                           route="none", escalated=False, model=hit.model, latency_ms=row.latency_total_ms,
                           cost_usd=float(row.cost_usd)),
        )

    def _maybe_store(self, req, normalized, vector, versions, retrieved, generated, sources, now) -> UUID | None:
        block = store_block_reason(generated=generated, top_score=retrieved.top_score, query=req.query,
                                   min_retrieval_score=self._cfg.cache.min_retrieval_score)
        if block is not None:
            return None
        entry = CacheEntry(
            id=uuid4(), namespace=req.namespace,
            kb_version=retrieved.kb_version or versions[0], prompt_version=generated.prompt_version,
            query_text=normalized, embedding=vector, answer=generated.answer,
            sources=[s.model_dump() for s in sources], source_ids=[s.id for s in sources],
            model=generated.model, tokens_in=generated.tokens_in, tokens_out=generated.tokens_out,
            expires_at=now + timedelta(hours=self._cfg.ttl_hours_for(req.namespace)),
        )
        store = self._cache.store
        self._cache.writer.submit(lambda: store.insert(entry))
        return entry.id

    def _embed_cost(self, row: RequestLogRow, today) -> Decimal:
        if row.embed_tokens is None:
            return Decimal(0)
        return self._prices.cost(self._cfg.cache.embed_model, row.embed_tokens, 0, today)

    def _choose_tier(self, req: QueryRequest) -> Tier:
        if self._cfg.kill_switch.force_large:
            return "large"
        return req.options.force_model or "large"
```
- Also add `from .config import WeirConfig` if it isn't already imported, and delete the old `_bypass_reason` method.
- Set `cache.enabled: true` in `configs/weir.yaml` and change its comment to `# Phase 2: on (addendum §5)`.

- [ ] **Step 6: Run.** `uv run pytest -q`. Expected: all green. The new pipeline tests number 29, and the existing API tests pass through the harness.

- [ ] **Step 7: Commit and push.**
```bash
git add configs/weir.yaml services/weir
git commit -m "feat(weir): semantic cache in the request pipeline (hit, miss, bypass, write-back)"
git push
```

---

### Task 8: Feedback and purge APIs, app wiring, live smoke test

**Files:**
- Create: `services/weir/src/weir/admin.py`
- Modify: `services/weir/src/weir/main.py`, `services/weir/tests/fakes.py` (add `FakeAdmin`), `docs/progress.md`
- Rewrite: `services/weir/tests/test_api.py`
- Test: `services/weir/tests/test_admin.py`

**Interfaces:**
- Produces:
  - `RequestRef(namespace: str, cache_entry_id: UUID | None)`
  - `AdminService(pool, store)` with:
    - `async find_request(request_id) -> RequestRef | None`
    - `async add_feedback(request_id, rating, comment)`
    - `async evict(entry_id) -> bool`
    - `async purge(*, namespace=None, source_id=None, entry_id=None) -> int`
  - `AppDeps(pipeline, tenants, config, health, admin, feedback_lookup_attempts=5, feedback_lookup_delay_s=0.2)`
- HTTP:
  - `POST /v1/feedback` returns 200 `{"evicted": bool}`. 401 for no or wrong key. 404 for an unknown request ID or another tenant's request. 422 for an invalid body.
  - `DELETE /v1/cache?namespace=|source_id=|entry_id=` returns 200 `{"deleted": n}`. 401 for no key. 403 for a non-admin key. 422 unless exactly one selector is given, or if the ID isn't a valid UUID.

- [ ] **Step 1: Failing tests.** Append to `services/weir/tests/fakes.py`:
```python
from weir.admin import RequestRef  # noqa: E402


class FakeAdmin:
    def __init__(self, requests=None, appear_after=0):
        self.requests = dict(requests or {})
        self.appear_after = appear_after
        self.lookups = 0
        self.feedback, self.evicted, self.purged = [], [], []

    async def find_request(self, request_id):
        self.lookups += 1
        if self.lookups <= self.appear_after:
            return None
        return self.requests.get(request_id)

    async def add_feedback(self, request_id, rating, comment):
        self.feedback.append((request_id, rating, comment))

    async def evict(self, entry_id):
        self.evicted.append(entry_id)
        return True

    async def purge(self, **selector):
        self.purged.append({k: v for k, v in selector.items() if v is not None})
        return 3
```
Replace `services/weir/tests/test_api.py` with:
```python
from uuid import uuid4

import httpx
import pytest

from weir.admin import RequestRef
from weir.auth import TenantRegistry
from weir.config import load_config
from weir.main import AppDeps, create_app

from .conftest import CONFIGS
from .fakes import FakeAdmin
from .test_pipeline import PUBLIC, STAFF, fake_rag, harness

ENV = {"WEIR_KEY_PUBLIC": "pub-key", "WEIR_KEY_STAFF": "staff-key", "WEIR_KEY_ADMIN": "admin-key"}
PUB = {"X-API-Key": "pub-key"}
ADMIN = {"X-API-Key": "admin-key"}


def app_client(rag=None, health_ok=True, admin=None):
    h = harness(rag or fake_rag())

    async def health():
        return {"db": health_ok, "rag": True}

    deps = AppDeps(h.p, TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", ENV), load_config(CONFIGS / "weir.yaml"),
                   health, admin or FakeAdmin(), feedback_lookup_delay_s=0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://t")
    return client, h.sink


async def test_query_ok_sets_request_id_header():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == r.json()["meta"]["request_id"] == str(sink.rows[0].request_id)


async def test_missing_key_401():
    client, sink = app_client()
    async with client:
        r1 = await client.post("/v1/query", json={"query": "hi", "namespace": PUBLIC})
        r2 = await client.post("/v1/query", headers={"X-API-Key": "bad"}, json={"query": "hi", "namespace": PUBLIC})
    assert r1.status_code == r2.status_code == 401 and sink.rows == []


async def test_wrong_namespace_403():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "hi", "namespace": STAFF})
    assert r.status_code == 403 and sink.rows == []


async def test_blank_query_422():
    client, _ = app_client()
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "  ", "namespace": PUBLIC})
    assert r.status_code == 422


async def test_rate_limited_generate_returns_503_with_request_id():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    client, sink = app_client(rag=fake_rag(generate_response=limited))
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 503 and r.headers["Retry-After"] == "12"
    assert r.json() == {"error": "rate_limited", "request_id": str(sink.rows[0].request_id)}


@pytest.mark.parametrize(("ok", "status"), [(True, 200), (False, 503)])
async def test_healthz(ok, status):
    client, _ = app_client(health_ok=ok)
    async with client:
        r = await client.get("/healthz")
    assert r.status_code == status and r.json()["checks"]["db"] is ok


async def test_feedback_negative_evicts_entry():
    rid, entry = uuid4(), uuid4()
    admin = FakeAdmin({rid: RequestRef(PUBLIC, entry)})
    client, _ = app_client(admin=admin)
    async with client:
        r = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(rid), "rating": -1, "comment": "wrong"})
    assert r.status_code == 200 and r.json() == {"evicted": True}
    assert admin.evicted == [entry] and admin.feedback == [(rid, -1, "wrong")]


async def test_feedback_positive_does_not_evict():
    rid = uuid4()
    admin = FakeAdmin({rid: RequestRef(PUBLIC, uuid4())})
    client, _ = app_client(admin=admin)
    async with client:
        r = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(rid), "rating": 1})
    assert r.json() == {"evicted": False} and admin.evicted == []


async def test_feedback_waits_for_log_row():
    rid = uuid4()
    admin = FakeAdmin({rid: RequestRef(PUBLIC, None)}, appear_after=2)
    client, _ = app_client(admin=admin)
    async with client:
        r = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(rid), "rating": 1})
    assert r.status_code == 200 and admin.lookups == 3


async def test_feedback_unknown_or_other_tenant_404():
    staff_rid = uuid4()
    admin = FakeAdmin({staff_rid: RequestRef(STAFF, uuid4())})
    client, _ = app_client(admin=admin)
    async with client:
        unknown = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(uuid4()), "rating": -1})
        other = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(staff_rid), "rating": -1})
        nokey = await client.post("/v1/feedback", json={"request_id": str(staff_rid), "rating": -1})
        bad = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(staff_rid), "rating": 5})
    assert unknown.status_code == other.status_code == 404 and admin.evicted == [] and admin.feedback == []
    assert nokey.status_code == 401 and bad.status_code == 422


async def test_purge_requires_admin():
    client, _ = app_client()
    async with client:
        r1 = await client.delete("/v1/cache", params={"namespace": PUBLIC})
        r2 = await client.delete("/v1/cache", headers=PUB, params={"namespace": PUBLIC})
    assert r1.status_code == 401 and r2.status_code == 403


async def test_purge_needs_exactly_one_valid_selector():
    admin = FakeAdmin()
    client, _ = app_client(admin=admin)
    async with client:
        none = await client.delete("/v1/cache", headers=ADMIN)
        two = await client.delete("/v1/cache", headers=ADMIN, params={"namespace": PUBLIC, "source_id": "pub-a"})
        bad_id = await client.delete("/v1/cache", headers=ADMIN, params={"entry_id": "nope"})
        ok = await client.delete("/v1/cache", headers=ADMIN, params={"source_id": "pub-a"})
    assert none.status_code == two.status_code == bad_id.status_code == 422
    assert ok.status_code == 200 and ok.json() == {"deleted": 3} and admin.purged == [{"source_id": "pub-a"}]
```
`services/weir/tests/test_admin.py`:
```python
from dataclasses import astuple
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from weir.admin import AdminService
from weir.cache.store import CacheStore
from weir.db import open_pool
from weir.metrics.logger import INSERT_SQL, RequestLogRow

from .fakes import make_entry

pytestmark = pytest.mark.db


async def test_admin_service_roundtrip(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        store = CacheStore(pool)
        admin = AdminService(pool, store)
        entry = make_entry()
        await store.insert(entry)
        row = RequestLogRow(request_id=uuid4(), ts=datetime.now(UTC), namespace="weir-general/en/public",
                            cache_status="hit", route="none", status="ok", latency_total_ms=5,
                            query_hash="h" * 64, cache_entry_id=entry.id)
        async with pool.connection() as conn:
            await conn.execute(INSERT_SQL, astuple(row))
        ref = await admin.find_request(row.request_id)
        assert ref.namespace == "weir-general/en/public" and ref.cache_entry_id == entry.id
        assert await admin.find_request(uuid4()) is None
        await admin.add_feedback(row.request_id, -1, "wrong")
        await admin.add_feedback(uuid4(), 1, None)  # no FK any more (migration 002)
        assert await admin.evict(entry.id) is True and await admin.evict(entry.id) is False
        assert await admin.purge(namespace="weir-general/en/public") == 0
    finally:
        await pool.close()
    with psycopg.connect(migrated_db_url) as conn:
        assert conn.execute("select count(*) from weir.feedback").fetchone()[0] == 2
```

- [ ] **Step 2: Confirm failure.** `uv run pytest tests/test_api.py tests/test_admin.py -q` → `ModuleNotFoundError: weir.admin`.

- [ ] **Step 3: Implement.** `services/weir/src/weir/admin.py`:
```python
"""Feedback and cache administration (Phase 2 addendum §6)."""
from dataclasses import dataclass
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from .cache.store import CacheStore


@dataclass(frozen=True)
class RequestRef:
    namespace: str
    cache_entry_id: UUID | None


class AdminService:
    def __init__(self, pool: AsyncConnectionPool, store: CacheStore):
        self._pool = pool
        self._store = store

    async def find_request(self, request_id: UUID) -> RequestRef | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "select namespace, cache_entry_id from weir.request_log where request_id = %s", (request_id,)
            )).fetchone()
        return RequestRef(row[0], row[1]) if row else None

    async def add_feedback(self, request_id: UUID, rating: int, comment: str | None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("insert into weir.feedback (request_id, rating, comment) values (%s, %s, %s)",
                               (request_id, rating, comment))

    async def evict(self, entry_id: UUID) -> bool:
        return await self._store.delete(entry_id=entry_id) > 0

    async def purge(self, *, namespace: str | None = None, source_id: str | None = None,
                    entry_id: UUID | None = None) -> int:
        return await self._store.delete(namespace=namespace, source_id=source_id, entry_id=entry_id)
```
In `services/weir/src/weir/main.py`:
- Add imports:
```python
import asyncio
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .admin import AdminService
from .background import BackgroundQueue, Periodic
from .cache.embedder import Embedder
from .cache.entities import Lexicon
from .cache.guards import BypassRules
from .cache.store import CacheStore
from .cache.versions import VersionCache
from .pipeline import CacheDeps
```
- Extend `AppDeps`:
```python
@dataclass
class AppDeps:
    pipeline: Pipeline
    tenants: TenantRegistry
    config: WeirConfig
    health: Callable[[], Awaitable[dict[str, bool]]]
    admin: Any                      # AdminService or a test double
    feedback_lookup_attempts: int = 5
    feedback_lookup_delay_s: float = 0.2


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)
```
- In the lifespan, replace everything from `prices.price_for` up to and including `app.state.deps = ...` and the `finally` block with:
```python
        for model in (cfg.router.small_model, cfg.router.large_model, cfg.cache.embed_model):
            prices.price_for(model, today)  # fail fast: every model we may bill must be priced
        pool = await open_pool(s.database_url)
        await sync_prices(pool, prices)
        writer = LogWriter(pool)
        writer.start()
        rag = RagClient(cfg.rag.base_url, cfg.rag.timeout_seconds)
        store = CacheStore(pool)
        cache_jobs = BackgroundQueue("cache")
        cache_jobs.start()
        versions = VersionCache(rag.info)
        refresher = Periodic(versions.refresh, cfg.rag.info_refresh_seconds, "kb-version-refresh")
        refresher.start()
        cleanup = Periodic(store.delete_expired, cfg.cache.cleanup_interval_minutes * 60, "cache-cleanup")
        cleanup.start()
        embedder = await asyncio.to_thread(Embedder, cfg.cache.embed_model, s.embed_cache_dir)
        cache = CacheDeps(embedder=embedder, versions=versions, store=store, writer=cache_jobs,
                          lexicon=Lexicon.from_yaml(s.weir_configs_dir / "entities.yaml"),
                          rules=BypassRules(cfg.bypass))

        async def health() -> dict[str, bool]:
            try:
                async with pool.connection() as conn:
                    await conn.execute("select 1")
                db_ok = True
            except Exception:  # noqa: BLE001
                db_ok = False
            return {"db": db_ok, "rag": await rag.health()}

        app.state.deps = AppDeps(Pipeline(cfg, rag, prices, writer, cache), tenants, cfg, health,
                                 AdminService(pool, store))
        try:
            yield
        finally:
            await refresher.stop()
            await cleanup.stop()
            await cache_jobs.stop()
            await writer.stop()
            await rag.aclose()
            await pool.close()
```
- Add the two routes inside `create_app`, after `/v1/query`:
```python
    @app.post("/v1/feedback")
    async def feedback(body: FeedbackIn, request: Request, x_api_key: str | None = Header(default=None)):
        d: AppDeps = request.app.state.deps
        tenant = d.tenants.authenticate(x_api_key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        ref = None
        for attempt in range(d.feedback_lookup_attempts):  # the log row is written asynchronously
            ref = await d.admin.find_request(body.request_id)
            if ref is not None:
                break
            if attempt < d.feedback_lookup_attempts - 1:
                await asyncio.sleep(d.feedback_lookup_delay_s)
        if ref is None or not tenant.allows(ref.namespace):
            raise HTTPException(status_code=404, detail="unknown request_id")
        await d.admin.add_feedback(body.request_id, body.rating, body.comment)
        evicted = body.rating == -1 and ref.cache_entry_id is not None and await d.admin.evict(ref.cache_entry_id)
        return {"evicted": bool(evicted)}

    @app.delete("/v1/cache")
    async def purge_cache(request: Request, namespace: str | None = None, source_id: str | None = None,
                          entry_id: UUID | None = None, x_api_key: str | None = Header(default=None)):
        d: AppDeps = request.app.state.deps
        tenant = d.tenants.authenticate(x_api_key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        if not tenant.admin:
            raise HTTPException(status_code=403, detail="admin key required")
        if sum(v is not None for v in (namespace, source_id, entry_id)) != 1:
            return JSONResponse(status_code=422,
                                content={"error": "give exactly one of namespace, source_id, entry_id"})
        deleted = await d.admin.purge(namespace=namespace, source_id=source_id, entry_id=entry_id)
        return {"deleted": deleted}
```
- Add `from .config import WeirConfig` to the imports if it isn't already there.

- [ ] **Step 4: Run.** `uv run pytest -q` → all green.

- [ ] **Step 5: Live smoke test (about 3 Groq calls).**
```bash
export MSYS_NO_PATHCONV=1
docker compose up -d --build                       # weir image now bakes bge-small
docker compose up migrate                          # applies 002 → "applied 1 migration(s): 002_phase2_cache.sql"
set -a; source .env; set +a
for i in $(seq 1 40); do curl -sf localhost:8000/healthz >/dev/null && break; sleep 3; done
Q='{"query":"What are the ICU visiting hours?","namespace":"weir-general/en/public"}'
P='{"query":"When can I visit a patient in intensive care?","namespace":"weir-general/en/public"}'
T='{"query":"What are the general ward visiting hours?","namespace":"weir-general/en/public"}'
for body in "$Q" "$Q" "$P" "$T"; do
  curl -s localhost:8000/v1/query -H "X-API-Key: $WEIR_KEY_PUBLIC" -H 'content-type: application/json' -d "$body" \
    | uv run --no-project python -c "import json,sys; m=json.load(sys.stdin)['meta']; print(m['cache_status'], m['similarity'], m['route'], m['request_id'])"
  sleep 2
done
```
Expected: `miss`, then `hit ~1.0 none`, then `hit` or `miss` for the paraphrase (record which, and its similarity), then `miss` for the general-ward trap. Then send feedback -1 for the second request's ID:
```bash
curl -s localhost:8000/v1/feedback -H "X-API-Key: $WEIR_KEY_PUBLIC" -H 'content-type: application/json' -d '{"request_id":"<id of the hit>","rating":-1}'
curl -s -X DELETE "localhost:8000/v1/cache?namespace=weir-general/en/public" -H "X-API-Key: $WEIR_KEY_ADMIN"
docker compose exec -T postgres psql -U weir -c "select cache_status, bypass_reason, similarity, route, cost_usd, counterfactual_cost_usd, latency_embed_ms, latency_cache_ms from weir.request_log order by ts desc limit 4"
```
Expected: `{"evicted":true}`, then `{"deleted":N}` with N ≥ 1, and the log rows match the four requests (the hit row has `cost_usd=0` and a non-zero counterfactual). Then run `docker compose stop`.

- [ ] **Step 6: Progress log, commit and push.** Append a "Phase 2: cache live" entry to `docs/progress.md`, including the smoke results and the paraphrase's similarity.
```bash
git add services/weir docs/progress.md
git commit -m "feat(weir): feedback eviction and admin purge APIs; cache wired into the app"
git push
```

---

### Task 9: Eval tooling for Phase 2

**Files:**
- Modify: `eval/pyproject.toml`, `eval/src/weir_eval/dataset.py`, `kb.py`, `judge.py`, `runner.py`, `summary.py`, `cli.py`
- Create: `eval/src/weir_eval/workload.py`
- Test: append to `eval/tests/test_dataset.py`, `test_judge.py`, `test_runner.py`, `test_summary.py`; create `eval/tests/test_workload.py`

**Interfaces:**
- Produces:
  - `EvalQuery.group` accepts `"unanswerable"`. `source_docs` defaults to `[]`, must be empty for unanswerable queries and non-empty otherwise.
  - `assign_splits` keeps any split that already exists.
  - `Judge.grade(query, facts, source_text, answer, unanswerable=False)`. The cache key changes only when `unanswerable` is true.
  - `run_eval(..., judge: Judge | None)`: `None` means skip judging.
  - `Limiter.release()`
  - `summarize` adds `hits`, `wrong_hits`, `hit_rate_by_group` and `latency_by_cache_status`.
  - `make_workload(query_ids, n, seed, exponent=1.1) -> list[str]` and `repeat_rate(ids) -> float`
  - New CLI options: `run --no-judge --exclude-report DIR --workload FILE --purge-cache`, plus the commands `merge-reports OUT DIR...` and `make-workload --n --seed [--exponent]`.
  - `eval` depends on `weir` (path dependency) and `matplotlib`.

- [ ] **Step 1: Dependencies.** In `eval/pyproject.toml`, add `"weir"` and `"matplotlib>=3.8"` to the dependencies, and append:
```toml
[tool.uv.sources]
weir = { path = "../services/weir", editable = true }
```
Run: `cd eval && uv lock && uv sync && uv run python -c "import weir.cache.entities, matplotlib; print('ok')"` → `ok`.

- [ ] **Step 2: Failing tests.** Append to `eval/tests/test_dataset.py`:
```python
import pytest  # noqa: E402

from weir_eval.dataset import EvalQuery  # noqa: E402


def test_unanswerable_rules():
    ok = EvalQuery(id="u1", namespace="weir-general/en/public", query="Do you have a helipad?", group="unanswerable",
                   cluster_id="u-01", difficulty="easy", required_facts=["couldn't find"])
    assert ok.source_docs == [] and validate([ok]) == []
    with pytest.raises(ValueError, match="no source_docs"):
        EvalQuery(**{**ok.model_dump(), "source_docs": ["pub-a"]})
    with pytest.raises(ValueError, match="at least one source_doc"):
        EvalQuery(**{**ok.model_dump(), "group": "distinct", "cluster_id": "d-x"})


def test_existing_splits_are_kept():
    old = [q("d0", "d0", split="holdout"), q("d1", "d1", split="tune")]
    new = [q(f"n{i}", f"n{i}") for i in range(10)]
    out = {x.id: x.split for x in assign_splits(old + new)}
    assert out["d0"] == "holdout" and out["d1"] == "tune"
    assert sum(out[f"n{i}"] == "holdout" for i in range(10)) == 3
```
Append to `eval/tests/test_judge.py`:
```python
async def test_unanswerable_note_and_separate_cache_key(tmp_path):
    import hashlib

    from weir_eval.judge import RUBRIC_VERSION

    call = FakeCall([json.dumps({"score": 5, "reason": "ok"})] * 2)
    judge = Judge(call, tmp_path, "m", sleep=no_sleep)
    await judge.grade("q", ["f"], "", "a")
    await judge.grade("q", ["f"], "", "a", unanswerable=True)
    assert len(call.prompts) == 2 and "does NOT contain" in call.prompts[1] and "(none)" in call.prompts[1]
    legacy = hashlib.sha256(json.dumps([RUBRIC_VERSION, "m", "q", ["f"], "a"]).encode()).hexdigest()
    assert (tmp_path / f"{legacy}.json").exists()  # answerable keys unchanged: Phase 1 grades stay valid
```
Append to `eval/tests/test_runner.py`:
```python
def weir_hit(request):
    resp = weir_ok(request)
    body = json.loads(resp.content)
    body["meta"]["cache_status"] = "hit"
    return httpx.Response(200, json=body)


async def test_run_eval_without_judge_and_no_wait_after_hits(tmp_path):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    async with httpx.AsyncClient(transport=httpx.MockTransport(weir_hit), base_url="http://w") as http:
        records = await run_eval([q("d1", "d1"), q("d2", "d2"), q("d3", "d3")], http,
                                 {"weir-general/en/public": "k"}, None, {"pub-a": "Open at 4 pm."}, tmp_path,
                                 min_interval_s=5, sleep=fake_sleep)
    assert all(r["judge_score"] is None and "not judged" in r["judge_error"] for r in records)
    assert slept == []  # every response was a cache hit, so the limiter never waited


def test_limiter_release():
    limiter = Limiter(10.0, clock=lambda: 0.0)
    limiter._last = 0.0
    limiter.release()
    assert limiter._last is None
```
Append to `eval/tests/test_summary.py`:
```python
def test_cache_metrics_and_wrong_hits():
    def r(i, status, fact, judge, group="paraphrase", latency=10):
        x = rec(i, latency, 0.0, judge, fact, group=group)
        x["meta"]["cache_status"] = status
        return x

    s = summarize([r(1, "miss", 1.0, 5, latency=900), r(2, "hit", 1.0, 5), r(3, "hit", 0.0, 5, group="trap"),
                   r(4, "hit", 1.0, 2), r(5, "bypass", 1.0, 5, group="trap")])
    assert s["hits"] == 3 and s["wrong_hits"] == 2
    assert s["hit_rate_by_group"] == {"paraphrase": 2 / 3, "trap": 0.5}
    assert s["latency_by_cache_status"]["hit"]["n"] == 3 and s["latency_by_cache_status"]["miss"]["p50"] == 900
```
`eval/tests/test_workload.py`:
```python
from weir_eval.workload import make_workload, repeat_rate


def test_workload_is_deterministic_skewed_and_sized():
    ids = [f"q-{i:03d}" for i in range(150)]
    a = make_workload(ids, 300, seed=7)
    assert a == make_workload(ids, 300, seed=7) and len(a) == 300 and set(a) <= set(ids)
    assert 0.3 < repeat_rate(a) < 0.95
    top = max(set(a), key=a.count)
    assert a.count(top) >= 30  # a few questions dominate


def test_repeat_rate_edges():
    assert repeat_rate([]) == 0.0 and repeat_rate(["a", "a", "b", "c"]) == 0.25
```

- [ ] **Step 3: Confirm failure.** `cd eval && uv run pytest -q` → failures and import errors.

- [ ] **Step 4: Implement.**

`dataset.py`:
- Group literal: `Literal["distinct", "paraphrase", "trap", "unanswerable"]`.
- Change `source_docs` to `source_docs: list[str] = Field(default_factory=list)`.
- Add `from pydantic import model_validator` and this method on `EvalQuery`:
```python
    @model_validator(mode="after")
    def sources_match_group(self) -> "EvalQuery":
        if self.group == "unanswerable" and self.source_docs:
            raise ValueError("unanswerable queries have no source_docs")
        if self.group != "unanswerable" and not self.source_docs:
            raise ValueError("answerable queries need at least one source_doc")
        return self
```
- Add `"unanswerable": (1, 1)` to `CLUSTER_SIZE`.
- Replace `assign_splits`:
```python
def assign_splits(queries: list[EvalQuery], holdout_frac: float = 0.3, seed: int = 7) -> list[EvalQuery]:
    """Hold out ~holdout_frac of the *unassigned* clusters per group (spec §11.1). Clusters that
    already have a split keep it, so adding questions never reshuffles the existing tune/holdout sets."""
    rng = random.Random(seed)
    assigned = {q.cluster_id: q.split for q in queries if q.split is not None}
    holdout: set[str] = set()
    for group in ("distinct", "paraphrase", "trap", "unanswerable"):
        new_ids = sorted({q.cluster_id for q in queries if q.group == group and q.cluster_id not in assigned})
        rng.shuffle(new_ids)
        holdout.update(new_ids[: round(len(new_ids) * holdout_frac)])
    return [q.model_copy(update={"split": assigned.get(q.cluster_id)
                                 or ("holdout" if q.cluster_id in holdout else "tune")}) for q in queries]
```

`kb.py`: at the top of the loop in `facts_missing_from_sources`, add `if q.group == "unanswerable": continue`.

`judge.py`:
- Add:
```python
UNANSWERABLE_NOTE = ("### Note\nThe knowledge base does NOT contain the answer to this question. "
                     "Score 5 if the answer clearly says the information could not be found. "
                     "Score 1 if it gives an answer anyway.")
```
- Change `grade` to:
```python
    async def grade(self, query: str, facts: list[str], source_text: str, answer: str,
                    unanswerable: bool = False) -> JudgeVerdict:
        payload = [RUBRIC_VERSION, self._model, query, facts, answer] + (["unanswerable"] if unanswerable else [])
        key = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        cached = self._cache_dir / f"{key}.json"
        if cached.exists():
            return JudgeVerdict.model_validate_json(cached.read_text(encoding="utf-8"))
        note = f"\n\n{UNANSWERABLE_NOTE}" if unanswerable else ""
        prompt = (f"{RUBRIC}\n\n### Source document\n{source_text or '(none)'}\n\n### Question\n{query}\n\n"
                  f"### Required facts\n{json.dumps(facts, ensure_ascii=False)}\n\n### Answer to grade\n{answer}\n{note}")
```
  The rest of the method (retry loop, cache write) is unchanged.

`runner.py`:
- Add to `Limiter`:
```python
    def release(self) -> None:
        """The last call was free (a cache hit), so the next one needn't wait."""
        self._last = None
```
- In `run_eval`, change the signature to `judge: Judge | None` and update the loop body:
```python
            await limiter.wait()
            record = await ask(http, keys[q.namespace], q, sleep=sleep)
            if record.get("meta", {}).get("cache_status") == "hit":
                limiter.release()
            if record["status_code"] == 200:
                facts = check_facts(record["answer"], q.required_facts)
                record.update(fact_hits=facts.hits, fact_total=facts.total, fact_score=facts.score)
                if judge is None:
                    record.update(judge_score=None, judge_error="not judged yet (--no-judge); run rejudge")
                else:
                    await _grade(record, q, judge, kb)
```
- In `_grade`, pass `unanswerable=q.group == "unanswerable"` to `judge.grade`.

`summary.py`: in `summarize`, after the `routes` line add:
```python
    hits = [r for r in ok if r["meta"]["cache_status"] == "hit"]
    wrong = [r for r in hits if r["fact_score"] < 1 or (r.get("judge_score") is not None and r["judge_score"] <= 3)]
    by_status: dict[str, list[int]] = defaultdict(list)
    for r in ok:
        by_status[r["meta"]["cache_status"]].append(r["client_latency_ms"])
```
  Then add these keys to the `summary.update({...})` dict, replacing the old `cache_hit_rate` line:
```python
        "cache_hit_rate": len(hits) / len(ok),
        "hits": len(hits),
        "wrong_hits": len(wrong),
        "hit_rate_by_group": {g: sum(r["meta"]["cache_status"] == "hit" for r in rs) / len(rs)
                              for g, rs in sorted(by_group.items())},
        "latency_by_cache_status": {s: {"n": len(v), "p50": percentile(v, 50), "p95": percentile(v, 95)}
                                    for s, v in sorted(by_status.items())},
```
  In `render_markdown`, after the "Cache hit rate" row add `f"| Cache hits / wrong hits | {summary['hits']} / {summary['wrong_hits']} |",`. After the difficulty table add:
```python
        lines += ["", "## Latency by cache status", "", "| Status | n | p50 (ms) | p95 (ms) |", "| --- | --- | --- | --- |"]
        lines += [f"| {s} | {v['n']} | {v['p50']} | {v['p95']} |" for s, v in summary["latency_by_cache_status"].items()]
```

`workload.py`:
```python
"""Skewed traffic replay (main spec §11.3): a few questions are asked constantly, most rarely."""
import random


def make_workload(query_ids: list[str], n: int, seed: int, exponent: float = 1.1) -> list[str]:
    rng = random.Random(seed)
    order = sorted(query_ids)
    rng.shuffle(order)
    weights = [1 / rank ** exponent for rank in range(1, len(order) + 1)]
    return rng.choices(order, weights=weights, k=n)


def repeat_rate(ids: list[str]) -> float:
    return 1 - len(set(ids)) / len(ids) if ids else 0.0
```

`cli.py`:
- Add imports `from .workload import make_workload, repeat_rate`.
- Add `ADMIN_KEY_ENV = "WEIR_KEY_ADMIN"`.
- Replace `_run` with:
```python
async def _run(args: argparse.Namespace) -> int:
    all_queries = load_queries(QUERIES)
    if args.workload:
        by_id = {q.id: q for q in all_queries}
        ids = [json.loads(line)["id"] for line in Path(args.workload).read_text(encoding="utf-8").splitlines() if line.strip()]
        queries = [by_id[i] for i in ids]
    else:
        queries = [q for q in all_queries if args.split == "all" or q.split == args.split]
    if args.exclude_report:
        done = {r["id"] for r in _load_results(Path(args.exclude_report)) if r.get("status_code") == 200}
        queries = [q for q in queries if q.id not in done]
    keys = {ns: os.environ[env] for ns, env in KEY_ENV.items()}
    judge, judge_model = (None, None) if args.no_judge else _make_judge()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    label = f"{args.config}-{Path(args.workload).stem if args.workload else args.split}"
    out_dir = EVAL_DIR / "reports" / f"{stamp}-{label}"
    async with httpx.AsyncClient(base_url=args.weir_url, timeout=90) as http:
        health = (await http.get("/healthz")).json()
        if health.get("config_label") != args.config:
            print(f"Weir is running config {health.get('config_label')!r}, expected {args.config!r}. "
                  f"Restart it with WEIR_ABLATION={args.config}.", file=sys.stderr)
            return 2
        if args.purge_cache:
            for ns in KEY_ENV:
                r = await http.delete("/v1/cache", params={"namespace": ns}, headers={"X-API-Key": os.environ[ADMIN_KEY_ENV]})
                if r.status_code != 200:
                    print(f"cache purge failed for {ns}: {r.status_code} {r.text}", file=sys.stderr)
                    return 2
                print(f"purged {r.json()['deleted']} cache entries in {ns}")
        records = await run_eval(queries, http, keys, judge, load_kb_texts(KB_DIR), out_dir, args.min_interval)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    header = {"config": args.config, "split": args.split, "workload": args.workload, "queries": len(queries),
              "judge_model": judge_model, "rubric": RUBRIC_VERSION, "git_commit": commit, "started_utc": stamp}
    if args.workload:
        header["workload_repeat_rate"] = round(repeat_rate([q.id for q in queries]), 3)
    _write_report(out_dir, header, records)
    return 0


def _load_results(report_dir: Path) -> list[dict]:
    path = report_dir / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cmd_merge_reports(args: argparse.Namespace) -> int:
    records, seen = [], set()
    for d in args.dirs:
        for r in _load_results(Path(d)):
            if r["id"] not in seen:
                seen.add(r["id"])
                records.append(r)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                                           encoding="utf-8")
    _write_report(out_dir, {"merged_from": [Path(d).name for d in args.dirs], "queries": len(records)}, records)
    return 0


def cmd_make_workload(args: argparse.Namespace) -> int:
    ids = make_workload([q.id for q in load_queries(QUERIES)], args.n, args.seed, args.exponent)
    out = EVAL_DIR / "datasets" / f"workload-{args.n}-seed{args.seed}.jsonl"
    out.write_text("".join(json.dumps({"id": i}) + "\n" for i in ids), encoding="utf-8")
    print(f"{out}: {len(ids)} requests, {len(set(ids))} unique, repeat rate {repeat_rate(ids):.1%}")
    return 0
```
- In `main()`, extend the `run` parser and add the new commands:
```python
    run.add_argument("--no-judge", action="store_true", help="skip judging; grade later with rejudge")
    run.add_argument("--exclude-report", help="skip queries already answered in this report dir")
    run.add_argument("--workload", help="jsonl of {id} lines to replay in order (ignores --split)")
    run.add_argument("--purge-cache", action="store_true", help="empty Weir's cache first (admin key)")
    merge = sub.add_parser("merge-reports", help="combine report dirs (first occurrence of an id wins)")
    merge.add_argument("out")
    merge.add_argument("dirs", nargs="+")
    merge.set_defaults(func=cmd_merge_reports)
    wl = sub.add_parser("make-workload", help="Zipf-skewed replay list")
    wl.add_argument("--n", type=int, default=300)
    wl.add_argument("--seed", type=int, default=7)
    wl.add_argument("--exponent", type=float, default=1.1)
    wl.set_defaults(func=cmd_make_workload)
```
- Use `_load_results` inside `_rejudge` where it reads `results.jsonl`, if anything there reads the file directly.

- [ ] **Step 5: Run.** `uv run pytest -q` → all green (43 + 8 new = 51). `uv run python -m weir_eval validate` → `ok: 50 queries`.

- [ ] **Step 6: Commit and push.**
```bash
git add eval
git commit -m "feat(eval): unanswerable group, split preservation, no-judge runs, workload replay, cache metrics"
git push
```

---

### Task 10: 100 new eval questions (content task, suited to a subagent)

**Files:**
- Modify: `eval/datasets/queries.jsonl` (append q-051 to q-150)

**Interfaces:**
- Consumes: the KB, `kb/README.md`, `EvalQuery` (Task 9), and `weir_eval validate` / `assign-splits`.
- Produces: 150 valid queries. The existing 50 keep their splits.

**Authoring rules (put these in the subagent prompt verbatim):**
- Read `kb/README.md` and every document under `kb/public` and `kb/staff`, plus the existing `eval/datasets/queries.jsonl`. Never invent facts. Never edit existing lines or anything outside `queries.jsonl`.
- Append exactly 100 lines with ids `q-051`…`q-150`, `"split": null`:
  - **10 paraphrase clusters** `para-4`…`para-13`, each with 5 members (a seed plus 4 rewordings that vary vocabulary, word order and formality). Members share identical `required_facts` and `source_docs`. Pick topics not already used by `para-1`…`para-3`. At least 2 clusters in the staff namespace.
  - **15 trap pairs** `trap-6`…`trap-20`, 2 members each. The two questions look nearly identical, but the right answers differ (different `required_facts`). Use contrasts the documents state explicitly, such as CT vs MRI price, X-ray vs ultrasound report time, morning vs evening slot, weekday vs weekend rate, first vs additional copy, private vs semi-private, cash vs insurance, adult vs child, nurse vs doctor, main vs OPD pharmacy, or one department vs another. Don't reuse the exact pairs in `trap-1`…`trap-5`. At least 3 pairs in the staff namespace.
  - **10 unanswerable** `u-01`…`u-10`, `"group": "unanswerable"`, `"source_docs": []`, `"required_facts": ["couldn't find|could not find"]`. These are plausible hospital questions the documents do NOT answer (for example a helipad, Wi-Fi password, a parking app, a specific doctor's name). Check by searching the KB that the answer really isn't there. No clinical questions.
  - **10 hard distinct** `d-26`…`d-35`, `"group": "distinct"`, `"difficulty": "hard"`. Each combines facts from 2 documents, so it has 2 `source_docs`.
- `required_facts`: 1–3 short literal strings that appear in the source documents. Use `|` alternatives for formatting, and give money as `₹N|Rs N|Rs. N|INR N|N rupees`. Never use a bare number alternative.
- Namespaces must match the source document folders, and a cluster never spans namespaces.
- No clinical questions (doses, symptoms, diagnosis, treatment).

- [ ] **Step 1: Write the 100 lines** following the rules above.
- [ ] **Step 2: Assign splits and validate.**
```bash
cd eval && PYTHONIOENCODING=utf-8 uv run python -m weir_eval assign-splits
uv run python - <<'EOF'
from collections import Counter
from pathlib import Path
from weir_eval.dataset import load_queries
qs = load_queries(Path("datasets/queries.jsonl"))
print(len(qs), Counter(q.group for q in qs), Counter(q.split for q in qs))
print([q.split for q in qs[:50]] == [q.split for q in qs[:50]])
EOF
git diff --stat datasets/queries.jsonl
git diff datasets/queries.jsonl | grep '^-{' | head -3   # must print nothing: existing lines untouched
```
Expected: `ok: 150 queries`, groups 35 distinct / 65 paraphrase / 40 trap / 10 unanswerable, and no removed lines.

- [ ] **Step 3: Self spot check.** Pick 10 random new lines and trace each fact to its sentence, as in Phase 1 (grep the KB). Confirm each unanswerable topic is absent from the KB. Record the outcome in the ledger.
- [ ] **Step 4: Commit and push.**
```bash
git add eval/datasets/queries.jsonl
git commit -m "data(eval): +100 questions (10 paraphrase clusters, 15 trap pairs, 10 unanswerable, 10 hard)"
git push
```

---

### Task 11: Baseline v2 (150 questions)

**Files:**
- Create: `eval/reports/<stamp>-baseline-all/` (100 new answers), `eval/reports/baseline-v2/` (merged)
- Modify: `docs/results/baseline.md` (v2 section), `docs/progress.md`

- [ ] **Step 1: Answer the 100 new questions, no cache, about 9 minutes, about 50K Groq tokens.**
```bash
WEIR_ABLATION=baseline docker compose up -d
for i in $(seq 1 40); do curl -s localhost:8000/healthz | grep -q '"baseline"' && break; sleep 3; done
cd eval && PYTHONIOENCODING=utf-8 uv run --env-file ../.env python -m weir_eval run --config baseline --split all \
  --exclude-report reports/20261001T124959Z-baseline-all --no-judge --min-interval 5
```
Expected: 100 progress lines and `errors 0`. Then run `docker compose stop` to free memory for judging.

- [ ] **Step 2: Merge with the original 50 answers.**
```bash
uv run python -m weir_eval merge-reports reports/baseline-v2 reports/20261001T124959Z-baseline-all reports/<new stamp>-baseline-all
```
Expected: `report: reports/baseline-v2 (errors 0, not judged 100)`.

- [ ] **Step 3: Judge the 100 new answers (about 100 Qwen calls, about 14 minutes, in two foreground chunks if needed).**
```bash
PYTHONIOENCODING=utf-8 timeout 580 uv run --env-file ../.env python -m weir_eval rejudge reports/baseline-v2
```
Repeat until the report says `not judged 0`. A rerun skips rows that are already graded. If Qwen's daily token limit is hit (429 on every call), stop and resume after midnight UTC.

- [ ] **Step 4: Check.** Read `reports/baseline-v2/summary.md`. Every unanswerable answer should be the NOT_FOUND message (judge 5). Print and read any row with a judge score below 5 or a fact score below 1. Decide whether each is a model error (that's a real baseline result, keep it) or a dataset error (fix the question, re-run only that ID with `--exclude-report`, and record a ruling).

- [ ] **Step 5: Document, commit and push.** Add a "Baseline v2 (150 queries)" section to `docs/results/baseline.md` with:
- the summary tables (overall, by group, by difficulty)
- the unanswerable result
- the run pacing (5 s)
- the note that v1's 50 answers are reused

Also append a progress entry.
```bash
git add eval/reports docs
git commit -m "results: baseline v2 on 150 questions"
git push
```

---

### Task 12: Threshold sweep

**Files:**
- Create: `eval/src/weir_eval/sweep.py`, `eval/tests/test_sweep.py`, `eval/datasets/pairs.jsonl`, `eval/reports/sweep-<stamp>/`, `docs/results/cache-threshold.md`
- Modify: `eval/src/weir_eval/cli.py` (the `sweep` command), `configs/weir.yaml` (`cache.threshold`)

**Interfaces:**
- Consumes: `weir.cache.embedder.Embedder`, `weir.cache.entities.Lexicon`, `weir.text.normalize`, `load_queries`.
- Produces:
  - `Pair(a, b, kind: "positive"|"trap"|"hard_negative", split: "tune"|"holdout"|"cross", similarity, guard_conflict)`
  - `build_pairs(queries, vectors, conflicts) -> list[Pair]`
  - `THRESHOLDS` (0.80 to 0.98, step 0.01)
  - `sweep(pairs, thresholds, use_guard) -> list[dict]`
  - `choose_threshold(rows, max_false_hit=0.01) -> float | None` (the lowest threshold with false-hit rate under the maximum, zero trap false hits, and at least one accepted pair)
  - `write_sweep_report(out_dir, results, chosen, pairs)`
- **Refinement of addendum §7.2 (ruling):** a hard-negative pair is skipped when the two questions share a required fact, because they have the same answer and so can't be a wrong hit.

- [ ] **Step 1: Failing tests.** `eval/tests/test_sweep.py`:
```python
import numpy as np

from weir_eval.sweep import Pair, build_pairs, choose_threshold, sweep, write_sweep_report

from .conftest import q


def vec(*xs):
    v = np.zeros(384, dtype=np.float32)
    v[: len(xs)] = xs
    return v / np.linalg.norm(v)


def toy():
    qs = [q("p1", "para-1", "paraphrase", "tune", facts=("A",)), q("p2", "para-1", "paraphrase", "tune", facts=("A",)),
          q("t1", "trap-1", "trap", "tune", facts=("B",)), q("t2", "trap-1", "trap", "tune", facts=("C",)),
          q("d1", "d-1", "distinct", "holdout", facts=("D",))]
    vecs = {"p1": vec(1, 0, 0), "p2": vec(1, 0.1, 0), "t1": vec(0, 1, 0), "t2": vec(0, 1, 0.2), "d1": vec(0.8, 0, 0.6)}
    return qs, vecs


def test_build_pairs_kinds_splits_and_guard():
    qs, vecs = toy()
    pairs = {(p.a, p.b): p for p in build_pairs(qs, vecs, lambda a, b: "t1" in a or "t1" in b)}
    assert pairs[("p1", "p2")].kind == "positive" and pairs[("p1", "p2")].split == "tune"
    assert pairs[("t1", "t2")].kind == "trap" and pairs[("t1", "t2")].guard_conflict
    assert pairs[("d1", "p1")].kind == "hard_negative" and pairs[("d1", "p1")].split == "cross"
    assert pairs[("p1", "p2")].similarity > 0.99


def test_hard_negatives_sharing_a_fact_are_skipped():
    qs, vecs = toy()
    qs[4] = q("d1", "d-1", "distinct", "holdout", facts=("A",))  # same answer as p1/p2
    same_answer = ({"d1", "p1"}, {"d1", "p2"})
    assert not any(p.kind == "hard_negative" and {p.a, p.b} in same_answer
                   for p in build_pairs(qs, vecs, lambda a, b: False))


def pairs_fixture():
    return [Pair("a", "b", "positive", "tune", 0.95, False), Pair("c", "d", "positive", "tune", 0.85, False),
            Pair("e", "f", "trap", "tune", 0.90, True), Pair("g", "h", "hard_negative", "tune", 0.83, False)]


def test_sweep_math_with_and_without_guard():
    on = {r["threshold"]: r for r in sweep(pairs_fixture(), [0.82, 0.84, 0.90], use_guard=True)}
    off = {r["threshold"]: r for r in sweep(pairs_fixture(), [0.84], use_guard=False)}
    assert on[0.84]["hit_rate"] == 1.0 and on[0.84]["false_hit_rate"] == 0.0
    assert abs(on[0.82]["false_hit_rate"] - 1 / 3) < 1e-9
    assert off[0.84]["trap_false_hits"] == 1 and abs(off[0.84]["false_hit_rate"] - 1 / 3) < 1e-9
    assert on[0.90]["hit_rate"] == 0.5


def test_choose_threshold_lowest_passing():
    rows = sweep(pairs_fixture(), [0.82, 0.84, 0.90], use_guard=True)
    assert choose_threshold(rows) == 0.84
    assert choose_threshold(sweep(pairs_fixture(), [0.82], use_guard=False)) is None


def test_report_files(tmp_path):
    rows = sweep(pairs_fixture(), [0.82, 0.84], use_guard=True)
    results = {("tune", True): rows, ("tune", False): rows, ("holdout", True): rows, ("holdout", False): rows,
               ("all", True): rows, ("all", False): rows}
    write_sweep_report(tmp_path, results, 0.84, pairs_fixture())
    assert {"sweep.csv", "summary.md", "threshold.png"} <= {p.name for p in tmp_path.iterdir()}
    assert "0.84" in (tmp_path / "summary.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Confirm failure.** `uv run pytest tests/test_sweep.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement.** `eval/src/weir_eval/sweep.py`:
```python
"""Threshold sweep (Phase 2 addendum §7.2): how often does the cache accept a pair it should,
and how often one it shouldn't, at each similarity threshold, with and without the entity guard."""
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .dataset import EvalQuery

THRESHOLDS = [round(0.80 + 0.01 * i, 2) for i in range(19)]


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    kind: str          # positive | trap | hard_negative
    split: str         # tune | holdout | cross
    similarity: float
    guard_conflict: bool


def build_pairs(queries: list[EvalQuery], vectors: dict[str, np.ndarray],
                conflicts: Callable[[str, str], bool]) -> list[Pair]:
    by_id = {q.id: q for q in queries}
    pairs: dict[tuple[str, str], Pair] = {}

    def add(a: str, b: str, kind: str) -> None:
        key = tuple(sorted((a, b)))
        if key in pairs:
            return
        qa, qb = by_id[key[0]], by_id[key[1]]
        split = qa.split if qa.split == qb.split else "cross"
        pairs[key] = Pair(key[0], key[1], kind, split, float(vectors[key[0]] @ vectors[key[1]]),
                          conflicts(qa.query, qb.query))

    clusters: dict[str, list[EvalQuery]] = defaultdict(list)
    for q in queries:
        clusters[q.cluster_id].append(q)
    for members in clusters.values():
        kind = {"paraphrase": "positive", "trap": "trap"}.get(members[0].group)
        if kind:
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    add(a.id, b.id, kind)
    for q in queries:  # hard negatives: the nearest question from another cluster with a different answer
        others = [o for o in queries if o.cluster_id != q.cluster_id
                  and not set(o.required_facts) & set(q.required_facts)]
        if others:
            nearest = max(others, key=lambda o: float(vectors[q.id] @ vectors[o.id]))
            add(q.id, nearest.id, "hard_negative")
    return list(pairs.values())


def sweep(pairs: list[Pair], thresholds: list[float], use_guard: bool) -> list[dict]:
    positives = sum(p.kind == "positive" for p in pairs)
    rows = []
    for t in thresholds:
        accepted = [p for p in pairs if p.similarity >= t and not (use_guard and p.guard_conflict)]
        pos = sum(p.kind == "positive" for p in accepted)
        rows.append({
            "threshold": round(t, 2), "use_guard": use_guard, "accepted": len(accepted),
            "hit_rate": pos / positives if positives else 0.0,
            "false_hit_rate": (len(accepted) - pos) / len(accepted) if accepted else 0.0,
            "trap_false_hits": sum(p.kind == "trap" for p in accepted),
            "hard_negative_false_hits": sum(p.kind == "hard_negative" for p in accepted),
        })
    return rows


def choose_threshold(rows: list[dict], max_false_hit: float = 0.01) -> float | None:
    passing = [r["threshold"] for r in rows
               if r["accepted"] > 0 and r["false_hit_rate"] < max_false_hit and r["trap_false_hits"] == 0]
    return min(passing) if passing else None


def write_sweep_report(out_dir: Path, results: dict[tuple[str, bool], list[dict]], chosen: float | None,
                       pairs: list[Pair]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "sweep.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["split", *results[("tune", True)][0].keys()])
        writer.writeheader()
        for (split, _), rows in results.items():
            for r in rows:
                writer.writerow({"split": split, **r})

    fig, ax = plt.subplots(figsize=(7, 4))
    for guard, style in ((True, "-"), (False, "--")):
        rows = results[("tune", guard)]
        xs = [r["threshold"] for r in rows]
        label = "guard on" if guard else "guard off"
        ax.plot(xs, [r["hit_rate"] for r in rows], style, color="tab:blue", label=f"hit rate ({label})")
        ax.plot(xs, [r["false_hit_rate"] for r in rows], style, color="tab:red", label=f"false-hit rate ({label})")
    if chosen is not None:
        ax.axvline(chosen, color="gray", linestyle=":", label=f"chosen {chosen:.2f}")
    ax.set_xlabel("cosine similarity threshold")
    ax.set_ylabel("rate")
    ax.set_title("Cache threshold sweep (tune split)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "threshold.png", dpi=120)
    plt.close(fig)

    counts = Counter((p.kind, p.split) for p in pairs)
    lines = ["# Threshold sweep", "", f"Chosen threshold: **{chosen if chosen is not None else 'none passes'}**", "",
             "Pairs: " + ", ".join(f"{k}/{s}: {n}" for (k, s), n in sorted(counts.items())), ""]
    for split in ("tune", "holdout", "all"):
        for guard in (True, False):
            lines += [f"## {split}, guard {'on' if guard else 'off'}", "",
                      "| threshold | accepted | hit rate | false-hit rate | trap false hits | hard-neg false hits |",
                      "| --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {r['threshold']:.2f} | {r['accepted']} | {r['hit_rate']:.3f} | {r['false_hit_rate']:.3f} | "
                      f"{r['trap_false_hits']} | {r['hard_negative_false_hits']} |" for r in results[(split, guard)]]
            lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "pairs.jsonl").write_text("".join(json.dumps(asdict(p)) + "\n" for p in pairs), encoding="utf-8")
```
Add to `cli.py`:
```python
REPO = EVAL_DIR.parent
CONFIGS_DIR = REPO / "configs"


def cmd_sweep(args: argparse.Namespace) -> int:
    from weir.cache.embedder import Embedder
    from weir.cache.entities import Lexicon
    from weir.text import normalize

    from .sweep import THRESHOLDS, build_pairs, choose_threshold, sweep, write_sweep_report

    queries = load_queries(QUERIES)
    vectors = dict(zip([q.id for q in queries],
                       Embedder("BAAI/bge-small-en-v1.5").embed_many([normalize(q.query) for q in queries]), strict=True))
    lexicon = Lexicon.from_yaml(CONFIGS_DIR / "entities.yaml")
    pairs = build_pairs(queries, vectors, lexicon.conflicts)
    results = {(split, guard): sweep([p for p in pairs if split == "all" or p.split == split], THRESHOLDS, guard)
               for split in ("tune", "holdout", "all") for guard in (True, False)}
    chosen = choose_threshold(results[("tune", True)], args.max_false_hit)
    out_dir = EVAL_DIR / "reports" / f"sweep-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    write_sweep_report(out_dir, results, chosen, pairs)
    (EVAL_DIR / "datasets" / "pairs.jsonl").write_text((out_dir / "pairs.jsonl").read_text(encoding="utf-8"),
                                                       encoding="utf-8")
    holdout = next((r for r in results[("holdout", True)] if r["threshold"] == chosen), None)
    print(f"chosen threshold (tune, guard on): {chosen}; holdout at chosen: {holdout}; report: {out_dir}")
    return 0
```
and in `main()`:
```python
    sw = sub.add_parser("sweep", help="similarity threshold sweep on paraphrase/trap/hard-negative pairs")
    sw.add_argument("--max-false-hit", type=float, default=0.01)
    sw.set_defaults(func=cmd_sweep)
```

- [ ] **Step 4: Run the tests.** `uv run pytest -q` → all green (51 + 5 = 56).

- [ ] **Step 5: Run the sweep (no Groq calls).** `PYTHONIOENCODING=utf-8 uv run python -m weir_eval sweep`.
Expected: a chosen threshold and a holdout row with `trap_false_hits = 0` and `false_hit_rate < 0.01`.
**If no threshold passes, or holdout fails:**
- Open the summary's trap and hard-negative pairs that were accepted. These are pairs with high similarity and no guard conflict.
- For each, decide whether the guard should separate them (missing lexicon term → add it to `configs/entities.yaml` and record a ruling) or whether the two answers are really the same (a dataset issue → record a ruling).
- Re-run until it passes, or record that no threshold is safe. That outcome is a reportable result (addendum §7.4), and the cache stays off for the affected namespace.

- [ ] **Step 6: Apply and document.**
- Set `cache.threshold` in `configs/weir.yaml` to the chosen value, with a comment citing `docs/results/cache-threshold.md`.
- Write `docs/results/cache-threshold.md`, containing:
  - the chosen threshold and why
  - the tune and holdout rows at that threshold
  - guard on vs off at the chosen threshold (how many trap pairs the guard rejected)
  - the pair counts
  - the embedded chart, copied to `docs/results/cache-threshold.png`
  - every lexicon ruling
- Add decision **D25** (chosen threshold) to `docs/decisions.md`, and a progress entry.
```bash
git add eval configs docs
git commit -m "results: cache threshold sweep; set cache.threshold from data"
git push
```

---

### Task 13: Cache run, results, Phase 2 exit

**Files:**
- Create: `eval/datasets/workload-300-seed7.jsonl`, `eval/reports/<stamp>-cache_only-all/`, `eval/reports/<stamp>-cache_only-workload-300-seed7/`, `docs/results/cache-only.md`
- Modify: `docs/progress.md`, `docs/decisions.md`, `docs/README.md`

- [ ] **Step 1: Workload.** `cd eval && uv run python -m weir_eval make-workload --n 300 --seed 7`.
Expected: `300 requests, N unique, repeat rate R%`. Record R.

- [ ] **Step 2: Cold pass (cache emptied first).**
```bash
WEIR_ABLATION=cache_only docker compose up -d
for i in $(seq 1 40); do curl -s localhost:8000/healthz | grep -q '"cache_only"' && break; sleep 3; done
cd eval && PYTHONIOENCODING=utf-8 uv run --env-file ../.env python -m weir_eval run --config cache_only --split all \
  --purge-cache --no-judge --min-interval 5
```
Expected: `purged …` lines, 150 progress lines, `errors 0`. Paraphrase members after the first in each cluster should mostly be hits.

- [ ] **Step 3: Warm replay.**
```bash
PYTHONIOENCODING=utf-8 uv run --env-file ../.env python -m weir_eval run --config cache_only \
  --workload datasets/workload-300-seed7.jsonl --no-judge --min-interval 5
```
Expected: 300 progress lines, `errors 0`, and a high hit rate (hits aren't paced, so this is fast).

- [ ] **Step 4: Request-log facts (bypass reasons, per-status cost).**
```bash
docker compose exec -T postgres psql -U weir -c "select cache_status, coalesce(bypass_reason,'-') reason, count(*), round(avg(latency_total_ms)) avg_ms, sum(cost_usd) cost, sum(counterfactual_cost_usd) cf from weir.request_log where config_label = 'cache_only' group by 1,2 order by 1,2"
docker compose stop
```

- [ ] **Step 5: Judge (stays within Qwen's daily budget).**
`rejudge` the cold report, then the workload report. Run in chunks of `timeout 580` until each says `not judged 0`. Answers identical to ones already graded are served from the judge cache for free.

- [ ] **Step 6: Exit gate.** From the two summaries:
1. **Wrong hits:** `wrong_hits = 0` on traps, and the trap hit rate is 0 (every trap was a miss).
2. **Quality:** the judge mean is within 0.1 of baseline v2 (the same queries for the cold pass), and the fact mean hasn't dropped.

If a wrong hit exists:
- Find its pair (its request's `cache_entry_id` → the entry's `query_text`).
- Fix the cause (lexicon or threshold) and record a ruling.
- Re-run the sweep (Task 12, Step 5), then this task from Step 2.

- [ ] **Step 7: Write `docs/results/cache-only.md`.**
- **The comparison table:**

  | Configuration | Cost per 1k | p50 | p95 | Judge | Facts | Hit rate | Wrong hits |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | Baseline v2 | | | | | | | |
  | Cache only, cold | | | | | | | |
  | Cache only, warm replay | | | | | | | |

- Latency by cache status (hit vs miss vs bypass), hit rate by group, and bypass reasons with counts.
- The workload's repeat rate, next to every hit-rate and cost number (main spec "Reporting honestly").
- Savings = counterfactual − actual, from the SQL in Step 4.
- Caveats: sequential, paced latency (not a load test); a synthetic KB; list prices.

Then:
- Add the D26+ decisions (any rulings that became decisions).
- Add a progress entry, **"Phase 2 exit ✅"** (or the recorded failure and its consequence).
- Link both results files in `docs/README.md`.

- [ ] **Step 8: Final whole-branch review, merge, push.** Run the executing-plans final review: one fresh reviewer on the most capable model, Critical and Important findings fixed TDD-first, Minors deferred. Then:
```bash
git push origin phase-2
git push origin phase-2:main && git branch -f main phase-2
gh run watch --exit-status   # CI green on all three suites
```
