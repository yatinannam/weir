# Weir Phase 6A: One-command Demo and Demo Page Design (addendum)

Date: 2026-10-08 · Author: Yatin Annam (with Claude Code)
Status: Draft for review
Builds on:
- [Main design spec](2026-09-30-weir-design.md): §16, the Phase 6 row ("Polish: README, diagram, demo script, write-up, optional router v2"; exit gate "a stranger can run it with one command").
- [Original spec](../../weir-original.md): "Five-minute demo script".
- [Backlog](../../backlog.md): the "Demo chat page" product idea.
- Decisions D35 (only grounded answers are cached), D46 (Grafana password), D55 (pin the stub model in every Compose call).

This addendum fixes the details for the first Phase 6 sub-project. Where it disagrees with the main spec, it wins for Phase 6A.

---

## 1. In plain terms

Weir's results are measured and documented, but seeing them still takes a terminal and `curl`. Phase 6A makes the story visible:
- **One command** (`uv run demo.py`) gets a fresh clone running and opens a page in the browser. It works **without a Groq key**: the stub model answers instead, and the page says so.
- **The demo page** lets anyone ask the hospital FAQ a question and shows how Weir handled it: from the cache, the small model or the large model; how long it took; what it cost; and what always using the large model would have cost.
- **A guided sidebar** walks the five-minute interview story: a miss, a reworded hit, a look-alike the guard refuses, an easy question on the small model and a hard one on the large model.

**User decisions (2026-10-08):**
- **D62, Phase 6 split:** 6A one-command demo and demo page; 6B write-up and demo script; 6C learned router, only if time allows. Each gets its own spec, plan and build.
- **D63, where the page lives:** local only, served by Weir at `http://127.0.0.1:8000/demo`. No public hosting.
- **D64, no key needed:** with no `GROQ_API_KEY` the command starts the stub model; with a key, real Groq answers.
- **D65, page features:** the answer card, plus guided demo buttons and a running savings panel. No cache, feedback, staff or kill-switch controls on the page.
- **D66, how it is built:** one static HTML file served by Weir, plus a standard-library Python launcher. The page reads the API key from the URL fragment (`#key=...`), which browsers never send to a server. Weir's API and auth are otherwise unchanged.
- **D67, layout:** two columns: answers on the left, a guided-demo and savings sidebar on the right (stacked below on narrow screens).

---

## 2. Components and data flow

| Piece | Where | What it does |
| --- | --- | --- |
| Launcher | `demo.py` (repo root) | Prepares `.env`, picks the mode, starts the stack, loads the KB once, empties the demo cache, opens the page |
| Demo page | `services/weir/src/weir/demo/index.html` | One self-contained file: HTML, CSS and plain JavaScript, no build step, no external fonts or libraries |
| Guided questions | `services/weir/src/weir/demo/questions.json` | The five steps: question, expected path, one-line "what to expect" |
| Page route | Weir, `GET /demo` (and `GET /demo/questions.json`) | Serves the two files. Always on: Weir listens only on 127.0.0.1 and the files hold no secrets |
| Response additions | Weir, `QueryMeta` | `counterfactual_cost_usd` and `guard_refused` (§3.3) |

**The flow:** the page posts each question to the normal `POST /v1/query` with the public tenant key, like any client. Auth, the cache, the entity guard, the router, logging and metrics all run unchanged, so every demo question is a real, logged request.

```text
uv run demo.py ──> .env (keys, mode) ──> docker compose up (stub or groq) ──> ingest once ──> purge public cache
      └──> browser: http://127.0.0.1:8000/demo#key=<public key>&mode=stub
                       │
                       └── POST /v1/query (X-API-Key) ──> Weir ──> cache / guard / router ──> hospital-rag
```

---

## 3. The demo page (D65, D67)

### 3.1 Header and answers

- **Header:** "Weir demo: Weir General Hospital FAQ" and a mode tag: **"stub answers (no Groq key)"** or **"real answers (Groq)"**, from the `mode` value in the URL fragment.
- **Question box:** free text; Enter sends. Questions go to the public namespace (`weir-general/en/public`).
- **Answer cards,** newest first: the question, the answer, the source titles, and a line with the badge, time and cost.

| Badge | Shown when |
| --- | --- |
| **CACHE HIT** (green) | `cache_status` is `hit`; shows the similarity; cost $0 |
| **SMALL MODEL** / **LARGE MODEL** | a miss answered by the routed model |
| **SMALL → LARGE** | `escalated` is true: the small model's answer failed the grounding check |
| **CACHE REFUSED** (orange, beside the model badge) | `guard_refused` is true; shows "look-alike at similarity 0.93" |
| **CACHE SKIPPED** (grey) | `cache_status` is `bypass` (a bypass rule applied) |

- **Errors** become a red card with a plain message: 401 ("the key is wrong; check WEIR_KEY_PUBLIC in .env"), 503 rate limit ("the Groq free-tier limit was reached; try again in a minute"), network failure ("Weir isn't reachable; is the stack running?"), anything else with its status.
- **No key in the fragment:** the page asks for the public key once and keeps it in `sessionStorage`.

### 3.2 Guided sidebar and savings

- **Five steps,** each a button that fills the question box and sends it, with a one-line "what to expect":
  1. Ask a question: a miss, answered via retrieval and a model.
  2. Reword it: a cache hit at near-zero cost.
  3. A look-alike: the guard refuses the cache.
  4. An easy question: the small model.
  5. A hard question: the large model.
- After each answer the step shows a tick if Weir took the expected path, or says plainly what happened instead (for example "already cached: the cache wasn't emptied").
- **Savings panel,** for this page session (reset on reload): requests, share from the cache, cost so far, the always-large cost, and the percentage saved.

### 3.3 Two additions to Weir's response

Both are additive; existing clients ignore them.
- **`counterfactual_cost_usd`:** what this request would have cost on the large model with no cache. Weir already computes and logs it per request (`RequestLogRow.counterfactual_cost_usd`); the response now carries it.
- **`guard_refused`:** true when the best cache candidate was at or above the threshold (0.90) but every such candidate failed the entity guard, so the request missed. A miss at or above the threshold can only come from the guard, so this is exact; it is false on hits, plain misses and bypasses.

---

## 4. The launcher (`uv run demo.py`)

One standard-library Python file, safe to run repeatedly, for Windows, macOS and Linux. It needs only Docker and uv (or any Python 3.12), which are already prerequisites. It never prints a key.

1. **Docker check:** `docker info`; if it fails, print "Start Docker Desktop, then run this again" and exit 1.
2. **`.env`:** create it from `.env.example` if missing; fill any blank `WEIR_KEY_PUBLIC`, `WEIR_KEY_STAFF`, `WEIR_KEY_ADMIN` and `GRAFANA_ADMIN_PASSWORD` with `secrets.token_urlsafe(24)`; never overwrite a value that is set.
3. **Mode:** stub when `GROQ_API_KEY` is blank or `--stub` is given, otherwise groq. Every Compose command it runs passes `LLM_MODE` explicitly (D55), so `.env`'s `LLM_MODE` can't override the choice.
4. **Start:** `docker compose up -d --build postgres migrate hospital-rag weir`, then poll `GET /healthz` until Weir is healthy, showing progress (the first build takes a few minutes; give up after 10 minutes with a clear message).
5. **Knowledge base:** if hospital-rag's `GET /info` lists no namespaces, run the ingest (`docker compose exec -T hospital-rag python -m hospital_rag.ingest --kb /app/kb`); otherwise skip.
6. **Fresh demo:** `DELETE /v1/cache?namespace=weir-general/en/public` with the admin key, so step 1 is a real miss. `--keep-cache` skips it.
7. **Open:** `webbrowser.open("http://127.0.0.1:8000/demo#key=<public>&mode=<stub|groq>")`. If that fails, print the address without the key; the page then asks for it (§3.1).

**Flags:** `--stub`, `--keep-cache`, `--dashboard` (also start the `monitoring` profile and print the Grafana address) and `--stop` (`docker compose --profile monitoring stop`).

---

## 5. The guided questions

- Picked from the eval set, starting from Phase 3's measured routes. Candidates: step 1 "What are the ICU visiting hours?", step 2 a reworded version of it, step 3 its look-alike about the general ward, step 4 a question the router sends to the small model, step 5 one it sends to the large model.
- **Chosen by running them.** A check script empties the cache and runs the five steps against the stub stack, asserting: step 1 misses and is cached (D35: a grounded answer); step 2 hits at similarity ≥ 0.90; step 3 has a look-alike ≥ 0.90 and `guard_refused`; step 4 routes small; step 5 routes large. Routing depends only on retrieval, so it is the same in stub and real mode.
- `questions.json` records each step's expected path; the sidebar's ticks compare against it.

---

## 6. Testing

- **Weir unit tests:**
  - `GET /demo` returns the page (`text/html`), and `GET /demo/questions.json` the steps; neither contains a key-like value or an external URL.
  - `counterfactual_cost_usd` is set on hits and misses.
  - `guard_refused` is true only for a miss whose look-alike scored ≥ the threshold, and false on hits, plain misses and bypasses.
- **Launcher unit tests** (new `tests/test_demo.py` at the repo root, run in CI):
  - `.env` creation and filling never overwrite a set value.
  - Mode choice with a key, without one, and with `--stub`.
  - Every Compose command carries `LLM_MODE`.
  - The key appears only in the URL fragment and never in printed output.
  - The Docker-not-running path prints its message and exits 1.
- **Guided-question check:** the script in §5, run against the stub stack.
- **Live smoke:** from a clean state, `uv run demo.py --stub`, then a Playwright script loads the page, clicks the five steps, checks every badge and tick and the savings panel, and saves the README screenshot.
- **Optional real check:** the five steps with a Groq key (five requests). Asked before running.

---

## 7. Documentation

- **README:** the Quick start leads with `uv run demo.py` (the manual steps stay below it), plus a screenshot of the page.
- **`docs/decisions.md`:** D62–D67, and any build decisions from D68.
- **`docs/progress.md`:** a Phase 6A entry.
- **`docs/backlog.md`:** mark the "Demo chat page" idea done.
- **`docs/README.md`:** link this addendum and the plan.
- No emojis.

---

## 8. Out of scope

- Public hosting, and any change to auth or tenants.
- Page controls for the cache, feedback, staff questions or kill switches.
- The write-up and demo-script document (Phase 6B) and the learned router (Phase 6C).
- The deferred backlog items M12–M40.
