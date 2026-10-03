# Eval run

- **config:** baseline
- **split:** all
- **workload:** None
- **queries:** 8
- **judge_model:** None
- **rubric:** r1
- **git_commit:** b88032d
- **started_utc:** 20261003T172520Z

Requests: 8 (ok 8, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.1131 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 717 / 1032 / 1032 |
| Judge score mean (1-5) | None (8 not judged) |
| Key-fact score mean (0-1) | 0.875 |
| Cache hit rate | 0.0% |
| Cache hits / wrong hits | 0 / 0 |
| Route mix | large 100% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| trap | 8 | None | 0.875 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| medium | 8 | None | 0.875 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| bypass | 8 | 717 | 1032 |
