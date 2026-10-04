# Router simulation

Inputs: baseline `baseline-v3`, small trial `20261004T171944Z-small_only-all`. 5400 settings.

## Chosen setting

`{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.5, 'min_overlap': 0.6}`

| split | n | cost / 1k (baseline) | judge (baseline) | facts (baseline) | routed small | escalated | small-route judge vs large | bar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tune | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| holdout | 48 | $0.0925 ($0.0973) | 4.92 (4.92) | 0.979 (0.979) | 10% | 0% | 5.00 vs 5.00 | yes |
| all | 158 | $0.0917 ($0.0980) | 4.90 (4.90) | 0.981 (0.981) | 13% | 0% | 5.00 vs 5.00 | yes |

## Questions routed small at the chosen setting (20)

| id | split | escalated | judge (final) | baseline judge |
| --- | --- | --- | --- | --- |
| q-007 | tune | False | 5 | 5 |
| q-009 | tune | False | 5 | 5 |
| q-013 | tune | False | 5 | 5 |
| q-023 | holdout | False | 5 | 5 |
| q-041 | tune | False | 5 | 5 |
| q-042 | tune | False | 5 | 5 |
| q-045 | holdout | False | 5 | 5 |
| q-046 | holdout | False | 5 | 5 |
| q-047 | tune | False | 5 | 5 |
| q-048 | tune | False | 5 | 5 |
| q-049 | tune | False | 5 | 5 |
| q-096 | tune | False | 5 | 5 |
| q-097 | tune | False | 5 | 5 |
| q-108 | tune | False | 5 | 5 |
| q-109 | tune | False | 5 | 5 |
| q-112 | tune | False | 5 | 5 |
| q-119 | holdout | False | 5 | 5 |
| q-120 | holdout | False | 5 | 5 |
| q-123 | tune | False | 5 | 5 |
| q-124 | tune | False | 5 | 5 |

## Cheapest passing settings on tune (top 10)

| setting | n | cost / 1k (baseline) | judge (baseline) | facts (baseline) | routed small | escalated | small-route judge vs large | bar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.3, 'min_overlap': 0.3}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.3, 'min_overlap': 0.4}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.3, 'min_overlap': 0.5}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.3, 'min_overlap': 0.6}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.35, 'min_overlap': 0.3}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.35, 'min_overlap': 0.4}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.35, 'min_overlap': 0.5}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.35, 'min_overlap': 0.6}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.4, 'min_overlap': 0.3}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
| `{'short_query_tokens': 16, 'high_confidence': 0.86, 'low_confidence': 0.4, 'min_overlap': 0.4}` | 110 | $0.0913 ($0.0983) | 4.89 (4.89) | 0.982 (0.982) | 14% | 0% | 5.00 vs 5.00 | yes |
