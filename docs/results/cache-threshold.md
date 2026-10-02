# Cache threshold sweep

Run on 2026-10-02. The final report is `eval/reports/sweep-20261002T180542Z/` (`sweep.csv`, `summary.md`, `pairs.jsonl`, `threshold.png`). Earlier runs are kept for the record: `sweep-20261002T173640Z` (chose 0.95) and `sweep-20261002T173802Z` (chose 0.88).

## Decision: threshold = 0.85 (decisions D25, D26)

**Rule:** take the lowest cosine similarity at which, with the entity guard on, **every** labelled pair has a false-hit rate under 1% and no trap pair is accepted, then add a **0.02 safety margin**. "Every pair" means tune, holdout, and the pairs that span both splits.

The lowest clean threshold is 0.83, because the closest real wrong match sits at 0.825 (see below). With the margin, that gives **0.85**.

| Split, guard on | Accepted pairs | Paraphrase hit rate | False-hit rate | Trap pairs accepted | Hard negatives accepted |
| --- | --- | --- | --- | --- | --- |
| tune | 28 | 31.1% | **0.0%** | **0** | **0** |
| holdout | 23 | 57.5% | **0.0%** | **0** | **0** |
| all (includes cross-split) | 51 | 39.2% | **0.0%** | **0** | **0** |

![Hit rate and false-hit rate against threshold](cache-threshold.png)

## Why the entity guard matters

These are the same pairs at the same 0.85 threshold, with the guard switched off:

| Split, guard **off** | Accepted | Hit rate | False-hit rate | Trap pairs accepted |
| --- | --- | --- | --- | --- |
| tune | 76 | 62.2% | **26.3%** | **12** |
| holdout | 36 | 65.0% | **27.8%** | **6** |
| all | 119 | 63.1% | **31.1%** | **18** |

Similarity alone can't tell "ICU visiting hours" from "general ward visiting hours". Without the guard, almost a third of accepted matches would serve the wrong answer. With it, none do.

The cost is recall: the guard also rejects some true paraphrases that name things differently. On all pairs the hit rate falls from 63.1% to 39.2%. That is a safe trade.

## How the pairs were built

- **Positive (should match):** every pair inside a paraphrase cluster. 13 clusters of 5, giving 130 pairs (90 tune, 40 holdout).
- **Trap (should not match):** every trap pair. 20 pairs (14 tune, 6 holdout).
- **Hard negative (should not match):** each question's single nearest question, by embedding, from another cluster whose answer is **not** compatible. "Compatible" means one fact appears in the other's as whole numbers ("8 pm" in "8 am to 8 pm"; never "₹50" in "₹500"). 125 pairs: 57 tune, 14 holdout, 54 cross-split.
- **Embeddings:** `BAAI/bge-small-en-v1.5` on `normalize(query)`, the same model and normalization as production Weir. No Groq calls were made.

## How we got here (rulings)

1. **First sweep: 0.95** (holdout hit rate 10%). Two trap pairs and a few hard negatives at 0.90–0.95 got past the guard:

   | Pair | Separated by adding |
   | --- | --- |
   | lost vs damaged ID badge | `item_condition` |
   | Code Blue response in the Main Block vs the OPD Block | `buildings` |
   | Basic vs Executive health checkup | `packages` |

   These groups were added to `configs/entities.yaml` (`test_entities.py::test_sweep_found_look_alikes_conflict`).
2. **Second sweep: 0.88.** Same-answer pairs were still mislabelled as negatives, for example two MRI-price questions whose ₹6,500 alternative lists were formatted differently. The pair builder now compares answers by whole-number containment (`test_sweep.py::test_same_answer_*`).
3. **Third sweep: 0.85.** With the labels fixed, the tune-only rule would have picked 0.80. That is the bottom of the swept range, and below a **real** wrong match the tune/holdout split can't see: "adult vaccination clinic *timings*" vs "*which room* is it in" at 0.825. The two questions mention the same entities but ask different things, so the guard can't separate them. The rule now checks every pair and adds the 0.02 margin (`test_choose_threshold_with_safety_margin`).

## Caveats

- **The hit rate is pairwise.** In the cache, each new wording is compared against every stored wording in its cluster, so the real hit rate on repeated traffic is higher. The cache run (`cache-only.md`) measures it directly.
- **The guard can't see "different question about the same thing"** (timings vs room vs price). The margin keeps the threshold above the known case. An "asked attribute" group (time / place / price) would be the next refinement.
- **The sample is small.** 150 questions and 275 pairs, with 20 trap pairs. "0 of 20 trap pairs accepted" is evidence, not proof. The cache run's wrong-hit count is the second check.
