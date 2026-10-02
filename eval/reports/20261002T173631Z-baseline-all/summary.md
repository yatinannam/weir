# Eval run

- **config:** baseline
- **split:** all
- **workload:** None
- **queries:** 100
- **judge_model:** None
- **rubric:** r1
- **git_commit:** 6d1a330
- **started_utc:** 20261002T173631Z

Requests: 100 (ok 100, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0964 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 551 / 1041 / 1429 |
| Judge score mean (1-5) | None (100 not judged) |
| Key-fact score mean (0-1) | 0.95 |
| Cache hit rate | 0.0% |
| Cache hits / wrong hits | 0 / 0 |
| Route mix | large 100% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 10 | None | 0.8 |
| paraphrase | 50 | None | 0.94 |
| trap | 30 | None | 1.0 |
| unanswerable | 10 | None | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 62 | None | 0.952 |
| hard | 10 | None | 0.8 |
| medium | 28 | None | 1.0 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| bypass | 100 | 551 | 1041 |
