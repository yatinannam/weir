# Eval run

- **config:** cache_only
- **split:** tune
- **workload:** datasets/workload-300-seed7.jsonl
- **queries:** 300
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** b88032d
- **started_utc:** 20261003T173739Z
- **workload_repeat_rate:** 0.737

Requests: 300 (ok 300, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0050 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 56 / 579 / 731 |
| Judge score mean (1-5) | 4.79 (0 not judged) |
| Key-fact score mean (0-1) | 0.948 |
| Cache hit rate | 93.3% |
| Cache hits / wrong hits | 280 / 1 |
| Route mix | none 93%, large 7% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 87 | 4.276 | 0.822 |
| paraphrase | 105 | 5 | 1.0 |
| trap | 104 | 5 | 1.0 |
| unanswerable | 4 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 104 | 5 | 1.0 |
| hard | 42 | 3.5 | 0.631 |
| medium | 154 | 5 | 1.0 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| hit | 280 | 56 | 63 |
| miss | 20 | 626 | 840 |

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
| q-141 | 2 | 0.50 |  |
| q-104 | 5 | 1.00 |  |
| q-090 | 5 | 1.00 |  |
| q-090 | 5 | 1.00 |  |
| q-017 | 5 | 1.00 |  |
| q-107 | 5 | 1.00 |  |
| q-090 | 5 | 1.00 |  |
| q-104 | 5 | 1.00 |  |
| q-143 | 1 | 0.00 |  |
| q-001 | 5 | 1.00 |  |
| q-033 | 5 | 1.00 |  |
| q-014 | 5 | 1.00 |  |
| q-028 | 5 | 1.00 |  |
| q-012 | 5 | 1.00 |  |
| q-067 | 5 | 1.00 |  |
| q-061 | 5 | 1.00 |  |
| q-104 | 5 | 1.00 |  |
| q-037 | 5 | 1.00 |  |
| q-085 | 5 | 1.00 |  |
| q-043 | 5 | 1.00 |  |
