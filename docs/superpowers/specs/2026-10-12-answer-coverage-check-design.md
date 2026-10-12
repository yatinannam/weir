# Answer coverage check: design

**Date:** 2026-10-12. **Status:** proposed.

**In plain terms:** Weir's current answer check confirms that an answer's words come from the source, but not that it says *everything the question asked for*. The small model's one real mistake in our data was q-036. Asked when the blood donation camp is held, it said "the first Saturday of every month" and left out "10 am to 3 pm".

This design adds a cheap rule-based check:
- **The check:** if the question asks *when*, *how much* or *which extension*, the answer must contain a time, a price or an extension number that the source gives.
- **When it fails:** the question goes to the large model, as it already does when grounding fails.
- **The payoff:** if the check catches omissions like q-036, the router can use a looser setting and save far more than today's 7%, without any answer getting worse.

## 1. Goal and success criteria

**Goal:** make a looser router setting safe under the existing strict bar (D33), with no visible quality loss against the large model.

**Success means all of these, measured offline on the saved answers:**
1. **It catches the real omission:** the check flags q-036's small-model answer.
2. **It catches synthetic omissions:**
   - **Test cases:** answers that score 5/5 with full facts, each with every detail of one required type removed (for example, all times stripped from a "when" answer).
   - **Target:** it flags at least 90% of them.
3. **It rarely flags good answers:**
   - **Measured on:** the small model's answers that score 5/5 with full facts.
   - **Target:** it flags at most 5% of them. Each false flag costs an extra large-model call.
4. **The router saves more:**
   - **Bar:** the strict D33 bar, with the check acting as an escalation trigger.
   - **Target:** the cheapest passing setting on tune saves clearly more than today's 7%.
   - **And:** that setting also meets the bar on holdout.

**Then confirmed live, once, with real models** (needs the user's go-ahead for the Groq quota; see §6):
- a same-day baseline (always large)
- full Weir with the new setting and the check
- the same strict bar, with 0 wrong cache hits

**If holdout or the live run fails the bar:**
- the check still ships, as a safety net
- the router setting stays as it is
- the result is documented either way

## 2. Scope

**In scope:**
- **The check:** a rule-based coverage check run on small-model answers. A failure escalates to the large model, exactly like a grounding failure.
- **Logging:** the check's result, for every answer.
- **Offline evaluation:**
  - a new eval command that computes coverage for saved answers
  - synthetic-omission test cases
  - the router simulation with the check
- **Re-tuning:** the router settings, if the simulation and the live run support it.

**Out of scope (YAGNI):**
- **An NLI model or an LLM reviewer.** Considered and deferred: more download, latency and false alarms, or Groq calls that eat the saving. Revisit only if the rules miss too much.
- **Using the check to block caching.** D35's grounding rule stays the cache gate. Large-model answers are not gated by coverage.
- **Detail types beyond the four below.** For example, a missing instruction like "bring ID proof" is not caught. This goes in the limitations.

## 3. How the check works

**Inputs:**
- the question
- the answer
- the text of the chunks the answer cites (the same chunks grounding uses)

**What it asks for**, decided by the question's wording, word-boundary matches, case-insensitive:

| The question asks... | Trigger words | Required detail types |
| :-- | :-- | :-- |
| when | when, what time, timings, hours, open, close, held, schedule, start, end | time, day |
| how much | how much, cost, fee, fees, charge, charges, price, rate, pay | money |
| which number | extension, ext, phone, number to call, contact, dial | extension |
| how long / how many | how long, how many, duration | quantity |

If no trigger matches (which, where, who, what is...), the check passes: it has nothing to judge.

**Detail extraction** uses regexes and a small word list, with canonical forms so that "10 am", "10:00 am" and "10am" compare equal:

| Type | Examples |
| :-- | :-- |
| time | `10 am`, `3:30 pm`, `noon`, `midnight`, `24 hours`, `round the clock` |
| day | `monday`…`sunday`, `weekday(s)`, `weekend(s)`, `daily`, `every day`, ordinals before a day (`first saturday`) |
| money | `₹500`, `₹ 1,200`, `rs 500`, `rs. 500`, `free of charge`, `no charge` |
| extension | `ext. 2150`, `extension 2150` |
| quantity | a number followed by a unit (`2 hours`, `48 hours`, `3 days`, `2 visitors`) |

**The source passage:**
- **Lines:** split the cited chunks into lines, with table rows and sentences as separate lines.
- **Scoring:** score each line by how many of the question's content words it contains, using the stopword list grounding already uses.
- **The passage:** the best-scoring line or lines (ties kept).
- **Fallback:** if no line shares a content word, the check passes, because it can't tell what is relevant.

**The rule (type coverage):**
- **Fails when:** a required detail type appears in the passage and the answer contains **no** detail of that type.
- **Reason:** `missing:<type>`, for example `missing:time`.

So q-036 fails: the passage "...first Saturday of every month, 10 am to 3 pm" has a time, and the answer has none.

**Why types, not every detail:** a morning-only question (q-001, "What time does ICU visiting start in the morning?") is answered by one of the two times on its line. Requiring every detail would flag it. The stricter "every detail" variant is measured in §5 for comparison only.

**Code:**
- `services/weir/src/weir/router/coverage.py`: `extract_details(text) -> dict[type, set[str]]`, `required_types(question) -> set[type]`, `check(question, answer, chunks) -> Coverage(passed, reason, missing)`.
- Pure functions with no I/O and no model: the cost is microseconds.

## 4. Where it plugs in

**`Pipeline._answer`:**
- **Today:** a small answer that fails grounding is retried once on large.
- **New:** it also retries when the small answer fails coverage.
- **What doesn't change:** the two-call cap and the fallback rules.
- **Config:** new `router.coverage_check: true` (false turns it off).

**Request log:** new columns `coverage_passed` (bool, null when not run) and `coverage_reason`, via migration `006`. They are logged for both tiers, so large-model omissions can be studied later; for the large model they are informational only.

**Metrics and dashboard:**
- **Counter:** `weir_coverage_failures_total{tier}` on `/metrics`.
- **Dashboard:** no new panel. The escalation-rate panel already shows the effect.

## 5. Offline evaluation (no model calls)

**1. New eval command `weir_eval coverage <report_dir>`:**
- **Input:** a saved report's questions.
- **Retrieval:** fetches each question's chunks from hospital-rag's `/retrieve`. The stub stack is fine; retrieval involves no LLM.
- **Which chunks:** the ones from the documents the saved answer cited.
- **Output:** runs the check on each saved answer and writes `coverage.jsonl` next to it.
- **Applied to:** the small-model trial and baseline v3.

**2. Synthetic omissions:**
- For every answer (either model) with judge 5 and facts 1.0 whose question requires a detail type found in its passage, make one variant per required type with all details of that type deleted.
- Each variant must be flagged. Report the recall.

**3. False flags:** the share of real 5/5, full-facts small answers the check flags.

**4. Simulation:**
- **Change:** `simulate` gains `--coverage`. A small answer then counts as passing only if grounding and coverage both pass; otherwise it escalates, costing small plus large.
- **Grid:** the same 5,400 settings.
- **Report:** the cheapest setting meeting the strict bar on tune, and its holdout result.
- **Comparison:** the "every detail" variant, also run.

**Evaluation fixes found while designing:**
- **q-154's labelling gap (D78):** already fixed.
- **Any other questions the new command exposes:** fixed and recorded the same way, never tuned around.

## 6. Live confirmation (real Groq, needs approval)

**Two cold runs on the same day:**

| Run | Model calls | Judge calls |
| :-- | :-- | :-- |
| Baseline (always large) | 158 large | 158 |
| Full Weir with the chosen setting and the check | about 150–200 (more small, a few escalations) | 158 |

**Quota:**
- **Large model:** about 200–250 calls. The free limit is about 1,000 a day, and earlier phases ran out after ~600.
- **Spacing:** the eval runner's existing 15 s spacing, so each run takes about 40 minutes.
- **Replay:** not re-run. On repeat-heavy traffic the cache serves 93%, so the router's effect there is small and already measured.

**Pass:** the strict bar against the same-day baseline, with 0 wrong cache hits.

## 7. Testing

**Unit tests (`tests/test_router_coverage.py`):**
- Detail extraction and canonical forms for each type (`10am` = `10 am` = `10:00 am`; `rs. 500` = `₹500`).
- Required types per question wording, including no trigger, so it passes.
- **q-036 shape:** a day without a time fails `missing:time`.
- **q-001 shape:** one of two times passes.
- A money question answered with a price passes.
- An extension question with no number fails.
- No relevant line passes.

**Pipeline tests:**
- a small answer failing coverage escalates once
- coverage off means no escalation
- the cap holds
- large answers log coverage but never re-call

**Eval tests:** the `coverage` command on fixtures, the synthetic-omission generator, and `simulate --coverage`.

**Migration test:** the list includes `006`.

## 8. Risks

- **Overfitting to one real omission.** This is the reason for the synthetic omissions and the holdout. The detail types come from the hospital's FAQ, not from q-036.
- **False flags on multi-item lines** (directory rows, timetables) cost large-model calls. Type coverage (not every detail) and best-line selection limit this, and the false-flag rate is measured.
- **The judge itself makes mistakes** (D78). Anything surprising in the evaluation gets read by hand, not just counted.

## 9. Decisions this will record

- **D79:** the check's design: rule-based type coverage as an escalation trigger, with the alternatives considered.
- **D80:** the router setting chosen with it, or the decision to keep the current one, with the offline and live evidence.
