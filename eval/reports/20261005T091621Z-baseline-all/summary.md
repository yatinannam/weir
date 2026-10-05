# Eval run

- **config:** baseline
- **split:** all
- **workload:** None
- **queries:** 158
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** 18d06b0
- **started_utc:** 20261005T091621Z

Requests: 158 (ok 158, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0988 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 767 / 1103 / 2697 |
| Judge score mean (1-5) | 4.899 (0 not judged) |
| Key-fact score mean (0-1) | 0.978 |
| Cache hit rate | 0.0% |
| Cache hits / wrong hits | 0 / 0 |
| Route mix | large 100% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 35 | 4.686 | 0.929 |
| paraphrase | 65 | 5 | 1.0 |
| trap | 48 | 4.896 | 0.979 |
| unanswerable | 10 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 95 | 5 | 1.0 |
| hard | 15 | 4.267 | 0.833 |
| medium | 48 | 4.896 | 0.979 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| bypass | 158 | 767 | 1103 |

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
| q-150 | 2 | 0.50 |  |
| q-154 | 4 | 1.00 |  |
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
| q-017 | 5 | 1.00 |  |
| q-018 | 5 | 1.00 |  |
