# Weir Phase 0 + 1 (Foundations and Baseline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the hospital chatbot (`hospital-rag`) and a pass-through Weir gateway with per-request cost/latency logging, build the first 50-question eval set with a free LLM judge, and record the frozen baseline numbers.

**Architecture:** Docker Compose runs Postgres+pgvector, a one-shot `migrate` job, `hospital-rag` (FastAPI: `/retrieve`, `/generate`, `/info`) and `weir` (FastAPI: `/v1/query`, `/healthz`). In these phases Weir has no cache and no router: every request is logged as `cache_status=bypass`, goes to the large model (or the tier forced by `options.force_model`), and writes one `weir.request_log` row in the background. A separate `eval/` package replays the eval set through Weir, grades answers with key-fact checks plus a Gemini judge, and writes reports. Prometheus and Grafana join the compose file in Phase 4, not here.

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn, psycopg 3 (async + pool), pgvector, fastembed (`BAAI/bge-small-en-v1.5`), tokenizers, groq SDK, google-genai, httpx, pydantic v2, pydantic-settings, PyYAML, pytest + pytest-asyncio, Docker Compose, `pgvector/pgvector:0.8.0-pg16`.

**Spec:** `docs/superpowers/specs/2026-09-30-weir-design.md` (read §5, §8, §9, §10, §11, §16). The original vision lives in `docs/weir-original.md`.

## Global Constraints

- **Zero spend.** Only free tools and free tiers. Never add a paid dependency or service.
- Python `>=3.12,<3.13`, managed by `uv`, with one `pyproject.toml` + `uv.lock` per package (`services/weir`, `services/hospital-rag`, `eval`).
- LLMs: Groq free tier. Small `openai/gpt-oss-20b`, large `openai/gpt-oss-120b`. Limits per model: 30 RPM, 1K RPD, 8K TPM, 200K TPD. Model IDs live only in `configs/weir.yaml`.
- List prices (USD per 1M tokens): gpt-oss-20b $0.075 in / $0.30 out, gpt-oss-120b $0.15 in / $0.60 out, `BAAI/bge-small-en-v1.5` $0 / $0.
- Embeddings: `BAAI/bge-small-en-v1.5`, 384 dimensions, unit-normalized.
- Chunks are 250 tokens or fewer. Retrieval `k = 4`.
- Namespaces: `weir-general/en/public` (not sensitive), `weir-general/en/staff` (sensitive: no raw query text in logs).
- Judge: Gemini free tier, model `gemini-2.5-flash` by default (env `JUDGE_MODEL`).
- Secrets live only in the repo-root `.env`, which is gitignored. Never commit a key.
- **Line endings LF** (`.gitattributes` enforces them). All files UTF-8. Do **not** edit files with Windows PowerShell `Get-Content`/`Set-Content`, because that corrupts UTF-8. Use the editor tools or bash.
- **Windows:** psycopg async needs a selector event loop. Every test `conftest.py` and every local `asyncio` entry point sets it (code is given in the tasks).
- **No cache or router code in these phases.** That's the original spec's Phase 1 gate: the baseline must exist first.
- Work on branch `phase-0-1`. Commit after every task. Update `docs/progress.md` at the end of Tasks 6, 11 and 16.
- Tests needing Postgres are marked `@pytest.mark.db` and use `TEST_DATABASE_URL`, default `postgresql://weir:weir@localhost:5432/weir_test`. Start it with `docker compose up -d postgres`. Run the three packages' test suites one after another, not in parallel, because they share `weir_test`.

## Review Focus

1. **Groq 429 in the middle of a run.** hospital-rag must return 503 `{"error":"rate_limited","retry_after":...}`. Weir must return 503 with the `request_id` and a `Retry-After` header, and log the row as `status=error`. The eval runner must wait and retry instead of recording a failure. Tests: Task 6 (`test_generate_rate_limited_returns_503`), Task 11 (`test_rate_limited_generate_returns_503_with_request_id`), Task 15 (`test_ask_retries_on_503`).
2. **Wrong, missing or cross-tenant API key.** No key or a wrong key gets 401. A valid key for another namespace gets 403. The pipeline never runs and nothing is logged. Tests: Task 11 (`test_missing_key_401`, `test_wrong_namespace_403`).
3. **Retrieval finds nothing** (unknown namespace, or not ingested yet). hospital-rag `/generate` with zero chunks must return the NOT_FOUND message without calling the LLM, and Weir must return 200 with empty `sources`. Tests: Task 6 (`test_generate_with_no_chunks_skips_llm`), Task 11 (`test_no_chunks_returns_not_found_answer`).
4. **Messy model output.** Citations to labels that weren't provided (`[c9]`), grouped citations (`[c1, c3]`), no citations at all, or a reply starting `NOT_FOUND`. The parser must never crash, must keep only valid chunk IDs, and must strip the markers. Tests: Task 5 (`test_parse_*`).
5. **Log database unavailable.** If writing `request_log` fails, the user's request must still succeed and the failure must be counted. Test: Task 10 (`test_write_failure_is_counted_not_raised`).

---

## File map

```text
.gitattributes, .gitignore, .dockerignore, .env.example        repo hygiene (Task 1)
docker-compose.yml                                              postgres, migrate (T1), hospital-rag (T6), weir (T11)
db/init/00-test-db.sql                                          creates weir_test (T1)
db/migrations/001_init.sql                                      full schema, spec §10 (T1)
configs/weir.yaml, configs/ablations/baseline.yaml              gateway config (T7)
configs/tenants.yaml                                            API-key tenants (T7)
configs/prices.yaml                                             list prices (T9)
kb/README.md, kb/public/*.md, kb/staff/*.md                     Weir General Hospital KB (T2)

services/weir/
  pyproject.toml, uv.lock, Dockerfile
  src/weir/__init__.py
  src/weir/migrate.py          apply numbered SQL migrations (T1)
  src/weir/db.py               async pool with pgvector registered (T10)
  src/weir/settings.py         env settings (T7)
  src/weir/config.py           weir.yaml + ablation overlay -> WeirConfig (T7)
  src/weir/auth.py             tenants and API keys (T7)
  src/weir/text.py             normalize + query_hash (T7)
  src/weir/rag/__init__.py, src/weir/rag/adapter.py   hospital-rag HTTP client (T8)
  src/weir/llm/__init__.py, src/weir/llm/pricing.py   price table + cost (T9)
  src/weir/metrics/__init__.py, src/weir/metrics/logger.py   async request-log writer (T10)
  src/weir/pipeline.py         request models + pass-through pipeline (T11)
  src/weir/main.py             FastAPI app (T11)
  tests/conftest.py, tests/test_*.py

services/hospital-rag/
  pyproject.toml, uv.lock, Dockerfile
  src/hospital_rag/__init__.py
  src/hospital_rag/aio.py        Windows-safe asyncio runner (T4)
  src/hospital_rag/settings.py   (T3)
  src/hospital_rag/embedding.py  bge-small embedder + token counter (T3)
  src/hospital_rag/chunking.py   markdown -> chunks (T3)
  src/hospital_rag/kb.py         frontmatter parse, load KB, kb_version (T4)
  src/hospital_rag/db.py         async pool (T4)
  src/hospital_rag/store.py      rag.* reads and writes (T4)
  src/hospital_rag/ingest.py     CLI (T4)
  src/hospital_rag/prompt.py     prompt build + answer parse (T5)
  src/hospital_rag/llm.py        Groq + stub LLM clients (T5)
  src/hospital_rag/schemas.py    API models (T6)
  src/hospital_rag/service.py    generate() orchestration (T6)
  src/hospital_rag/main.py       FastAPI app (T6)
  tests/conftest.py, tests/test_*.py

eval/
  pyproject.toml, uv.lock
  src/weir_eval/__init__.py, __main__.py
  src/weir_eval/dataset.py     EvalQuery, load/save/validate/assign_splits (T12)
  src/weir_eval/keyfacts.py    fact matching (T12)
  src/weir_eval/kb.py          KB text loader + facts-in-source check (T12)
  src/weir_eval/retry.py       async retry helper (T14)
  src/weir_eval/judge.py       Gemini judge with disk cache (T14)
  src/weir_eval/summary.py     percentiles, summary, markdown, spot checks (T15)
  src/weir_eval/runner.py      replay through Weir (T15)
  src/weir_eval/cli.py         validate / assign-splits / run (T15)
  datasets/queries.jsonl       50 queries (T13)
  reports/                     run outputs (T16)
  tests/conftest.py, tests/test_*.py

.github/workflows/tests.yml                                     CI (T16)
docs/results/baseline.md                                        frozen baseline (T16)
```

---

## Phase 0: Foundations

### Task 1: Repo scaffolding, Postgres, and migrations

**Files:**
- Create: `.dockerignore`, `.env.example`, `configs/README.md`, `docker-compose.yml`, `db/init/00-test-db.sql`, `db/migrations/001_init.sql` (`.gitattributes` already exists; keep it)
- Create: `services/weir/pyproject.toml`, `services/weir/Dockerfile`, `services/weir/src/weir/__init__.py`, `services/weir/src/weir/migrate.py`
- Test: `services/weir/tests/conftest.py`, `services/weir/tests/test_migrate.py`

**Interfaces:**
- Produces: `weir.migrate.apply_migrations(url: str, directory: pathlib.Path) -> list[str]` (the file names applied by this call). The CLI is `python -m weir.migrate` and reads `DATABASE_URL` and `WEIR_MIGRATIONS_DIR` (default `/app/db/migrations`).
- Produces: the full database schema (spec §10 plus `rag.kb_versions`) used by every later task.
- Produces the conftest fixtures `clean_db_url` and `migrated_db_url` (both return a URL string for a reset `weir_test` DB).

- [ ] **Step 1: Create the branch**

```bash
git checkout -b phase-0-1
```

- [ ] **Step 2: Repo hygiene files**

`.dockerignore`:
```text
.git
**/.venv
**/__pycache__
**/.pytest_cache
.env
docs
eval
```

`.env.example`:
```text
# Groq free tier: https://console.groq.com/keys
GROQ_API_KEY=
# Gemini free tier: https://aistudio.google.com/apikey
GEMINI_API_KEY=
# Weir tenant API keys. Generate each with:
#   uv run python -c "import secrets; print(secrets.token_urlsafe(24))"
WEIR_KEY_PUBLIC=
WEIR_KEY_STAFF=
WEIR_KEY_ADMIN=
# Optional ablation overlay from configs/ablations/ (e.g. baseline). Empty = none.
WEIR_ABLATION=
# hospital-rag LLM mode: groq or stub
LLM_MODE=groq
# Judge model for eval (Gemini free tier)
JUDGE_MODEL=gemini-2.5-flash
```

`db/init/00-test-db.sql`:
```sql
create database weir_test;
```

`configs/README.md` (the Weir Dockerfile copies `configs/`, so the folder must exist from Task 1):
```markdown
# configs

- `weir.yaml`: gateway settings (models, kill switches, namespaces). Added in Task 7.
- `ablations/*.yaml`: overlays merged on top of `weir.yaml`, selected with `WEIR_ABLATION`.
- `tenants.yaml`: API-key tenants. Keys come from `.env`, never from this folder.
- `prices.yaml`: list prices with effective dates. Added in Task 9.
```

- [ ] **Step 3: Write the schema migration**

`db/migrations/001_init.sql`:
```sql
create extension if not exists vector;
create schema if not exists rag;
create schema if not exists weir;

-- hospital-rag ------------------------------------------------------------
create table rag.documents (
  id text primary key,
  namespace text not null,
  title text not null,
  path text not null,
  kb_version text not null,
  content_hash text not null,
  ingested_at timestamptz not null default now()
);

create table rag.chunks (
  id text primary key,
  doc_id text not null references rag.documents(id) on delete cascade,
  namespace text not null,
  kb_version text not null,
  chunk_index int not null,
  text text not null,
  token_count int not null,
  embedding vector(384) not null
);
create index on rag.chunks using hnsw (embedding vector_cosine_ops);
create index on rag.chunks (namespace, kb_version);

create table rag.kb_versions (
  namespace text primary key,
  kb_version text not null,
  updated_at timestamptz not null default now()
);

-- weir --------------------------------------------------------------------
create table weir.cache_entries (
  id uuid primary key,
  namespace text not null,
  kb_version text not null,
  prompt_version text not null,
  query_text text not null,
  embedding vector(384) not null,
  answer text not null,
  sources jsonb not null,
  source_ids text[] not null,
  model text not null,
  tokens_in int not null,
  tokens_out int not null,
  hit_count int not null default 0,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index on weir.cache_entries using hnsw (embedding vector_cosine_ops);
create index on weir.cache_entries (namespace, kb_version, prompt_version);
create index on weir.cache_entries using gin (source_ids);

create table weir.model_prices (
  model text not null,
  usd_per_m_input numeric not null,
  usd_per_m_output numeric not null default 0,
  effective_from date not null,
  primary key (model, effective_from)
);

create table weir.request_log (
  request_id uuid primary key,
  ts timestamptz not null,
  namespace text not null,
  cache_status text not null check (cache_status in ('hit','miss','bypass')),
  bypass_reason text,
  similarity real,
  cache_entry_id uuid,
  route text not null check (route in ('none','small','large')),
  escalated boolean not null default false,
  model_calls smallint not null default 0,
  model text,
  tokens_in int,
  tokens_out int,
  embed_tokens int,
  retrieval_top_score real,
  grounding_passed boolean,
  latency_embed_ms int,
  latency_cache_ms int,
  latency_retrieval_ms int,
  latency_llm_ms int,
  latency_total_ms int not null,
  cost_usd numeric not null default 0,
  counterfactual_cost_usd numeric not null default 0,
  status text not null check (status in ('ok','error','timeout')),
  error_detail text,
  query_hash text not null,
  query_text text,
  answer_len int,
  config_label text
);
create index on weir.request_log (ts);
create index on weir.request_log (namespace, ts);

create table weir.feedback (
  request_id uuid not null references weir.request_log(request_id),
  rating smallint not null,
  comment text,
  ts timestamptz not null default now()
);
```

- [ ] **Step 4: Weir package skeleton**

`services/weir/pyproject.toml`:
```toml
[project]
name = "weir"
version = "0.1.0"
description = "Semantic cache + model router gateway in front of a RAG service"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "httpx>=0.27",
  "psycopg[binary,pool]>=3.2",
  "pgvector>=0.3",
  "numpy>=1.26",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "pyyaml>=6.0",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/weir"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
markers = ["db: needs the compose Postgres (weir_test database)"]
```

`services/weir/src/weir/__init__.py`:
```python
"""Weir: a semantic-cache and model-routing gateway in front of a RAG service."""
```

`services/weir/Dockerfile` (build context is the repo root):
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY services/weir/pyproject.toml services/weir/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/weir/src ./src
RUN uv sync --frozen --no-dev
COPY db/migrations /app/db/migrations
COPY configs /app/configs
EXPOSE 8000
CMD ["uvicorn", "weir.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker-compose.yml`:
```yaml
name: weir

services:
  postgres:
    image: pgvector/pgvector:0.8.0-pg16
    environment:
      POSTGRES_USER: weir
      POSTGRES_PASSWORD: weir
      POSTGRES_DB: weir
    ports: ["${PG_PORT:-5432}:5432"]
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U weir -d weir"]
      interval: 3s
      timeout: 3s
      retries: 20

  migrate:
    build: { context: ., dockerfile: services/weir/Dockerfile }
    command: ["python", "-m", "weir.migrate"]
    environment:
      DATABASE_URL: postgresql://weir:weir@postgres:5432/weir
    depends_on:
      postgres: { condition: service_healthy }

volumes:
  pgdata:
```

Run: `cd services/weir && uv lock && uv sync`
Expected: `uv.lock` created, `.venv` created with Python 3.12 (uv downloads it if needed).

- [ ] **Step 5: Test fixtures**

`services/weir/tests/conftest.py`:
```python
import asyncio
import os
import sys
from pathlib import Path

import psycopg
import pytest

from weir.migrate import apply_migrations

if sys.platform == "win32":  # psycopg async cannot use the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO / "db" / "migrations"
CONFIGS = REPO / "configs"
TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://weir:weir@localhost:5432/weir_test")


def _reset(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "drop schema if exists rag cascade; drop schema if exists weir cascade; "
            "drop table if exists public.schema_migrations"
        )


@pytest.fixture
def clean_db_url() -> str:
    _reset(TEST_DB)
    return TEST_DB


@pytest.fixture
def migrated_db_url(clean_db_url: str) -> str:
    apply_migrations(clean_db_url, MIGRATIONS)
    return clean_db_url
```

- [ ] **Step 6: Write the failing migration test**

`services/weir/tests/test_migrate.py`:
```python
import psycopg
import pytest

from weir.migrate import apply_migrations

from .conftest import MIGRATIONS

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "rag.documents", "rag.chunks", "rag.kb_versions",
    "weir.cache_entries", "weir.model_prices", "weir.request_log", "weir.feedback",
}


def test_applies_all_then_is_idempotent(clean_db_url):
    assert apply_migrations(clean_db_url, MIGRATIONS) == ["001_init.sql"]
    assert apply_migrations(clean_db_url, MIGRATIONS) == []


def test_creates_schema_and_pgvector_0_8(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(clean_db_url) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "select schemaname || '.' || tablename from pg_tables "
                "where schemaname in ('rag', 'weir')"
            )
        }
        version = conn.execute(
            "select extversion from pg_extension where extname = 'vector'"
        ).fetchone()[0]
    assert EXPECTED_TABLES <= tables
    major, minor = (int(x) for x in version.split(".")[:2])
    assert (major, minor) >= (0, 8)  # needed for hnsw.iterative_scan
```

Also create an empty `services/weir/tests/__init__.py` so `from .conftest import ...` works.

- [ ] **Step 7: Start Postgres and run the test to verify it fails**

Run: `docker compose up -d postgres` (from the repo root), then `cd services/weir && uv run pytest tests/test_migrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'weir.migrate'` (or an ImportError in the conftest).

- [ ] **Step 8: Implement the migration runner**

`services/weir/src/weir/migrate.py`:
```python
"""Apply numbered SQL migrations in file-name order, once each.

Usage: python -m weir.migrate   (reads DATABASE_URL and WEIR_MIGRATIONS_DIR)
"""
import os
from pathlib import Path

import psycopg


def apply_migrations(url: str, directory: Path) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "create table if not exists public.schema_migrations ("
            " version text primary key,"
            " applied_at timestamptz not null default now())"
        )
        done = {r[0] for r in conn.execute("select version from public.schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "insert into public.schema_migrations (version) values (%s)", (path.name,)
                )
            applied.append(path.name)
    return applied


def main() -> None:
    url = os.environ["DATABASE_URL"]
    directory = Path(os.environ.get("WEIR_MIGRATIONS_DIR", "/app/db/migrations"))
    applied = apply_migrations(url, directory)
    print(f"applied {len(applied)} migration(s): {', '.join(applied) or 'none'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `cd services/weir && uv run pytest tests/test_migrate.py -v`
Expected: 2 passed.

- [ ] **Step 10: Verify the compose migrate job**

Run: `docker compose up --build migrate`
Expected: the log shows `applied 1 migration(s): 001_init.sql`, and the container exits with code 0. Running it again prints `applied 0 migration(s): none`.

- [ ] **Step 11: Commit**

```bash
git add .dockerignore .env.example configs docker-compose.yml db services/weir
git commit -m "feat: compose postgres+pgvector, schema migration and runner"
```

---

### Task 2: Weir General Hospital knowledge base (content task, suited to a subagent)

**Files:**
- Create: `kb/README.md`, 30 files in `kb/public/`, 10 files in `kb/staff/`

**Interfaces:**
- Produces Markdown files, each starting with YAML frontmatter holding `id` and `title`, then a body with `##` sections. `id` equals the file name without `.md`. Task 4's ingest and Task 12's KB loader parse exactly this format.

**Writing rules (put these in the subagent prompt verbatim):**
- The hospital is fictional: "Weir General Hospital", 12 Riverside Road, Weir City. Invent every fact. No real people, brands, phone numbers or emails.
- Contact points are 4-digit internal extensions only, written like `ext. 2140`. Never include a number with 6 or more digits.
- Money is in rupees, written like `₹1,500`. Times are written like `4 pm`, `11:30 am`.
- Each document is 150–400 words, with 2–5 `##` sections, and states concrete facts (times, days, prices, floors, counts, documents needed, steps).
- **No clinical advice** (doses, symptoms, diagnoses, treatments). Procedures and logistics only.
- Facts must stay consistent across documents. For example, the department directory's extension for Cardiology must match the Cardiology OPD document.
- Plant these **look-alike pairs**, with clearly different facts in each:
  1. General ward visiting hours vs ICU visiting hours
  2. Cardiology OPD days/times vs Neurology OPD days/times
  3. Car parking rates vs two-wheeler parking rates, and weekday vs weekend rates
  4. Adult vaccination clinic days vs child vaccination clinic days
  5. Nurse shift timings vs doctor shift timings (staff)
  6. Cashless insurance admission deposit vs self-pay admission deposit
  7. Private room tariff vs semi-private room tariff
  8. Main pharmacy hours (24 hours) vs OPD pharmacy hours

Frontmatter format (exact):
```markdown
---
id: pub-visiting-hours-general
title: General ward visiting hours
---

## Weekdays
...
```

**Documents to write:**

Public (`kb/public/`): `pub-visiting-hours-general`, `pub-visiting-hours-icu`, `pub-visiting-hours-pediatric`, `pub-visiting-hours-maternity`, `pub-departments-directory`, `pub-contact-and-location`, `pub-opd-cardiology`, `pub-opd-neurology`, `pub-opd-orthopedics`, `pub-opd-pediatrics`, `pub-emergency`, `pub-admission-process`, `pub-discharge-process`, `pub-room-tariffs`, `pub-billing-self-pay`, `pub-billing-insurance`, `pub-billing-government-scheme`, `pub-refunds`, `pub-parking`, `pub-pharmacy`, `pub-cafeteria`, `pub-lab-reports`, `pub-radiology-appointments`, `pub-health-checkup-packages`, `pub-vaccination-clinic`, `pub-blood-bank`, `pub-medical-records`, `pub-patient-rights`, `pub-feedback-complaints`, `pub-attendant-passes`.

Staff (`kb/staff/`): `staff-patient-registration-sop`, `staff-shift-timings`, `staff-leave-policy`, `staff-code-blue-procedure`, `staff-biomedical-waste`, `staff-it-helpdesk`, `staff-id-badge-policy`, `staff-incident-reporting`, `staff-discharge-summary-sop`, `staff-canteen-allowance`.

`kb/README.md` describes the fictional hospital in one paragraph, lists every document id and title, and lists the 8 planted look-alike pairs with the file and exact fact on each side. Task 13's question authors use this list. `kb/README.md` is not ingested, because ingest only reads `public/` and `staff/`.

- [ ] **Step 1: Write the 40 documents and `kb/README.md`** following the rules above.

- [ ] **Step 2: Verify structure mechanically**

Run (from the repo root):
```bash
uv run --no-project python - <<'EOF'
import pathlib, re
ids = []
for p in sorted(pathlib.Path("kb").glob("*/*.md")):
    t = p.read_text(encoding="utf-8")
    m = re.match(r"^---\nid: (.+)\ntitle: (.+)\n---\n", t)
    assert m, f"bad frontmatter: {p}"
    assert m.group(1) == p.stem, f"id != filename: {p}"
    words = len(t.split())
    assert 150 <= words <= 460, f"{p}: {words} words"
    assert not re.search(r"\d{6,}", t), f"6+ digit number in {p}"
    assert not re.search(r"[\w.]+@[\w.]+", t), f"email-like text in {p}"
    ids.append(m.group(1))
assert len(ids) == len(set(ids)) == 40, len(ids)
print("ok", len(ids))
EOF
```
Expected: `ok 40`

- [ ] **Step 3: Spot-read the planted pairs.** Open the 8 pairs listed in `kb/README.md` and confirm each side states a different, explicit fact.

- [ ] **Step 4: Commit**

```bash
git add kb
git commit -m "docs: add fictional Weir General Hospital knowledge base (40 docs)"
```

---

### Task 3: hospital-rag package, settings, embedder, and chunker

**Files:**
- Create: `services/hospital-rag/pyproject.toml`, `src/hospital_rag/__init__.py`, `src/hospital_rag/settings.py`, `src/hospital_rag/embedding.py`, `src/hospital_rag/chunking.py`
- Test: `services/hospital-rag/tests/__init__.py`, `tests/conftest.py`, `tests/test_embedding.py`, `tests/test_chunking.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings) with fields `database_url, groq_api_key, llm_mode ("groq"|"stub"), stub_latency_ms, groq_timeout_s, max_completion_tokens, reasoning_effort, embed_model, embed_cache_dir, retrieve_k, chunk_max_tokens`.
- Produces: `Embedder(model_name: str, cache_dir: str | None = None)` with `.embed(texts: list[str]) -> list[numpy.ndarray]` (float32, shape (384,), unit norm) and `.count_tokens(text: str) -> int`.
- Produces: `ChunkText(index: int, text: str, token_count: int)` and `chunk_document(title: str, body: str, count_tokens: Callable[[str], int], max_tokens: int = 250, overlap_words: int = 30) -> list[ChunkText]`.

- [ ] **Step 1: Package files**

`services/hospital-rag/pyproject.toml`:
```toml
[project]
name = "hospital-rag"
version = "0.1.0"
description = "Minimal RAG chatbot for the fictional Weir General Hospital"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "psycopg[binary,pool]>=3.2",
  "pgvector>=0.3",
  "numpy>=1.26",
  "fastembed>=0.4",
  "tokenizers>=0.19",
  "groq>=0.11",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "pyyaml>=6.0",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "httpx>=0.27"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/hospital_rag"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
markers = ["db: needs the compose Postgres (weir_test database)"]
```

`src/hospital_rag/__init__.py`:
```python
"""hospital-rag: the basic chatbot that Weir sits in front of."""
```

`src/hospital_rag/settings.py`:
```python
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql://weir:weir@localhost:5432/weir"
    groq_api_key: str = ""
    llm_mode: Literal["groq", "stub"] = "groq"
    stub_latency_ms: int = 800
    groq_timeout_s: float = 20.0
    max_completion_tokens: int = 700
    reasoning_effort: str | None = "low"  # gpt-oss models: low | medium | high
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str | None = None
    retrieve_k: int = 4
    chunk_max_tokens: int = 250
```

`tests/__init__.py`: empty.

`tests/conftest.py`:
```python
import asyncio
import os
import sys
from pathlib import Path

import psycopg
import pytest

if sys.platform == "win32":  # psycopg async cannot use the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO / "db" / "migrations"
TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://weir:weir@localhost:5432/weir_test")


@pytest.fixture
def migrated_db_url() -> str:
    """Fresh weir_test with every migration applied (plain replay, no tracking table)."""
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute(
            "drop schema if exists rag cascade; drop schema if exists weir cascade; "
            "drop table if exists public.schema_migrations"
        )
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
    return TEST_DB


def word_count(text: str) -> int:
    return len(text.split())
```

Run: `cd services/hospital-rag && uv lock && uv sync`
Expected: lock and venv created.

- [ ] **Step 2: Write the failing chunker tests**

`tests/test_chunking.py`:
```python
from hospital_rag.chunking import chunk_document, split_sections

from .conftest import word_count

DOC = """Intro line before any heading.

## Weekdays

Visiting is from 4 pm to 8 pm.

Two visitors at a time.

## Weekends

Visiting is from 11 am to 8 pm.
"""


def test_split_sections_keeps_preamble_and_headings():
    sections = split_sections(DOC)
    assert [h for h, _ in sections] == ["", "Weekdays", "Weekends"]
    assert "4 pm to 8 pm" in sections[1][1]


def test_chunks_carry_title_and_heading_prefix():
    chunks = chunk_document("General ward visiting hours", DOC, word_count, max_tokens=250)
    assert chunks[1].text.startswith("General ward visiting hours: Weekdays\n")
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_every_chunk_within_budget_and_counts_match():
    long_para = " ".join(f"word{i}" for i in range(700))
    body = f"## Big\n\n{long_para}\n\n## Small\n\nshort text"
    chunks = chunk_document("T", body, word_count, max_tokens=100, overlap_words=10)
    assert all(c.token_count <= 100 for c in chunks)
    assert all(c.token_count == word_count(c.text) for c in chunks)


def test_long_paragraph_windows_overlap():
    long_para = " ".join(f"w{i}" for i in range(300))
    chunks = chunk_document("T", f"## S\n\n{long_para}", word_count, max_tokens=60, overlap_words=10)
    first = chunks[0].text.split()
    second = chunks[1].text.split()
    assert first[-1] in second  # consecutive windows share words


def test_paragraphs_packed_together_when_they_fit():
    chunks = chunk_document("T", DOC, word_count, max_tokens=250)
    weekdays = [c for c in chunks if "Weekdays" in c.text]
    assert len(weekdays) == 1
    assert "Two visitors" in weekdays[0].text
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_chunking.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hospital_rag.chunking'`.

- [ ] **Step 4: Implement the chunker**

`src/hospital_rag/chunking.py`:
```python
"""Split a Markdown document into retrieval chunks of at most `max_tokens` tokens.

Sections are cut at headings; each chunk is prefixed with "<title>: <heading>" so it
stands alone. Paragraphs are packed greedily; a paragraph larger than the budget is
cut into overlapping word windows.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass

HEADING = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass(frozen=True)
class ChunkText:
    index: int
    text: str
    token_count: int


def split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading, lines = "", []
    for line in body.splitlines():
        match = HEADING.match(line)
        if match:
            if any(l.strip() for l in lines):
                sections.append((heading, "\n".join(lines).strip()))
            heading, lines = match.group(1).strip(), []
        else:
            lines.append(line)
    if any(l.strip() for l in lines):
        sections.append((heading, "\n".join(lines).strip()))
    return sections


def chunk_document(
    title: str,
    body: str,
    count_tokens: Callable[[str], int],
    max_tokens: int = 250,
    overlap_words: int = 30,
) -> list[ChunkText]:
    texts: list[str] = []
    for heading, text in split_sections(body):
        prefix = f"{title}: {heading}\n" if heading else f"{title}\n"
        budget = max_tokens - count_tokens(prefix)
        for part in _pack_paragraphs(text, count_tokens, budget, overlap_words):
            texts.append(prefix + part)
    return [ChunkText(i, t, count_tokens(t)) for i, t in enumerate(texts)]


def _pack_paragraphs(
    text: str, count_tokens: Callable[[str], int], budget: int, overlap_words: int
) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    current = ""
    for para in paragraphs:
        if count_tokens(para) > budget:
            if current:
                out.append(current)
                current = ""
            out.extend(_word_windows(para, count_tokens, budget, overlap_words))
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if count_tokens(candidate) <= budget:
            current = candidate
        else:
            out.append(current)
            current = para
    if current:
        out.append(current)
    return out


def _word_windows(
    text: str, count_tokens: Callable[[str], int], budget: int, overlap_words: int
) -> list[str]:
    words = text.split()
    out: list[str] = []
    start = 0
    while start < len(words):
        end = start + 1
        while end < len(words) and count_tokens(" ".join(words[start : end + 1])) <= budget:
            end += 1
        out.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = max(end - overlap_words, start + 1)
    return out
```

Note on the budget: the prefix plus a joined part can come out one or two tokens over the sum of their counts with a real tokenizer. The tests use word counts, which are exact. The real-KB check in Task 4 asserts that every chunk is 260 tokens or fewer.

- [ ] **Step 5: Run the chunker tests**

Run: `uv run pytest tests/test_chunking.py -v`
Expected: 5 passed.

- [ ] **Step 6: Write the failing embedder tests**

`tests/test_embedding.py`:
```python
import numpy as np
import pytest

from hospital_rag.embedding import Embedder


@pytest.fixture(scope="module")
def embedder():
    return Embedder("BAAI/bge-small-en-v1.5")  # first run downloads ~70 MB


def test_vectors_are_384_dim_unit_norm(embedder):
    [v] = embedder.embed(["What are the ICU visiting hours?"])
    assert v.shape == (384,)
    assert v.dtype == np.float32
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_paraphrase_closer_than_unrelated(embedder):
    a, b, c = embedder.embed([
        "When can I visit a patient in the ICU?",
        "What are the visiting hours for the intensive care unit?",
        "How much does parking cost for a car?",
    ])
    assert float(a @ b) > float(a @ c)


def test_count_tokens(embedder):
    assert embedder.count_tokens("visiting hours") >= 2
    assert embedder.count_tokens("") == 0
```

- [ ] **Step 7: Run to verify failure**

Run: `uv run pytest tests/test_embedding.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hospital_rag.embedding'`.

- [ ] **Step 8: Implement the embedder**

`src/hospital_rag/embedding.py`:
```python
import numpy as np
from fastembed import TextEmbedding
from tokenizers import Tokenizer


class Embedder:
    """Local bge-small embeddings (free, CPU) plus the matching tokenizer for counts."""

    dim = 384

    def __init__(self, model_name: str, cache_dir: str | None = None):
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self._tokenizer = Tokenizer.from_pretrained(model_name)

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        vectors = []
        for raw in self._model.embed(texts):
            v = np.asarray(raw, dtype=np.float32)
            vectors.append(v / np.linalg.norm(v))
        return vectors

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
```

- [ ] **Step 9: Run all tests**

Run: `uv run pytest tests/test_chunking.py tests/test_embedding.py -v`
Expected: 8 passed.

- [ ] **Step 10: Commit**

```bash
git add services/hospital-rag
git commit -m "feat(hospital-rag): settings, bge-small embedder, markdown chunker"
```

---

### Task 4: KB loading, vector store, and ingest CLI

**Files:**
- Create: `src/hospital_rag/aio.py`, `src/hospital_rag/kb.py`, `src/hospital_rag/db.py`, `src/hospital_rag/store.py`, `src/hospital_rag/ingest.py`
- Test: `tests/test_kb.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `ChunkText`, `chunk_document`, `Embedder` (Task 3).
- Produces: `KbDoc(namespace, id, title, path, body, content_hash)`; `parse_doc(text: str) -> tuple[dict, str]`; `load_kb(kb_dir: Path) -> list[KbDoc]`; `kb_version(docs: list[KbDoc]) -> str` (12 hex chars); `NAMESPACE_DIRS = {"public": "weir-general/en/public", "staff": "weir-general/en/staff"}`.
- Produces: `open_pool(url: str, max_size: int = 10) -> AsyncConnectionPool` (async, pgvector registered).
- Produces: `ChunkRecord(doc_id: str, chunk: ChunkText, embedding: np.ndarray)`; `RetrievedChunk(id, doc_id, title, text, score: float, token_count: int)`; `async replace_namespace(pool, namespace, kb_version, docs, records) -> None`; `async search(pool, namespace, embedding, k) -> tuple[str | None, list[RetrievedChunk]]` (kb_version or None, chunks sorted by score descending); `async versions(pool) -> dict[str, str]`.
- Produces: `run(coro)` in `aio.py`, which runs a coroutine on a selector loop on Windows.
- Produces the CLI `python -m hospital_rag.ingest --kb PATH`.

- [ ] **Step 1: Write the failing KB tests**

`tests/test_kb.py`:
```python
import pytest

from hospital_rag.kb import kb_version, load_kb, parse_doc


def write(path, doc_id, title, body="## A\n\nText."):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {doc_id}\ntitle: {title}\n---\n\n{body}\n", encoding="utf-8")


def test_parse_doc_reads_frontmatter():
    meta, body = parse_doc("---\nid: x\ntitle: Hello\n---\n\n## S\n\nBody")
    assert meta == {"id": "x", "title": "Hello"}
    assert body.startswith("## S")


def test_parse_doc_rejects_missing_id():
    with pytest.raises(ValueError, match="id"):
        parse_doc("---\ntitle: Hello\n---\nBody")


def test_load_kb_maps_folders_to_namespaces(tmp_path):
    write(tmp_path / "public" / "pub-a.md", "pub-a", "A")
    write(tmp_path / "staff" / "staff-b.md", "staff-b", "B")
    (tmp_path / "README.md").write_text("not ingested", encoding="utf-8")
    docs = {d.id: d for d in load_kb(tmp_path)}
    assert docs["pub-a"].namespace == "weir-general/en/public"
    assert docs["staff-b"].namespace == "weir-general/en/staff"
    assert len(docs) == 2


def test_load_kb_rejects_duplicate_ids(tmp_path):
    write(tmp_path / "public" / "one.md", "same", "A")
    write(tmp_path / "public" / "two.md", "same", "B")
    with pytest.raises(ValueError, match="duplicate"):
        load_kb(tmp_path)


def test_kb_version_changes_only_when_content_changes(tmp_path):
    write(tmp_path / "public" / "pub-a.md", "pub-a", "A")
    v1 = kb_version(load_kb(tmp_path))
    assert v1 == kb_version(load_kb(tmp_path))
    write(tmp_path / "public" / "pub-a.md", "pub-a", "A", body="## A\n\nChanged.")
    v2 = kb_version(load_kb(tmp_path))
    assert v1 != v2 and len(v2) == 12
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_kb.py -v`
Expected: FAIL, `No module named 'hospital_rag.kb'`.

- [ ] **Step 3: Implement kb.py and aio.py**

`src/hospital_rag/kb.py`:
```python
"""Load the Markdown knowledge base. Folder name picks the namespace."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

NAMESPACE_DIRS = {
    "public": "weir-general/en/public",
    "staff": "weir-general/en/staff",
}


@dataclass(frozen=True)
class KbDoc:
    namespace: str
    id: str
    title: str
    path: str
    body: str
    content_hash: str


def parse_doc(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("document must start with YAML frontmatter ('---')")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("frontmatter is not closed with '---'")
    meta = yaml.safe_load(text[4:end]) or {}
    for key in ("id", "title"):
        if not meta.get(key):
            raise ValueError(f"frontmatter is missing '{key}'")
    body = text[end + 4 :].lstrip("\n")
    return {"id": str(meta["id"]), "title": str(meta["title"])}, body


def load_kb(kb_dir: Path) -> list[KbDoc]:
    docs: list[KbDoc] = []
    seen: set[str] = set()
    for folder, namespace in NAMESPACE_DIRS.items():
        for path in sorted((kb_dir / folder).glob("*.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = parse_doc(text)
            if meta["id"] in seen:
                raise ValueError(f"duplicate document id: {meta['id']}")
            seen.add(meta["id"])
            docs.append(KbDoc(
                namespace=namespace,
                id=meta["id"],
                title=meta["title"],
                path=f"{folder}/{path.name}",
                body=body,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ))
    return docs


def kb_version(docs: list[KbDoc]) -> str:
    digest = hashlib.sha256()
    for doc in sorted(docs, key=lambda d: d.id):
        digest.update(f"{doc.id}:{doc.content_hash}\n".encode())
    return digest.hexdigest()[:12]
```

`src/hospital_rag/aio.py`:
```python
import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    """asyncio.run, but on a selector loop on Windows (psycopg async needs it)."""
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)
```

- [ ] **Step 4: Run the KB tests**

Run: `uv run pytest tests/test_kb.py -v`
Expected: 5 passed.

- [ ] **Step 5: Write the failing store tests**

`tests/test_store.py`:
```python
import numpy as np
import pytest

from hospital_rag.chunking import ChunkText
from hospital_rag.db import open_pool
from hospital_rag.kb import KbDoc
from hospital_rag.store import ChunkRecord, replace_namespace, search, versions

pytestmark = pytest.mark.db
NS = "weir-general/en/public"


def unit(i: int) -> np.ndarray:
    v = np.zeros(384, dtype=np.float32)
    v[i] = 1.0
    return v


def doc(doc_id: str) -> KbDoc:
    return KbDoc(NS, doc_id, f"Title {doc_id}", f"public/{doc_id}.md", "body", "hash")


def records(doc_id: str, axes: list[int]) -> list[ChunkRecord]:
    return [ChunkRecord(doc_id, ChunkText(i, f"{doc_id} chunk {i}", 5), unit(a)) for i, a in enumerate(axes)]


async def test_search_returns_nearest_first(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        await replace_namespace(pool, NS, "v1", [doc("a"), doc("b")], records("a", [0, 1]) + records("b", [2]))
        version, chunks = await search(pool, NS, unit(2), k=2)
        assert version == "v1"
        assert chunks[0].id == "b#0" and chunks[0].title == "Title b"
        assert chunks[0].score == pytest.approx(1.0)
        assert chunks[0].score >= chunks[1].score
    finally:
        await pool.close()


async def test_replace_removes_old_chunks_and_updates_version(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        await replace_namespace(pool, NS, "v1", [doc("a")], records("a", [0]))
        await replace_namespace(pool, NS, "v2", [doc("c")], records("c", [0]))
        version, chunks = await search(pool, NS, unit(0), k=4)
        assert version == "v2"
        assert [c.doc_id for c in chunks] == ["c"]
        assert await versions(pool) == {NS: "v2"}
    finally:
        await pool.close()


async def test_unknown_namespace_returns_nothing(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        assert await search(pool, "nope/en/x", unit(0), k=4) == (None, [])
    finally:
        await pool.close()
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL, `No module named 'hospital_rag.db'`.

- [ ] **Step 7: Implement db.py and store.py**

`src/hospital_rag/db.py`:
```python
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool


async def open_pool(url: str, max_size: int = 10) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        url, min_size=1, max_size=max_size, open=False, configure=register_vector_async
    )
    await pool.open(wait=True)
    return pool
```

`src/hospital_rag/store.py`:
```python
from dataclasses import dataclass

import numpy as np
from psycopg_pool import AsyncConnectionPool

from .chunking import ChunkText
from .kb import KbDoc


@dataclass(frozen=True)
class ChunkRecord:
    doc_id: str
    chunk: ChunkText
    embedding: np.ndarray


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    doc_id: str
    title: str
    text: str
    score: float
    token_count: int


async def replace_namespace(
    pool: AsyncConnectionPool,
    namespace: str,
    kb_version: str,
    docs: list[KbDoc],
    records: list[ChunkRecord],
) -> None:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("delete from rag.documents where namespace = %s", (namespace,))
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into rag.documents (id, namespace, title, path, kb_version, content_hash)"
                " values (%s, %s, %s, %s, %s, %s)",
                [(d.id, namespace, d.title, d.path, kb_version, d.content_hash) for d in docs],
            )
            await cur.executemany(
                "insert into rag.chunks"
                " (id, doc_id, namespace, kb_version, chunk_index, text, token_count, embedding)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (f"{r.doc_id}#{r.chunk.index}", r.doc_id, namespace, kb_version,
                     r.chunk.index, r.chunk.text, r.chunk.token_count, r.embedding)
                    for r in records
                ],
            )
        await conn.execute(
            "insert into rag.kb_versions (namespace, kb_version) values (%s, %s)"
            " on conflict (namespace) do update"
            " set kb_version = excluded.kb_version, updated_at = now()",
            (namespace, kb_version),
        )


async def search(
    pool: AsyncConnectionPool, namespace: str, embedding: np.ndarray, k: int
) -> tuple[str | None, list[RetrievedChunk]]:
    async with pool.connection() as conn, conn.transaction():
        row = await (await conn.execute(
            "select kb_version from rag.kb_versions where namespace = %s", (namespace,)
        )).fetchone()
        if row is None:
            return None, []
        version = row[0]
        # Filtered HNSW can under-return; iterative scan keeps searching until k rows match.
        await conn.execute("set local hnsw.iterative_scan = relaxed_order")
        rows = await (await conn.execute(
            "select c.id, c.doc_id, d.title, c.text, 1 - (c.embedding <=> %s) as score, c.token_count"
            " from rag.chunks c join rag.documents d on d.id = c.doc_id"
            " where c.namespace = %s and c.kb_version = %s"
            " order by c.embedding <=> %s limit %s",
            (embedding, namespace, version, embedding, k),
        )).fetchall()
    chunks = [RetrievedChunk(r[0], r[1], r[2], r[3], float(r[4]), r[5]) for r in rows]
    chunks.sort(key=lambda c: c.score, reverse=True)  # relaxed_order may be slightly unordered
    return version, chunks


async def versions(pool: AsyncConnectionPool) -> dict[str, str]:
    async with pool.connection() as conn:
        rows = await (await conn.execute("select namespace, kb_version from rag.kb_versions")).fetchall()
    return {ns: v for ns, v in rows}
```

- [ ] **Step 8: Run the store tests**

Run: `uv run pytest tests/test_store.py -v`
Expected: 3 passed.

- [ ] **Step 9: Implement the ingest CLI**

`src/hospital_rag/ingest.py`:
```python
"""Load kb/, chunk, embed and replace each namespace's chunks.

Usage: python -m hospital_rag.ingest --kb /app/kb
"""
import argparse
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from .aio import run
from .chunking import chunk_document
from .db import open_pool
from .embedding import Embedder
from .kb import kb_version, load_kb
from .settings import Settings
from .store import ChunkRecord, replace_namespace


async def ingest(kb_dir: Path, pool: AsyncConnectionPool, embedder: Embedder, max_tokens: int) -> dict[str, str]:
    docs = load_kb(kb_dir)
    result: dict[str, str] = {}
    for namespace in sorted({d.namespace for d in docs}):
        ns_docs = [d for d in docs if d.namespace == namespace]
        version = kb_version(ns_docs)
        records: list[ChunkRecord] = []
        for doc in ns_docs:
            chunks = chunk_document(doc.title, doc.body, embedder.count_tokens, max_tokens)
            vectors = embedder.embed([c.text for c in chunks])
            records.extend(ChunkRecord(doc.id, c, v) for c, v in zip(chunks, vectors, strict=True))
        await replace_namespace(pool, namespace, version, ns_docs, records)
        result[namespace] = version
        print(f"{namespace}: {len(ns_docs)} docs, {len(records)} chunks, kb_version={version}")
    return result


async def _main(kb_dir: Path) -> None:
    settings = Settings()
    embedder = Embedder(settings.embed_model, settings.embed_cache_dir)
    pool = await open_pool(settings.database_url)
    try:
        await ingest(kb_dir, pool, embedder, settings.chunk_max_tokens)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb", type=Path, default=Path("/app/kb"))
    run(_main(parser.parse_args().kb))


if __name__ == "__main__":
    main()
```

- [ ] **Step 10: Ingest the real KB into the test DB and check the chunk sizes**

Run (from `services/hospital-rag`, with Postgres up):
```bash
DATABASE_URL=postgresql://weir:weir@localhost:5432/weir_test uv run python -m hospital_rag.ingest --kb ../../kb
uv run --no-project python - <<'EOF'
import psycopg
with psycopg.connect("postgresql://weir:weir@localhost:5432/weir_test") as c:
    print(c.execute("select namespace, count(*), max(token_count) from rag.chunks group by 1").fetchall())
EOF
```
Expected: two lines like `weir-general/en/public: 30 docs, N chunks, kb_version=...`, then counts where `max(token_count)` is 260 or fewer. (If the migrations aren't applied to `weir_test`, run `uv run pytest tests/test_store.py` first, which applies them.)

- [ ] **Step 11: Commit**

```bash
git add services/hospital-rag
git commit -m "feat(hospital-rag): KB loader, pgvector store, ingest CLI"
```

---

### Task 5: Prompt contract and LLM clients (Groq and stub)

**Files:**
- Create: `src/hospital_rag/prompt.py`, `src/hospital_rag/llm.py`
- Test: `tests/test_prompt.py`, `tests/test_llm.py`

**Interfaces:**
- Produces: `PROMPT_VERSION = "p1"`, `NOT_FOUND_MESSAGE: str`, `build_messages(query: str, chunks: list[tuple[str, str]]) -> tuple[list[dict], dict[str, str]]` (chunks are `(chunk_id, text)` pairs; returns the messages and a label→chunk_id map like `{"c1": "pub-a#0"}`), `ParsedAnswer(answer: str, cited_chunk_ids: list[str], invalid_citations: int, not_found: bool)`, `parse_answer(raw: str, labels: dict[str, str]) -> ParsedAnswer`.
- Produces: `LLMResult(text, tokens_in, tokens_out, finish_reason, model, latency_ms)`, exceptions `LLMError`, `RateLimited(LLMError)` with `.retry_after: float | None`, `LLMTimeout(LLMError)`, class `GroqLLM(api_key, timeout_s, max_completion_tokens, reasoning_effort, client=None)` and `StubLLM(latency_ms, count_tokens)`, both with `async complete(messages: list[dict], model: str) -> LLMResult`.

- [ ] **Step 1: Write the failing prompt tests**

`tests/test_prompt.py`:
```python
from hospital_rag.prompt import NOT_FOUND_MESSAGE, build_messages, parse_answer

LABELS = {"c1": "pub-a#0", "c2": "pub-b#1", "c3": "pub-c#0"}


def test_build_messages_numbers_passages():
    messages, labels = build_messages("When?", [("pub-a#0", "Alpha text"), ("pub-b#1", "Beta text")])
    assert labels == {"c1": "pub-a#0", "c2": "pub-b#1"}
    assert messages[0]["role"] == "system" and "NOT_FOUND" in messages[0]["content"]
    assert "[c1] Alpha text" in messages[1]["content"]
    assert messages[1]["content"].rstrip().endswith("Question: When?")


def test_parse_strips_citations_and_maps_ids():
    p = parse_answer("Visiting is 4 pm to 8 pm [c1]. Two visitors [c2].", LABELS)
    assert p.answer == "Visiting is 4 pm to 8 pm. Two visitors."
    assert p.cited_chunk_ids == ["pub-a#0", "pub-b#1"]
    assert p.not_found is False and p.invalid_citations == 0


def test_parse_grouped_and_duplicate_citations():
    p = parse_answer("Yes [c1, c3] and again [c1].", LABELS)
    assert p.cited_chunk_ids == ["pub-a#0", "pub-c#0"]


def test_parse_counts_invalid_labels():
    p = parse_answer("Answer [c9] [c2].", LABELS)
    assert p.cited_chunk_ids == ["pub-b#1"]
    assert p.invalid_citations == 1


def test_parse_no_citations():
    p = parse_answer("Plain answer.", LABELS)
    assert p.cited_chunk_ids == [] and p.answer == "Plain answer."


def test_parse_not_found_and_empty():
    for raw in ("NOT_FOUND", "  not_found.", ""):
        p = parse_answer(raw, LABELS)
        assert p.not_found is True
        assert p.answer == NOT_FOUND_MESSAGE
        assert p.cited_chunk_ids == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: FAIL, `No module named 'hospital_rag.prompt'`.

- [ ] **Step 3: Implement prompt.py**

`src/hospital_rag/prompt.py`:
```python
"""Prompt contract: numbered passages in, cited answer or NOT_FOUND out.

Bump PROMPT_VERSION on any change to SYSTEM or the message layout; Weir keys its
cache on it.
"""
import re
from dataclasses import dataclass

PROMPT_VERSION = "p1"
NOT_FOUND = "NOT_FOUND"
NOT_FOUND_MESSAGE = "Sorry, I couldn't find that in Weir General Hospital's information."

SYSTEM = """You are the help desk assistant for Weir General Hospital.
Answer ONLY from the numbered context passages. Keep answers short (1-4 sentences).
After each fact, cite the passage it came from, like [c1] or [c2].
If the passages do not contain the answer, reply with exactly: NOT_FOUND
Never give medical advice beyond what the passages state."""

CITATION = re.compile(r"\[\s*(c\d+(?:\s*,\s*c\d+)*)\s*\]", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedAnswer:
    answer: str
    cited_chunk_ids: list[str]
    invalid_citations: int
    not_found: bool


def build_messages(query: str, chunks: list[tuple[str, str]]) -> tuple[list[dict], dict[str, str]]:
    labels = {f"c{i + 1}": chunk_id for i, (chunk_id, _) in enumerate(chunks)}
    context = "\n\n".join(f"[c{i + 1}] {text}" for i, (_, text) in enumerate(chunks))
    user = f"Context passages:\n\n{context}\n\nQuestion: {query}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], labels


def parse_answer(raw: str, labels: dict[str, str]) -> ParsedAnswer:
    text = raw.strip()
    if not text or text.upper().startswith(NOT_FOUND):
        return ParsedAnswer(NOT_FOUND_MESSAGE, [], 0, True)
    cited: list[str] = []
    invalid = 0
    for match in CITATION.finditer(text):
        for label in re.split(r"\s*,\s*", match.group(1).lower()):
            if label in labels:
                if labels[label] not in cited:
                    cited.append(labels[label])
            else:
                invalid += 1
    clean = CITATION.sub("", text)
    clean = re.sub(r"\s+([.,;:!?])", r"\1", clean)
    clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
    return ParsedAnswer(clean, cited, invalid, False)
```

- [ ] **Step 4: Run the prompt tests**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: 6 passed.

- [ ] **Step 5: Write the failing LLM tests**

`tests/test_llm.py`:
```python
from types import SimpleNamespace

import groq
import httpx
import pytest

from hospital_rag.llm import GroqLLM, LLMError, LLMTimeout, RateLimited, StubLLM
from hospital_rag.prompt import build_messages

from .conftest import word_count

REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


class FakeCompletions:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.kwargs = result, error, None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def fake_client(completions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def ok_response(text="Answer [c1]", finish="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
    )


def llm_with(completions):
    return GroqLLM("key", 20.0, 700, "low", client=fake_client(completions))


async def test_groq_success_maps_usage_and_sends_settings():
    comp = FakeCompletions(result=ok_response())
    result = await llm_with(comp).complete([{"role": "user", "content": "q"}], "openai/gpt-oss-120b")
    assert (result.text, result.tokens_in, result.tokens_out) == ("Answer [c1]", 120, 30)
    assert result.finish_reason == "stop" and result.model == "openai/gpt-oss-120b"
    assert comp.kwargs["temperature"] == 0
    assert comp.kwargs["max_completion_tokens"] == 700
    assert comp.kwargs["extra_body"] == {"reasoning_effort": "low"}


async def test_groq_rate_limit_raises_with_retry_after():
    err = groq.RateLimitError("slow down", response=httpx.Response(429, headers={"retry-after": "7"}, request=REQ), body=None)
    with pytest.raises(RateLimited) as exc:
        await llm_with(FakeCompletions(error=err)).complete([], "m")
    assert exc.value.retry_after == 7.0


async def test_groq_timeout_raises_llm_timeout():
    with pytest.raises(LLMTimeout):
        await llm_with(FakeCompletions(error=groq.APITimeoutError(request=REQ))).complete([], "m")


async def test_groq_other_error_raises_llm_error():
    err = groq.InternalServerError("boom", response=httpx.Response(500, request=REQ), body=None)
    with pytest.raises(LLMError):
        await llm_with(FakeCompletions(error=err)).complete([], "m")


async def test_stub_answers_from_first_passage_without_network():
    messages, _ = build_messages("When?", [("a#0", "Title: S\nVisiting is from 4 pm to 8 pm daily."), ("b#0", "Other")])
    result = await StubLLM(latency_ms=1, count_tokens=word_count).complete(messages, "m")
    assert result.text.endswith("[c1]")
    assert "4 pm to 8 pm" in result.text
    assert result.tokens_in > 0 and result.tokens_out > 0 and result.finish_reason == "stop"
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL, `No module named 'hospital_rag.llm'`.

- [ ] **Step 7: Implement llm.py**

`src/hospital_rag/llm.py`:
```python
import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import groq


@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    finish_reason: str
    model: str
    latency_ms: int


class LLMError(Exception):
    pass


class RateLimited(LLMError):
    def __init__(self, retry_after: float | None):
        super().__init__(f"rate limited (retry after {retry_after}s)")
        self.retry_after = retry_after


class LLMTimeout(LLMError):
    pass


class LLM(Protocol):
    async def complete(self, messages: list[dict], model: str) -> LLMResult: ...


class GroqLLM:
    def __init__(self, api_key: str, timeout_s: float, max_completion_tokens: int,
                 reasoning_effort: str | None, client=None):
        if client is None and not api_key:
            raise ValueError("GROQ_API_KEY is empty; set it in .env or use LLM_MODE=stub")
        self._client = client or groq.AsyncGroq(api_key=api_key, timeout=timeout_s, max_retries=0)
        self._max_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort

    async def complete(self, messages: list[dict], model: str) -> LLMResult:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_completion_tokens": self._max_tokens,
        }
        if self._reasoning_effort:
            kwargs["extra_body"] = {"reasoning_effort": self._reasoning_effort}
        started = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except groq.RateLimitError as e:
            raise RateLimited(_retry_after(e)) from e
        except groq.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except groq.APIError as e:
            raise LLMError(str(e)) from e
        choice = resp.choices[0]
        return LLMResult(
            text=choice.message.content or "",
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            finish_reason=choice.finish_reason or "stop",
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _retry_after(error: groq.RateLimitError) -> float | None:
    value = error.response.headers.get("retry-after") if error.response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class StubLLM:
    """Fixed-latency fake used for load tests: answers from passage [c1], no network."""

    FIRST_PASSAGE = re.compile(r"\[c1\] (.+?)(?:\n\n\[c2\] |\n\nQuestion:)", re.DOTALL)

    def __init__(self, latency_ms: int, count_tokens: Callable[[str], int]):
        self._latency_ms = latency_ms
        self._count = count_tokens

    async def complete(self, messages: list[dict], model: str) -> LLMResult:
        await asyncio.sleep(self._latency_ms / 1000)
        match = self.FIRST_PASSAGE.search(messages[-1]["content"])
        if match:
            body = match.group(1).split("\n", 1)[-1]  # drop the "Title: heading" line
            text = " ".join(body.split()[:25]) + " [c1]"
        else:
            text = "NOT_FOUND"
        tokens_in = sum(self._count(m["content"]) for m in messages)
        return LLMResult(text, tokens_in, self._count(text), "stop", model, self._latency_ms)
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_prompt.py tests/test_llm.py -v`
Expected: 11 passed.

- [ ] **Step 9: Commit**

```bash
git add services/hospital-rag
git commit -m "feat(hospital-rag): citation prompt contract, Groq and stub LLM clients"
```

---

### Task 6: hospital-rag HTTP API, container, and real smoke test

**Files:**
- Create: `src/hospital_rag/schemas.py`, `src/hospital_rag/service.py`, `src/hospital_rag/main.py`, `services/hospital-rag/Dockerfile`
- Modify: `docker-compose.yml` (add the `hospital-rag` service)
- Create locally, never commit: `.env` (copied from `.env.example` and filled in)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Embedder`, `open_pool`, `search`, `versions`, `build_messages`, `parse_answer`, `PROMPT_VERSION`, `NOT_FOUND_MESSAGE`, `GroqLLM`, `StubLLM`, `RateLimited`, `LLMTimeout`, `LLMError`, `Settings`.
- Produces the HTTP API (Weir's adapter in Task 8 depends on these exact shapes):
  - `GET /info` → `{"namespaces": {"<ns>": {"kb_version": str, "prompt_version": str}}}`
  - `POST /retrieve` `{query, namespace, k?}` → `{chunks: [{id, doc_id, title, text, score, token_count}], top_score, score_gap, context_tokens, kb_version, latency_ms}`
  - `POST /generate` `{query, namespace, chunks: [{id, text, ...}], model}` → `{answer, cited_chunk_ids, invalid_citations, not_found, finish_reason, tokens_in, tokens_out, model, prompt_version, latency_ms}`. With zero chunks it returns `finish_reason: "skipped"`, `not_found: true` and 0 tokens, without calling the LLM.
  - Errors: 503 `{"error": "rate_limited", "retry_after": float|null}`, 504 `{"error": "timeout"}`, 502 `{"error": "llm_error", "detail": str}`.
  - `GET /healthz` → 200 `{"status": "ok", "llm_mode": ...}`, or 503 if the DB is down.
- Produces: `Deps(pool, embedder, llm, retrieve_k)` and `create_app(deps: Deps | None = None) -> FastAPI`. When `deps` is given, it's attached immediately (tests). Otherwise it's built in the lifespan from `Settings`.

- [ ] **Step 1: Write the failing API tests**

`tests/test_api.py`:
```python
import httpx
import numpy as np
import pytest

from hospital_rag.chunking import ChunkText
from hospital_rag.db import open_pool
from hospital_rag.kb import KbDoc
from hospital_rag.llm import LLMResult, RateLimited
from hospital_rag.main import Deps, create_app
from hospital_rag.store import ChunkRecord, replace_namespace

NS = "weir-general/en/public"


class FakeLLM:
    def __init__(self, text="Open 4 pm to 8 pm [c1].", error=None):
        self.text, self.error, self.calls = text, error, 0

    async def complete(self, messages, model):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResult(self.text, 100, 20, "stop", model, 5)


class FakeEmbedder:
    def embed(self, texts):
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        return [v for _ in texts]

    def count_tokens(self, text):
        return len(text.split())


def client_for(deps):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://t")


GEN_BODY = {"query": "When?", "namespace": NS, "model": "m", "chunks": [{"id": "pub-a#0", "text": "Open 4 pm to 8 pm"}]}


async def test_generate_parses_answer():
    async with client_for(Deps(None, FakeEmbedder(), FakeLLM(), 4)) as c:
        r = await c.post("/generate", json=GEN_BODY)
    body = r.json()
    assert r.status_code == 200
    assert body["answer"] == "Open 4 pm to 8 pm."
    assert body["cited_chunk_ids"] == ["pub-a#0"]
    assert body["tokens_in"] == 100 and body["prompt_version"] == "p1"


async def test_generate_with_no_chunks_skips_llm():
    llm = FakeLLM()
    async with client_for(Deps(None, FakeEmbedder(), llm, 4)) as c:
        r = await c.post("/generate", json={**GEN_BODY, "chunks": []})
    body = r.json()
    assert r.status_code == 200 and llm.calls == 0
    assert body["not_found"] is True and body["finish_reason"] == "skipped"
    assert body["tokens_in"] == 0 and body["tokens_out"] == 0


async def test_generate_rate_limited_returns_503():
    async with client_for(Deps(None, FakeEmbedder(), FakeLLM(error=RateLimited(12.0)), 4)) as c:
        r = await c.post("/generate", json=GEN_BODY)
    assert r.status_code == 503
    assert r.json() == {"error": "rate_limited", "retry_after": 12.0}


async def test_retrieve_rejects_blank_query():
    async with client_for(Deps(None, FakeEmbedder(), FakeLLM(), 4)) as c:
        r = await c.post("/retrieve", json={"query": "", "namespace": NS})
    assert r.status_code == 422


@pytest.mark.db
async def test_retrieve_and_info_against_db(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        doc = KbDoc(NS, "pub-a", "Visiting", "public/pub-a.md", "b", "h")
        await replace_namespace(pool, NS, "v1", [doc], [ChunkRecord("pub-a", ChunkText(0, "Visiting: 4 pm", 3), v)])
        async with client_for(Deps(pool, FakeEmbedder(), FakeLLM(), 4)) as c:
            r = await c.post("/retrieve", json={"query": "visiting?", "namespace": NS})
            info = await c.get("/info")
        body = r.json()
        assert body["kb_version"] == "v1"
        assert body["chunks"][0]["id"] == "pub-a#0"
        assert body["top_score"] == pytest.approx(1.0)
        assert body["score_gap"] == pytest.approx(1.0)  # single chunk: gap = top score
        assert body["context_tokens"] == 3
        assert info.json() == {"namespaces": {NS: {"kb_version": "v1", "prompt_version": "p1"}}}
    finally:
        await pool.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL, `No module named 'hospital_rag.main'`.

- [ ] **Step 3: Implement the schemas, service and app**

`src/hospital_rag/schemas.py`:
```python
from pydantic import BaseModel, Field, field_validator


class RetrieveIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    namespace: str
    k: int | None = Field(default=None, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query is blank")
        return v.strip()


class ChunkOut(BaseModel):
    id: str
    doc_id: str
    title: str
    text: str
    score: float
    token_count: int


class RetrieveOut(BaseModel):
    chunks: list[ChunkOut]
    top_score: float
    score_gap: float
    context_tokens: int
    kb_version: str | None
    latency_ms: int


class ChunkIn(BaseModel):
    id: str
    text: str


class GenerateIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    namespace: str
    chunks: list[ChunkIn] = Field(max_length=10)
    model: str


class GenerateOut(BaseModel):
    answer: str
    cited_chunk_ids: list[str]
    invalid_citations: int
    not_found: bool
    finish_reason: str
    tokens_in: int
    tokens_out: int
    model: str
    prompt_version: str
    latency_ms: int
```

`src/hospital_rag/service.py`:
```python
from .llm import LLM
from .prompt import NOT_FOUND_MESSAGE, PROMPT_VERSION, build_messages, parse_answer
from .schemas import GenerateIn, GenerateOut


async def generate(req: GenerateIn, llm: LLM) -> GenerateOut:
    if not req.chunks:
        return GenerateOut(
            answer=NOT_FOUND_MESSAGE, cited_chunk_ids=[], invalid_citations=0, not_found=True,
            finish_reason="skipped", tokens_in=0, tokens_out=0, model=req.model,
            prompt_version=PROMPT_VERSION, latency_ms=0,
        )
    messages, labels = build_messages(req.query, [(c.id, c.text) for c in req.chunks])
    result = await llm.complete(messages, req.model)
    parsed = parse_answer(result.text, labels)
    return GenerateOut(
        answer=parsed.answer, cited_chunk_ids=parsed.cited_chunk_ids,
        invalid_citations=parsed.invalid_citations, not_found=parsed.not_found,
        finish_reason=result.finish_reason, tokens_in=result.tokens_in,
        tokens_out=result.tokens_out, model=result.model,
        prompt_version=PROMPT_VERSION, latency_ms=result.latency_ms,
    )
```

`src/hospital_rag/main.py`:
```python
import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

from . import service
from .db import open_pool
from .embedding import Embedder
from .llm import LLM, GroqLLM, LLMError, LLMTimeout, RateLimited, StubLLM
from .prompt import PROMPT_VERSION
from .schemas import ChunkOut, GenerateIn, GenerateOut, RetrieveIn, RetrieveOut
from .settings import Settings
from .store import search, versions


@dataclass
class Deps:
    pool: AsyncConnectionPool | None
    embedder: Embedder
    llm: LLM
    retrieve_k: int
    llm_mode: str = "test"


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def create_app(deps: Deps | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is not None:
            yield
            return
        s = Settings()
        embedder = Embedder(s.embed_model, s.embed_cache_dir)
        llm: LLM = (
            StubLLM(s.stub_latency_ms, embedder.count_tokens)
            if s.llm_mode == "stub"
            else GroqLLM(s.groq_api_key, s.groq_timeout_s, s.max_completion_tokens, s.reasoning_effort)
        )
        pool = await open_pool(s.database_url)
        app.state.deps = Deps(pool, embedder, llm, s.retrieve_k, s.llm_mode)
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(title="hospital-rag", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps

    @app.get("/info")
    async def info(request: Request) -> dict:
        found = await versions(request.app.state.deps.pool)
        return {"namespaces": {ns: {"kb_version": v, "prompt_version": PROMPT_VERSION} for ns, v in found.items()}}

    @app.post("/retrieve", response_model=RetrieveOut)
    async def retrieve(body: RetrieveIn, request: Request) -> RetrieveOut:
        d: Deps = request.app.state.deps
        started = time.perf_counter()
        [vector] = await asyncio.to_thread(d.embedder.embed, [body.query])
        version, chunks = await search(d.pool, body.namespace, vector, body.k or d.retrieve_k)
        scores = [c.score for c in chunks]
        top = scores[0] if scores else 0.0
        gap = scores[0] - scores[1] if len(scores) > 1 else top
        return RetrieveOut(
            chunks=[ChunkOut(**asdict(c)) for c in chunks], top_score=top, score_gap=gap,
            context_tokens=sum(c.token_count for c in chunks), kb_version=version,
            latency_ms=_ms(started),
        )

    @app.post("/generate", response_model=GenerateOut)
    async def generate(body: GenerateIn, request: Request):
        try:
            return await service.generate(body, request.app.state.deps.llm)
        except RateLimited as e:
            return JSONResponse(status_code=503, content={"error": "rate_limited", "retry_after": e.retry_after})
        except LLMTimeout:
            return JSONResponse(status_code=504, content={"error": "timeout"})
        except LLMError as e:
            return JSONResponse(status_code=502, content={"error": "llm_error", "detail": str(e)[:300]})

    @app.get("/healthz")
    async def healthz(request: Request):
        d: Deps = request.app.state.deps
        try:
            async with d.pool.connection() as conn:
                await conn.execute("select 1")
        except Exception as e:  # noqa: BLE001 - report any DB failure as unhealthy
            return JSONResponse(status_code=503, content={"status": "db_error", "detail": str(e)[:200]})
        return {"status": "ok", "llm_mode": d.llm_mode}

    return app


app = create_app()
```

- [ ] **Step 4: Run all hospital-rag tests**

Run: `uv run pytest -v`
Expected: all pass (5 in test_api.py, 32 in total).

- [ ] **Step 5: Dockerfile and compose service**

`services/hospital-rag/Dockerfile`:
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    EMBED_CACHE_DIR=/models/fastembed \
    HF_HOME=/models/hf
WORKDIR /app
COPY services/hospital-rag/pyproject.toml services/hospital-rag/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Bake the embedding model and tokenizer into the image so startup needs no download.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models/fastembed'); from tokenizers import Tokenizer; Tokenizer.from_pretrained('BAAI/bge-small-en-v1.5')"
COPY services/hospital-rag/src ./src
RUN uv sync --frozen --no-dev
EXPOSE 8001
CMD ["uvicorn", "hospital_rag.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

Append to `docker-compose.yml` under `services:`:
```yaml
  hospital-rag:
    build: { context: ., dockerfile: services/hospital-rag/Dockerfile }
    environment:
      DATABASE_URL: postgresql://weir:weir@postgres:5432/weir
      GROQ_API_KEY: ${GROQ_API_KEY:-}
      LLM_MODE: ${LLM_MODE:-groq}
    volumes: ["./kb:/app/kb:ro"]
    ports: ["8001:8001"]
    depends_on:
      migrate: { condition: service_completed_successfully }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/healthz')"]
      interval: 5s
      timeout: 3s
      retries: 30
```

- [ ] **Step 6: Create `.env` (user action, needs the free Groq key)**

Copy `.env.example` to `.env`. Paste `GROQ_API_KEY` from console.groq.com/keys, and generate the three `WEIR_KEY_*` values with `uv run python -c "import secrets; print(secrets.token_urlsafe(24))"`. Confirm `.env` is ignored: `git check-ignore .env` should print `.env`.

- [ ] **Step 7: Confirm the Groq model IDs are available to this key**

Run (Git Bash, from the repo root):
```bash
set -a; source .env; set +a
curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY" | uv run --no-project python -c "import json,sys; ids={m['id'] for m in json.load(sys.stdin)['data']}; print({m: m in ids for m in ['openai/gpt-oss-20b','openai/gpt-oss-120b']})"
```
Expected: `{'openai/gpt-oss-20b': True, 'openai/gpt-oss-120b': True}`. If either is False, stop and record the replacement model and its price in `docs/decisions.md` before continuing.

- [ ] **Step 8: Build, start, ingest**

```bash
docker compose up -d --build hospital-rag
docker compose exec hospital-rag python -m hospital_rag.ingest --kb /app/kb
```
Expected: two lines, `weir-general/en/public: 30 docs, ...` and `weir-general/en/staff: 10 docs, ...`.

- [ ] **Step 9: Real end-to-end smoke test (2 Groq calls)**

```bash
curl -s localhost:8001/info
curl -s localhost:8001/retrieve -H 'content-type: application/json' \
  -d '{"query":"What are the ICU visiting hours?","namespace":"weir-general/en/public"}' > /tmp/r.json
uv run --no-project python -c "import json; r=json.load(open('/tmp/r.json')); print(r['top_score'], [c['id'] for c in r['chunks']])"
uv run --no-project python - <<'EOF'
import json, urllib.request
r = json.load(open('/tmp/r.json'))
body = {"query": "What are the ICU visiting hours?", "namespace": "weir-general/en/public",
        "chunks": r["chunks"], "model": "openai/gpt-oss-120b"}
req = urllib.request.Request("http://localhost:8001/generate", json.dumps(body).encode(), {"content-type": "application/json"})
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```
Expected: the top chunk comes from `pub-visiting-hours-icu`. The generate response has a short answer with the ICU hours, `cited_chunk_ids` non-empty, `not_found: false`, `finish_reason: "stop"`, and tokens_in around 1,000–1,600.

- [ ] **Step 10: Update the progress log and commit**

Append to `docs/progress.md`:
```markdown
## <date>: Phase 0, hospital-rag up

- Knowledge base: 40 fictional docs (30 public, 10 staff) with 8 planted look-alike pairs.
- hospital-rag: /retrieve, /generate, /info, /healthz; Groq gpt-oss-20b/120b confirmed on the free key.
- Smoke test: "ICU visiting hours" retrieved pub-visiting-hours-icu and got a cited answer (<tokens_in> tokens in).
```

```bash
git add services/hospital-rag docker-compose.yml docs/progress.md
git commit -m "feat(hospital-rag): HTTP API, container with baked model, compose service"
```

---

### Task 7: Weir config, tenants, and text helpers

**Files:**
- Create: `services/weir/src/weir/settings.py`, `src/weir/config.py`, `src/weir/auth.py`, `src/weir/text.py`
- Create: `configs/weir.yaml`, `configs/ablations/baseline.yaml`, `configs/tenants.yaml`
- Test: `tests/test_config.py`, `tests/test_auth.py`, `tests/test_text.py`

**Interfaces:**
- Produces: `Settings` (fields `database_url`, `weir_configs_dir: Path`, `weir_ablation: str | None`, methods `config_path()`, `overlay_path()`).
- Produces: `WeirConfig` with `.config_label: str`, `.rag.base_url: str`, `.rag.timeout_seconds: float`, `.rag.retrieve_k: int`, `.router.small_model: str`, `.router.large_model: str`, `.cache.enabled: bool`, `.kill_switch.force_large: bool`, `.kill_switch.disable_cache: bool`, `.namespaces: dict[str, NamespaceConfig]`, `.is_sensitive(namespace: str) -> bool`, `.model_for(tier: str) -> str`. Also `load_config(path: Path, overlay: Path | None = None) -> WeirConfig` and `deep_merge(base: dict, over: dict) -> dict`.
- Produces: `Tenant(name: str, namespaces: frozenset[str], admin: bool)` with `.allows(namespace) -> bool`, and `TenantRegistry.from_yaml(path: Path, env: Mapping[str, str])` with `.authenticate(key: str | None) -> Tenant | None`.
- Produces: `normalize(query: str) -> str` (trim, collapse whitespace, lowercase) and `query_hash(query: str) -> str` (sha256 hex of the normalized query).

- [ ] **Step 1: Config files**

`configs/weir.yaml`:
```yaml
# Weir gateway configuration. Every threshold lives here; experiments change config, not code.
# Sections are added phase by phase (see docs/superpowers/plans/). Unknown keys are rejected.
config_label: dev

rag:
  base_url: http://hospital-rag:8001
  timeout_seconds: 30
  retrieve_k: 4

router:
  small_model: openai/gpt-oss-20b
  large_model: openai/gpt-oss-120b

cache:
  enabled: false          # the semantic cache arrives in Phase 2

kill_switch:
  force_large: false      # send every request to the large model
  disable_cache: false    # skip the cache entirely

namespaces:
  weir-general/en/public:
    sensitive: false
  weir-general/en/staff:
    sensitive: true       # logs keep only hashes, never raw query text
```

`configs/ablations/baseline.yaml`:
```yaml
# Baseline: no cache, always the large model (docs/weir-original.md, "Step 0: the baseline").
config_label: baseline
cache:
  enabled: false
kill_switch:
  force_large: true
```

`configs/tenants.yaml`:
```yaml
# API-key tenants. Keys come from environment variables (.env), never from this file.
tenants:
  - name: public-app
    key_env: WEIR_KEY_PUBLIC
    namespaces: [weir-general/en/public]
  - name: staff-app
    key_env: WEIR_KEY_STAFF
    namespaces: [weir-general/en/staff]
  - name: admin
    key_env: WEIR_KEY_ADMIN
    namespaces: []
    admin: true
```

- [ ] **Step 2: Write the failing tests**

`tests/test_text.py`:
```python
from weir.text import normalize, query_hash


def test_normalize_trims_collapses_lowercases():
    assert normalize("  What are\tthe  ICU\nhours? ") == "what are the icu hours?"


def test_query_hash_ignores_case_and_spacing():
    assert query_hash("ICU  hours") == query_hash("icu hours")
    assert len(query_hash("x")) == 64
```

`tests/test_config.py`:
```python
import pytest
from pydantic import ValidationError

from weir.config import deep_merge, load_config

from .conftest import CONFIGS


def test_repo_config_loads():
    cfg = load_config(CONFIGS / "weir.yaml")
    assert cfg.config_label == "dev"
    assert cfg.model_for("large") == "openai/gpt-oss-120b"
    assert cfg.model_for("small") == "openai/gpt-oss-20b"
    assert cfg.is_sensitive("weir-general/en/staff") is True
    assert cfg.is_sensitive("weir-general/en/public") is False
    assert cfg.is_sensitive("unknown/ns") is True  # unknown namespaces are treated as sensitive


def test_baseline_overlay_forces_large():
    cfg = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / "baseline.yaml")
    assert cfg.config_label == "baseline"
    assert cfg.kill_switch.force_large is True
    assert cfg.rag.retrieve_k == 4  # untouched keys survive the merge


def test_deep_merge_nested():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}}) == {"a": {"b": 1, "c": 3}}


def test_unknown_key_rejected(tmp_path):
    bad = tmp_path / "w.yaml"
    bad.write_text((CONFIGS / "weir.yaml").read_text(encoding="utf-8") + "\ntypo_key: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(bad)
```

`tests/test_auth.py`:
```python
import pytest

from weir.auth import TenantRegistry

from .conftest import CONFIGS

ENV = {"WEIR_KEY_PUBLIC": "pub-key", "WEIR_KEY_STAFF": "staff-key", "WEIR_KEY_ADMIN": "admin-key"}


def registry():
    return TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", ENV)


def test_authenticate_maps_key_to_tenant():
    t = registry().authenticate("pub-key")
    assert t.name == "public-app"
    assert t.allows("weir-general/en/public") and not t.allows("weir-general/en/staff")
    assert registry().authenticate("admin-key").admin is True


def test_unknown_or_missing_key_is_none():
    assert registry().authenticate("nope") is None
    assert registry().authenticate(None) is None
    assert registry().authenticate("") is None


def test_missing_env_var_fails_fast():
    with pytest.raises(ValueError, match="WEIR_KEY_STAFF"):
        TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", {**ENV, "WEIR_KEY_STAFF": ""})


def test_duplicate_keys_rejected():
    with pytest.raises(ValueError, match="same API key"):
        TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", {**ENV, "WEIR_KEY_STAFF": "pub-key"})
```

- [ ] **Step 3: Run to verify failure**

Run: `cd services/weir && uv run pytest tests/test_text.py tests/test_config.py tests/test_auth.py -v`
Expected: FAIL with import errors for `weir.text`, `weir.config` and `weir.auth`.

- [ ] **Step 4: Implement**

`src/weir/text.py`:
```python
import hashlib


def normalize(query: str) -> str:
    return " ".join(query.split()).lower()


def query_hash(query: str) -> str:
    return hashlib.sha256(normalize(query).encode("utf-8")).hexdigest()
```

`src/weir/settings.py`:
```python
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql://weir:weir@localhost:5432/weir"
    weir_configs_dir: Path = Path("/app/configs")
    weir_ablation: str | None = None

    @field_validator("weir_ablation")
    @classmethod
    def empty_is_none(cls, v: str | None) -> str | None:
        return v or None

    def config_path(self) -> Path:
        return self.weir_configs_dir / "weir.yaml"

    def overlay_path(self) -> Path | None:
        if not self.weir_ablation:
            return None
        return self.weir_configs_dir / "ablations" / f"{self.weir_ablation}.yaml"
```

`src/weir/config.py`:
```python
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RagConfig(_Strict):
    base_url: str
    timeout_seconds: float = 30.0
    retrieve_k: int = 4


class RouterConfig(_Strict):
    small_model: str
    large_model: str


class CacheConfig(_Strict):
    enabled: bool = False


class KillSwitch(_Strict):
    force_large: bool = False
    disable_cache: bool = False


class NamespaceConfig(_Strict):
    sensitive: bool = False


class WeirConfig(_Strict):
    config_label: str
    rag: RagConfig
    router: RouterConfig
    cache: CacheConfig = CacheConfig()
    kill_switch: KillSwitch = KillSwitch()
    namespaces: dict[str, NamespaceConfig] = {}

    def is_sensitive(self, namespace: str) -> bool:
        ns = self.namespaces.get(namespace)
        return True if ns is None else ns.sensitive  # unknown namespace: be careful

    def model_for(self, tier: Literal["small", "large"]) -> str:
        return self.router.small_model if tier == "small" else self.router.large_model


def deep_merge(base: dict, over: dict) -> dict:
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path, overlay: Path | None = None) -> WeirConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if overlay is not None:
        data = deep_merge(data, yaml.safe_load(overlay.read_text(encoding="utf-8")) or {})
    return WeirConfig.model_validate(data)
```

`src/weir/auth.py`:
```python
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Tenant:
    name: str
    namespaces: frozenset[str]
    admin: bool = False

    def allows(self, namespace: str) -> bool:
        return namespace in self.namespaces


class TenantRegistry:
    def __init__(self, keyed: list[tuple[str, Tenant]]):
        self._keyed = keyed

    @classmethod
    def from_yaml(cls, path: Path, env: Mapping[str, str]) -> "TenantRegistry":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        keyed: list[tuple[str, Tenant]] = []
        for t in data["tenants"]:
            key = env.get(t["key_env"], "")
            if not key:
                raise ValueError(f"tenant '{t['name']}': environment variable {t['key_env']} is empty")
            tenant = Tenant(t["name"], frozenset(t.get("namespaces", [])), bool(t.get("admin", False)))
            keyed.append((key, tenant))
        keys = [k for k, _ in keyed]
        if len(set(keys)) != len(keys):
            raise ValueError("two tenants share the same API key")
        return cls(keyed)

    def authenticate(self, key: str | None) -> Tenant | None:
        if not key:
            return None
        found = None
        for candidate, tenant in self._keyed:  # compare against all keys: constant-time per key
            if hmac.compare_digest(candidate.encode(), key.encode()):
                found = tenant
        return found
```

`CONFIGS` is already defined in `tests/conftest.py` (Task 1).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_text.py tests/test_config.py tests/test_auth.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add configs services/weir
git commit -m "feat(weir): YAML config with ablation overlays, API-key tenants, query normalization"
```

---

### Task 8: Weir's hospital-rag adapter

**Files:**
- Create: `src/weir/rag/__init__.py` (empty), `src/weir/rag/adapter.py`
- Test: `tests/test_adapter.py`

**Interfaces:**
- Consumes: the hospital-rag HTTP API (Task 6).
- Produces: `RagError(kind: str, detail: str = "", retry_after: float | None = None)`, where `.kind` is one of `"rate_limited" | "timeout" | "unavailable" | "bad_response"`. Pydantic models `RetrievedChunk(id, doc_id, title, text, score, token_count)`, `RetrieveResult(chunks, top_score, score_gap, context_tokens, kb_version, latency_ms)`, `GenerateResult(answer, cited_chunk_ids, invalid_citations, not_found, finish_reason, tokens_in, tokens_out, model, prompt_version, latency_ms)`. Class `RagClient(base_url: str, timeout_s: float, client: httpx.AsyncClient | None = None)` with `async retrieve(query, namespace, k) -> RetrieveResult`, `async generate(query, namespace, chunks: list[RetrievedChunk], model) -> GenerateResult`, `async health() -> bool`, `async aclose()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_adapter.py`:
```python
import json

import httpx
import pytest

from weir.rag.adapter import RagClient, RagError, RetrievedChunk

CHUNK = {"id": "pub-a#0", "doc_id": "pub-a", "title": "A", "text": "t", "score": 0.8, "token_count": 3}
RETRIEVE = {"chunks": [CHUNK], "top_score": 0.8, "score_gap": 0.8, "context_tokens": 3, "kb_version": "v1", "latency_ms": 4}
GENERATE = {"answer": "x", "cited_chunk_ids": ["pub-a#0"], "invalid_citations": 0, "not_found": False,
            "finish_reason": "stop", "tokens_in": 10, "tokens_out": 2, "model": "m", "prompt_version": "p1", "latency_ms": 5}


def client(handler):
    return RagClient("http://rag", 5, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag"))


async def test_retrieve_parses_result():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=RETRIEVE)

    result = await client(handler).retrieve("q", "ns", 4)
    assert seen == {"query": "q", "namespace": "ns", "k": 4}
    assert result.chunks[0].id == "pub-a#0" and result.kb_version == "v1"


async def test_generate_sends_chunks_and_model():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=GENERATE)

    result = await client(handler).generate("q", "ns", [RetrievedChunk(**CHUNK)], "m")
    assert seen["model"] == "m" and seen["chunks"][0]["id"] == "pub-a#0"
    assert result.tokens_in == 10


@pytest.mark.parametrize(("response", "kind"), [
    (httpx.Response(503, json={"error": "rate_limited", "retry_after": 9.0}), "rate_limited"),
    (httpx.Response(504, json={"error": "timeout"}), "timeout"),
    (httpx.Response(502, json={"error": "llm_error", "detail": "x"}), "bad_response"),
    (httpx.Response(500, text="oops"), "bad_response"),
    (httpx.Response(503, text="not json"), "bad_response"),
])
async def test_error_statuses_map_to_kinds(response, kind):
    with pytest.raises(RagError) as exc:
        await client(lambda r: response).generate("q", "ns", [], "m")
    assert exc.value.kind == kind
    if kind == "rate_limited":
        assert exc.value.retry_after == 9.0


async def test_transport_errors():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(RagError) as exc:
        await client(timeout).retrieve("q", "ns", 4)
    assert exc.value.kind == "timeout"
    with pytest.raises(RagError) as exc:
        await client(refused).retrieve("q", "ns", 4)
    assert exc.value.kind == "unavailable"


async def test_health():
    assert await client(lambda r: httpx.Response(200, json={"status": "ok"})).health() is True
    assert await client(lambda r: httpx.Response(503, json={})).health() is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_adapter.py -v`
Expected: FAIL, `No module named 'weir.rag'`.

- [ ] **Step 3: Implement**

`src/weir/rag/adapter.py`:
```python
"""HTTP client for hospital-rag's /retrieve and /generate (the two-step split Weir needs)."""
import httpx
from pydantic import BaseModel


class RagError(Exception):
    """kind: rate_limited | timeout | unavailable | bad_response"""

    def __init__(self, kind: str, detail: str = "", retry_after: float | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail
        self.retry_after = retry_after


class RetrievedChunk(BaseModel):
    id: str
    doc_id: str
    title: str
    text: str
    score: float
    token_count: int


class RetrieveResult(BaseModel):
    chunks: list[RetrievedChunk]
    top_score: float
    score_gap: float
    context_tokens: int
    kb_version: str | None
    latency_ms: int


class GenerateResult(BaseModel):
    answer: str
    cited_chunk_ids: list[str]
    invalid_citations: int
    not_found: bool
    finish_reason: str
    tokens_in: int
    tokens_out: int
    model: str
    prompt_version: str
    latency_ms: int


class RagClient:
    def __init__(self, base_url: str, timeout_s: float, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def retrieve(self, query: str, namespace: str, k: int) -> RetrieveResult:
        data = await self._post("/retrieve", {"query": query, "namespace": namespace, "k": k})
        return RetrieveResult.model_validate(data)

    async def generate(self, query: str, namespace: str, chunks: list[RetrievedChunk], model: str) -> GenerateResult:
        payload = {"query": query, "namespace": namespace, "model": model,
                   "chunks": [c.model_dump() for c in chunks]}
        return GenerateResult.model_validate(await self._post("/generate", payload))

    async def health(self) -> bool:
        try:
            return (await self._client.get("/healthz")).status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException as e:
            raise RagError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise RagError("unavailable", str(e)) from e
        if response.status_code == 200:
            return response.json()
        body = _json_or_none(response)
        if response.status_code == 503 and body and body.get("error") == "rate_limited":
            raise RagError("rate_limited", "provider rate limit", body.get("retry_after"))
        if response.status_code == 504:
            raise RagError("timeout", response.text[:300])
        raise RagError("bad_response", f"{response.status_code}: {response.text[:300]}")


def _json_or_none(response: httpx.Response) -> dict | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_adapter.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add services/weir
git commit -m "feat(weir): hospital-rag adapter with typed results and error kinds"
```

---

## Phase 1: Baseline and logging

### Task 9: Price table and cost math

**Files:**
- Create: `configs/prices.yaml`, `src/weir/llm/__init__.py` (empty), `src/weir/llm/pricing.py`, `src/weir/db.py`
- Test: `tests/test_pricing.py`

**Interfaces:**
- Produces: `Price(model: str, usd_per_m_input: Decimal, usd_per_m_output: Decimal, effective_from: date)`, `UnknownModelPrice(KeyError)`, `PriceTable(prices: list[Price])` with `.from_yaml(path) -> PriceTable`, `.price_for(model: str, on: date) -> Price`, `.cost(model: str, tokens_in: int, tokens_out: int, on: date) -> Decimal`, `.prices: list[Price]`. Also `async sync_prices(pool, table: PriceTable) -> None`.
- Produces: `weir.db.open_pool(url: str, max_size: int = 10) -> AsyncConnectionPool` (pgvector registered).

- [ ] **Step 1: Price config**

`configs/prices.yaml`:
```yaml
# USD per 1M tokens at Groq's published paid (Developer) tier. We pay $0 on the free tier;
# these list prices let Weir report "what this would cost in production" (decision D7/D13).
# Source: https://console.groq.com/docs/models, checked 2026-09-30.
# When a price changes, ADD a row with a new effective_from. Never edit old rows.
prices:
  - model: openai/gpt-oss-20b
    usd_per_m_input: 0.075
    usd_per_m_output: 0.30
    effective_from: 2026-09-01
  - model: openai/gpt-oss-120b
    usd_per_m_input: 0.15
    usd_per_m_output: 0.60
    effective_from: 2026-09-01
  - model: BAAI/bge-small-en-v1.5   # local embeddings: free
    usd_per_m_input: 0
    usd_per_m_output: 0
    effective_from: 2026-09-01
```

- [ ] **Step 2: Write the failing tests**

`tests/test_pricing.py`:
```python
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from weir.db import open_pool
from weir.llm.pricing import Price, PriceTable, UnknownModelPrice, sync_prices

from .conftest import CONFIGS

D = Decimal


def table():
    return PriceTable([
        Price("m", D("0.10"), D("0.40"), date(2026, 1, 1)),
        Price("m", D("0.20"), D("0.80"), date(2026, 6, 1)),
    ])


def test_repo_prices_load():
    t = PriceTable.from_yaml(CONFIGS / "prices.yaml")
    p = t.price_for("openai/gpt-oss-120b", date(2026, 10, 1))
    assert (p.usd_per_m_input, p.usd_per_m_output) == (D("0.15"), D("0.60"))


def test_cost_math_exact():
    t = PriceTable.from_yaml(CONFIGS / "prices.yaml")
    # 1000/1e6*0.15 + 500/1e6*0.60 = 0.00015 + 0.0003
    assert t.cost("openai/gpt-oss-120b", 1000, 500, date(2026, 10, 1)) == D("0.00045")


def test_price_by_effective_date():
    assert table().price_for("m", date(2026, 3, 1)).usd_per_m_input == D("0.10")
    assert table().price_for("m", date(2026, 6, 1)).usd_per_m_input == D("0.20")


def test_unknown_model_or_date_raises():
    with pytest.raises(UnknownModelPrice):
        table().price_for("other", date(2026, 3, 1))
    with pytest.raises(UnknownModelPrice):
        table().price_for("m", date(2025, 12, 31))


@pytest.mark.db
async def test_sync_prices_upserts(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        await sync_prices(pool, table())
        await sync_prices(pool, table())  # idempotent
    finally:
        await pool.close()
    with psycopg.connect(migrated_db_url) as conn:
        assert conn.execute("select count(*) from weir.model_prices").fetchone()[0] == 2
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_pricing.py -v`
Expected: FAIL, `No module named 'weir.db'`.

- [ ] **Step 4: Implement**

`src/weir/db.py`:
```python
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool


async def open_pool(url: str, max_size: int = 10) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        url, min_size=1, max_size=max_size, open=False, configure=register_vector_async
    )
    await pool.open(wait=True)
    return pool
```

`src/weir/llm/pricing.py`:
```python
"""Versioned list prices and per-request cost (spec §8)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from psycopg_pool import AsyncConnectionPool

PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    model: str
    usd_per_m_input: Decimal
    usd_per_m_output: Decimal
    effective_from: date


class UnknownModelPrice(KeyError):
    pass


class PriceTable:
    def __init__(self, prices: list[Price]):
        self.prices = sorted(prices, key=lambda p: (p.model, p.effective_from))

    @classmethod
    def from_yaml(cls, path: Path) -> "PriceTable":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls([
            Price(
                model=row["model"],
                usd_per_m_input=Decimal(str(row["usd_per_m_input"])),
                usd_per_m_output=Decimal(str(row["usd_per_m_output"])),
                effective_from=row["effective_from"],
            )
            for row in data["prices"]
        ])

    def price_for(self, model: str, on: date) -> Price:
        candidates = [p for p in self.prices if p.model == model and p.effective_from <= on]
        if not candidates:
            raise UnknownModelPrice(f"no price for {model!r} on {on}")
        return candidates[-1]

    def cost(self, model: str, tokens_in: int, tokens_out: int, on: date) -> Decimal:
        p = self.price_for(model, on)
        return (Decimal(tokens_in) * p.usd_per_m_input + Decimal(tokens_out) * p.usd_per_m_output) / PER_MILLION


async def sync_prices(pool: AsyncConnectionPool, table: PriceTable) -> None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.executemany(
            "insert into weir.model_prices (model, usd_per_m_input, usd_per_m_output, effective_from)"
            " values (%s, %s, %s, %s) on conflict (model, effective_from) do update"
            " set usd_per_m_input = excluded.usd_per_m_input, usd_per_m_output = excluded.usd_per_m_output",
            [(p.model, p.usd_per_m_input, p.usd_per_m_output, p.effective_from) for p in table.prices],
        )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_pricing.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add configs/prices.yaml services/weir
git commit -m "feat(weir): versioned list-price table and cost math"
```

---

### Task 10: Async request-log writer

**Files:**
- Create: `src/weir/metrics/__init__.py` (empty), `src/weir/metrics/logger.py`
- Test: `tests/test_logger.py`

**Interfaces:**
- Consumes: `open_pool` (Task 9).
- Produces: dataclass `RequestLogRow`. Required fields: `request_id: UUID, ts: datetime, namespace: str, cache_status: str, route: str, status: str, latency_total_ms: int, query_hash: str`. Every other column from the `weir.request_log` schema is optional, defaulting to `None`, or to `False`/`0`/`Decimal(0)` for `escalated`/`model_calls`/costs. Also the protocol `LogSink` with `submit(row: RequestLogRow) -> None`, and class `LogWriter(pool, max_queue=10_000, batch_size=100, flush_interval_s=0.5)` with `start()`, `submit(row)`, `async stop(timeout_s=5.0)`, and counters `.dropped: int` and `.failed: int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_logger.py`:
```python
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from weir.db import open_pool
from weir.metrics.logger import LogWriter, RequestLogRow


def row(**overrides):
    base = dict(request_id=uuid4(), ts=datetime.now(UTC), namespace="weir-general/en/public",
                cache_status="bypass", route="large", status="ok", latency_total_ms=120,
                query_hash="h" * 64, cost_usd=Decimal("0.00045"), config_label="test")
    return RequestLogRow(**{**base, **overrides})


@pytest.mark.db
async def test_rows_are_written_on_stop(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    writer = LogWriter(pool, flush_interval_s=0.05)
    writer.start()
    for _ in range(3):
        writer.submit(row(bypass_reason="cache_disabled"))
    await writer.stop()
    await pool.close()
    with psycopg.connect(migrated_db_url) as conn:
        count, cost = conn.execute("select count(*), sum(cost_usd) from weir.request_log").fetchone()
    assert count == 3 and cost == Decimal("0.00135")
    assert writer.failed == 0 and writer.dropped == 0


class BrokenPool:
    @asynccontextmanager
    async def connection(self):
        raise RuntimeError("db down")
        yield  # pragma: no cover


async def test_write_failure_is_counted_not_raised():
    writer = LogWriter(BrokenPool(), flush_interval_s=0.01)
    writer.start()
    writer.submit(row())
    await writer.stop()
    assert writer.failed == 1


async def test_full_queue_drops_instead_of_blocking():
    writer = LogWriter(BrokenPool(), max_queue=1)  # not started: nothing drains the queue
    writer.submit(row())
    writer.submit(row())
    assert writer.dropped == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_logger.py -v`
Expected: FAIL, `No module named 'weir.metrics'`.

- [ ] **Step 3: Implement**

`src/weir/metrics/logger.py`:
```python
"""One row per request into weir.request_log, written off the request path.

Rows go into an in-process queue; a background task batches them into Postgres.
A logging failure never fails the user's request: it is counted and logged.
"""
import asyncio
import contextlib
import logging
from dataclasses import astuple, dataclass, fields
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

log = logging.getLogger("weir.metrics")


@dataclass
class RequestLogRow:
    request_id: UUID
    ts: datetime
    namespace: str
    cache_status: str
    route: str
    status: str
    latency_total_ms: int
    query_hash: str
    bypass_reason: str | None = None
    similarity: float | None = None
    cache_entry_id: UUID | None = None
    escalated: bool = False
    model_calls: int = 0
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    embed_tokens: int | None = None
    retrieval_top_score: float | None = None
    grounding_passed: bool | None = None
    latency_embed_ms: int | None = None
    latency_cache_ms: int | None = None
    latency_retrieval_ms: int | None = None
    latency_llm_ms: int | None = None
    cost_usd: Decimal = Decimal(0)
    counterfactual_cost_usd: Decimal = Decimal(0)
    error_detail: str | None = None
    query_text: str | None = None
    answer_len: int | None = None
    config_label: str | None = None


COLUMNS = [f.name for f in fields(RequestLogRow)]
INSERT_SQL = (
    f"insert into weir.request_log ({', '.join(COLUMNS)}) "
    f"values ({', '.join(['%s'] * len(COLUMNS))})"
)


class LogSink(Protocol):
    def submit(self, row: RequestLogRow) -> None: ...


class LogWriter:
    def __init__(self, pool, max_queue: int = 10_000, batch_size: int = 100, flush_interval_s: float = 0.5):
        self._pool = pool
        self._queue: asyncio.Queue[RequestLogRow] = asyncio.Queue(max_queue)
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._task: asyncio.Task | None = None
        self.dropped = 0
        self.failed = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def submit(self, row: RequestLogRow) -> None:
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            self.dropped += 1
            log.warning("request log queue full; dropped row %s", row.request_id)

    async def stop(self, timeout_s: float = 5.0) -> None:
        if self._task is None:
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._queue.join(), timeout_s)
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            batch = [await self._queue.get()]
            deadline = loop.time() + self._flush_interval_s
            while len(batch) < self._batch_size:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self._queue.get(), remaining))
                except asyncio.TimeoutError:
                    break
            await self._write(batch)
            for _ in batch:
                self._queue.task_done()

    async def _write(self, batch: list[RequestLogRow]) -> None:
        try:
            async with self._pool.connection() as conn, conn.cursor() as cur:
                await cur.executemany(INSERT_SQL, [astuple(r) for r in batch])
        except Exception:  # noqa: BLE001 - logging must never break requests
            self.failed += len(batch)
            log.exception("failed to write %d request log rows", len(batch))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_logger.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add services/weir
git commit -m "feat(weir): batched async request-log writer that never blocks requests"
```

---

### Task 11: Pass-through pipeline, gateway API, container (Phase 0 exit)

**Files:**
- Create: `src/weir/pipeline.py`, `src/weir/main.py`
- Modify: `docker-compose.yml` (add the `weir` service)
- Test: `tests/test_pipeline.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `WeirConfig`, `load_config`, `Settings`, `TenantRegistry`, `RagClient`, `RagError`, `RetrievedChunk`, `PriceTable`, `sync_prices`, `open_pool`, `LogWriter`, `LogSink`, `RequestLogRow`, `query_hash`.
- Produces request and response models: `QueryOptions(bypass_cache: bool = False, force_model: Literal["small", "large"] | None = None)`, `QueryRequest(query, namespace, session_id=None, personalized=False, options=QueryOptions())`, `Source(id, title)`, `QueryMeta(request_id, cache_status, similarity, route, escalated, model, latency_ms, cost_usd)`, `QueryResponse(answer, sources, meta)`.
- Produces: `PipelineError(status_code: int, error: str, request_id: str, retry_after: float | None)`; `Pipeline(cfg, rag, prices, log: LogSink, now=lambda: datetime.now(UTC))` with `async handle(req: QueryRequest) -> QueryResponse`.
- Produces: `AppDeps(pipeline, tenants, config, health: Callable[[], Awaitable[dict[str, bool]]])`, `create_app(deps: AppDeps | None = None) -> FastAPI`, and the module-level `app`.
- HTTP: `POST /v1/query` (header `X-API-Key`) returns 200 `QueryResponse` with header `X-Request-ID`; 401 for a missing or wrong key; 403 for a namespace the key isn't allowed; 422 for invalid input; 502/503/504 `{"error", "request_id"}` from `PipelineError`. `GET /healthz` returns 200 or 503 `{"status", "checks", "config_label"}`.

**Phase 1 behavior (no cache, no router, spec §5.3 reduced):**
- `cache_status = "bypass"`. `bypass_reason` is the first match of: `personalized` → `request_option` (options.bypass_cache) → `kill_switch` (kill_switch.disable_cache) → `cache_disabled`.
- Tier: `large` if `kill_switch.force_large`, else `options.force_model`, else `large`.
- `cost_usd = prices.cost(model, tokens_in, tokens_out, today)`. `counterfactual_cost_usd = prices.cost(large_model, tokens_in, tokens_out, today)` (spec §8: small route uses the actual tokens at the large model's price).
- `sources` are the cited chunks' documents, deduplicated by `doc_id`, in citation order.
- `query_text` is null for sensitive namespaces.

- [ ] **Step 1: Write the failing pipeline tests**

`tests/test_pipeline.py`:
```python
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from weir.config import load_config
from weir.llm.pricing import PriceTable
from weir.pipeline import Pipeline, PipelineError, QueryOptions, QueryRequest
from weir.rag.adapter import RagClient

from .conftest import CONFIGS

PUBLIC = "weir-general/en/public"
STAFF = "weir-general/en/staff"
CHUNKS = [
    {"id": "pub-a#0", "doc_id": "pub-a", "title": "Visiting", "text": "t", "score": 0.9, "token_count": 3},
    {"id": "pub-a#1", "doc_id": "pub-a", "title": "Visiting", "text": "t", "score": 0.8, "token_count": 3},
    {"id": "pub-b#0", "doc_id": "pub-b", "title": "ICU", "text": "t", "score": 0.7, "token_count": 3},
]


class ListSink:
    def __init__(self):
        self.rows = []

    def submit(self, row):
        self.rows.append(row)


def fake_rag(generate_response=None, chunks=CHUNKS, seen=None):
    def handler(request):
        body = json.loads(request.content)
        if request.url.path == "/retrieve":
            return httpx.Response(200, json={"chunks": chunks, "top_score": 0.9, "score_gap": 0.1,
                                             "context_tokens": 9, "kb_version": "v1", "latency_ms": 3})
        if seen is not None:
            seen.append(body)
        if generate_response is not None:
            return generate_response
        cited = ["pub-a#1", "pub-b#0", "pub-a#0"] if body["chunks"] else []
        return httpx.Response(200, json={
            "answer": "Answer." if body["chunks"] else "Sorry, not found.", "cited_chunk_ids": cited,
            "invalid_citations": 0, "not_found": not body["chunks"],
            "finish_reason": "stop" if body["chunks"] else "skipped",
            "tokens_in": 1000 if body["chunks"] else 0, "tokens_out": 500 if body["chunks"] else 0,
            "model": body["model"], "prompt_version": "p1", "latency_ms": 7})
    return RagClient("http://rag", 5, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag"))


def pipeline(rag, overlay=None, **config_overrides):
    cfg = load_config(CONFIGS / "weir.yaml", overlay)
    for path, value in config_overrides.items():
        section, key = path.split("__")
        setattr(getattr(cfg, section), key, value)
    sink = ListSink()
    fixed_now = lambda: datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # noqa: E731
    return Pipeline(cfg, rag, PriceTable.from_yaml(CONFIGS / "prices.yaml"), sink, now=fixed_now), sink


async def test_happy_path_large_with_cost_and_log():
    p, sink = pipeline(fake_rag())
    resp = await p.handle(QueryRequest(query="  When can I visit? ", namespace=PUBLIC))
    assert resp.answer == "Answer."
    assert [s.id for s in resp.sources] == ["pub-a", "pub-b"]  # dedup by doc, citation order
    assert resp.meta.cache_status == "bypass" and resp.meta.route == "large"
    assert resp.meta.model == "openai/gpt-oss-120b"
    assert resp.meta.cost_usd == pytest.approx(0.00045)
    [row] = sink.rows
    assert row.bypass_reason == "cache_disabled" and row.status == "ok"
    assert row.cost_usd == Decimal("0.00045") == row.counterfactual_cost_usd
    assert (row.tokens_in, row.tokens_out, row.model_calls) == (1000, 500, 1)
    assert row.query_text == "When can I visit?" and row.config_label == "dev"
    assert str(row.request_id) == resp.meta.request_id


async def test_force_small_is_cheaper_than_counterfactual():
    seen = []
    p, sink = pipeline(fake_rag(seen=seen))
    resp = await p.handle(QueryRequest(query="q", namespace=PUBLIC, options=QueryOptions(force_model="small")))
    assert seen[0]["model"] == "openai/gpt-oss-20b" and resp.meta.route == "small"
    [row] = sink.rows
    # small: 1000*0.075 + 500*0.30 = 225 per 1e6; counterfactual at large prices = 450 per 1e6
    assert row.cost_usd == Decimal("0.000225") and row.counterfactual_cost_usd == Decimal("0.00045")


async def test_kill_switch_force_large_beats_force_model():
    seen = []
    p, _ = pipeline(fake_rag(seen=seen), overlay=CONFIGS / "ablations" / "baseline.yaml")
    resp = await p.handle(QueryRequest(query="q", namespace=PUBLIC, options=QueryOptions(force_model="small")))
    assert resp.meta.route == "large" and seen[0]["model"] == "openai/gpt-oss-120b"


@pytest.mark.parametrize(("request_kwargs", "overrides", "reason"), [
    ({"personalized": True}, {}, "personalized"),
    ({"options": QueryOptions(bypass_cache=True)}, {}, "request_option"),
    ({}, {"kill_switch__disable_cache": True}, "kill_switch"),
    ({}, {}, "cache_disabled"),
])
async def test_bypass_reasons(request_kwargs, overrides, reason):
    p, sink = pipeline(fake_rag(), **overrides)
    await p.handle(QueryRequest(query="q", namespace=PUBLIC, **request_kwargs))
    assert sink.rows[0].bypass_reason == reason


async def test_sensitive_namespace_logs_no_query_text():
    p, sink = pipeline(fake_rag())
    await p.handle(QueryRequest(query="How do I register a patient?", namespace=STAFF))
    assert sink.rows[0].query_text is None
    assert len(sink.rows[0].query_hash) == 64


async def test_no_chunks_returns_not_found_answer():
    p, sink = pipeline(fake_rag(chunks=[]))
    resp = await p.handle(QueryRequest(query="q", namespace=PUBLIC))
    assert resp.sources == [] and resp.answer == "Sorry, not found."
    assert sink.rows[0].model_calls == 0 and sink.rows[0].cost_usd == 0


async def test_rate_limited_generate_raises_503_and_logs_error():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    p, sink = pipeline(fake_rag(generate_response=limited))
    with pytest.raises(PipelineError) as exc:
        await p.handle(QueryRequest(query="q", namespace=PUBLIC))
    assert exc.value.status_code == 503 and exc.value.retry_after == 12.0
    assert exc.value.request_id == str(sink.rows[0].request_id)
    assert sink.rows[0].status == "error" and "rate_limited" in sink.rows[0].error_detail


async def test_timeout_maps_to_504_and_status_timeout():
    p, sink = pipeline(fake_rag(generate_response=httpx.Response(504, json={"error": "timeout"})))
    with pytest.raises(PipelineError) as exc:
        await p.handle(QueryRequest(query="q", namespace=PUBLIC))
    assert exc.value.status_code == 504 and sink.rows[0].status == "timeout"


def test_blank_query_rejected():
    with pytest.raises(ValueError):
        QueryRequest(query="   ", namespace=PUBLIC)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL, `No module named 'weir.pipeline'`.

- [ ] **Step 3: Implement the pipeline**

`src/weir/pipeline.py`:
```python
"""Request pipeline. Phase 0/1: no cache, no router — retrieve, generate, log (spec §5.3).

Phase 2 inserts the cache before retrieval; Phase 3 replaces _choose_tier with the router.
"""
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import WeirConfig
from .llm.pricing import PriceTable
from .metrics.logger import LogSink, RequestLogRow
from .rag.adapter import RagClient, RagError, RetrievedChunk
from .text import query_hash

Tier = Literal["small", "large"]
ERROR_STATUS = {"rate_limited": 503, "timeout": 504, "unavailable": 502, "bad_response": 502}


class QueryOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bypass_cache: bool = False
    force_model: Tier | None = None


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    namespace: str
    session_id: str | None = None
    personalized: bool = False
    options: QueryOptions = QueryOptions()

    @field_validator("query")
    @classmethod
    def strip_and_require(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query is blank")
        return v.strip()


class Source(BaseModel):
    id: str
    title: str


class QueryMeta(BaseModel):
    request_id: str
    cache_status: Literal["hit", "miss", "bypass"]
    similarity: float | None
    route: Literal["none", "small", "large"]
    escalated: bool
    model: str | None
    latency_ms: int
    cost_usd: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    meta: QueryMeta


class PipelineError(Exception):
    def __init__(self, status_code: int, error: str, request_id: str, retry_after: float | None = None):
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.request_id = request_id
        self.retry_after = retry_after


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class Pipeline:
    def __init__(self, cfg: WeirConfig, rag: RagClient, prices: PriceTable, log: LogSink,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._cfg = cfg
        self._rag = rag
        self._prices = prices
        self._log = log
        self._now = now

    async def handle(self, req: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        now = self._now()
        row = RequestLogRow(
            request_id=uuid4(), ts=now, namespace=req.namespace,
            cache_status="bypass", bypass_reason=self._bypass_reason(req),
            route="none", status="ok", latency_total_ms=0,
            query_hash=query_hash(req.query),
            query_text=None if self._cfg.is_sensitive(req.namespace) else req.query,
            config_label=self._cfg.config_label,
        )
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

        today = now.date()
        row.model = generated.model
        row.model_calls = 0 if generated.finish_reason == "skipped" else 1
        row.tokens_in, row.tokens_out = generated.tokens_in, generated.tokens_out
        row.cost_usd = self._prices.cost(model, generated.tokens_in, generated.tokens_out, today)
        row.counterfactual_cost_usd = self._prices.cost(
            self._cfg.router.large_model, generated.tokens_in, generated.tokens_out, today)
        row.answer_len = len(generated.answer)
        row.latency_total_ms = _ms(started)
        self._log.submit(row)

        return QueryResponse(
            answer=generated.answer,
            sources=_sources(retrieved.chunks, generated.cited_chunk_ids),
            meta=QueryMeta(
                request_id=str(row.request_id), cache_status=row.cache_status, similarity=None,
                route=row.route, escalated=False, model=row.model,
                latency_ms=row.latency_total_ms, cost_usd=float(row.cost_usd),
            ),
        )

    def _bypass_reason(self, req: QueryRequest) -> str:
        if req.personalized:
            return "personalized"
        if req.options.bypass_cache:
            return "request_option"
        if self._cfg.kill_switch.disable_cache:
            return "kill_switch"
        return "cache_disabled"

    def _choose_tier(self, req: QueryRequest) -> Tier:
        if self._cfg.kill_switch.force_large:
            return "large"
        return req.options.force_model or "large"


def _sources(chunks: list[RetrievedChunk], cited_ids: list[str]) -> list[Source]:
    by_id = {c.id: c for c in chunks}
    sources: list[Source] = []
    seen: set[str] = set()
    for chunk_id in cited_ids:
        chunk = by_id.get(chunk_id)
        if chunk and chunk.doc_id not in seen:
            seen.add(chunk.doc_id)
            sources.append(Source(id=chunk.doc_id, title=chunk.title))
    return sources
```

- [ ] **Step 4: Run the pipeline tests**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: 12 passed.

- [ ] **Step 5: Write the failing API tests**

`tests/test_api.py`:
```python
import httpx
import pytest

from weir.auth import TenantRegistry
from weir.config import load_config
from weir.main import AppDeps, create_app

from .conftest import CONFIGS
from .test_pipeline import PUBLIC, STAFF, fake_rag, pipeline

ENV = {"WEIR_KEY_PUBLIC": "pub-key", "WEIR_KEY_STAFF": "staff-key", "WEIR_KEY_ADMIN": "admin-key"}


def app_client(rag=None, health_ok=True):
    p, sink = pipeline(rag or fake_rag())

    async def health():
        return {"db": health_ok, "rag": True}

    deps = AppDeps(p, TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", ENV), load_config(CONFIGS / "weir.yaml"), health)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://t")
    return client, sink


async def test_query_ok_sets_request_id_header():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == r.json()["meta"]["request_id"] == str(sink.rows[0].request_id)


async def test_missing_key_401():
    client, sink = app_client()
    async with client:
        r1 = await client.post("/v1/query", json={"query": "hi", "namespace": PUBLIC})
        r2 = await client.post("/v1/query", headers={"X-API-Key": "bad"}, json={"query": "hi", "namespace": PUBLIC})
    assert r1.status_code == r2.status_code == 401
    assert sink.rows == []


async def test_wrong_namespace_403():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "hi", "namespace": STAFF})
    assert r.status_code == 403 and sink.rows == []


async def test_blank_query_422():
    client, _ = app_client()
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "  ", "namespace": PUBLIC})
    assert r.status_code == 422


async def test_rate_limited_generate_returns_503_with_request_id():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    client, sink = app_client(rag=fake_rag(generate_response=limited))
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 503
    assert r.json() == {"error": "rate_limited", "request_id": str(sink.rows[0].request_id)}
    assert r.headers["Retry-After"] == "12"
    assert r.headers["X-Request-ID"] == str(sink.rows[0].request_id)


@pytest.mark.parametrize(("ok", "status"), [(True, 200), (False, 503)])
async def test_healthz(ok, status):
    client, _ = app_client(health_ok=ok)
    async with client:
        r = await client.get("/healthz")
    assert r.status_code == status
    assert r.json()["config_label"] == "dev" and r.json()["checks"]["db"] is ok
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL, `No module named 'weir.main'`.

- [ ] **Step 7: Implement the app**

`src/weir/main.py`:
```python
import logging
import math
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .auth import TenantRegistry
from .config import WeirConfig, load_config
from .db import open_pool
from .llm.pricing import PriceTable, sync_prices
from .metrics.logger import LogWriter
from .pipeline import Pipeline, PipelineError, QueryRequest, QueryResponse
from .rag.adapter import RagClient
from .settings import Settings

logging.basicConfig(level=logging.INFO)


@dataclass
class AppDeps:
    pipeline: Pipeline
    tenants: TenantRegistry
    config: WeirConfig
    health: Callable[[], Awaitable[dict[str, bool]]]


def create_app(deps: AppDeps | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is not None:
            yield
            return
        s = Settings()
        cfg = load_config(s.config_path(), s.overlay_path())
        tenants = TenantRegistry.from_yaml(s.weir_configs_dir / "tenants.yaml", os.environ)
        prices = PriceTable.from_yaml(s.weir_configs_dir / "prices.yaml")
        today = datetime.now(UTC).date()
        for model in (cfg.router.small_model, cfg.router.large_model):
            prices.price_for(model, today)  # fail fast: every configured model must be priced
        pool = await open_pool(s.database_url)
        await sync_prices(pool, prices)
        writer = LogWriter(pool)
        writer.start()
        rag = RagClient(cfg.rag.base_url, cfg.rag.timeout_seconds)

        async def health() -> dict[str, bool]:
            try:
                async with pool.connection() as conn:
                    await conn.execute("select 1")
                db_ok = True
            except Exception:  # noqa: BLE001
                db_ok = False
            return {"db": db_ok, "rag": await rag.health()}

        app.state.deps = AppDeps(Pipeline(cfg, rag, prices, writer), tenants, cfg, health)
        try:
            yield
        finally:
            await writer.stop()
            await rag.aclose()
            await pool.close()

    app = FastAPI(title="Weir", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps

    @app.post("/v1/query", response_model=QueryResponse)
    async def query(body: QueryRequest, request: Request, response: Response,
                    x_api_key: str | None = Header(default=None)):
        d: AppDeps = request.app.state.deps
        tenant = d.tenants.authenticate(x_api_key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        if not tenant.allows(body.namespace):
            raise HTTPException(status_code=403, detail="namespace not allowed for this API key")
        try:
            result = await d.pipeline.handle(body)
        except PipelineError as e:
            headers = {"X-Request-ID": e.request_id}
            if e.retry_after is not None:
                headers["Retry-After"] = str(math.ceil(e.retry_after))
            return JSONResponse(status_code=e.status_code, headers=headers,
                                content={"error": e.error, "request_id": e.request_id})
        response.headers["X-Request-ID"] = result.meta.request_id
        return result

    @app.get("/healthz")
    async def healthz(request: Request):
        d: AppDeps = request.app.state.deps
        checks = await d.health()
        ok = all(checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={
            "status": "ok" if ok else "degraded", "checks": checks, "config_label": d.config.config_label})

    return app


app = create_app()
```

- [ ] **Step 8: Run the whole Weir test suite**

Run: `uv run pytest -v`
Expected: all pass (48 tests).

- [ ] **Step 9: Compose service**

Append to `docker-compose.yml` under `services:`:
```yaml
  weir:
    build: { context: ., dockerfile: services/weir/Dockerfile }
    environment:
      DATABASE_URL: postgresql://weir:weir@postgres:5432/weir
      WEIR_KEY_PUBLIC: ${WEIR_KEY_PUBLIC:?set WEIR_KEY_PUBLIC in .env}
      WEIR_KEY_STAFF: ${WEIR_KEY_STAFF:?set WEIR_KEY_STAFF in .env}
      WEIR_KEY_ADMIN: ${WEIR_KEY_ADMIN:?set WEIR_KEY_ADMIN in .env}
      WEIR_ABLATION: ${WEIR_ABLATION:-}
    volumes: ["./configs:/app/configs:ro"]
    ports: ["8000:8000"]
    depends_on:
      migrate: { condition: service_completed_successfully }
      hospital-rag: { condition: service_healthy }
```

- [ ] **Step 10: Phase 0 exit check (1 Groq call)**

```bash
docker compose up -d --build
set -a; source .env; set +a
curl -s localhost:8000/healthz
curl -s -i localhost:8000/v1/query -H "X-API-Key: $WEIR_KEY_PUBLIC" -H 'content-type: application/json' \
  -d '{"query":"What are the visiting hours for the ICU?","namespace":"weir-general/en/public"}'
docker compose exec postgres psql -U weir -c "select cache_status, bypass_reason, route, model, tokens_in, tokens_out, cost_usd, latency_total_ms, status from weir.request_log order by ts desc limit 1"
```
Expected: healthz returns `{"status":"ok","checks":{"db":true,"rag":true},"config_label":"dev"}`. The query returns 200 with an `X-Request-ID` header, an ICU-hours answer, `sources` containing `pub-visiting-hours-icu`, and `meta.cost_usd` around 0.0003. The log row shows `bypass | cache_disabled | large | openai/gpt-oss-120b | ... | ok`.

- [ ] **Step 11: Update the progress log and commit**

Append to `docs/progress.md`:
```markdown
## <date>: Phase 0 exit ✅

- Weir pass-through gateway: auth (401/403), /v1/query → hospital-rag retrieve+generate, /healthz.
- Every request writes a weir.request_log row off the request path, priced at list prices.
- Exit criterion met: POST /v1/query returned a grounded, cited ICU-hours answer.
```

```bash
git add services/weir docker-compose.yml docs/progress.md
git commit -m "feat(weir): pass-through pipeline, gateway API, request logging (Phase 0 exit)"
```

---

### Task 12: Eval dataset model, key-fact checks, and splits

**Files:**
- Create: `eval/pyproject.toml`, `eval/src/weir_eval/__init__.py`, `eval/src/weir_eval/dataset.py`, `eval/src/weir_eval/keyfacts.py`, `eval/src/weir_eval/kb.py`
- Test: `eval/tests/__init__.py`, `eval/tests/conftest.py`, `eval/tests/test_dataset.py`, `eval/tests/test_keyfacts.py`, `eval/tests/test_kb.py`

**Interfaces:**
- Produces: `EvalQuery` (fields `id, namespace, query, group: "distinct"|"paraphrase"|"trap", cluster_id, difficulty: "easy"|"medium"|"hard", required_facts: list[str] (at least 1), source_docs: list[str] (at least 1), split: "tune"|"holdout"|None`), `load_queries(path) -> list[EvalQuery]`, `save_queries(path, queries) -> None`, `validate(queries) -> list[str]` (problems, empty when valid), `assign_splits(queries, holdout_frac=0.3, seed=7) -> list[EvalQuery]`.
- Produces: `norm(text) -> str`, `fact_present(answer, fact) -> bool` (`fact` may be `alt1|alt2`), `FactResult(hits, total)` with `.score`, `check_facts(answer, facts) -> FactResult`.
- Produces: `load_kb_texts(kb_dir: Path) -> dict[str, str]` (doc id → full text) and `facts_missing_from_sources(queries, kb) -> list[str]`.

- [ ] **Step 1: Package**

`eval/pyproject.toml`:
```toml
[project]
name = "weir-eval"
version = "0.1.0"
description = "Eval runner for Weir: replay, key-fact checks, Gemini judge, reports"
requires-python = ">=3.12,<3.13"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.8",
  "pyyaml>=6.0",
  "google-genai>=1.0",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/weir_eval"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

`eval/src/weir_eval/__init__.py`:
```python
"""Eval tooling for Weir (docs/superpowers/specs/2026-09-30-weir-design.md §11)."""
```

`eval/tests/__init__.py`: empty. `eval/tests/conftest.py`:
```python
from weir_eval.dataset import EvalQuery


def q(id, cluster, group="distinct", split=None, facts=("4 pm",), ns="weir-general/en/public", docs=("pub-a",)):
    return EvalQuery(id=id, namespace=ns, query=f"question {id}", group=group, cluster_id=cluster,
                     difficulty="easy", required_facts=list(facts), source_docs=list(docs), split=split)
```

Run: `cd eval && uv lock && uv sync`

- [ ] **Step 2: Write the failing tests**

`eval/tests/test_keyfacts.py`:
```python
from weir_eval.keyfacts import check_facts, fact_present, norm


def test_norm_handles_case_space_dashes_and_am_pm():
    assert norm("  4 P.M.– 8 p.m. ") == "4 pm- 8 pm"


def test_alternatives():
    assert fact_present("Visiting ends at 8:00 PM daily.", "8 pm|8:00 pm")
    assert not fact_present("Visiting ends at 9 pm.", "8 pm|8:00 pm")


def test_check_facts_score():
    r = check_facts("ICU visiting is 11 am to 11:30 am, one visitor.", ["11 am", "one visitor|1 visitor", "5 pm"])
    assert (r.hits, r.total) == (2, 3)
    assert abs(r.score - 2 / 3) < 1e-9
```

`eval/tests/test_dataset.py`:
```python
from weir_eval.dataset import assign_splits, load_queries, save_queries, validate

from .conftest import q


def valid_set():
    return (
        [q(f"d{i}", f"d{i}") for i in range(10)]
        + [q(f"p{i}", "para-1", group="paraphrase") for i in range(4)]
        + [q("t1", "trap-1", group="trap", facts=("4 pm",)), q("t2", "trap-1", group="trap", facts=("11 am",))]
    )


def test_round_trip(tmp_path):
    path = tmp_path / "q.jsonl"
    save_queries(path, valid_set())
    assert load_queries(path) == valid_set()


def test_valid_set_has_no_problems():
    assert validate(valid_set()) == []


def test_problems_detected():
    bad = valid_set() + [q("d0", "dup")]  # duplicate id
    bad += [q("p9", "para-2", group="paraphrase")]  # cluster too small
    bad += [q("t3", "trap-2", group="trap"), q("t4", "trap-2", group="trap")]  # same facts in a trap pair
    problems = "\n".join(validate(bad))
    assert "duplicate id d0" in problems
    assert "para-2" in problems
    assert "trap-2" in problems


def test_split_by_cluster_never_splits_a_cluster():
    queries = assign_splits(valid_set() * 1, holdout_frac=0.3, seed=7)
    by_cluster = {}
    for x in queries:
        by_cluster.setdefault(x.cluster_id, set()).add(x.split)
    assert all(len(s) == 1 for s in by_cluster.values())
    assert {x.split for x in queries} == {"tune", "holdout"}
    assert validate(queries) == []


def test_split_is_deterministic():
    assert assign_splits(valid_set(), seed=7) == assign_splits(valid_set(), seed=7)


def test_mixed_split_in_cluster_is_a_problem():
    qs = [q("p1", "para-1", "paraphrase", "tune")] + [q(f"p{i}", "para-1", "paraphrase", "holdout") for i in range(2, 5)]
    assert any("para-1" in p for p in validate(qs))
```

`eval/tests/test_kb.py`:
```python
from weir_eval.kb import facts_missing_from_sources, load_kb_texts

from .conftest import q


def test_facts_checked_against_source_docs(tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "pub-a.md").write_text("---\nid: pub-a\ntitle: A\n---\n\nOpen 4 pm to 8 pm.", encoding="utf-8")
    kb = load_kb_texts(tmp_path)
    assert set(kb) == {"pub-a"}
    assert facts_missing_from_sources([q("d1", "d1", facts=("4 pm",))], kb) == []
    problems = facts_missing_from_sources([q("d2", "d2", facts=("9 pm",)), q("d3", "d3", docs=("nope",))], kb)
    assert any("d2" in p and "9 pm" in p for p in problems)
    assert any("d3" in p and "nope" in p for p in problems)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest -v`
Expected: FAIL with import errors.

- [ ] **Step 4: Implement**

`eval/src/weir_eval/keyfacts.py`:
```python
import re
from dataclasses import dataclass

DASHES = re.compile(r"[‐-―−]")
AM_PM = re.compile(r"\b([ap])\.m\.?", re.IGNORECASE)


def norm(text: str) -> str:
    text = DASHES.sub("-", text)
    text = AM_PM.sub(lambda m: m.group(1) + "m", text)
    return " ".join(text.lower().split())


def fact_present(answer: str, fact: str) -> bool:
    haystack = norm(answer)
    return any(norm(alt) in haystack for alt in fact.split("|") if alt.strip())


@dataclass(frozen=True)
class FactResult:
    hits: int
    total: int

    @property
    def score(self) -> float:
        return self.hits / self.total if self.total else 0.0


def check_facts(answer: str, facts: list[str]) -> FactResult:
    return FactResult(sum(fact_present(answer, f) for f in facts), len(facts))
```

`eval/src/weir_eval/dataset.py`:
```python
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    namespace: str
    query: str
    group: Literal["distinct", "paraphrase", "trap"]
    cluster_id: str
    difficulty: Literal["easy", "medium", "hard"]
    required_facts: list[str] = Field(min_length=1)
    source_docs: list[str] = Field(min_length=1)
    split: Literal["tune", "holdout"] | None = None


def load_queries(path: Path) -> list[EvalQuery]:
    queries = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                queries.append(EvalQuery.model_validate_json(line))
            except ValueError as e:
                raise ValueError(f"{path}:{n}: {e}") from e
    return queries


def save_queries(path: Path, queries: list[EvalQuery]) -> None:
    lines = [json.dumps(q.model_dump(), ensure_ascii=False) for q in queries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


CLUSTER_SIZE = {"distinct": (1, 1), "paraphrase": (4, 6), "trap": (2, 2)}


def validate(queries: list[EvalQuery]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for q in queries:
        if q.id in seen:
            problems.append(f"duplicate id {q.id}")
        seen.add(q.id)
    clusters: dict[str, list[EvalQuery]] = defaultdict(list)
    for q in queries:
        clusters[q.cluster_id].append(q)
    for cid, members in clusters.items():
        groups = {m.group for m in members}
        if len(groups) != 1:
            problems.append(f"cluster {cid} mixes groups {sorted(groups)}")
            continue
        low, high = CLUSTER_SIZE[members[0].group]
        if not low <= len(members) <= high:
            problems.append(f"cluster {cid} ({members[0].group}) has {len(members)} members, needs {low}-{high}")
        if len({m.namespace for m in members}) != 1:
            problems.append(f"cluster {cid} spans namespaces")
        if len({m.split for m in members}) != 1:
            problems.append(f"cluster {cid} is split across tune/holdout")
        if members[0].group == "trap" and len({tuple(m.required_facts) for m in members}) != len(members):
            problems.append(f"trap cluster {cid} members must need different facts")
    return problems


def assign_splits(queries: list[EvalQuery], holdout_frac: float = 0.3, seed: int = 7) -> list[EvalQuery]:
    """Hold out ~holdout_frac of clusters per group; a cluster is never split (spec §11.1)."""
    rng = random.Random(seed)
    holdout: set[str] = set()
    for group in ("distinct", "paraphrase", "trap"):
        cluster_ids = sorted({q.cluster_id for q in queries if q.group == group})
        rng.shuffle(cluster_ids)
        holdout.update(cluster_ids[: round(len(cluster_ids) * holdout_frac)])
    return [q.model_copy(update={"split": "holdout" if q.cluster_id in holdout else "tune"}) for q in queries]
```

`eval/src/weir_eval/kb.py`:
```python
import re
from pathlib import Path

from .dataset import EvalQuery
from .keyfacts import fact_present

ID_LINE = re.compile(r"^id:\s*(.+)$", re.MULTILINE)


def load_kb_texts(kb_dir: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    for path in sorted(kb_dir.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        match = ID_LINE.search(text)
        if match:
            texts[match.group(1).strip()] = text
    return texts


def facts_missing_from_sources(queries: list[EvalQuery], kb: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for q in queries:
        missing_docs = [d for d in q.source_docs if d not in kb]
        if missing_docs:
            problems.append(f"{q.id}: unknown source docs {missing_docs}")
            continue
        corpus = "\n".join(kb[d] for d in q.source_docs)
        for fact in q.required_facts:
            if not fact_present(corpus, fact):
                problems.append(f"{q.id}: fact {fact!r} not found in {q.source_docs}")
    return problems
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add eval
git commit -m "feat(eval): dataset model, cluster-safe splits, key-fact checks"
```

---

### Task 13: First 50 eval queries (content task, suited to a subagent)

**Files:**
- Create: `eval/datasets/queries.jsonl`

**Interfaces:**
- Consumes: `kb/README.md` (the planted pairs) and the KB documents (Task 2), plus `EvalQuery`, `validate`, `assign_splits` and `facts_missing_from_sources` (Task 12).
- Produces: 50 JSONL lines conforming to `EvalQuery`, with `split` assigned.

**Authoring rules (put these in the subagent prompt verbatim):**
- Read `kb/README.md` and every document under `kb/public` and `kb/staff`. Every fact must come from the documents. Never invent any.
- **Mix:**
  - 25 `distinct` queries, each its own `cluster_id` (`d-01`…`d-25`). 20 public, 5 staff. Difficulty: 10 easy (single fact), 10 medium (two facts from one document), 5 hard (compare or combine two documents, with 2 entries in `source_docs`).
  - 15 `paraphrase` queries: 3 clusters (`para-1`…`para-3`) of 5 each (a seed question plus 4 natural rewordings, varying vocabulary and word order, not only synonyms). All members of a cluster share the same `required_facts` and `source_docs`. All public.
  - 10 `trap` queries: 5 clusters (`trap-1`…`trap-5`) of 2, each built from a planted pair in `kb/README.md`. The two questions look nearly identical but need different facts, for example "ICU visiting hours" vs "general ward visiting hours". Use at least one staff pair (nurse vs doctor shifts).
- `required_facts` holds 1–3 short, literal strings that appear in the source document, with `|` alternatives for formatting variants a model might produce (`8 pm|8:00 pm|20:00`). Keep each fact minimal (the time or the number, not a sentence).
- `namespace`: `weir-general/en/public` or `weir-general/en/staff`, matching the source document folder.
- No clinical questions. Ids are `q-001`…`q-050`.

Line format:
```json
{"id": "q-001", "namespace": "weir-general/en/public", "query": "What time does ICU visiting start in the morning?", "group": "distinct", "cluster_id": "d-01", "difficulty": "easy", "required_facts": ["11 am|11:00 am"], "source_docs": ["pub-visiting-hours-icu"], "split": null}
```

- [ ] **Step 1: Write the 50 lines** following the rules above.

- [ ] **Step 2: Assign splits and validate**

Run (from `eval/`):
```bash
uv run python - <<'EOF'
from pathlib import Path
from weir_eval.dataset import load_queries, save_queries, assign_splits, validate
from weir_eval.kb import load_kb_texts, facts_missing_from_sources
p = Path("datasets/queries.jsonl")
qs = assign_splits(load_queries(p))
save_queries(p, qs)
problems = validate(qs) + facts_missing_from_sources(qs, load_kb_texts(Path("../kb")))
from collections import Counter
print(Counter(q.group for q in qs), Counter(q.split for q in qs))
print("\n".join(problems) or "no problems")
EOF
```
Expected: `Counter({'distinct': 25, 'paraphrase': 15, 'trap': 10})`, about a 70/30 tune/holdout split, and `no problems`. Fix every reported problem by editing the query, never the KB, then re-run.

- [ ] **Step 3: Human review (user)**

Ask the user to read 10 random lines against the KB (their spot check of the eval set) and record the outcome in `docs/progress.md` at Task 16.

- [ ] **Step 4: Commit**

```bash
git add eval/datasets/queries.jsonl
git commit -m "data(eval): first 50 eval queries (25 distinct, 3 paraphrase clusters, 5 trap pairs)"
```

---

### Task 14: Retry helper and Gemini judge with a disk cache

**Files:**
- Create: `eval/src/weir_eval/retry.py`, `eval/src/weir_eval/judge.py`
- Test: `eval/tests/test_retry.py`, `eval/tests/test_judge.py`

**Interfaces:**
- Produces: `async with_retries(fn: Callable[[], Awaitable[T]], is_retryable: Callable[[Exception], float | None], max_attempts: int = 4, sleep=asyncio.sleep) -> T`. `is_retryable` returns the seconds to wait, or `None` to re-raise.
- Produces: `RUBRIC_VERSION = "r1"`, `JudgeVerdict(score: int 1..5, reason: str)`, `Judge(call: Callable[[str], Awaitable[str]], cache_dir: Path, model: str, sleep=asyncio.sleep)` with `async grade(query: str, facts: list[str], source_text: str, answer: str) -> JudgeVerdict`, and `gemini_call(api_key: str, model: str) -> Callable[[str], Awaitable[str]]`.

- [ ] **Step 1: Write the failing tests**

`eval/tests/test_retry.py`:
```python
import pytest

from weir_eval.retry import with_retries


class Flaky(Exception):
    pass


async def test_retries_then_succeeds():
    calls, sleeps = [], []

    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise Flaky()
        return "ok"

    async def fake_sleep(s):
        sleeps.append(s)

    result = await with_retries(fn, lambda e: 5.0 if isinstance(e, Flaky) else None, sleep=fake_sleep)
    assert result == "ok" and sleeps == [5.0, 5.0]


async def test_non_retryable_raises_immediately():
    async def fn():
        raise ValueError("no")

    with pytest.raises(ValueError):
        await with_retries(fn, lambda e: None)


async def test_gives_up_after_max_attempts():
    async def fn():
        raise Flaky()

    async def fake_sleep(s):
        pass

    with pytest.raises(Flaky):
        await with_retries(fn, lambda e: 1.0, max_attempts=3, sleep=fake_sleep)
```

`eval/tests/test_judge.py`:
```python
import json

import pytest

from weir_eval.judge import Judge


class FakeCall:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


async def no_sleep(s):
    pass


async def test_grade_parses_and_caches(tmp_path):
    call = FakeCall([json.dumps({"score": 4, "reason": "fine"})])
    judge = Judge(call, tmp_path, "gemini-x", sleep=no_sleep)
    v1 = await judge.grade("q?", ["4 pm"], "SOURCE", "It opens at 4 pm.")
    v2 = await judge.grade("q?", ["4 pm"], "SOURCE", "It opens at 4 pm.")
    assert (v1.score, v2.score) == (4, 4)
    assert len(call.prompts) == 1  # second call served from disk cache
    assert "SOURCE" in call.prompts[0] and "4 pm" in call.prompts[0]


async def test_invalid_json_retried_once_then_raises(tmp_path):
    judge = Judge(FakeCall(["not json", "still not"]), tmp_path, "m", sleep=no_sleep)
    with pytest.raises(ValueError):
        await judge.grade("q", ["f"], "s", "a")


async def test_rate_limit_is_retried(tmp_path):
    class RateErr(Exception):
        code = 429

    call = FakeCall([RateErr(), json.dumps({"score": 5, "reason": "ok"})])
    v = await Judge(call, tmp_path, "m", sleep=no_sleep).grade("q", ["f"], "s", "a")
    assert v.score == 5


async def test_out_of_range_score_rejected(tmp_path):
    judge = Judge(FakeCall([json.dumps({"score": 9, "reason": "x"})] * 2), tmp_path, "m", sleep=no_sleep)
    with pytest.raises(ValueError):
        await judge.grade("q", ["f"], "s", "a")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_retry.py tests/test_judge.py -v`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement**

`eval/src/weir_eval/retry.py`:
```python
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    is_retryable: Callable[[Exception], float | None],
    max_attempts: int = 4,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as e:  # noqa: BLE001 - classified by is_retryable
            wait = is_retryable(e)
            if wait is None or attempt == max_attempts:
                raise
            await sleep(wait)
    raise AssertionError("unreachable")
```

`eval/src/weir_eval/judge.py`:
```python
"""LLM judge on the Gemini free tier, with answers cached on disk so reruns cost nothing."""
import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .retry import with_retries

RUBRIC_VERSION = "r1"
RUBRIC = """You are grading an answer from a hospital help-desk chatbot for Weir General Hospital.
Use ONLY the source document below as the truth.

Score from 1 to 5:
5 = correct and complete: every required fact is present and nothing contradicts the source.
4 = correct, with a minor omission or extra detail that is still true per the source.
3 = partly correct: some required facts are missing, nothing is false.
2 = mostly wrong or missing key facts, or includes a claim the source does not support.
1 = wrong, contradicts the source, or answers a different question.
If the answer says the information could not be found but the source contains it, score 1.

Return JSON only: {"score": <integer 1-5>, "reason": "<one sentence>"}"""


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str


def _rate_limit_wait(error: Exception) -> float | None:
    return 30.0 if getattr(error, "code", None) == 429 else None


class Judge:
    def __init__(self, call: Callable[[str], Awaitable[str]], cache_dir: Path, model: str,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._call = call
        self._cache_dir = cache_dir
        self._model = model
        self._sleep = sleep
        cache_dir.mkdir(parents=True, exist_ok=True)

    async def grade(self, query: str, facts: list[str], source_text: str, answer: str) -> JudgeVerdict:
        key = hashlib.sha256(json.dumps([RUBRIC_VERSION, self._model, query, facts, answer]).encode()).hexdigest()
        cached = self._cache_dir / f"{key}.json"
        if cached.exists():
            return JudgeVerdict.model_validate_json(cached.read_text(encoding="utf-8"))
        prompt = (f"{RUBRIC}\n\n### Source document\n{source_text}\n\n### Question\n{query}\n\n"
                  f"### Required facts\n{json.dumps(facts, ensure_ascii=False)}\n\n### Answer to grade\n{answer}\n")
        last_error: Exception | None = None
        for _ in range(2):  # one retry on malformed output
            raw = await with_retries(lambda: self._call(prompt), _rate_limit_wait, sleep=self._sleep)
            try:
                verdict = JudgeVerdict.model_validate_json(raw)
            except ValidationError as e:
                last_error = e
                continue
            cached.write_text(verdict.model_dump_json(), encoding="utf-8")
            return verdict
        raise ValueError(f"judge returned invalid output twice: {last_error}")


def gemini_call(api_key: str, model: str) -> Callable[[str], Awaitable[str]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json", response_schema=JudgeVerdict)

    async def call(prompt: str) -> str:
        response = await client.aio.models.generate_content(model=model, contents=prompt, config=config)
        return response.text or ""

    return call
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_retry.py tests/test_judge.py -v`
Expected: 7 passed.

- [ ] **Step 5: Confirm the judge model is available to the key (user needs `GEMINI_API_KEY` in `.env`)**

Run (from `eval/`):
```bash
uv run --env-file ../.env python -c "import os; from google import genai; c=genai.Client(api_key=os.environ['GEMINI_API_KEY']); names=[m.name for m in c.models.list()]; print([n for n in names if 'flash' in n])"
```
Expected: the list includes `models/gemini-2.5-flash`. If it doesn't, pick a listed Flash model, put it in `.env` as `JUDGE_MODEL`, and record the choice in `docs/decisions.md`.

- [ ] **Step 6: Commit**

```bash
git add eval
git commit -m "feat(eval): retry helper and cached Gemini judge"
```

---

### Task 15: Eval runner, summary, and CLI

**Files:**
- Create: `eval/src/weir_eval/summary.py`, `eval/src/weir_eval/runner.py`, `eval/src/weir_eval/cli.py`, `eval/src/weir_eval/__main__.py`
- Test: `eval/tests/test_summary.py`, `eval/tests/test_runner.py`

**Interfaces:**
- Consumes: `EvalQuery`, `load_queries`, `check_facts`, `load_kb_texts`, `Judge`, `gemini_call`, `with_retries`.
- Produces: `percentile(values: list[float], p: float) -> float` (nearest rank), `summarize(records: list[dict]) -> dict`, `pick_spot_checks(records, n=20) -> list[dict]`, `render_markdown(summary: dict, header: dict, spot_checks: list[dict]) -> str`.
- Produces: `Limiter(min_interval_s: float, clock=time.monotonic, sleep=asyncio.sleep)` with `async wait()`, `HttpRetry(Exception)` with `.wait_s`, `async ask(http: httpx.AsyncClient, key: str, q: EvalQuery, sleep=asyncio.sleep) -> dict`, and `async run_eval(queries, http, keys: dict[str, str], judge: Judge, kb: dict[str, str], out_dir: Path, min_interval_s: float, sleep=asyncio.sleep) -> list[dict]`.
- Record dict keys: `id, group, cluster_id, difficulty, namespace, query, status_code, answer, sources, meta, client_latency_ms, fact_hits, fact_total, fact_score, judge_score, judge_reason, error`.
- CLI: `python -m weir_eval run --config LABEL --split tune|holdout|all [--min-interval 15] [--weir-url http://localhost:8000]`, `python -m weir_eval validate`, `python -m weir_eval assign-splits`.

- [ ] **Step 1: Write the failing tests**

`eval/tests/test_summary.py`:
```python
from weir_eval.summary import percentile, pick_spot_checks, render_markdown, summarize


def rec(i, latency, cost, judge, fact, group="distinct", status=200, route="large"):
    return {"id": f"q{i}", "group": group, "difficulty": "easy", "status_code": status,
            "client_latency_ms": latency, "meta": {"cost_usd": cost, "cache_status": "bypass", "route": route},
            "judge_score": judge, "fact_score": fact, "query": "q", "answer": "a"}


def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([7], 99) == 7


def test_summarize_numbers():
    records = [rec(1, 100, 0.001, 5, 1.0), rec(2, 300, 0.003, 3, 0.5, group="trap"),
               {"id": "q3", "group": "distinct", "difficulty": "easy", "status_code": 503, "error": "x"}]
    s = summarize(records)
    assert (s["n"], s["ok"], s["errors"]) == (3, 2, 1)
    assert abs(s["cost_per_1k_usd"] - 2.0) < 1e-9  # (0.004 / 2) * 1000
    assert s["judge_mean"] == 4.0 and s["fact_mean"] == 0.75
    assert s["by_group"]["trap"]["n"] == 1
    assert s["route_mix"] == {"large": 1.0}


def test_spot_checks_prefer_disagreement():
    agree = rec(1, 1, 0, 5, 1.0)
    disagree = rec(2, 1, 0, 5, 0.0)  # judge says perfect, facts say nothing
    assert pick_spot_checks([agree, disagree], n=1)[0]["id"] == "q2"


def test_render_markdown_contains_key_numbers():
    s = summarize([rec(1, 100, 0.001, 5, 1.0)])
    md = render_markdown(s, {"config": "baseline", "split": "all"}, [])
    assert "baseline" in md and "Cost per 1,000 requests" in md and "p95" in md
```

`eval/tests/test_runner.py`:
```python
import json

import httpx
import pytest

from weir_eval.judge import Judge
from weir_eval.runner import Limiter, ask, run_eval

from .conftest import q


async def no_sleep(s):
    pass


def weir_ok(request):
    return httpx.Response(200, json={"answer": "Open at 4 pm.", "sources": [{"id": "pub-a", "title": "A"}],
                                     "meta": {"request_id": "r", "cache_status": "bypass", "similarity": None,
                                              "route": "large", "escalated": False, "model": "m",
                                              "latency_ms": 10, "cost_usd": 0.0004}})


class ScoreCall:
    async def __call__(self, prompt):
        return json.dumps({"score": 5, "reason": "ok"})


async def test_ask_retries_on_503():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "rate_limited", "request_id": "r"}, headers={"Retry-After": "3"})
        return weir_ok(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://w") as http:
        record = await ask(http, "key", q("d1", "d1"), sleep=no_sleep)
    assert record["status_code"] == 200 and len(calls) == 2


async def test_ask_records_non_retryable_error():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})), base_url="http://w") as http:
        record = await ask(http, "key", q("d1", "d1"), sleep=no_sleep)
    assert record["status_code"] == 403 and record["error"]


async def test_run_eval_writes_scored_jsonl(tmp_path):
    seen_keys = []

    def handler(request):
        seen_keys.append(request.headers["X-API-Key"])
        return weir_ok(request)

    judge = Judge(ScoreCall(), tmp_path / "cache", "m", sleep=no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://w") as http:
        records = await run_eval([q("d1", "d1"), q("d2", "d2")], http, {"weir-general/en/public": "pub-key"},
                                 judge, {"pub-a": "Open at 4 pm."}, tmp_path, min_interval_s=0, sleep=no_sleep)
    assert [r["fact_score"] for r in records] == [1.0, 1.0]
    assert [r["judge_score"] for r in records] == [5, 5]
    assert seen_keys == ["pub-key", "pub-key"]
    lines = (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["id"] == "d1"


async def test_limiter_spaces_calls():
    now = [0.0]
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        now[0] += s

    limiter = Limiter(10.0, clock=lambda: now[0], sleep=fake_sleep)
    await limiter.wait()
    now[0] += 4.0
    await limiter.wait()
    assert slept == [pytest.approx(6.0)]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_summary.py tests/test_runner.py -v`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement the summary**

`eval/src/weir_eval/summary.py`:
```python
import math
from collections import Counter, defaultdict
from statistics import mean


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _group_stats(records: list[dict]) -> dict:
    return {"n": len(records),
            "judge_mean": round(mean(r["judge_score"] for r in records), 3),
            "fact_mean": round(mean(r["fact_score"] for r in records), 3)}


def summarize(records: list[dict]) -> dict:
    ok = [r for r in records if r.get("status_code") == 200]
    summary: dict = {"n": len(records), "ok": len(ok), "errors": len(records) - len(ok)}
    if not ok:
        return summary
    latencies = [r["client_latency_ms"] for r in ok]
    total_cost = sum(r["meta"]["cost_usd"] for r in ok)
    by_group: dict[str, list[dict]] = defaultdict(list)
    by_difficulty: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        by_group[r["group"]].append(r)
        by_difficulty[r["difficulty"]].append(r)
    routes = Counter(r["meta"]["route"] for r in ok)
    hits = sum(1 for r in ok if r["meta"]["cache_status"] == "hit")
    summary.update({
        "cost_usd_total": total_cost,
        "cost_per_1k_usd": total_cost / len(ok) * 1000,
        "latency_ms": {f"p{p}": percentile(latencies, p) for p in (50, 95, 99)},
        "judge_mean": round(mean(r["judge_score"] for r in ok), 3),
        "fact_mean": round(mean(r["fact_score"] for r in ok), 3),
        "cache_hit_rate": hits / len(ok),
        "route_mix": {k: v / len(ok) for k, v in routes.items()},
        "by_group": {g: _group_stats(rs) for g, rs in sorted(by_group.items())},
        "by_difficulty": {d: _group_stats(rs) for d, rs in sorted(by_difficulty.items())},
    })
    return summary


def pick_spot_checks(records: list[dict], n: int = 20) -> list[dict]:
    """Human review sample, weighted toward judge vs key-fact disagreement (spec §11.2)."""
    ok = [r for r in records if r.get("status_code") == 200]
    return sorted(ok, key=lambda r: abs((r["judge_score"] - 1) / 4 - r["fact_score"]), reverse=True)[:n]


def render_markdown(summary: dict, header: dict, spot_checks: list[dict]) -> str:
    lines = ["# Eval run", ""]
    lines += [f"- **{k}:** {v}" for k, v in header.items()]
    lines += ["", f"Requests: {summary['n']} (ok {summary['ok']}, errors {summary['errors']})", ""]
    if summary.get("ok"):
        lat = summary["latency_ms"]
        lines += [
            "| Metric | Value |", "| --- | --- |",
            f"| Cost per 1,000 requests (USD, list prices) | {summary['cost_per_1k_usd']:.4f} |",
            f"| Latency p50 / p95 / p99 (ms, sequential, client-side) | {lat['p50']} / {lat['p95']} / {lat['p99']} |",
            f"| Judge score mean (1-5) | {summary['judge_mean']} |",
            f"| Key-fact score mean (0-1) | {summary['fact_mean']} |",
            f"| Cache hit rate | {summary['cache_hit_rate']:.1%} |",
            f"| Route mix | {', '.join(f'{k} {v:.0%}' for k, v in summary['route_mix'].items())} |",
            "", "## By group", "", "| Group | n | Judge | Facts |", "| --- | --- | --- | --- |",
        ]
        lines += [f"| {g} | {s['n']} | {s['judge_mean']} | {s['fact_mean']} |" for g, s in summary["by_group"].items()]
        lines += ["", "## By difficulty", "", "| Difficulty | n | Judge | Facts |", "| --- | --- | --- | --- |"]
        lines += [f"| {d} | {s['n']} | {s['judge_mean']} | {s['fact_mean']} |" for d, s in summary["by_difficulty"].items()]
    if spot_checks:
        lines += ["", "## Human spot check (judge vs key-fact disagreement first)", "",
                  "| id | judge | facts | your verdict |", "| --- | --- | --- | --- |"]
        lines += [f"| {r['id']} | {r['judge_score']} | {r['fact_score']:.2f} |  |" for r in spot_checks]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Implement the runner**

`eval/src/weir_eval/runner.py`:
```python
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from .dataset import EvalQuery
from .judge import Judge
from .keyfacts import check_facts
from .retry import with_retries

RETRYABLE = {429, 502, 503, 504}


class Limiter:
    """Keeps at least min_interval_s between calls (free-tier TPM budget)."""

    def __init__(self, min_interval_s: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._interval = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    async def wait(self) -> None:
        if self._last is not None:
            remaining = self._interval - (self._clock() - self._last)
            if remaining > 0:
                await self._sleep(remaining)
        self._last = self._clock()


class HttpRetry(Exception):
    def __init__(self, wait_s: float):
        super().__init__(f"retry in {wait_s}s")
        self.wait_s = wait_s


async def ask(http: httpx.AsyncClient, key: str, q: EvalQuery,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> dict:
    record = {"id": q.id, "group": q.group, "cluster_id": q.cluster_id, "difficulty": q.difficulty,
              "namespace": q.namespace, "query": q.query}

    async def once() -> tuple[httpx.Response, int]:
        started = time.perf_counter()
        response = await http.post("/v1/query", headers={"X-API-Key": key},
                                   json={"query": q.query, "namespace": q.namespace})
        elapsed = int((time.perf_counter() - started) * 1000)
        if response.status_code in RETRYABLE:
            raise HttpRetry(float(response.headers.get("Retry-After", "30")) + 1)
        return response, elapsed

    try:
        response, elapsed = await with_retries(
            once, lambda e: e.wait_s if isinstance(e, HttpRetry) else None, sleep=sleep)
    except HttpRetry as e:
        return {**record, "status_code": 503, "error": f"gave up after retries: {e}"}
    record.update(status_code=response.status_code, client_latency_ms=elapsed)
    if response.status_code != 200:
        return {**record, "error": response.text[:300]}
    body = response.json()
    record.update(answer=body["answer"], sources=body["sources"], meta=body["meta"], error=None)
    return record


async def run_eval(queries: list[EvalQuery], http: httpx.AsyncClient, keys: dict[str, str], judge: Judge,
                   kb: dict[str, str], out_dir: Path, min_interval_s: float,
                   sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    limiter = Limiter(min_interval_s, sleep=sleep)
    records: list[dict] = []
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as out:
        for i, q in enumerate(queries, start=1):
            await limiter.wait()
            record = await ask(http, keys[q.namespace], q, sleep=sleep)
            if record["status_code"] == 200:
                facts = check_facts(record["answer"], q.required_facts)
                source = "\n\n".join(kb.get(d, "") for d in q.source_docs)
                verdict = await judge.grade(q.query, q.required_facts, source, record["answer"])
                record.update(fact_hits=facts.hits, fact_total=facts.total, fact_score=facts.score,
                              judge_score=verdict.score, judge_reason=verdict.reason)
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()  # keep progress if the run is interrupted
            records.append(record)
            print(f"[{i}/{len(queries)}] {q.id} {record['status_code']} "
                  f"judge={record.get('judge_score')} facts={record.get('fact_score')}")
    return records
```

- [ ] **Step 5: Implement the CLI**

`eval/src/weir_eval/cli.py`:
```python
import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .dataset import assign_splits, load_queries, save_queries, validate
from .judge import RUBRIC_VERSION, Judge, gemini_call
from .kb import facts_missing_from_sources, load_kb_texts
from .runner import run_eval
from .summary import pick_spot_checks, render_markdown, summarize

EVAL_DIR = Path(__file__).resolve().parents[2]
QUERIES = EVAL_DIR / "datasets" / "queries.jsonl"
KB_DIR = EVAL_DIR.parent / "kb"
KEY_ENV = {"weir-general/en/public": "WEIR_KEY_PUBLIC", "weir-general/en/staff": "WEIR_KEY_STAFF"}


def cmd_validate(_: argparse.Namespace) -> int:
    queries = load_queries(QUERIES)
    problems = validate(queries) + facts_missing_from_sources(queries, load_kb_texts(KB_DIR))
    print("\n".join(problems) or f"ok: {len(queries)} queries")
    return 1 if problems else 0


def cmd_assign_splits(_: argparse.Namespace) -> int:
    save_queries(QUERIES, assign_splits(load_queries(QUERIES)))
    return cmd_validate(_)


async def _run(args: argparse.Namespace) -> int:
    queries = [q for q in load_queries(QUERIES) if args.split == "all" or q.split == args.split]
    keys = {ns: os.environ[env] for ns, env in KEY_ENV.items()}
    judge_model = os.environ.get("JUDGE_MODEL", "gemini-2.5-flash")
    judge = Judge(gemini_call(os.environ["GEMINI_API_KEY"], judge_model), EVAL_DIR / ".judge_cache", judge_model)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = EVAL_DIR / "reports" / f"{stamp}-{args.config}-{args.split}"
    async with httpx.AsyncClient(base_url=args.weir_url, timeout=90) as http:
        health = (await http.get("/healthz")).json()
        if health.get("config_label") != args.config:
            print(f"Weir is running config {health.get('config_label')!r}, expected {args.config!r}. "
                  f"Restart it with WEIR_ABLATION={args.config}.", file=sys.stderr)
            return 2
        records = await run_eval(queries, http, keys, judge, load_kb_texts(KB_DIR), out_dir, args.min_interval)
    summary = summarize(records)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    header = {"config": args.config, "split": args.split, "queries": len(queries), "judge_model": judge_model,
              "rubric": RUBRIC_VERSION, "git_commit": commit, "started_utc": stamp}
    (out_dir / "summary.json").write_text(json.dumps({"header": header, "summary": summary}, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_markdown(summary, header, pick_spot_checks(records)), encoding="utf-8")
    print(f"report: {out_dir}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="weir_eval")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    sub.add_parser("assign-splits").set_defaults(func=cmd_assign_splits)
    run = sub.add_parser("run")
    run.add_argument("--config", required=True, help="expected Weir config_label, e.g. baseline")
    run.add_argument("--split", choices=["tune", "holdout", "all"], default="tune")
    run.add_argument("--min-interval", type=float, default=15.0, help="seconds between requests (free-tier TPM)")
    run.add_argument("--weir-url", default=os.environ.get("WEIR_URL", "http://localhost:8000"))
    run.set_defaults(func=lambda a: asyncio.run(_run(a)))
    args = parser.parse_args()
    sys.exit(args.func(args))
```

`eval/src/weir_eval/__main__.py`:
```python
from .cli import main

main()
```

- [ ] **Step 6: Run the eval test suite**

Run: `uv run pytest -v`
Expected: all pass (25 tests).

- [ ] **Step 7: Commit**

```bash
git add eval
git commit -m "feat(eval): throttled runner with retries, summary report, CLI"
```

---

### Task 16: Baseline run, CI, docs (Phase 1 exit)

**Files:**
- Create: `.github/workflows/tests.yml`, `docs/results/baseline.md`, `eval/reports/<run>/` (committed)
- Modify: `docs/progress.md`, `docs/README.md` (link the results)

**Interfaces:**
- Consumes: everything above.
- Produces: the frozen baseline numbers that Phase 2+ compare against.

- [ ] **Step 1: CI workflow**

`.github/workflows/tests.yml`:
```yaml
name: tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        project: [services/weir, services/hospital-rag, eval]
    services:
      postgres:
        image: pgvector/pgvector:0.8.0-pg16
        env:
          POSTGRES_USER: weir
          POSTGRES_PASSWORD: weir
          POSTGRES_DB: weir_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U weir -d weir_test"
          --health-interval 5s --health-timeout 5s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - name: Install
        working-directory: ${{ matrix.project }}
        run: uv sync --frozen
      - name: Test
        working-directory: ${{ matrix.project }}
        env:
          TEST_DATABASE_URL: postgresql://weir:weir@localhost:5432/weir_test
        run: uv run pytest -q
```

- [ ] **Step 2: Run the baseline (about 13 minutes, about 75K Groq tokens and 50 Gemini calls)**

```bash
WEIR_ABLATION=baseline docker compose up -d weir
curl -s localhost:8000/healthz          # must show "config_label":"baseline"
cd eval
uv run --env-file ../.env python -m weir_eval validate
uv run --env-file ../.env python -m weir_eval run --config baseline --split all --min-interval 15
```
Expected: 50 progress lines, then `report: .../eval/reports/<stamp>-baseline-all`. Errors should be 0. If the run shows errors after retries, check the Groq console's usage page, wait for the daily budget to reset if needed, and re-run. The judge cache means already-graded answers aren't re-sent to Gemini.

- [ ] **Step 3: Cross-check the cost against the request log**

```bash
docker compose exec postgres psql -U weir -c "select count(*), sum(cost_usd)*1000/count(*) as cost_per_1k, percentile_cont(0.95) within group (order by latency_total_ms) as p95_server_ms from weir.request_log where config_label = 'baseline' and status = 'ok'"
```
Expected: `count` is 50 (more if you re-ran), and `cost_per_1k` matches `summary.md` to 4 decimal places.

- [ ] **Step 4: Human spot check (user)**

The user fills the "your verdict" column of the spot-check table in the run's `summary.md` (agree/disagree with the judge), and notes any systematic judge bias.

- [ ] **Step 5: Write `docs/results/baseline.md`**

Content: copy the run's `summary.md` tables, plus a **Frozen baseline settings** section:
- large model `openai/gpt-oss-120b`, `reasoning_effort=low`, `temperature=0`, `max_completion_tokens=700`
- prompt `p1`, retrieve `k=4`, chunk budget 250
- `kb_version` for each namespace (from `curl localhost:8001/info`)
- judge model and rubric `r1`, and the eval set (50 queries, the git commit)
- machine specs (CPU, RAM, Windows version, Docker Desktop version)

Also add: the spot-check outcome, and a **Caveats** section:
- latency is sequential and throttled (not a load test; Phase 5 measures p95 under load)
- 50 queries is small, so differences of about 0.2 judge points are noise
- the KB is synthetic
- costs are at list prices, and the real spend was $0

- [ ] **Step 6: Update the docs index and progress log**

In `docs/README.md`, add a row: `| [results/baseline.md](results/baseline.md) | Frozen Phase 1 baseline: cost, latency, quality |`.

Append to `docs/progress.md`:
```markdown
## <date>: Phase 1 exit ✅: baseline frozen

- Eval set: 50 queries (25 distinct, 3×5 paraphrase, 5×2 traps), 70/30 split by cluster; user spot-checked 10.
- Baseline (always gpt-oss-120b, no cache): cost/1k $<X>, p95 <Y> ms (sequential), judge <Z>/5, facts <W>.
- Numbers and frozen settings: docs/results/baseline.md. Raw: eval/reports/<run>/.
- **Gate:** Phase 2 (semantic cache) may start. Next: write the Phase 2 plan.
```

- [ ] **Step 7: Commit, push, verify CI**

```bash
git add .github/workflows/tests.yml docs eval/reports
git commit -m "chore: CI, baseline eval run and frozen baseline results (Phase 1 exit)"
git push -u origin phase-0-1
gh run watch --exit-status
```
Expected: all three matrix jobs pass. Then follow superpowers:finishing-a-development-branch to merge `phase-0-1` into `main`.
