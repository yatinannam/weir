# Eval run

- **config:** full
- **split:** tune
- **workload:** datasets/workload-300-seed7.jsonl
- **queries:** 300
- **judge_model:** None
- **rubric:** r1
- **git_commit:** c1d76c2
- **started_utc:** 20261006T093142Z
- **workload_repeat_rate:** 0.737

Requests: 300 (ok 300, errors 0)

| Metric | Value |
| --- | --- |
| Cost per 1,000 requests (USD, list prices) | 0.0055 |
| Latency p50 / p95 / p99 (ms, sequential, client-side) | 13 / 690 / 1050 |
| Judge score mean (1-5) | None (300 not judged) |
| Key-fact score mean (0-1) | 0.947 |
| Cache hit rate | 93.0% |
| Cache hits / wrong hits | 279 / 0 |
| Route mix | none 93%, large 7% |

## By group

| Group | n | Judge | Facts |
| --- | --- | --- | --- |
| distinct | 87 | None | 0.816 |
| paraphrase | 105 | None | 1.0 |
| trap | 104 | None | 1.0 |
| unanswerable | 4 | None | 1.0 |

## By difficulty

| Difficulty | n | Judge | Facts |
| --- | --- | --- | --- |
| easy | 104 | None | 1.0 |
| hard | 42 | None | 0.619 |
| medium | 154 | None | 1.0 |

## Latency by cache status

| Status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| hit | 279 | 13 | 33 |
| miss | 21 | 786 | 2521 |

## By route

| Route | n | Judge | Facts | Cost / 1k | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| large | 21 | None | 0.238 | $0.0781 | 786 | 2521 |
| none | 279 | None | 1.0 | $0.0000 | 13 | 33 |
