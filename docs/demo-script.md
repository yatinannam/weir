# Five-minute demo script

A walk-through for showing Weir live in an interview: the demo page's five guided steps, the Grafana dashboard, and the load-test results. The talking points behind each step are in the [case study](writeup.md).

## Before you start (10 minutes ahead)

1. **Power and memory:** keep the laptop on its charger and close heavy apps (browser tabs, IDEs). The stack and the embedding model want a few GB of memory.
2. **Start Docker Desktop** and wait until it says it's running.
3. **Check the story works with real answers** (about 4 Groq calls):
   ```bash
   uv run demo.py --dashboard --check
   ```
   All five steps should print `pass`. If Groq is out of quota (a step fails with a fallback or HTTP 503), use the stub model for the demo: add `--stub` to the next command. Every step still works, and the page says "stub answers".
4. **Reset and open everything** (this empties the demo cache, so the story starts from a miss):
   ```bash
   uv run demo.py --dashboard
   ```
5. **Open three tabs:**
   - the demo page (opened by the command above)
   - Grafana at <http://127.0.0.1:3000>: user `admin`, password `GRAFANA_ADMIN_PASSWORD` from `.env`; open the **Weir** dashboard (last 30 days, configuration filter **All**)
   - the load-test chart: [`results/loadtest-ramp.png`](results/loadtest-ramp.png), or the [report](results/loadtest-2026-10-07.md) on GitHub
6. **Don't click any guided step** until the demo starts: each one changes the cache.

## The script

| Time | Do | What appears | Say |
| :-- | :-- | :-- | :-- |
| 0:00 | (demo page open) | The empty page, mode tag "real answers (Groq)" | "Weir sits in front of a hospital FAQ chatbot. For every question it decides whether it needs a model at all, and if so, which is the cheapest one that answers well. And it measures every saving." |
| 0:20 | Click **1. Ask a question** | **LARGE MODEL**, about 1.3 s, about $0.0001, ₹40, sources | "A normal miss: Weir searches the documents and asks the model. The answer cites its source, so it's safe to cache, and it is." |
| 0:50 | Click **2. Reword it** | **CACHE HIT**, similarity 0.98, about 20 ms, $0.00000 | "Different wording, same meaning, same details: served from the cache in 20 milliseconds, for free. On realistic repeat-heavy traffic, 93% of requests are like this: 94% cheaper and about 50 times faster than the baseline." |
| 1:20 | Click **3. A look-alike** | **CACHE REFUSED** and **LARGE MODEL**, "look-alike at similarity 0.96", answer ₹60 | "This is the dangerous one. The embedding says it's 96% the same question, but it's the weekend, and the price is different. Similarity alone would have served the wrong price: at this threshold, 37% of cache matches were wrong without the entity guard. With it, zero." |
| 2:10 | Click **4. An easy question** | **SMALL MODEL**, about 0.8 s, cheaper | "Short, one document, a confident match: the small, cheaper model answers. The router is strict: it only takes questions the small model answered perfectly in testing, about 13% of them." |
| 2:40 | Click **5. A hard question**, then point at **Savings this session** | **LARGE MODEL**; the panel shows 5 requests, 20% from the cache, about 28% saved | "Two questions in one goes to the large model. In this short session, Weir was already about 28% cheaper than always using the large model, and every request is logged with that comparison." |
| 3:00 | Switch to **Grafana**: the headline row, then the comparison table, then latency by path | Requests, cost per 1,000, estimated savings, hit rate; the four configurations side by side; p95 for hits, small and large | "This reads every request Weir has served: the eval runs, the load tests, this demo. The comparison row is the ablation: cache only, router only and both, measured on the same questions. The cache does most of the work; the router adds a small, safe saving." |
| 4:00 | Switch to the **load-test chart** | p95 against request rate, full Weir vs the baseline, on a log scale | "On one laptop with a simulated model, Weir held 100 requests a second at about 40 ms. The baseline topped out at 60, at 1.5 seconds. The honest finding: in one run Weir collapsed at 100. When the cache got slow, it bypassed itself, which added load. That's documented with a fix in the backlog." |
| 4:45 | Back to the page | | "Everything here is measured against a fixed eval set with same-day baselines, and one command runs it: `uv run demo.py`." |

## If something goes wrong

| What you see | What it means | What to do or say |
| :-- | :-- | :-- |
| **FALLBACK TO SMALL** on a card, and the step says "Got a fallback" | Groq's free-tier limit was reached for the large model | Say: "That's the fallback working: the large model is rate-limited, so Weir answered with the small one instead of failing." It's a talking point, not a failure. Continue; switch to `--stub` afterwards if it keeps happening. |
| A step says "already cached" | The demo cache wasn't emptied before the story | Run `uv run demo.py` again (it empties the cache) and reload the page. |
| "Weir isn't reachable" | Docker Desktop stopped | Start Docker Desktop and run `uv run demo.py` again. Meanwhile, show the README screenshot. |
| "The key was rejected" | The keys in `.env` changed since the page was opened | Run `uv run demo.py` again; it opens the page with the current key. |
| Grafana shows empty panels | The time range or filter changed | Set the range to the last 30 days and the configuration filter to **All**. |

## Likely questions

The [case study](writeup.md#interview-talking-points) has short answers for the questions this demo invites:
- how the 0.90 threshold was chosen
- how quality was measured
- what went wrong (the outage that cached stand-in answers, the 100 req/s collapse)
- when not to use a semantic cache
- what each part contributes
- why the router's saving is deliberately small

## Afterwards

```bash
uv run demo.py --stop
```
