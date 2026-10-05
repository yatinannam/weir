# Eval run

- **config:** full
- **split:** tune
- **workload:** datasets/workload-300-seed7.jsonl
- **queries:** 300
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** c4043e5
- **started_utc:** 20261005T104855Z
- **workload_repeat_rate:** 0.737

Requests: 300 (ok 300, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0030 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 22 / 614 / 780 |
| Judge score mean (1-5) | 4.787 (0 not judged) |
| Key-fact score mean (0-1) | 0.947 |
| Cache hit rate | 93.0% |
| Cache hits / wrong hits | 279 / 0 |
| Route mix | none 93%, large 7% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 87 | 4.264 | 0.816 |
| paraphrase | 105 | 5 | 1.0 |
| trap | 104 | 5 | 1.0 |
| unanswerable | 4 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 104 | 5 | 1.0 |
| hard | 42 | 3.476 | 0.619 |
| medium | 154 | 5 | 1.0 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| hit | 279 | 22 | 37 |
| miss | 21 | 710 | 811 |

## By route

| Route | n | Judge | Facts | Cost / 1k | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| large | 21 | 1.952 | 0.238 | $0.0434 | 710 | 811 |
| none | 279 | 5 | 1.0 | $0.0000 | 22 | 37 |

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
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
| q-116 | 5 | 1.00 |  |
