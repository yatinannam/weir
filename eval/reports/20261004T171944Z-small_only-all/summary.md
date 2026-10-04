# Eval run

- **config:** small_only
- **split:** all
- **workload:** None
- **queries:** 158
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** e74b365
- **started_utc:** 20261004T171944Z

Requests: 158 (ok 158, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0467 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 561 / 754 / 1505 |
| Judge score mean (1-5) | 4.867 (0 not judged) |
| Key-fact score mean (0-1) | 0.953 |
| Cache hit rate | 0.0% |
| Cache hits / wrong hits | 0 / 0 |
| Route mix | small 100% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 35 | 4.657 | 0.914 |
| paraphrase | 65 | 4.969 | 0.992 |
| trap | 48 | 4.854 | 0.917 |
| unanswerable | 10 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 95 | 4.979 | 0.995 |
| hard | 15 | 4.2 | 0.8 |
| medium | 48 | 4.854 | 0.917 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| bypass | 158 | 561 | 754 |

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
| q-129 | 5 | 0.00 |  |
| q-151 | 5 | 0.00 |  |
| q-152 | 5 | 0.00 |  |
| q-154 | 2 | 1.00 |  |
| q-001 | 5 | 1.00 |  |
| q-002 | 5 | 1.00 |  |
| q-003 | 5 | 1.00 |  |
| q-004 | 5 | 1.00 |  |
| q-005 | 5 | 1.00 |  |
| q-006 | 5 | 1.00 |  |
| q-007 | 5 | 1.00 |  |
| q-008 | 5 | 1.00 |  |
| q-009 | 5 | 1.00 |  |
| q-010 | 5 | 1.00 |  |
| q-011 | 5 | 1.00 |  |
| q-012 | 5 | 1.00 |  |
| q-013 | 5 | 1.00 |  |
| q-014 | 5 | 1.00 |  |
| q-015 | 5 | 1.00 |  |
| q-016 | 5 | 1.00 |  |
