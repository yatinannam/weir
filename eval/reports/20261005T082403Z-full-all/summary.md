# Eval run

- **config:** full
- **split:** all
- **workload:** None
- **queries:** 158
- **judge_model:** groq:qwen/qwen3.8-27b
- **rubric:** r1
- **git_commit:** 2517246
- **started_utc:** 20261005T082403Z

Requests: 158 (ok 158, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0763 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 788 / 7180 / 27692 |
| Judge score mean (1-5) | 4.892 (0 not judged) |
| Key-fact score mean (0-1) | 0.975 |
| Cache hit rate | 14.6% |
| Cache hits / wrong hits | 23 / 0 |
| Route mix | large 74%, small 11%, none 15% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 35 | 4.657 | 0.914 |
| paraphrase | 65 | 5 | 1.0 |
| trap | 48 | 4.896 | 0.979 |
| unanswerable | 10 | 5 | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 95 | 5 | 1.0 |
| hard | 15 | 4.2 | 0.8 |
| medium | 48 | 4.896 | 0.979 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| hit | 23 | 32 | 57 |
| miss | 135 | 825 | 7836 |

## By route

| Route | n | Judge | Facts | Cost / 1k | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| large | 117 | 4.855 | 0.966 | $0.0960 | 839 | 8291 |
| none | 23 | 5 | 1.0 | $0.0000 | 32 | 57 |
| small | 18 | 5 | 1.0 | $0.0457 | 691 | 6144 |

Escalation rate (of requests routed small): 0.0%

## Human spot check (judge vs key-fact disagreement first)

| id | judge | facts | your verdict |
| --- | --- | --- | --- |
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
| q-019 | 5 | 1.00 |  |
