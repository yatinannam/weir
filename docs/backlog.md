# Backlog

Ideas and deferred findings that aren't scheduled yet. Each item says where it came from. When one is picked up, move it into that phase's plan and log the decision in `decisions.md`.

## Product ideas

| Idea | Why | Suggested phase |
| --- | --- | --- |
| **Demo chat page.** A small web page: ask a question and see the answer, plus a badge for "from cache / small model / large model", time and cost | Makes the story visible in a 5-minute demo: slow first answer, instant reworded answer, trap correctly not cached. The FastAPI page at `localhost:8000/docs` works today but is plain. | Phase 6 (polish) |
| **"Asked attribute" guard group.** Time vs place vs price, plus open vs close | The guard can't tell "clinic timings" from "which room" (0.825 similarity). The threshold margin covers it today. Adding this could allow a lower threshold and more hits. | After Phase 3 |

## Deferred minor findings: Phase 2 final review (2026-10-03)

| # | Area | Finding | Suggested fix |
| --- | --- | --- | --- |
| M1 | Sweep | The threshold is chosen on all pairs (including holdout), and the lexicon was tuned after seeing failures, so holdout is not an independent check | State this in the results caveats (done in `cache-threshold.md`). For the final numbers, keep a fresh held-out set the sweep never sees. |
| M2 | Sweep | `choose_threshold` assumes the false-hit rate falls as the threshold rises (it's a ratio, so it can rise again) | Choose the lowest t such that every t' ≥ t passes |
| M3 | Sweep | Hard negatives ignore namespace (some pairs can never meet in the cache) | Restrict `others` to the same namespace |
| M4 | Feedback | The retry window (~0.8 s) is tight against the log flush. An unknown ID takes longer than another tenant's ID. | ~2 s total, and always wait to the same deadline before a 404 |
| M5 | Feedback | A thumbs-down or purge can race a cache insert that is still queued | Re-check after the queue drains, or record purges with a timestamp |
| M6 | Store | `%s = any(source_ids)` can't use the GIN index | `source_ids @> array[%s]::text[]` |
| M7 | Monitoring | The background queue's `failed` / `dropped` counters aren't exposed | Phase 4 Prometheus counters, or show them in `/healthz` |
| M8 | Startup | If the embedder or lexicon fails to load, the background tasks already started aren't stopped | Start the tasks after loading, or widen the `try` |
| M9 | Router | Answers from `force_model="small"` are cached and served to every caller | Decide in Phase 3: key on tier, or only cache large-model answers |
| M10 | Eval tool | `--exclude-report` and `merge-reports` dedupe by ID, so they would drop repeats on workload reports | Error out when used with `--workload` |
| M11 | Eval tool | `rejudge` re-scores facts but keeps judge grades made against an older answer key | Re-grade the affected clusters, or record the key version on each row |
