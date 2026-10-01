# Eval run

- **config:** baseline
- **split:** all
- **queries:** 50
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** a61ce0b
- **started_utc:** 20261001T124959Z

Requests: 50 (ok 50, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0989 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 853 / 5999 / 9238 |
| Judge score mean (1-5) | 5 (0 not judged) |
| Key-fact score mean (0-1) | 1.0 |
| Cache hit rate | 0.0% |
| Route mix | large 100% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 25 | 5 | 1.0 |
| paraphrase | 15 | 5 | 1.0 |
| trap | 10 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 33 | 5 | 1.0 |
| hard | 5 | 5 | 1.0 |
| medium | 12 | 5 | 1.0 |

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
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
| q-019 | 5 | 1.00 |  |
| q-020 | 5 | 1.00 |  |
