# Eval run

- **merged_from:** ['baseline-v2', '20261003T172520Z-baseline-all']
- **queries:** 158
- **judge_model:** groq:qwen/qwen3.8-27b

Requests: 158 (ok 158, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0980 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 617 / 3547 / 8830 |
| Judge score mean (1-5) | 4.899 (0 not judged) |
| Key-fact score mean (0-1) | 0.981 |
| Cache hit rate | 0.0% |
| Cache hits / wrong hits | 0 / 0 |
| Route mix | large 100% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 35 | 4.714 | 0.943 |
| paraphrase | 65 | 4.985 | 1.0 |
| trap | 48 | 4.896 | 0.979 |
| unanswerable | 10 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 95 | 4.989 | 1.0 |
| hard | 15 | 4.333 | 0.867 |
| medium | 48 | 4.896 | 0.979 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| bypass | 158 | 617 | 3547 |

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
| q-078 | 4 | 1.00 |  |
| q-141 | 2 | 0.50 |  |
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
