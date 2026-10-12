# Router simulation

Inputs: baseline `baseline-v3`, small trial `20261004T171944Z-small_only-all`. 5400 settings.

## Chosen setting

`{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.5, 'min_overlap': 0.5}`

| split | n | cost / 1k (baseline) | judge (baseline) | facts (baseline) | routed small | escalated | small-route judge vs large | bar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tune | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| holdout | 48 | $0.0647 ($0.0973) | 4.92 (4.92) | 0.979 (0.979) | 65% | 0% | 5.00 vs 5.00 | yes |
| all | 158 | $0.0613 ($0.0980) | 4.91 (4.91) | 0.981 (0.981) | 77% | 2% | 4.98 vs 4.97 | yes |

## Questions routed small at the chosen setting (121)

| id | split | escalated | judge (final) | baseline judge |
| --- | --- | --- | --- | --- |
| q-001 | tune | False | 5 | 5 |
| q-002 | tune | False | 5 | 5 |
| q-003 | tune | False | 5 | 5 |
| q-004 | tune | False | 5 | 5 |
| q-005 | tune | False | 5 | 5 |
| q-006 | holdout | False | 5 | 5 |
| q-007 | tune | False | 5 | 5 |
| q-008 | holdout | False | 5 | 5 |
| q-009 | tune | False | 5 | 5 |
| q-013 | tune | False | 5 | 5 |
| q-014 | holdout | False | 5 | 5 |
| q-021 | tune | False | 5 | 5 |
| q-022 | tune | False | 5 | 5 |
| q-023 | holdout | False | 5 | 5 |
| q-026 | tune | False | 5 | 5 |
| q-027 | tune | False | 5 | 5 |
| q-028 | tune | False | 5 | 5 |
| q-029 | tune | False | 5 | 5 |
| q-030 | tune | False | 5 | 5 |
| q-031 | holdout | False | 5 | 5 |
| q-032 | holdout | False | 5 | 5 |
| q-033 | holdout | False | 5 | 5 |
| q-034 | holdout | False | 5 | 5 |
| q-035 | holdout | False | 5 | 5 |
| q-036 | tune | True | 5 | 5 |
| q-037 | tune | False | 5 | 5 |
| q-038 | tune | False | 5 | 5 |
| q-039 | tune | False | 5 | 5 |
| q-040 | tune | False | 5 | 5 |
| q-041 | tune | False | 5 | 5 |
| q-042 | tune | False | 5 | 5 |
| q-043 | holdout | False | 5 | 5 |
| q-044 | holdout | False | 5 | 5 |
| q-045 | holdout | False | 5 | 5 |
| q-046 | holdout | False | 5 | 5 |
| q-047 | tune | False | 5 | 5 |
| q-048 | tune | False | 5 | 5 |
| q-049 | tune | False | 5 | 5 |
| q-050 | tune | False | 5 | 5 |
| q-051 | holdout | False | 5 | 5 |
| q-052 | holdout | False | 5 | 5 |
| q-054 | holdout | False | 5 | 5 |
| q-055 | holdout | False | 5 | 5 |
| q-056 | tune | False | 5 | 5 |
| q-057 | tune | False | 5 | 5 |
| q-058 | tune | False | 5 | 5 |
| q-059 | tune | False | 5 | 5 |
| q-060 | tune | False | 5 | 5 |
| q-061 | tune | False | 5 | 5 |
| q-062 | tune | False | 5 | 5 |
| q-063 | tune | False | 5 | 5 |
| q-064 | tune | False | 5 | 5 |
| q-065 | tune | False | 5 | 5 |
| q-066 | tune | False | 5 | 5 |
| q-067 | tune | False | 5 | 5 |
| q-068 | tune | False | 5 | 5 |
| q-069 | tune | False | 5 | 5 |
| q-070 | tune | False | 5 | 5 |
| q-071 | tune | False | 5 | 5 |
| q-073 | tune | False | 5 | 5 |
| q-074 | tune | False | 5 | 5 |
| q-075 | tune | False | 5 | 5 |
| q-076 | tune | False | 5 | 5 |
| q-077 | tune | False | 5 | 5 |
| q-078 | tune | False | 5 | 4 |
| q-079 | tune | False | 5 | 5 |
| q-080 | tune | False | 5 | 5 |
| q-081 | tune | False | 5 | 5 |
| q-082 | tune | False | 5 | 5 |
| q-083 | tune | False | 5 | 5 |
| q-084 | tune | False | 5 | 5 |
| q-085 | tune | False | 5 | 5 |
| q-089 | holdout | False | 5 | 5 |
| q-090 | holdout | False | 5 | 5 |
| q-091 | holdout | False | 5 | 5 |
| q-092 | holdout | False | 5 | 5 |
| q-093 | holdout | False | 5 | 5 |
| q-095 | holdout | False | 5 | 5 |
| q-096 | tune | False | 5 | 5 |
| q-097 | tune | False | 5 | 5 |
| q-098 | tune | False | 5 | 5 |
| q-099 | tune | False | 5 | 5 |
| q-100 | tune | False | 5 | 5 |
| q-101 | holdout | False | 5 | 5 |
| q-102 | holdout | False | 5 | 5 |
| q-103 | tune | False | 5 | 5 |
| q-104 | tune | False | 5 | 5 |
| q-105 | tune | False | 5 | 5 |
| q-106 | tune | False | 5 | 5 |
| q-107 | tune | False | 5 | 5 |
| q-108 | tune | False | 5 | 5 |
| q-109 | tune | False | 5 | 5 |
| q-110 | tune | False | 5 | 5 |
| q-111 | tune | False | 5 | 5 |
| q-112 | tune | False | 5 | 5 |
| q-113 | holdout | False | 5 | 5 |
| q-114 | holdout | False | 5 | 5 |
| q-115 | tune | False | 5 | 5 |
| q-116 | tune | False | 5 | 5 |
| q-117 | holdout | False | 5 | 5 |
| q-118 | holdout | False | 5 | 5 |
| q-119 | holdout | False | 5 | 5 |
| q-120 | holdout | False | 5 | 5 |
| q-121 | tune | False | 5 | 5 |
| q-122 | tune | False | 5 | 5 |
| q-123 | tune | False | 5 | 5 |
| q-124 | tune | False | 5 | 5 |
| q-125 | tune | False | 5 | 5 |
| q-126 | tune | False | 5 | 5 |
| q-127 | tune | False | 5 | 5 |
| q-128 | tune | False | 5 | 5 |
| q-129 | tune | False | 5 | 5 |
| q-130 | tune | False | 5 | 5 |
| q-138 | tune | True | 5 | 5 |
| q-150 | tune | True | 2 | 2 |
| q-151 | tune | False | 5 | 5 |
| q-152 | tune | False | 5 | 5 |
| q-153 | tune | False | 5 | 5 |
| q-154 | tune | False | 5 | 5 |
| q-155 | tune | False | 5 | 5 |
| q-156 | tune | False | 5 | 5 |

## Cheapest passing settings on tune (top 10)

| setting | n | cost / 1k (baseline) | judge (baseline) | facts (baseline) | routed small | escalated | small-route judge vs large | bar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.3, 'min_overlap': 0.3}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.3, 'min_overlap': 0.4}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.3, 'min_overlap': 0.5}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.35, 'min_overlap': 0.3}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.35, 'min_overlap': 0.4}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.35, 'min_overlap': 0.5}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.4, 'min_overlap': 0.3}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.4, 'min_overlap': 0.4}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.4, 'min_overlap': 0.5}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
| `{'short_query_tokens': 25, 'high_confidence': 0.72, 'low_confidence': 0.45, 'min_overlap': 0.3}` | 110 | $0.0598 ($0.0983) | 4.91 (4.90) | 0.982 (0.982) | 82% | 3% | 4.97 vs 4.96 | yes |
