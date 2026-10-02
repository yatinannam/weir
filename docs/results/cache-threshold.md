# Cache threshold sweep

Run on 2026-10-02. Raw data:
- `eval/reports/sweep-20261002T173802Z/`: `sweep.csv`, `summary.md`, `pairs.jsonl`, `threshold.png`
- `eval/datasets/pairs.jsonl`

## Decision: threshold = 0.88 (decision D25)

0.88 is the lowest cosine similarity at which, with the entity guard on, the **tune** split has a false-hit rate under 1% and zero trap pairs accepted. The **holdout** split confirms it.

| Split, guard on | Accepted pairs | Paraphrase hit rate | False-hit rate | Trap pairs accepted | Hard negatives accepted |
| --- | --- | --- | --- | --- | --- |
| tune | 23 | 25.6% | **0.0%** | **0** | **0** |
| holdout | 21 | 52.5% | **0.0%** | **0** | **0** |
| all | 44 | 33.8% | **0.0%** | **0** | **0** |

![Hit rate and false-hit rate against threshold](cache-threshold.png)

## Why the entity guard matters

These are the same pairs at the same 0.88 threshold, with the guard switched off:

| Split, guard **off** | Accepted | Hit rate | False-hit rate | Trap pairs accepted |
| --- | --- | --- | --- | --- |
| tune | 59 | 46.7% | **28.8%** | **10** |
| holdout | 27 | 55.0% | **18.5%** | **5** |
| all | 89 | 49.2% | **28.1%** | **15** |

Similarity alone can't tell "ICU visiting hours" from "general ward visiting hours". Without the guard, more than a quarter of accepted matches would serve the wrong answer. With it, none do.

The cost is recall: the guard also rejects some true paraphrases that name things differently. On the tune split the hit rate falls from 46.7% to 25.6%. That is a safe trade.

## How the pairs were built

- **Positive (should match):** every pair inside a paraphrase cluster. 13 clusters of 5, giving 130 pairs (90 tune, 40 holdout).
- **Trap (should not match):** every trap pair. 20 pairs (14 tune, 6 holdout).
- **Hard negative (should not match):** each question's single nearest question, by embedding, from another cluster with a different answer. 124 pairs: 57 tune, 14 holdout, and 53 that span both splits (counted only in "all").
- **Embeddings:** `BAAI/bge-small-en-v1.5` on `normalize(query)`, the same model and normalization as production Weir. No Groq calls were made.

## What changed along the way (rulings)

The first sweep chose **0.95**, with only a 10% holdout hit rate. Two findings explained it:

1. **The lexicon had gaps.** Two trap pairs and some hard negatives at 0.90–0.95 similarity weren't separated by the guard:

   | Pair | Separated by adding |
   | --- | --- |
   | lost vs damaged ID badge | `item_condition` |
   | Code Blue response in the Main Block vs the OPD Block | `buildings` |
   | Basic vs Executive health checkup | `packages` |

   These groups were added to `configs/entities.yaml`, with tests in `test_entities.py::test_sweep_found_look_alikes_conflict`.
2. **Same-answer pairs were mislabelled.** For example, "How much is an MRI scan?" and "How much is an MRI scan at the hospital?" are both ₹6,500, but were counted as negatives because their alternative lists were formatted differently. The pair builder now treats two questions as having the same answer if any of their fact alternatives match (`test_sweep.py::test_same_answer_detected_by_any_shared_alternative`).

## Caveats

- **The hit rate is pairwise.** In the cache, each new wording is compared against every stored wording in its cluster, so the real hit rate on repeated traffic is higher. The cache run (`cache-only.md`) measures it directly.
- **Hard negatives below 0.88 still exist.** For example, "adult vaccination clinic timings" vs "room" sits at 0.825, and "Sunday lab hours" vs "when does it close on Sunday" at 0.871 (that one is arguably the same answer). The chosen threshold sits above both. Lowering it would need an "asked attribute" group (time vs place vs price), which is a possible later refinement.
- **The sample is small.** 150 questions and 274 pairs, with 20 trap pairs. "0 of 20 trap pairs at 0.88" is evidence, not proof. The cache run's wrong-hit count is the second check.
