# Eval run

- **merged_from:** ['20261001T124959Z-baseline-all', '20261002T173631Z-baseline-all']
- **queries:** 150

Requests: 150 (ok 150, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0972 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 615 / 3547 / 8830 |
| Judge score mean (1-5) | 5 (100 not judged) |
| Key-fact score mean (0-1) | 0.967 |
| Cache hit rate | 0.0% |
| Cache hits / wrong hits | 0 / 0 |
| Route mix | large 100% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 35 | 5 | 0.943 |
| paraphrase | 65 | 5 | 0.954 |
| trap | 40 | 5 | 1.0 |
| unanswerable | 10 | None | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 95 | 5 | 0.968 |
| hard | 15 | 5 | 0.867 |
| medium | 40 | 5 | 1.0 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| bypass | 150 | 615 | 3547 |

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
