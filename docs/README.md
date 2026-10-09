# Weir docs

The record of everything planned, decided and measured for Weir. Start here.

| Doc | What it is |
| --- | --- |
| [writeup.md](writeup.md) | The case study: start here for the story, results, lessons and interview talking points |
| [demo-script.md](demo-script.md) | The five-minute demo script |
| [Pitch video](https://github.com/user-attachments/assets/e2c106bf-0dc8-4f55-8e54-e6d97f661f81) | The two-minute pitch film, played inline on the README (also [as a download](https://github.com/yatinannam/weir/releases/download/v1.0.0/weir-pitch.mp4)) |
| [weir-original.md](weir-original.md) | The original project spec: what Weir is and why |
| [superpowers/specs/2026-09-30-weir-design.md](superpowers/specs/2026-09-30-weir-design.md) | The implementation design: how it is built. Where it disagrees with the original, it wins. |
| [superpowers/specs/2026-10-02-phase-2-semantic-cache-design.md](superpowers/specs/2026-10-02-phase-2-semantic-cache-design.md) | Phase 2 addendum: semantic cache details, threshold sweep, cache eval |
| [superpowers/specs/2026-10-04-phase-3-router-design.md](superpowers/specs/2026-10-04-phase-3-router-design.md) | Phase 3 addendum: router, grounding check, escalation, offline tuning |
| [superpowers/specs/2026-10-06-phase-4-monitoring-design.md](superpowers/specs/2026-10-06-phase-4-monitoring-design.md) | Phase 4 addendum: Prometheus metrics, Grafana dashboard, alerts |
| [superpowers/specs/2026-10-06-phase-5-load-testing-design.md](superpowers/specs/2026-10-06-phase-5-load-testing-design.md) | Phase 5 addendum: k6 load tests, realistic stub, failure injection |
| [superpowers/specs/2026-10-08-phase-6a-demo-page-design.md](superpowers/specs/2026-10-08-phase-6a-demo-page-design.md) | Phase 6A addendum: one-command demo and demo page |
| [backlog.md](backlog.md) | Unscheduled ideas (e.g. demo chat page) and deferred review findings |
| [decisions.md](decisions.md) | A log of every decision, with the reason |
| [progress.md](progress.md) | A phase-by-phase log of what was done and what's next |
| [superpowers/plans/](superpowers/plans/) | One implementation plan per build phase |
| [plans/…phase-0-1…](superpowers/plans/2026-09-30-phase-0-1-foundations-baseline.md) | Phase 0 + 1: foundations and baseline (16 tasks) |
| [plans/…phase-2…](superpowers/plans/2026-10-02-phase-2-semantic-cache.md) | Phase 2: semantic cache (13 tasks) |
| [plans/…phase-4…](superpowers/plans/2026-10-06-phase-4-monitoring.md) | Phase 4: Prometheus metrics, alerts, Grafana dashboard (8 tasks) |
| [plans/…phase-5…](superpowers/plans/2026-10-06-phase-5-load-testing.md) | Phase 5: k6 load tests, realistic stub, failure injection (10 tasks) |
| [plans/…phase-6a…](superpowers/plans/2026-10-08-phase-6a-demo-page.md) | Phase 6A: one-command demo and demo page (7 tasks) |
| [plans/…phase-3…](superpowers/plans/2026-10-04-phase-3-router.md) | Phase 3: router, grounding check, offline tuning, live runs (13 tasks) |
| [results/](results/) | Baseline, threshold sweep, ablation and load-test results |
| [results/baseline.md](results/baseline.md) | Frozen baselines: v1 (50 questions), v2 (150) and v3 (158); v4 (same-day, Phase 3) is in router.md |
| [results/cache-threshold.md](results/cache-threshold.md) | Threshold sweep: 0.90, and why the entity guard matters |
| [results/cache-only.md](results/cache-only.md) | Phase 2 result: cache hit rate, cost, latency, wrong hits |
| [results/router-tuning.md](results/router-tuning.md) | Phase 3: offline router tuning, the strict bar, the option not taken |
| [results/router.md](results/router.md) | Phase 3: live router results, exit gate, outage incidents |
| [results/summary.md](results/summary.md) | The four-way ablation (baseline, cache, router, full) on both workloads, and under load |
| [results/loadtest-2026-10-07.md](results/loadtest-2026-10-07.md) | Phase 5: k6 load tests (31 runs): four-way under load, ramp ceilings, spike, soak, failure injection, checks |
