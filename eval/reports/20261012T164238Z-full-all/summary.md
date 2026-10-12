# Eval run

- **config:** full
- **split:** all
- **workload:** None
- **queries:** 158
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** 07702f8
- **started_utc:** 20261012T164238Z

Requests: 158 (ok 158, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0547 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 685 / 1053 / 1326 |
| Judge score mean (1-5) | 4.905 (0 not judged) |
| Key-fact score mean (0-1) | 0.978 |
| Cache hit rate | 14.6% |
| Cache hits / wrong hits | 23 / 0 |
| Route mix | small 62%, large 23%, none 15% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 35 | 4.686 | 0.929 |
| paraphrase | 65 | 5 | 1.0 |
| trap | 48 | 4.917 | 0.979 |
| unanswerable | 10 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 95 | 5 | 1.0 |
| hard | 15 | 4.267 | 0.833 |
| medium | 48 | 4.917 | 0.979 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| bypass | 1 | 2502 | 2502 |
| hit | 23 | 37 | 75 |
| miss | 134 | 706 | 1053 |

## By route

| Route | n | Judge | Facts | Cost / 1k | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| large | 37 | 4.676 | 0.919 | $0.1053 | 813 | 1305 |
| none | 23 | 5 | 1.0 | $0.0000 | 37 | 75 |
| small | 98 | 4.969 | 0.995 | $0.0484 | 684 | 986 |

Escalation rate (of requests routed small): 2.0%

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
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
| q-019 | 5 | 1.00 |  |
