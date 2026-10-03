# Cache threshold sweep

Last run on 2026-10-03, after the final review. The current report is `eval/reports/sweep-20261003T172254Z/` (`sweep.csv`, `summary.md`, `pairs.jsonl`, `threshold.png`). Earlier runs are kept for the record:

| Report | Chose | Superseded because |
| --- | --- | --- |
| `sweep-20261002T173640Z` | 0.95 | Lexicon gaps |
| `sweep-20261002T173802Z` | 0.88 | Same-answer labelling bug |
| `sweep-20261002T180542Z` | 0.85 | Final-review findings C1 and I1 |

## Decision: threshold = 0.90 (decisions D25, D26, D30)

**Rule:** take the lowest cosine similarity at which, with the entity guard on, **every** labelled pair has a false-hit rate under 1% and no trap pair is accepted, then add a **0.02 safety margin**. "Every pair" means tune, holdout, and the pairs that span both splits.

The lowest clean threshold is **0.88**, so the chosen value is **0.90**.

| Split, guard on | Accepted pairs | Paraphrase hit rate | False-hit rate | Trap pairs accepted | Hard negatives accepted |
| --- | --- | --- | --- | --- | --- |
| tune | 18 | 20.0% | **0.0%** | **0** | **0** |
| holdout | 15 | 37.5% | **0.0%** | **0** | **0** |
| all (includes cross-split) | 33 | 25.4% | **0.0%** | **0** | **0** |

![Hit rate and false-hit rate against threshold](cache-threshold.png)

## Why the entity guard matters

These are the same pairs at the same 0.90 threshold, with the guard switched off:

| Split, guard **off** | Accepted | Hit rate | False-hit rate | Trap pairs accepted |
| --- | --- | --- | --- | --- |
| tune | 44 | 30.0% | **38.6%** | **12** |
| holdout | 19 | 40.0% | **15.8%** | **3** |
| all | 68 | 33.1% | **36.8%** | **15** |

Similarity alone can't tell "ICU visiting hours" from "general ward visiting hours". Without the guard, more than a third of accepted matches would serve the wrong answer. With it, none do.

## How the pairs were built

- **Positive (should match):** every pair inside a paraphrase cluster. 13 clusters of 5, giving 130 pairs (90 tune, 40 holdout).
- **Trap (should not match):** every trap pair. 24 pairs (17 tune, 7 holdout). This includes 4 pairs added after the final review that use number words and ordinals: "three days" vs "one day", "first" vs "third floor", "two" vs "one attendant", "3rd" vs "4th floor".
- **Hard negative (should not match):** each question's single nearest question, by embedding, from another cluster whose answer is **not** the same. "The same" now means **each** side's required facts are covered by the other's, as whole numbers. So "CT price **and** report time" vs "CT price" is a negative, because the shorter answer misses a fact. There are 131 hard-negative pairs.
- **Embeddings:** `BAAI/bge-small-en-v1.5` on `normalize(query)`, the same model and normalization as production Weir. No Groq calls were made.

## How we got here (rulings)

1. **0.95.** The lexicon had gaps. Lost vs damaged badge, Main vs OPD Block, and Basic vs Executive checkup got past the guard. Added `item_condition`, `buildings` and `packages` (with tests).
2. **0.88.** Same-answer pairs were mislabelled as negatives when their fact lists were formatted differently (₹6,500 written two ways). Fixed with whole-number fact matching (with tests).
3. **0.85.** The tune-only rule would have picked 0.80, below a real wrong match that only appears in cross-split pairs: "adult vaccination clinic *timings*" vs "*which room*", at 0.825. The rule now checks every pair and adds a 0.02 margin (with tests).
4. **0.90, after the final review.**
   - **C1, Critical:** the guard ignored numbers written as words or ordinals. "Cancel the checkup three days before" vs "one day before" scored 0.966 with no conflict, and the refund differs (90% vs 50%). "2nd" vs "3rd floor" and "two" vs "one attendant" behaved the same way.
     - The guard now reads "three" as 3 and both "second" and "2nd" as 2. Numbers inside lexicon phrases ("two-wheeler") stay terms.
     - 4 trap pairs were added to keep this tested.
   - **I1, Important:** the same-answer label was not directional. A two-part question could be served a one-part answer, and the sweep counted that pair as safe. A pair now counts as "same answer" only when each side covers the other. Those pairs became negatives at 0.86–0.87, which moved the lowest clean threshold to 0.88.

## Caveats

- **The hit rate is pairwise.** In the cache, each new wording is compared against every stored wording in its cluster, so the real hit rate on repeated traffic is higher. The cache run (`cache-only.md`) measures it directly.
- **Holdout is not an independent confirmation any more.** The rule now uses every pair, including holdout, and the lexicon was extended after seeing sweep failures. The holdout rows are reported, but they confirm less than a held-out set normally would.
- **Some differences are still invisible to the guard.** It can't see "different question about the same thing" (timings vs room vs price) or open vs close. The margin keeps the threshold above the known cases. An "asked attribute" group would be the next refinement.
- **The sample is small.** 158 questions and 285 pairs, including 24 trap pairs. "0 of 24 trap pairs accepted" is evidence, not proof. The cache run's wrong-hit count is the second check.
