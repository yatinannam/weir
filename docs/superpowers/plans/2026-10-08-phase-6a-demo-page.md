# Phase 6A: One-command Demo and Demo Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `uv run demo.py` takes a fresh clone to a running stack and opens a demo page at `http://127.0.0.1:8000/demo` that shows, for every question, how Weir handled it (cache, small or large model), what it cost and what it saved, with a guided five-step interview story.

**Architecture:** Weir gains two additive response fields (`counterfactual_cost_usd`, `guard_refused`) and serves two static files (`/demo`, `/demo/questions.json`). The page is one self-contained HTML file that calls the normal `POST /v1/query` with the public key, which it reads from the URL fragment. A standard-library launcher at the repo root prepares `.env`, starts Compose with the model mode pinned, loads the knowledge base once, empties the demo cache and opens the browser.

**Tech Stack:** Python 3.12, FastAPI (`FileResponse`), plain HTML/CSS/JavaScript (no build step, no external resources), Python standard library (`argparse`, `urllib`, `subprocess`, `webbrowser`), pytest, Playwright (live smoke only, via `uv run --with playwright`), Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-08-phase-6a-demo-page-design.md`

## Global Constraints

- Free tools only; nothing paid.
- The page loads nothing external: no CDN, fonts or analytics. A Content-Security-Policy header enforces `default-src 'self'`.
- Keys are never printed, never committed and never placed in a URL path or query string; only in the URL fragment, which the page moves to `sessionStorage` and removes from the address bar. `.env` stays gitignored.
- Every Compose command the launcher runs passes `LLM_MODE` explicitly (D55), so `.env`'s `LLM_MODE=groq` can never override the chosen mode.
- Weir listens on 127.0.0.1 only; no change to auth or tenants. Weir API changes are additive only (two `meta` fields, two GET routes).
- Python 3.12. The launcher uses the standard library only and runs with `uv run demo.py` or `python demo.py`; its printed text is ASCII.
- No emojis in the README or docs. The page shows status in words ("As expected."), not emoji or check-mark glyphs.
- Windows first: the launcher calls `docker` directly (no shell), so it works from PowerShell, cmd and Git Bash alike.

## Review Focus

1. **Docker Desktop not running, not installed, or failing mid-start** (it closes by itself on this machine): the launcher says so in plain words and exits 1, never a traceback. Pinned in Task 4 (`test_docker_not_running_says_so_and_stops`, `test_compose_failure_shows_its_error_and_stops`).
2. **Re-running with an existing `.env`** that holds a real Groq key or custom keys: nothing is overwritten and no value is printed. Pinned in Task 4 (`test_prepare_env_never_overwrites_and_adds_missing_names`, `test_main_starts_pins_the_mode_purges_and_opens_without_printing_keys`).
3. **A missing, wrong or stale key at the page** (opened `/demo` directly, keys regenerated): the page asks for the key or shows "The key was rejected", never a blank page. Pinned in Task 6 (smoke: no-key prompt, wrong-key card).
4. **The Groq free-tier limit reached in real mode** (503 `rate_limited`): a plain card, and the guided step reports it instead of a tick. Pinned in Task 3 (`test_page_shows_every_badge_mode_and_error_message`) and Task 6 (smoke with an intercepted 503).
5. **The demo cache already holds the guided answers** (`--keep-cache`, or a step clicked twice): the step says "already cached" instead of a false tick. Pinned in Task 4 (`test_a_cached_question_never_passes_as_a_miss`) and Task 6 (smoke clicks step 1 again).

---

## File Structure

| File | Create/Modify | Responsibility |
| --- | --- | --- |
| `services/weir/src/weir/pipeline.py` | Modify | `QueryMeta.counterfactual_cost_usd`, `QueryMeta.guard_refused` |
| `services/weir/src/weir/main.py` | Modify | `GET /demo`, `GET /demo/questions.json` |
| `services/weir/src/weir/demo/index.html` | Create | The demo page |
| `services/weir/src/weir/demo/questions.json` | Create | The five guided steps |
| `services/weir/tests/test_pipeline.py` | Modify | Task 1 tests |
| `services/weir/tests/test_api.py` | Modify | Task 1 API test |
| `services/weir/tests/test_demo_page.py` | Create | Tasks 2 and 3 tests |
| `demo.py` | Create | The launcher |
| `tests/conftest.py`, `tests/test_demo.py` | Create | Launcher tests (repo root) |
| `.github/workflows/tests.yml` | Modify | Run the launcher tests |
| `scripts/demo_smoke.py` | Create | Live Playwright smoke and the README screenshot |
| `docs/images/demo.png` | Create | Screenshot |
| `README.md`, `docs/*.md` | Modify | Quick start, decisions, progress, backlog, index |

---

### Task 1: Two additions to Weir's response

**Files:**
- Modify: `services/weir/src/weir/pipeline.py` (`QueryMeta`, `Pipeline.handle`, `Pipeline._serve_hit`)
- Test: `services/weir/tests/test_pipeline.py`, `services/weir/tests/test_api.py`

**Interfaces:**
- Produces: `QueryMeta.counterfactual_cost_usd: float` (default 0.0) and `QueryMeta.guard_refused: bool` (default False), in every `POST /v1/query` response's `meta`.

- [ ] **Step 1: Write the failing tests.** Append to `services/weir/tests/test_pipeline.py`:

```python
# --- Phase 6A: response additions for the demo page -----------------------------------------------

async def test_meta_carries_the_counterfactual_cost_on_miss_and_hit():
    h = harness(fake_rag())
    miss = await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    hit = await h.p.handle(ask("When can I visit?"))
    assert miss.meta.counterfactual_cost_usd == pytest.approx(0.00045) == miss.meta.cost_usd   # router off: large
    assert hit.meta.cost_usd == 0 and hit.meta.counterfactual_cost_usd == pytest.approx(0.00045)


async def test_guard_refused_only_for_a_look_alike_at_or_above_the_threshold():
    h = harness(fake_rag(), aliases={"what are the icu visiting hours?": "what are the general ward visiting hours?"})
    first = await h.p.handle(ask("What are the general ward visiting hours?"))           # empty cache
    await h.writer.drain()
    refused = await h.p.handle(ask("What are the ICU visiting hours?"))                    # same vector, other ward
    await h.writer.drain()
    unrelated = await h.p.handle(ask("How much is parking?"))                              # below the threshold
    hit = await h.p.handle(ask("What are the general ward visiting hours?"))
    skipped = await h.p.handle(ask("What are the ICU visiting hours?", options=QueryOptions(bypass_cache=True)))
    assert refused.meta.cache_status == "miss" and refused.meta.guard_refused is True
    assert refused.meta.similarity == pytest.approx(1.0)
    for resp in (first, unrelated, hit, skipped):
        assert resp.meta.guard_refused is False
```

Append to `services/weir/tests/test_api.py`:

```python
async def test_query_meta_includes_the_demo_fields():  # Phase 6A: the demo page reads both
    client, _ = app_client()
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "When can I visit?", "namespace": PUBLIC})
    meta = r.json()["meta"]
    assert meta["guard_refused"] is False and meta["counterfactual_cost_usd"] > 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_pipeline.py tests/test_api.py -k "counterfactual or guard_refused or demo_fields"`

Expected: FAIL (`AttributeError: 'QueryMeta' object has no attribute 'counterfactual_cost_usd'`, `KeyError: 'guard_refused'`).

- [ ] **Step 3: Implement.** In `services/weir/src/weir/pipeline.py`, extend `QueryMeta`:

```python
class QueryMeta(BaseModel):
    request_id: str
    cache_status: Literal["hit", "miss", "bypass"]
    similarity: float | None
    route: Literal["none", "small", "large"]
    escalated: bool
    model: str | None
    latency_ms: int
    cost_usd: float
    counterfactual_cost_usd: float = 0.0   # the large model with no cache: the demo page's savings panel (Phase 6A)
    guard_refused: bool = False            # a look-alike at or above the threshold was refused by the entity guard
```

In `Pipeline.handle`, replace `vector = None` (just before the `if reason is None:` lookup block) with:

```python
        vector = None
        guard_refused = False
```

and, inside the lookup's `else:` branch, after `row.cache_status = "miss"`, add:

```python
                row.cache_status = "miss"
                # a miss whose best candidate reached the threshold can only be the entity guard refusing it
                guard_refused = row.similarity is not None and row.similarity >= self._cfg.cache.threshold
```

Change the miss path's `QueryMeta(...)` (at the end of `handle`) to:

```python
            meta=QueryMeta(request_id=str(row.request_id), cache_status=row.cache_status,
                           similarity=row.similarity, route=row.route, escalated=row.escalated, model=row.model,
                           latency_ms=row.latency_total_ms, cost_usd=float(row.cost_usd),
                           counterfactual_cost_usd=float(row.counterfactual_cost_usd), guard_refused=guard_refused),
```

and the hit path's `QueryMeta(...)` in `_serve_hit` to:

```python
            meta=QueryMeta(request_id=str(row.request_id), cache_status="hit", similarity=hit.similarity,
                           route="none", escalated=False, model=hit.model, latency_ms=row.latency_total_ms,
                           cost_usd=float(row.cost_usd), counterfactual_cost_usd=float(row.counterfactual_cost_usd)),
```

- [ ] **Step 4: Run the tests**

Run: `cd services/weir && uv run pytest -q`

Expected: all pass (3 new).

- [ ] **Step 5: Commit, push and merge**

```bash
git add services/weir/src/weir/pipeline.py services/weir/tests/test_pipeline.py services/weir/tests/test_api.py
git commit -m "feat(weir): response meta adds counterfactual_cost_usd and guard_refused (Phase 6A)"
git push origin phase-6 && git push origin phase-6:main
```

---

### Task 2: Serve the demo files

**Files:**
- Modify: `services/weir/src/weir/main.py`
- Create: `services/weir/src/weir/demo/questions.json`, `services/weir/src/weir/demo/index.html` (a shell; Task 3 replaces it)
- Test: `services/weir/tests/test_demo_page.py`

**Interfaces:**
- Produces:
  - `GET /demo` returns `index.html` (`text/html`) with headers `Content-Security-Policy: default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'` and `Cache-Control: no-store`.
  - `GET /demo/questions.json` returns `{"namespace": str, "steps": [{"n": int, "title": str, "expect": "miss"|"hit"|"guard_refused"|"small"|"large", "question": str, "hint": str}]}`.
  - Both need no key and stay out of `/openapi.json`.

The guided story (chosen during planning with Weir's own embedder and entity lexicon; Task 5 re-checks it live):

| Step | Question | Why |
| --- | --- | --- |
| 1 | What does car parking cost for the first 2 hours on a weekday? | eval q-113; a miss, then cached |
| 2 | Weekday car parking cost for the first 2 hours? | written for the demo (no eval paraphrase of q-113 exists): similarity 0.984, same entities (`days:weekday`, `vehicles:car`, `2 hour`), so a hit |
| 3 | What does car parking cost for the first 2 hours on a weekend? | eval q-114: similarity 0.964 to step 1, different day, so the guard refuses (the KB price is ₹60, not the cached ₹40) |
| 4 | What is the first consultation fee at the Orthopedics OPD? | eval q-119: routed small in the final Phase 3 run, judge 5/5 |
| 5 | What colour attendant pass does a parent staying with a child in the pediatric ward get, and what are the evening visiting hours there? | eval q-146: routed large, judge 5/5 |

The spec's ICU example could not be used: its look-alike scores 0.896, below the 0.90 threshold, so it is a plain miss rather than a guard refusal; a two-wheeler parking-pass look-alike scored 0.869–0.892 for the same reason.

- [ ] **Step 1: Write the failing tests.** Create `services/weir/tests/test_demo_page.py`:

```python
"""Phase 6A demo page: the two static routes and the page's own guarantees."""
import re
from pathlib import Path

from .test_api import app_client

DEMO = Path(__file__).resolve().parents[1] / "src" / "weir" / "demo"


async def test_demo_page_is_served_with_a_strict_policy():
    client, _ = app_client()
    async with client:
        r = await client.get("/demo")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


async def test_guided_questions_are_served_and_well_formed():
    client, _ = app_client()
    async with client:
        r = await client.get("/demo/questions.json")
    data = r.json()
    assert r.status_code == 200 and data["namespace"] == "weir-general/en/public"
    assert [s["n"] for s in data["steps"]] == [1, 2, 3, 4, 5]
    assert [s["expect"] for s in data["steps"]] == ["miss", "hit", "guard_refused", "small", "large"]
    assert all(s["question"].strip() and s["title"] and s["hint"] for s in data["steps"])


async def test_demo_routes_need_no_key_and_stay_out_of_the_api_docs():
    client, _ = app_client()
    async with client:
        schema = (await client.get("/openapi.json")).json()
    assert "/demo" not in schema["paths"] and "/demo/questions.json" not in schema["paths"]


def test_demo_files_hold_no_keys_or_external_urls():
    for f in DEMO.iterdir():
        text = f.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f.name
        assert not re.search(r"[A-Za-z0-9_-]{32}", text), f"{f.name} holds a key-like value"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_demo_page.py`

Expected: FAIL (404 for `/demo`, and `FileNotFoundError` for the demo folder).

- [ ] **Step 3: Implement.** Create `services/weir/src/weir/demo/questions.json`:

```json
{
  "namespace": "weir-general/en/public",
  "steps": [
    {"n": 1, "title": "Ask a question", "expect": "miss",
     "question": "What does car parking cost for the first 2 hours on a weekday?",
     "hint": "A miss: Weir searches the documents, asks a model and caches the answer."},
    {"n": 2, "title": "Reword it", "expect": "hit",
     "question": "Weekday car parking cost for the first 2 hours?",
     "hint": "Same meaning, same details: a cache hit at near-zero cost."},
    {"n": 3, "title": "A look-alike", "expect": "guard_refused",
     "question": "What does car parking cost for the first 2 hours on a weekend?",
     "hint": "Almost the same words, a different day: the guard refuses the cached weekday price (the weekend price is ₹60, not ₹40)."},
    {"n": 4, "title": "An easy question", "expect": "small",
     "question": "What is the first consultation fee at the Orthopedics OPD?",
     "hint": "Short and answered by one document: the small, cheaper model."},
    {"n": 5, "title": "A hard question", "expect": "large",
     "question": "What colour attendant pass does a parent staying with a child in the pediatric ward get, and what are the evening visiting hours there?",
     "hint": "Two questions in one: the large model."}
  ]
}
```

Create `services/weir/src/weir/demo/index.html` (a shell Task 3 replaces):

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Weir demo</title></head>
<body><h1>Weir demo</h1></body>
</html>
```

In `services/weir/src/weir/main.py`, add `from pathlib import Path` to the imports, change `from fastapi.responses import JSONResponse` to `from fastapi.responses import FileResponse, JSONResponse`, add below the imports:

```python
DEMO_DIR = Path(__file__).parent / "demo"
# The demo page loads nothing external; inline script and style only (Phase 6A addendum §2).
DEMO_HEADERS = {"Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                           "base-uri 'none'; frame-ancestors 'none'",
                "Cache-Control": "no-store"}
```

and add these routes inside `create_app`, after the `/metrics` route:

```python
    @app.get("/demo", include_in_schema=False)
    async def demo_page():
        return FileResponse(DEMO_DIR / "index.html", media_type="text/html", headers=DEMO_HEADERS)

    @app.get("/demo/questions.json", include_in_schema=False)
    async def demo_questions():
        return FileResponse(DEMO_DIR / "questions.json", media_type="application/json", headers=DEMO_HEADERS)
```

- [ ] **Step 4: Run the tests**

Run: `cd services/weir && uv run pytest -q`

Expected: all pass (4 new).

- [ ] **Step 5: Commit, push and merge**

```bash
git add services/weir/src/weir/main.py services/weir/src/weir/demo/ services/weir/tests/test_demo_page.py
git commit -m "feat(weir): serve the demo page and the guided questions at /demo (Phase 6A)"
git push origin phase-6 && git push origin phase-6:main
```

---

### Task 3: The demo page

**Files:**
- Modify: `services/weir/src/weir/demo/index.html` (replace the shell)
- Test: `services/weir/tests/test_demo_page.py`

**Interfaces:**
- Consumes: `POST /v1/query` with `meta.{cache_status, similarity, route, escalated, latency_ms, cost_usd, counterfactual_cost_usd, guard_refused}` (Task 1); `GET /demo/questions.json` (Task 2).
- Produces (used by the Task 6 smoke): element ids `mode`, `question`, `send`, `answers`, `steps`, `s-n`, `s-hit`, `s-cost`, `s-cf`, `s-saved`; step buttons `button.step[data-step="N"]` with a `.result` span and class `pass` or `other`; answer cards `.card` (newest first, `.card.error` for errors) holding `.badge` spans.
- The URL fragment `#key=...&mode=stub|groq` (the launcher builds it in Task 4).

- [ ] **Step 1: Write the failing tests.** Append to `services/weir/tests/test_demo_page.py`:

```python
def page_html() -> str:
    return (DEMO / "index.html").read_text(encoding="utf-8")


def test_page_reads_the_key_from_the_fragment_and_never_puts_it_in_the_url():
    html = page_html()
    assert "location.hash" in html and "history.replaceState" in html and "sessionStorage" in html
    assert "?key=" not in html


def test_page_shows_every_badge_mode_and_error_message():  # Review Focus 4
    html = page_html()
    for text in ("CACHE HIT", "SMALL MODEL", "LARGE MODEL", "SMALL → LARGE", "CACHE REFUSED", "CACHE SKIPPED",
                 "stub answers (no Groq key)", "real answers (Groq)", "The key was rejected",
                 "Groq free-tier limit", "isn't reachable", "already cached", "/v1/query", "/demo/questions.json",
                 "counterfactual_cost_usd", "guard_refused"):
        assert text in html, text


def test_page_renders_server_text_safely():
    assert "innerHTML" not in page_html()          # answers and errors go through textContent only
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/weir && uv run pytest -q tests/test_demo_page.py`

Expected: FAIL (the shell has none of these).

- [ ] **Step 3: Implement.** Replace `services/weir/src/weir/demo/index.html` with:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weir demo</title>
<style>
  :root {
    --ink: #1f2933; --muted: #52606d; --line: #e4e7eb; --bg: #f5f7fa; --card: #ffffff; --blue: #2563eb;
    --hit: #15803d; --small: #0e7490; --large: #6d28d9; --guard: #c2410c; --skip: #52606d; --err: #b91c1c;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         color: var(--ink); background: var(--bg); }
  header { display: flex; flex-wrap: wrap; gap: 8px; justify-content: space-between; align-items: center;
           padding: 12px 20px; background: var(--ink); color: #fff; }
  header h1 { margin: 0; font-size: 17px; font-weight: 600; }
  #mode { font-size: 12px; padding: 3px 10px; border-radius: 12px; background: #fde68a; color: #78350f; }
  #mode.real { background: #bbf7d0; color: #14532d; }
  main { display: grid; grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); gap: 20px;
         max-width: 1200px; margin: 20px auto; padding: 0 20px; }
  @media (max-width: 820px) { main { grid-template-columns: 1fr; } }
  form { display: flex; gap: 8px; margin-bottom: 14px; }
  input[type="text"] { flex: 1; padding: 10px 12px; border: 1px solid #cbd2d9; border-radius: 6px; font: inherit; }
  button { font: inherit; cursor: pointer; border-radius: 6px; }
  button:disabled { opacity: .6; cursor: wait; }
  #send { padding: 10px 18px; border: 0; background: var(--blue); color: #fff; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px;
          margin-bottom: 10px; }
  .card .q { font-weight: 600; margin-bottom: 4px; }
  .card .a { white-space: pre-wrap; }
  .card .src { color: var(--muted); font-size: 13px; margin-top: 4px; }
  .card.error { border-color: #fecaca; background: #fef2f2; color: var(--err); }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; font-size: 13px;
          color: var(--muted); }
  .badge { color: #fff; font-size: 11px; font-weight: 700; letter-spacing: .03em; padding: 2px 8px; border-radius: 4px; }
  .b-hit { background: var(--hit); } .b-small { background: var(--small); } .b-large { background: var(--large); }
  .b-guard { background: var(--guard); } .b-skip { background: var(--skip); }
  aside section { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px;
                  margin-bottom: 14px; }
  aside h2 { margin: 0 0 8px; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
  .step { display: block; width: 100%; text-align: left; background: var(--bg); border: 1px solid var(--line);
          padding: 8px 10px; margin-bottom: 6px; color: var(--ink); }
  .step b { display: block; }
  .step small { color: var(--muted); }
  .step .result { display: block; font-size: 12px; margin-top: 2px; }
  .step.pass { border-color: #86efac; } .step.pass .result { color: var(--hit); }
  .step.other { border-color: #fdba74; } .step.other .result { color: var(--guard); }
  dl { display: grid; grid-template-columns: auto auto; gap: 4px 12px; margin: 0; }
  dt { color: var(--muted); }
  dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
  #s-saved { font-weight: 700; color: var(--hit); }
  #empty { color: var(--muted); }
</style>
</head>
<body>
<header>
  <h1>Weir demo: Weir General Hospital FAQ</h1>
  <span id="mode">mode unknown</span>
</header>
<main>
  <section>
    <form id="ask">
      <input id="question" type="text" autocomplete="off" placeholder="Ask the hospital a question..." aria-label="Question">
      <button id="send" type="submit">Ask</button>
    </form>
    <div id="answers"><p id="empty">Pick a step on the right, or ask your own question.</p></div>
  </section>
  <aside>
    <section>
      <h2>Guided demo</h2>
      <div id="steps"></div>
    </section>
    <section>
      <h2>Savings this session</h2>
      <dl>
        <dt>Requests</dt><dd id="s-n">0</dd>
        <dt>From the cache</dt><dd id="s-hit">0%</dd>
        <dt>Cost</dt><dd id="s-cost">$0.00000</dd>
        <dt>Always-large cost</dt><dd id="s-cf">$0.00000</dd>
        <dt>Saved</dt><dd id="s-saved">0%</dd>
      </dl>
    </section>
  </aside>
</main>
<script>
"use strict";
// Weir demo page (Phase 6A addendum §3). Every question is a normal POST /v1/query with the public key.
// The key arrives in the URL fragment (never sent to a server), moves to sessionStorage and leaves the URL.
const NAMESPACE = "weir-general/en/public";
const MODE_TEXT = { stub: "stub answers (no Groq key)", groq: "real answers (Groq)" };
const PATH_TEXT = { hit: "a cache hit", guard_refused: "the cache refusing a look-alike", bypass: "the cache skipped",
                    escalated: "the small model, escalated to the large one", small: "the small model",
                    large: "the large model" };
const totals = { n: 0, hits: 0, cost: 0, counterfactual: 0 };
const $ = (id) => document.getElementById(id);

const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.get("key")) sessionStorage.setItem("weirKey", fragment.get("key"));
if (fragment.get("mode")) sessionStorage.setItem("weirMode", fragment.get("mode"));
if (location.hash) history.replaceState(null, "", location.pathname);   // keep the key out of the address bar

const mode = sessionStorage.getItem("weirMode");
$("mode").textContent = MODE_TEXT[mode] || "mode unknown";
if (mode === "groq") $("mode").classList.add("real");

function apiKey() {
  let key = sessionStorage.getItem("weirKey");
  if (!key) {
    key = (window.prompt("Paste WEIR_KEY_PUBLIC from your .env file") || "").trim();
    if (key) sessionStorage.setItem("weirKey", key);
  }
  return key;
}

function observedPath(meta) {
  if (meta.cache_status === "hit") return "hit";
  if (meta.guard_refused) return "guard_refused";
  if (meta.cache_status === "bypass") return "bypass";
  if (meta.escalated) return "escalated";
  return meta.route;
}

function stepPassed(expect, meta) {
  if (expect === "miss") return meta.cache_status === "miss" && !meta.guard_refused;
  return observedPath(meta) === expect;
}

function badges(meta) {
  if (meta.cache_status === "hit") return [["b-hit", "CACHE HIT"]];
  const out = [];
  if (meta.cache_status === "bypass") out.push(["b-skip", "CACHE SKIPPED"]);
  if (meta.guard_refused) out.push(["b-guard", "CACHE REFUSED"]);
  if (meta.escalated) out.push(["b-large", "SMALL → LARGE"]);
  else if (meta.route === "small") out.push(["b-small", "SMALL MODEL"]);
  else if (meta.route === "large") out.push(["b-large", "LARGE MODEL"]);
  return out;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function money(x) { return "$" + x.toFixed(5); }

function addCard(card) {
  const empty = $("empty");
  if (empty) empty.remove();
  $("answers").prepend(card);
}

function renderAnswer(question, body) {
  const meta = body.meta;
  const card = el("div", "card");
  card.append(el("div", "q", question), el("div", "a", body.answer));
  if (body.sources && body.sources.length) {
    card.append(el("div", "src", "Sources: " + body.sources.map((s) => s.title).join(", ")));
  }
  const line = el("div", "meta");
  for (const [cls, label] of badges(meta)) line.append(el("span", "badge " + cls, label));
  const details = [];
  if (meta.similarity !== null && meta.similarity !== undefined) {
    if (meta.cache_status === "hit") details.push("similarity " + meta.similarity.toFixed(2));
    else if (meta.guard_refused) details.push("look-alike at similarity " + meta.similarity.toFixed(2));
  }
  details.push(meta.latency_ms.toLocaleString() + " ms", money(meta.cost_usd));
  line.append(el("span", "", details.join(" · ")));
  card.append(line);
  addCard(card);
}

function renderError(question, message) {
  const card = el("div", "card error");
  card.append(el("div", "q", question), el("div", "", message));
  addCard(card);
}

function errorText(status, body) {
  if (status === 0) return "Weir isn't reachable. Is the stack running? Start it with: uv run demo.py";
  if (status === 401) return "The key was rejected. Check WEIR_KEY_PUBLIC in .env, then reload the page.";
  if (status === 503 && body && body.error === "rate_limited") {
    return "The Groq free-tier limit was reached. Try again in a minute.";
  }
  return "Weir returned an error (" + status + (body && body.error ? ": " + body.error : "") + ").";
}

function tally(meta) {
  totals.n += 1;
  if (meta.cache_status === "hit") totals.hits += 1;
  totals.cost += meta.cost_usd;
  totals.counterfactual += meta.counterfactual_cost_usd;
  $("s-n").textContent = String(totals.n);
  $("s-hit").textContent = Math.round(100 * totals.hits / totals.n) + "%";
  $("s-cost").textContent = money(totals.cost);
  $("s-cf").textContent = money(totals.counterfactual);
  const saved = totals.counterfactual > 0 ? 100 * (1 - totals.cost / totals.counterfactual) : 0;
  $("s-saved").textContent = Math.round(saved) + "%";
}

function markStep(button, step, meta) {
  const result = button.querySelector(".result");
  button.classList.remove("pass", "other");
  if (stepPassed(step.expect, meta)) {
    button.classList.add("pass");
    result.textContent = "As expected.";
  } else {
    const path = observedPath(meta);
    button.classList.add("other");
    result.textContent = "Got " + (PATH_TEXT[path] || path) + " instead"
      + (path === "hit" ? ": it was already cached (run demo.py again for a fresh cache)." : ".");
  }
}

function setBusy(busy) {
  for (const b of document.querySelectorAll("button")) b.disabled = busy;
}

async function ask(question, button, step) {
  question = question.trim();
  if (!question) return;
  const key = apiKey();
  setBusy(true);
  let status = 0;
  let body = null;
  try {
    const response = await fetch("/v1/query", {
      method: "POST",
      headers: { "content-type": "application/json", "X-API-Key": key },
      body: JSON.stringify({ query: question, namespace: NAMESPACE }),
    });
    status = response.status;
    body = await response.json().catch(() => null);
  } catch (err) {
    status = 0;
  }
  if (status === 200 && body && body.meta) {
    renderAnswer(question, body);
    tally(body.meta);
    if (step) markStep(button, step, body.meta);
  } else {
    if (status === 401) sessionStorage.removeItem("weirKey");
    const message = errorText(status, body);
    renderError(question, message);
    if (step) {
      button.classList.remove("pass");
      button.classList.add("other");
      button.querySelector(".result").textContent = "Not answered: " + message;
    }
  }
  setBusy(false);
}

$("ask").addEventListener("submit", (event) => {
  event.preventDefault();
  ask($("question").value);
});

fetch("/demo/questions.json")
  .then((response) => response.json())
  .then((data) => {
    for (const step of data.steps) {
      const button = el("button", "step");
      button.type = "button";
      button.dataset.step = String(step.n);
      button.append(el("b", "", step.n + ". " + step.title), el("small", "", step.hint), el("span", "result"));
      button.addEventListener("click", () => {
        $("question").value = step.question;
        ask(step.question, button, step);
      });
      $("steps").append(button);
    }
  })
  .catch(() => $("steps").append(el("p", "", "The guided steps could not be loaded.")));
</script>
</body>
</html>
```

- [ ] **Step 4: Run the tests**

Run: `cd services/weir && uv run pytest -q`

Expected: all pass (3 new; the Task 2 file checks still pass on the full page).

- [ ] **Step 5: Commit, push and merge**

```bash
git add services/weir/src/weir/demo/index.html services/weir/tests/test_demo_page.py
git commit -m "feat(weir): the demo page: answer cards with path badges, guided steps, savings panel (Phase 6A)"
git push origin phase-6 && git push origin phase-6:main
```

---

### Task 4: The launcher (`uv run demo.py`)

**Files:**
- Create: `demo.py`, `tests/conftest.py`, `tests/test_demo.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: `services/weir/src/weir/demo/questions.json` (Task 2); Weir `GET /healthz`, `DELETE /v1/cache`, `POST /v1/query` (with Task 1's meta); hospital-rag `GET /info`.
- Produces (the Task 6 smoke imports `demo`):
  - `WEIR = "http://127.0.0.1:8000"`, `FILL: tuple[str, ...]`, `QUESTIONS: Path`, `KB_VERSION_WAIT_S = 35`
  - `read_env(path: Path) -> dict[str, str]`
  - `prepare_env(env_path: Path, example_path: Path, token: Callable[[], str] = ...) -> list[str]` (names filled, never values)
  - `choose_mode(env: dict[str, str], force_stub: bool) -> str` (`"stub"` or `"groq"`)
  - `compose_command(*args: str, monitoring: bool = False) -> list[str]`
  - `compose_env(base: dict[str, str], mode: str) -> dict[str, str]`
  - `demo_url(key: str, mode: str) -> str`
  - `observed_path(meta: dict) -> str`, `step_passed(expect: str, meta: dict) -> bool`
  - `main(argv=None, *, run, http, opener, sleep, root, out, environ) -> int`
  - Flags: `--stub`, `--keep-cache`, `--dashboard`, `--check`, `--no-browser`, `--stop`.

- [ ] **Step 1: Write the failing tests.** Create `tests/conftest.py`:

```python
"""Repo-root tests (the demo launcher). The repo root has no package, so put it on the import path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

Create `tests/test_demo.py`:

```python
"""The one-command demo launcher (Phase 6A addendum §4). No Docker, no network: every side effect is faked."""
from types import SimpleNamespace

import pytest

import demo

EXAMPLE = (demo.ROOT / ".env.example").read_text(encoding="utf-8")
GOOD = [{"cache_status": "miss", "route": "large"},
        {"cache_status": "hit", "route": "none", "similarity": 0.984},
        {"cache_status": "miss", "guard_refused": True, "route": "large", "similarity": 0.964},
        {"cache_status": "miss", "route": "small"},
        {"cache_status": "miss", "route": "large"}]


class FakeRun:
    def __init__(self, fail=None):                     # fail: {word in the command: (returncode, stderr)}
        self.calls, self.fail = [], fail or {}

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        for word, (code, err) in self.fail.items():
            if word in cmd:
                return SimpleNamespace(returncode=code, stdout="", stderr=err)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class FakeHttp:
    def __init__(self, namespaces=("weir-general/en/public",), metas=None):
        self.calls, self.namespaces, self.metas = [], namespaces, list(metas or [])

    def __call__(self, method, url, headers=None, body=None, timeout=10):
        self.calls.append((method, url, headers or {}, body))
        if url.endswith("/healthz"):
            return 200, {"status": "ok"}
        if url.endswith("/info"):
            return 200, {"namespaces": {n: {} for n in self.namespaces}}
        if method == "DELETE":
            return 200, {"deleted": 3}
        if url.endswith("/v1/query"):
            return 200, {"answer": "x", "sources": [], "meta": self.metas.pop(0)}
        raise AssertionError(url)


def project(tmp_path, env_text=None):
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    if env_text is not None:
        (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    return tmp_path


def run_main(root, argv, run=None, http=None, opener_result=True):
    lines, opened = [], []
    code = demo.main(argv, run=run or FakeRun(), http=http or FakeHttp(),
                     opener=lambda url: opened.append(url) or opener_result, sleep=lambda s: None,
                     root=root, out=lines.append, environ={"PATH": "x"})
    return code, lines, opened


def test_prepare_env_creates_from_the_example_and_fills_blank_keys(tmp_path):
    root = project(tmp_path)
    filled = demo.prepare_env(root / ".env", root / ".env.example", token=iter(["t1", "t2", "t3", "t4"]).__next__)
    env = demo.read_env(root / ".env")
    assert filled == list(demo.FILL)
    assert [env[k] for k in demo.FILL] == ["t1", "t2", "t3", "t4"] and env["GROQ_API_KEY"] == ""
    assert (root / ".env").read_text(encoding="utf-8").count("#") == EXAMPLE.count("#")   # comments kept


def test_prepare_env_never_overwrites_and_adds_missing_names(tmp_path):  # Review Focus 2
    root = project(tmp_path, "GROQ_API_KEY=gsk_real\nWEIR_KEY_PUBLIC=mine\nWEIR_KEY_STAFF=\n")
    filled = demo.prepare_env(root / ".env", root / ".env.example", token=iter(["a", "b", "c"]).__next__)
    env = demo.read_env(root / ".env")
    assert filled == ["WEIR_KEY_STAFF", "WEIR_KEY_ADMIN", "GRAFANA_ADMIN_PASSWORD"]
    assert (env["GROQ_API_KEY"], env["WEIR_KEY_PUBLIC"], env["WEIR_KEY_STAFF"]) == ("gsk_real", "mine", "a")
    assert demo.prepare_env(root / ".env", root / ".env.example") == []          # a second run changes nothing


def test_demo_url_carries_the_key_only_in_the_fragment():
    base, fragment = demo.demo_url("k-123", "stub").split("#")
    assert base == "http://127.0.0.1:8000/demo" and fragment == "key=k-123&mode=stub"


@pytest.mark.parametrize("meta, path", [
    ({"cache_status": "hit", "route": "none"}, "hit"),
    ({"cache_status": "miss", "guard_refused": True, "route": "large"}, "guard_refused"),
    ({"cache_status": "bypass", "route": "large"}, "bypass"),
    ({"cache_status": "miss", "escalated": True, "route": "large"}, "escalated"),
    ({"cache_status": "miss", "route": "small"}, "small"),
])
def test_observed_path(meta, path):
    assert demo.observed_path(meta) == path


def test_a_cached_question_never_passes_as_a_miss():  # Review Focus 5
    assert not demo.step_passed("miss", {"cache_status": "hit", "route": "none"})
    assert not demo.step_passed("miss", {"cache_status": "miss", "guard_refused": True, "route": "large"})
    assert demo.step_passed("miss", {"cache_status": "miss", "route": "small"})


def test_main_starts_pins_the_mode_purges_and_opens_without_printing_keys(tmp_path):  # Review Focus 2
    root = project(tmp_path)
    run, http = FakeRun(), FakeHttp()
    code, lines, opened = run_main(root, [], run=run, http=http)
    env = demo.read_env(root / ".env")
    compose = [(cmd, kw) for cmd, kw in run.calls if cmd[:2] == ["docker", "compose"]]
    assert code == 0 and compose and all(kw["env"]["LLM_MODE"] == "stub" for _, kw in compose)
    [delete] = [c for c in http.calls if c[0] == "DELETE"]
    assert delete[2]["X-API-Key"] == env["WEIR_KEY_ADMIN"] and "namespace=weir-general%2Fen%2Fpublic" in delete[1]
    [url] = opened
    assert url.split("#")[0] == "http://127.0.0.1:8000/demo" and env["WEIR_KEY_PUBLIC"] in url.split("#")[1]
    printed = "\n".join(lines)
    assert not any(env[k] in printed for k in demo.FILL)
    assert not any("hospital_rag.ingest" in cmd for cmd, _ in run.calls)     # the KB is already loaded


def test_first_run_loads_the_kb_then_waits_for_weir_to_see_it(tmp_path):
    run, slept = FakeRun(), []
    code = demo.main([], run=run, http=FakeHttp(namespaces=()), opener=lambda url: True, sleep=slept.append,
                     root=project(tmp_path), out=lambda line: None, environ={})
    [ingest] = [kw for cmd, kw in run.calls if "hospital_rag.ingest" in cmd]
    assert code == 0 and ingest["env"]["LLM_MODE"] == "stub" and demo.KB_VERSION_WAIT_S in slept


def test_a_groq_key_selects_real_models_unless_stub_is_forced(tmp_path):
    root = project(tmp_path, EXAMPLE.replace("GROQ_API_KEY=", "GROQ_API_KEY=gsk_test"))
    for argv, mode in (([], "groq"), (["--stub"], "stub")):
        run = FakeRun()
        run_main(root, argv, run=run)
        assert all(kw["env"]["LLM_MODE"] == mode for cmd, kw in run.calls if cmd[:2] == ["docker", "compose"])


def test_docker_not_running_says_so_and_stops(tmp_path):  # Review Focus 1
    run = FakeRun(fail={"info": (1, "error during connect")})
    code, lines, opened = run_main(project(tmp_path), [], run=run)
    assert code == 1 and "Start Docker Desktop" in lines[0] and len(run.calls) == 1 and not opened


def test_compose_failure_shows_its_error_and_stops(tmp_path):  # Review Focus 1
    run = FakeRun(fail={"up": (1, "Error: port 8000 is already allocated")})
    code, lines, opened = run_main(project(tmp_path), [], run=run)
    assert code == 1 and "port 8000 is already allocated" in "\n".join(lines) and not opened


def test_no_browser_prints_the_address_without_the_key(tmp_path):
    root = project(tmp_path)
    code, lines, opened = run_main(root, [], opener_result=False)
    key = demo.read_env(root / ".env")["WEIR_KEY_PUBLIC"]
    assert code == 0 and any("http://127.0.0.1:8000/demo" in line and "paste" in line for line in lines)
    assert not any(key in line for line in lines)
    code, lines, opened = run_main(root, ["--no-browser"])
    assert code == 0 and not opened


def test_check_runs_the_five_steps_and_fails_on_a_wrong_path(tmp_path):
    root = project(tmp_path)
    code, lines, opened = run_main(root, ["--check"], http=FakeHttp(metas=GOOD))
    assert code == 0 and sum(line.startswith("step") and ": pass" in line for line in lines) == 5 and not opened
    bad = GOOD[:3] + [{"cache_status": "miss", "route": "large"}] + GOOD[4:]
    code, lines, _ = run_main(root, ["--check"], http=FakeHttp(metas=bad))
    assert code == 1 and any(line.startswith("step 4: FAIL") for line in lines)


def test_dashboard_starts_monitoring_and_points_to_grafana(tmp_path):
    run = FakeRun()
    code, lines, _ = run_main(project(tmp_path), ["--dashboard"], run=run)
    [up] = [cmd for cmd, _ in run.calls if "up" in cmd]
    assert code == 0 and up[2:4] == ["--profile", "monitoring"] and "grafana" in up
    assert any("http://127.0.0.1:3000" in line for line in lines)


def test_stop_stops_every_service(tmp_path):
    run = FakeRun()
    code, _, _ = run_main(project(tmp_path), ["--stop"], run=run)
    assert code == 0 and run.calls[-1][0] == ["docker", "compose", "--profile", "monitoring", "stop"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --no-project --python 3.12 --with pytest pytest -q tests`

Expected: FAIL (`ModuleNotFoundError: No module named 'demo'`).

- [ ] **Step 3: Implement.** Create `demo.py` at the repo root:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""One-command Weir demo (Phase 6A addendum §4). Standard library only; never prints a key.

    uv run demo.py               start (the stub model if GROQ_API_KEY is blank) and open the demo page
    uv run demo.py --stub        the stub model even when a Groq key is set (no quota used)
    uv run demo.py --keep-cache  don't empty the demo cache first
    uv run demo.py --dashboard   also start Prometheus and Grafana
    uv run demo.py --check       run the five guided steps and check each path (no browser)
    uv run demo.py --no-browser  start everything but don't open a browser
    uv run demo.py --stop        stop everything
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEIR = "http://127.0.0.1:8000"
RAG = "http://127.0.0.1:8001"
GRAFANA = "http://127.0.0.1:3000"
NAMESPACE = "weir-general/en/public"
QUESTIONS = ROOT / "services" / "weir" / "src" / "weir" / "demo" / "questions.json"
FILL = ("WEIR_KEY_PUBLIC", "WEIR_KEY_STAFF", "WEIR_KEY_ADMIN", "GRAFANA_ADMIN_PASSWORD")
SERVICES = ["postgres", "migrate", "hospital-rag", "weir"]
HEALTH_TIMEOUT_S = 600
KB_VERSION_WAIT_S = 35      # Weir re-reads KB versions every 30 s (configs/weir.yaml: rag.info_refresh_seconds)
CACHE_WRITE_WAIT_S = 2      # cache writes are asynchronous: let step 1's answer land before step 2


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def prepare_env(env_path: Path, example_path: Path,
                token: Callable[[], str] = lambda: secrets.token_urlsafe(24)) -> list[str]:
    """Create .env from the example if missing and fill blank or missing keys. Returns the names filled."""
    if not env_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    filled, seen, lines = [], set(), []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and not line.lstrip().startswith("#"):
            seen.add(name)
            if name in FILL and not value.strip():
                line = f"{name}={token()}"
                filled.append(name)
        lines.append(line)
    for name in FILL:
        if name not in seen:
            lines.append(f"{name}={token()}")
            filled.append(name)
    if filled:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return filled


def choose_mode(env: dict[str, str], force_stub: bool) -> str:
    return "stub" if force_stub or not env.get("GROQ_API_KEY", "").strip() else "groq"


def compose_command(*args: str, monitoring: bool = False) -> list[str]:
    return ["docker", "compose", *(["--profile", "monitoring"] if monitoring else []), *args]


def compose_env(base: dict[str, str], mode: str) -> dict[str, str]:
    return {**base, "LLM_MODE": mode}    # D55: pinned on every compose call, so .env's LLM_MODE can't override it


def demo_url(key: str, mode: str) -> str:
    return f"{WEIR}/demo#" + urllib.parse.urlencode({"key": key, "mode": mode})   # a fragment never reaches a server


def observed_path(meta: dict) -> str:
    if meta.get("cache_status") == "hit":
        return "hit"
    if meta.get("guard_refused"):
        return "guard_refused"
    if meta.get("cache_status") == "bypass":
        return "bypass"
    if meta.get("escalated"):
        return "escalated"
    return str(meta.get("route"))


def step_passed(expect: str, meta: dict) -> bool:
    if expect == "miss":
        return meta.get("cache_status") == "miss" and not meta.get("guard_refused")
    return observed_path(meta) == expect


def http_json(method: str, url: str, headers: dict | None = None, body: dict | None = None,
              timeout: float = 10) -> tuple[int, object]:
    """(status, parsed JSON); status 0 when the server can't be reached."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def tail(text: str, lines: int = 15) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def wait_healthy(http, sleep, out, timeout_s: int = HEALTH_TIMEOUT_S, every_s: int = 3) -> bool:
    waited = 0
    while waited < timeout_s:
        status, body = http("GET", f"{WEIR}/healthz")
        if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
            return True
        sleep(every_s)
        waited += every_s
        if waited % 30 == 0:
            out(f"  still starting... ({waited} s)")
    return False


def run_check(http, sleep, public_key: str, out) -> int:
    steps = json.loads(QUESTIONS.read_text(encoding="utf-8"))["steps"]
    failures = 0
    for step in steps:
        status, body = http("POST", f"{WEIR}/v1/query", headers={"X-API-Key": public_key},
                            body={"query": step["question"], "namespace": NAMESPACE}, timeout=60)
        if status != 200 or not isinstance(body, dict):
            out(f"step {step['n']}: FAIL  HTTP {status}")
            failures += 1
            continue
        meta = body["meta"]
        ok = step_passed(step["expect"], meta)
        failures += not ok
        similarity = meta.get("similarity")
        out(f"step {step['n']}: {'pass' if ok else 'FAIL'}  expected {step['expect']}, got {observed_path(meta)}"
            + (f" (similarity {similarity:.3f})" if similarity is not None else ""))
        sleep(CACHE_WRITE_WAIT_S)
    return 1 if failures else 0


def parse_args(argv):
    p = argparse.ArgumentParser(prog="demo.py", description="Start Weir and open the demo page.")
    p.add_argument("--stub", action="store_true", help="use the stub model even if GROQ_API_KEY is set")
    p.add_argument("--keep-cache", action="store_true", help="don't empty the demo cache first")
    p.add_argument("--dashboard", action="store_true", help="also start Prometheus and Grafana")
    p.add_argument("--check", action="store_true", help="run the five guided steps and check each path")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser")
    p.add_argument("--stop", action="store_true", help="stop everything")
    return p.parse_args(argv)


def main(argv=None, *, run=subprocess.run, http=http_json, opener=webbrowser.open, sleep=time.sleep,
         root: Path = ROOT, out: Callable[[str], None] = print, environ: dict | None = None) -> int:
    args = parse_args(argv)
    base = dict(os.environ if environ is None else environ)
    try:
        docker_ok = run(["docker", "info"], capture_output=True, text=True).returncode == 0
    except FileNotFoundError:
        out("Docker isn't installed. Install Docker Desktop, then run this again.")
        return 1
    if not docker_ok:
        out("Docker isn't running. Start Docker Desktop, then run this again.")
        return 1
    if args.stop:
        run(compose_command("stop", monitoring=True), cwd=root, env=compose_env(base, "stub"),
            capture_output=True, text=True)
        out("Stopped. Start again with: uv run demo.py")
        return 0

    filled = prepare_env(root / ".env", root / ".env.example")
    if filled:
        out(f"Created in .env: {', '.join(filled)} (values not shown).")
    env = read_env(root / ".env")
    mode = choose_mode(env, args.stub)
    out("Mode: " + ("the stub model (no Groq key needed)" if mode == "stub" else "real Groq models"))
    compose = {"cwd": root, "env": compose_env(base, mode), "capture_output": True, "text": True}

    services = SERVICES + (["prometheus", "grafana"] if args.dashboard else [])
    out("Starting the stack (the first run builds the images and takes a few minutes)...")
    proc = run(compose_command("up", "-d", "--build", *services, monitoring=args.dashboard), **compose)
    if proc.returncode != 0:
        out("docker compose failed:\n" + tail(proc.stderr))
        return 1
    if not wait_healthy(http, sleep, out):
        out(f"Weir didn't become healthy within {HEALTH_TIMEOUT_S // 60} minutes. Check: docker compose logs weir")
        return 1

    status, info = http("GET", f"{RAG}/info")
    if status == 200 and isinstance(info, dict) and not info.get("namespaces"):
        out("Loading the knowledge base (first run only)...")
        ingest = run(compose_command("exec", "-T", "hospital-rag", "python", "-m", "hospital_rag.ingest",
                                     "--kb", "/app/kb"), **compose)
        if ingest.returncode != 0:
            out("Loading the knowledge base failed:\n" + tail(ingest.stderr))
            return 1
        out(f"Waiting {KB_VERSION_WAIT_S} s for Weir to pick up the new knowledge base...")
        sleep(KB_VERSION_WAIT_S)

    if not args.keep_cache:
        status, _ = http("DELETE", f"{WEIR}/v1/cache?" + urllib.parse.urlencode({"namespace": NAMESPACE}),
                         headers={"X-API-Key": env["WEIR_KEY_ADMIN"]})
        if status != 200:
            out(f"Couldn't empty the demo cache (HTTP {status}); the guided story may start from a cache hit.")
    if args.check:
        return run_check(http, sleep, env["WEIR_KEY_PUBLIC"], out)
    if args.dashboard:
        out(f"Dashboard: {GRAFANA} (user admin; the password is GRAFANA_ADMIN_PASSWORD in .env)")

    if not args.no_browser and opener(demo_url(env["WEIR_KEY_PUBLIC"], mode)):
        out(f"Opened the demo page: {WEIR}/demo")
    else:
        out(f"Open {WEIR}/demo in a browser and paste WEIR_KEY_PUBLIC from .env when the page asks.")
    out("Stop everything later with: uv run demo.py --stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add the launcher tests to CI. In `.github/workflows/tests.yml`, in the `monitoring` job, add after `- uses: actions/checkout@v4`:

```yaml
      - uses: astral-sh/setup-uv@v6
      - name: Launcher tests (demo.py)
        run: uv run --no-project --python 3.12 --with pytest pytest -q tests
```

- [ ] **Step 4: Run the tests**

Run: `uv run --no-project --python 3.12 --with pytest pytest -q tests`

Expected: all pass (16 tests).

Run: `uv run demo.py --help`

Expected: the usage text with the six flags.

- [ ] **Step 5: Commit, push and merge**

```bash
git add demo.py tests/conftest.py tests/test_demo.py .github/workflows/tests.yml
git commit -m "feat: one-command demo launcher (uv run demo.py): .env, stub without a key, KB once, fresh cache (Phase 6A)"
git push origin phase-6 && git push origin phase-6:main
```

---

### Task 5: Prove the guided story on the live stack

**Files:**
- Modify (only if a step fails): `services/weir/src/weir/demo/questions.json`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: `uv run demo.py --stub --check` (Task 4) and the Weir image with Tasks 1–3.

- [ ] **Step 1: Run the check on a fresh demo cache.** Docker Desktop must be running.

```bash
uv run demo.py --stub --check
```

Expected (the image rebuilds first because Weir changed):

```text
step 1: pass  expected miss, got large
step 2: pass  expected hit, got hit (similarity 0.98x)
step 3: pass  expected guard_refused, got guard_refused (similarity 0.96x)
step 4: pass  expected small, got small
step 5: pass  expected large, got large
```

and exit code 0.

- [ ] **Step 2: Check the honest report on a warm cache** (Review Focus 5):

```bash
uv run demo.py --stub --check --keep-cache
```

Expected: step 1 `FAIL expected miss, got hit`, step 2 `pass`, step 3 `FAIL expected guard_refused, got hit` (the weekend answer was cached in Step 1), and exit code 1. This is the intended behaviour, not a defect.

- [ ] **Step 3: If Step 1 failed on any step,** swap that step for its fallback, run `uv run demo.py --stub --check` again, and record the swap and its reason as a ruling:
  - steps 1–3 together (all three must change at once): "When does lab sample collection close on a Sunday?" (eval q-115), "Lab sample collection closing time on Sunday?" (similarity 0.983 to step 1, same entities), "When does lab sample collection close on a Monday?" (eval q-116, similarity 0.960, different day)
  - step 4: "What are the opening hours of the OPD pharmacy?" (eval q-108, routed small)
  - step 5: "What is the service charge per visit at the vaccination clinic, and what is the first consultation fee at the Pediatrics OPD?" (eval q-147, routed large)

  Update the matching `hint` text with the swap.

- [ ] **Step 4: Record and commit.** Add a Task 5 line to `docs/progress.md` with the five observed paths and similarities.

```bash
git add docs/progress.md services/weir/src/weir/demo/questions.json
git commit -m "docs: Phase 6A guided story verified on the live stub stack"
git push origin phase-6 && git push origin phase-6:main
```

---

### Task 6: Live smoke of the page and the README screenshot

**Files:**
- Create: `scripts/demo_smoke.py`, `docs/images/demo.png`

**Interfaces:**
- Consumes: `demo.read_env`, `demo.demo_url`, `demo.WEIR`, `demo.ROOT` (Task 4); the page's ids and classes (Task 3).

- [ ] **Step 1: Write the smoke script.** Create `scripts/demo_smoke.py`:

```python
"""Live smoke for the demo page (Phase 6A addendum §6). Free: Playwright's headless Chromium.

    uv run --with playwright python -m playwright install chromium   # once, ~150 MB
    uv run demo.py --stub --no-browser                               # a fresh stack and an empty demo cache
    uv run --with playwright python scripts/demo_smoke.py

Clicks the five guided steps and checks every badge and tick, the savings panel, the key leaving the address
bar, a repeated step, and the three error paths (no key, a wrong key, a Groq rate limit).
Saves docs/images/demo.png. Never prints a key.
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import demo  # noqa: E402

SHOT = ROOT / "docs" / "images" / "demo.png"
CACHE_WRITE_WAIT_MS = 2000
PASS = re.compile(r"\bpass\b")
OTHER = re.compile(r"\bother\b")
BADGE = {2: "CACHE HIT", 3: "CACHE REFUSED", 4: "SMALL MODEL", 5: "LARGE MODEL"}


def ask_free_text(page, question: str) -> None:
    page.fill("#question", question)
    page.click("#send")


def guided_steps(page) -> None:
    for n in range(1, 6):
        step = page.locator(f'button.step[data-step="{n}"]')
        step.click()
        expect(step.locator(".result")).not_to_be_empty(timeout=60_000)
        expect(step).to_have_class(PASS)
        badges = page.locator(".card").first.locator(".badge").all_inner_texts()
        assert n not in BADGE or BADGE[n] in badges, f"step {n}: badges {badges}"
        assert n != 1 or "CACHE HIT" not in badges, f"step 1 was a hit: {badges}"
        page.wait_for_timeout(CACHE_WRITE_WAIT_MS)


def main() -> None:
    key = demo.read_env(demo.ROOT / ".env")["WEIR_KEY_PUBLIC"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)

        page.goto(demo.demo_url(key, "stub"))
        expect(page.locator("#mode")).to_have_text("stub answers (no Groq key)")
        assert "key=" not in page.url, "the key stayed in the address bar"
        expect(page.locator("button.step")).to_have_count(5)
        guided_steps(page)
        expect(page.locator("#s-n")).to_have_text("5")
        expect(page.locator("#s-hit")).to_have_text("20%")
        assert int(page.locator("#s-saved").inner_text().rstrip("%")) > 0
        page.screenshot(path=str(SHOT), full_page=True)

        step1 = page.locator('button.step[data-step="1"]')            # Review Focus 5: a repeat is reported
        step1.click()
        expect(step1).to_have_class(OTHER, timeout=60_000)
        expect(step1.locator(".result")).to_contain_text("already cached")

        page.route("**/v1/query", lambda route: route.fulfill(           # Review Focus 4: the Groq limit
            status=503, content_type="application/json", body=json.dumps({"error": "rate_limited", "retry_after": 30})))
        ask_free_text(page, "Is there a pharmacy open at night?")
        expect(page.locator(".card").first).to_contain_text("Groq free-tier limit")
        page.unroute("**/v1/query")

        wrong = browser.new_context().new_page()                          # Review Focus 3: a wrong key
        wrong.goto(demo.demo_url("not-the-key", "stub"))
        ask_free_text(wrong, "Is there a pharmacy open at night?")
        expect(wrong.locator(".card.error").first).to_contain_text("The key was rejected")

        missing = browser.new_context().new_page()                        # Review Focus 3: no key at all
        missing.once("dialog", lambda dialog: dialog.accept(key))
        missing.goto(f"{demo.WEIR}/demo")
        expect(missing.locator("#mode")).to_have_text("mode unknown")
        ask_free_text(missing, "Is there a pharmacy open at night?")
        expect(missing.locator(".card").first.locator(".badge").first).to_be_visible(timeout=60_000)

        browser.close()
    print(f"demo smoke: every check passed; wrote {SHOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it on a fresh stack**

```bash
uv run --with playwright python -m playwright install chromium
uv run demo.py --stub --no-browser
uv run --with playwright python scripts/demo_smoke.py
```

Expected: `demo smoke: every check passed; wrote docs/images/demo.png`. Open the screenshot and check it shows the two-column layout, five ticked steps, five cards with badges and the savings panel.

- [ ] **Step 3: Optional real-Groq check.** Ask the user first: it spends five Groq requests. If they agree and `GROQ_API_KEY` is set, run `uv run demo.py --check` and record the five paths; expect the same paths (routing depends on retrieval only) and the mode tag "real answers (Groq)" when opened in a browser.

- [ ] **Step 4: Commit, push and merge**

```bash
git add scripts/demo_smoke.py docs/images/demo.png
git commit -m "test: live Playwright smoke for the demo page, and its screenshot (Phase 6A)"
git push origin phase-6 && git push origin phase-6:main
```

---

### Task 7: Docs, final review, close

**Files:**
- Modify: `README.md`, `docs/decisions.md`, `docs/progress.md`, `docs/backlog.md`, `docs/README.md`

- [ ] **Step 1: README.** Replace the opening of the "Quick start" section (up to and including the `docker compose exec ... ingest` block) with:

````markdown
## Quick start

**Prerequisites:** Docker Desktop (running) and [uv](https://docs.astral.sh/uv/). A free [Groq API key](https://console.groq.com/keys) is optional.

```bash
uv run demo.py
```

That one command creates `.env` with fresh keys, starts the stack, loads the knowledge base, empties the demo cache and opens the demo page at <http://127.0.0.1:8000/demo>. Without a Groq key it uses the stub model: retrieval, the cache, the guard and the router are real, the generated answers are simulated, and the page says so. Add your key to `.env` as `GROQ_API_KEY` and run it again for real model answers. `uv run demo.py --stop` stops everything; `--dashboard` also starts Grafana; `--check` runs the guided story without a browser.

<p align="center">
  <img src="docs/images/demo.png" alt="The Weir demo page: answer cards with cache and model badges, a guided five-step sidebar and a savings panel" width="900">
</p>

The guided sidebar walks the five-minute story: a weekday parking question (a miss), the same question reworded (a cache hit), the weekend look-alike (the guard refuses the cached weekday price), an easy question (the small model) and a hard one (the large model).

### Manual setup

```bash
cp .env.example .env
# Fill in GROQ_API_KEY, then generate three tenant keys (WEIR_KEY_PUBLIC / _STAFF / _ADMIN):
uv run python -c "import secrets; print(secrets.token_urlsafe(24))"

docker compose up -d --build                     # postgres, migrations, hospital-rag, weir
docker compose exec hospital-rag python -m hospital_rag.ingest --kb /app/kb
```
````

In the same section's example response, add `"counterfactual_cost_usd": 0.00009,` and `"guard_refused": false` to `meta` after `"cost_usd": 0.0`. In "Tests", update the counts from `uv run pytest --collect-only -q` per suite and add `uv run --no-project --python 3.12 --with pytest pytest -q tests   # launcher`. Update the status note: Phase 6A done, next 6B. In the roadmap, set Phase 6 to "In progress (6A done)".

- [ ] **Step 2: Docs.**
  - `docs/decisions.md`: D68 (the guided story uses weekday vs weekend car parking; step 2 is written for the demo because no public eval topic has both a reworded twin and a look-alike at or above 0.90) and D69 (after a first-time knowledge-base load the launcher waits 35 s, because Weir re-reads KB versions every 30 s and step 1 would otherwise bypass the cache and never be stored), plus any build decisions.
  - `docs/progress.md`: a Phase 6A entry with the test counts, the live check and smoke results.
  - `docs/backlog.md`: mark the "Demo chat page" idea done (Phase 6A).
  - `docs/README.md`: link this plan.
  - No emojis.

- [ ] **Step 3: Final whole-branch review.** Build a code-only package from the Phase 6A start (`37bd79a`) covering `demo.py`, `tests`, `scripts`, `services`, `.github`. Dispatch one fresh reviewer on the most capable model with the plan, the addendum and the Review Focus list. Re-grade findings by effect; fix Critical and Important ones test-first in one pass; put Minor ones in `docs/backlog.md`.

- [ ] **Step 4: Commit, push, close**

```bash
git add README.md docs/
git commit -m "docs: Phase 6A one-command demo and demo page: README quick start, decisions, progress; Phase 6A closed"
git push origin phase-6 && git push origin phase-6:main
```

Update the memory file `weir-project.md`: Phase 6A done with its date; next is Phase 6B (write-up and demo script).

---

## Self-Review Notes

**Spec coverage** (addendum section → task):

| Addendum section | Task(s) |
| --- | --- |
| §1 decisions D62–D67 | logged with the spec |
| §2 components and flow | 1, 2, 3, 4 |
| §3.1 header, answers, badges, errors, missing key | 3 (tested in 3 and 6) |
| §3.2 guided sidebar and savings | 2 (questions), 3 (page), 6 (smoke) |
| §3.3 response additions | 1 |
| §4 launcher steps 1–7 and flags | 4 |
| §5 guided questions chosen by running them | planning (table in Task 2), 5 (live check) |
| §6 testing | 1, 2, 3, 4, 5, 6 |
| §7 documentation | 7 |
| §8 out of scope | respected |

**Deliberate refinements:**
- **The guided story is weekday vs weekend car parking, not the spec's ICU example.** The ICU look-alike scores 0.896 against the threshold of 0.90, so it would be a plain miss, not a guard refusal. Step 2 is written for the demo because no public eval topic has both a reworded twin and a look-alike at or above 0.90 (D68).
- **A 35 s wait after a first-time knowledge-base load** (D69): Weir re-reads KB versions every 30 s, and until it does every request bypasses the cache ("no_version"), so step 1 would never be stored.
- **The page removes the key from the address bar** after reading it, so it doesn't appear in screen shares or screenshots.
- **`--check` and `--no-browser` flags** were added to the launcher: `--check` is how Task 5 proves the story, `--no-browser` is how the smoke prepares a fresh stack.
