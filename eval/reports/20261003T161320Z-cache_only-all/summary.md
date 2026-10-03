# Eval run

- **config:** cache_only
- **split:** all
- **workload:** None
- **queries:** 150
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** 32dba3d
- **started_utc:** 20261003T161320Z

Requests: 150 (ok 150, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0753 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 606 / 1190 / 1507 |
| Judge score mean (1-5) | 4.933 (0 not judged) |
| Key-fact score mean (0-1) | 0.987 |
| Cache hit rate | 23.3% |
| Cache hits / wrong hits | 35 / 0 |
| Route mix | large 77%, none 23% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 35 | 4.714 | 0.943 |
| paraphrase | 65 | 5 | 1.0 |
| trap | 40 | 5 | 1.0 |
| unanswerable | 10 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 95 | 5 | 1.0 |
| hard | 15 | 4.333 | 0.867 |
| medium | 40 | 5 | 1.0 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| hit | 35 | 19 | 57 |
| miss | 115 | 652 | 1209 |

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
| q-141 | 2 | 0.50 |  |
| q-150 | 2 | 0.50 |  |
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
