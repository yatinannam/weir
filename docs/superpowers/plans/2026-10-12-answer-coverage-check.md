# Answer Coverage Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rule-based check that escalates small-model answers missing the kind of detail the question asks for (a time, a day, a price, an extension, a quantity), then measure whether it makes a looser, cheaper router setting safe.

**Architecture:**
- **The check:** a pure module `weir/router/coverage.py` maps question wording to required detail types, picks the source line that best matches the question, and fails when that line has a required type the answer lacks.
- **Weir:** the pipeline runs it next to grounding. A failure on a small answer escalates once, like a grounding failure. The result is logged (migration 006) and counted on `/metrics`.
- **The eval tool:** gains `coverage` (offline scoring of saved answers, plus synthetic omissions) and `simulate --coverage`. The live confirmation reuses the existing `run` and `rejudge` commands.

**Tech Stack:** Python 3.12, FastAPI, Postgres 16, pytest, uv; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-answer-coverage-check-design.md`

## Global Constraints

- **Free and local:** no new model, no new package, and no Groq calls except the approved live confirmation (Task 6: one same-day baseline run and one full-Weir run, about 200–250 large-model calls plus about 316 judge calls).
- **Load tests:** every Compose call pins `LLM_MODE=stub` and uses `--no-deps`, except the live confirmation runs. Those use `LLM_MODE=groq` explicitly.
- **Secrets:** keys are passed by name only, never printed or written to files.
- **Docs:** no emojis anywhere committed.
- **The check runs only as an escalation trigger** on router-decided small answers. It never gates caching (D35 unchanged), never re-calls the large model, and respects `router.max_model_calls`.
- **The bar is unchanged:** the strict D33 bar decides the router setting; the looser bar is reported for comparison only.
- **`router.coverage_check` defaults to `true`;** `false` restores today's behaviour exactly.

## Review Focus

1. **A "when" question whose source says "daily".** An answer with the times but not "daily" must pass. "Daily" and "every day" are not day details. The test lives in Task 1.
2. **A morning-only question on a line with morning and evening times.** An answer with only the morning time must pass, because type coverage needs only one detail per type. Task 1.
3. **An extension question answered "the extension is 2171"** (no "ext." prefix) must pass. On the answer side, any 3–5 digit number counts as an extension. Task 1.
4. **A small answer that fails both grounding and coverage** must escalate once and record `escalated_for="grounding"`. Grounding is checked first. Task 2.
5. **Coverage turned off** (`router.coverage_check: false`) must never escalate for coverage and must leave `coverage_passed` null. Task 2.

---

### Task 1: The coverage module

**Files:**
- Create: `services/weir/src/weir/router/coverage.py`
- Test: `services/weir/tests/test_router_coverage.py`

**Interfaces:**
- **Consumes:** `weir.router.grounding.content_words(text) -> list[str]` and `WORD` (existing).
- **Produces:**
  - `required_types(question: str) -> frozenset[str]`
  - `details(text: str, lenient: bool = False) -> dict[str, set[str]]`, mapping a type to its canonical values
  - `passage(question: str, chunk_texts: list[str]) -> list[str]`
  - `strip_type(text: str, kind: str) -> str`
  - `check(question: str, answer: str, chunk_texts: list[str]) -> Coverage`
  - `Coverage(passed: bool, reason: str | None, missing: tuple[str, ...], strict_passed: bool)`

- [ ] **Step 1: Write the failing tests**

```python
# services/weir/tests/test_router_coverage.py
from weir.router.coverage import check, details, passage, required_types, strip_type

CAMP = "The blood donation camp is held on the first Saturday of every month, 10 am to 3 pm, in the Main Block lobby."
ICU = "ICU visiting hours: 11 am to 1 pm and 5 pm to 7 pm daily. Two visitors at a time."
PARKING = "Cars: ₹40 for the first 2 hours on weekdays and ₹60 on weekends."
DIRECTORY = "| Pediatric ward | Mother and Child Wing, 1st | ext. 2171 |"


def test_canonical_forms_compare_equal():
    assert details("10am, 10:00 am and 10 AM")["time"] == {"10am"}
    assert details("Rs. 500 or ₹ 500 or INR 500")["money"] == {"500"}
    assert details("ext. 2150 and extension 2150")["extension"] == {"2150"}
    assert details("Saturdays and saturday")["day"] == {"saturday"}


def test_daily_is_not_a_day_detail():  # Review Focus 1
    assert "day" not in details("open daily and every day")


def test_required_types_follow_the_question():
    assert required_types("When is the blood donation camp held?") == {"time", "day"}
    assert required_types("What time does ICU visiting start in the morning?") == {"time"}
    assert required_types("How much is car parking for 2 hours?") == {"money"}
    assert required_types("What is the pediatric ward desk extension?") == {"extension"}
    assert required_types("How many visitors are allowed in the ICU?") == {"quantity"}
    assert required_types("Which floor is cardiology on?") == frozenset()


def test_the_best_matching_line_is_the_passage():
    assert passage("When is the blood donation camp held?", ["Blood bank opens 24 hours.\n" + CAMP]) == [CAMP]
    assert passage("Where is the cafeteria?", [CAMP]) == []


def test_a_day_without_its_time_fails():  # q-036
    c = check("When is the blood donation camp held?", "It is held on the first Saturday of every month.", [CAMP])
    assert not c.passed and c.reason == "missing:time" and c.missing == ("time",)


def test_the_full_answer_passes():
    c = check("When is the blood donation camp held?", "First Saturday of every month, 10 am to 3 pm.", [CAMP])
    assert c.passed and c.reason is None and c.strict_passed


def test_one_of_two_times_is_enough():  # Review Focus 2 (q-001)
    c = check("What time does ICU visiting start in the morning?", "Morning visiting starts at 11 am.", [ICU])
    assert c.passed and not c.strict_passed      # the strict variant wants every time on the line


def test_times_without_daily_pass():  # Review Focus 1
    assert check("When can I visit the ICU?", "11 am to 1 pm and 5 pm to 7 pm.", [ICU]).passed


def test_a_price_question_needs_a_price():
    q = "How much is car parking for 2 hours on a weekday?"
    assert check(q, "₹40 for the first 2 hours.", [PARKING]).passed
    assert check(q, "Parking is charged by the hour.", [PARKING]).reason == "missing:money"


def test_an_extension_without_the_prefix_counts():  # Review Focus 3 (q-129)
    q = "What is the pediatric ward desk extension?"
    assert check(q, "The extension is 2171.", [DIRECTORY]).passed
    assert check(q, "Call the pediatric ward desk.", [DIRECTORY]).reason == "missing:extension"


def test_nothing_to_judge_passes():
    assert check("Which floor is cardiology on?", "The first floor.", [DIRECTORY]).passed
    assert check("When is the camp held?", "Saturday.", ["Unrelated text about parking."]).passed


def test_strip_type_removes_every_detail_of_one_type():
    assert details(strip_type("First Saturday, 10 am to 3 pm.", "time")).get("time") is None
    assert details(strip_type("First Saturday, 10 am to 3 pm.", "time"))["day"] == {"first saturday"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/weir && uv run pytest tests/test_router_coverage.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'weir.router.coverage'`

- [ ] **Step 3: Write the module**

```python
# services/weir/src/weir/router/coverage.py
"""Answer coverage check (D79): does the answer give the kind of detail the question asks for?

Grounding checks that an answer's words come from the source; it can't see what the answer leaves out. Asked
when the blood donation camp is held, the small model said "the first Saturday of every month" and dropped
"10 am to 3 pm" (q-036). This check maps the question to the detail types it asks for, finds the source line
that best matches the question, and fails when that line has a detail of a wanted type and the answer has
none of that type. One detail per type is enough (type coverage): a morning-only question answered with the
morning time passes. `strict_passed` (every detail) is reported for comparison only.
"""
import re
from dataclasses import dataclass

from .grounding import WORD, content_words

_NUM = r"\d[\d,]*"
PATTERNS: dict[str, re.Pattern[str]] = {
    "time": re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)(?![a-z])|\bnoon\b|\bmidnight\b"
                       r"|\b24\s?(?:hours|hrs)\b|\b24\s?x\s?7\b|\b24/7\b|\bround the clock\b", re.I),
    "day": re.compile(r"\b(?:(?:first|second|third|fourth|last)\s+)?(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b"
                      r"|\bweekdays?\b|\bweekends?\b", re.I),
    "money": re.compile(rf"₹\s?{_NUM}|\brs\.?\s?{_NUM}|\binr\s?{_NUM}|\bfree of charge\b|\bno charge\b", re.I),
    "extension": re.compile(r"\b(?:ext\.?|extension)\s*(?:no\.?|number|is)?\s*:?\s*(\d{3,5})\b", re.I),
    "quantity": re.compile(r"\b\d+\s?(?:hours?|hrs?|minutes?|mins?|days?|weeks?|months?|years?|visitors?"
                           r"|people|persons?|beds?)\b", re.I),
}
_BARE_NUMBER = re.compile(r"\b\d{3,5}\b")      # answer side only: "the extension is 2171" (Review Focus 3)

# Question wording -> the detail types it asks for (word-boundary, case-insensitive).
TRIGGERS: list[tuple[re.Pattern[str], frozenset[str]]] = [
    (re.compile(r"\bwhen\b|\bheld\b|\bschedule\b", re.I), frozenset({"time", "day"})),
    (re.compile(r"\bwhat time\b|\btimings?\b|\bhours\b|\bopens?\b|\bcloses?\b|\bstarts?\b|\bends?\b", re.I),
     frozenset({"time"})),
    (re.compile(r"\bwhich days?\b|\bwhat days?\b", re.I), frozenset({"day"})),
    (re.compile(r"\bhow much\b|\bcosts?\b|\bfees?\b|\bcharges?\b|\bprices?\b|\brates?\b|\bpay\b", re.I),
     frozenset({"money"})),
    (re.compile(r"\bextension\b|\bext\b|\bphone\b|\bnumber to call\b|\bcontact\b|\bdial\b", re.I),
     frozenset({"extension"})),
    (re.compile(r"\bhow long\b|\bhow many\b|\bduration\b", re.I), frozenset({"quantity"})),
]
_SPLIT = re.compile(r"\n+|(?<=[.!?])\s+")


@dataclass(frozen=True)
class Coverage:
    passed: bool
    reason: str | None          # "missing:time" or "missing:money,time"; None when passed
    missing: tuple[str, ...]
    strict_passed: bool         # every required detail on the passage is in the answer (comparison only)


def _canonical(kind: str, raw: str, match: re.Match[str]) -> str:
    s = raw.lower().strip()
    if kind == "time":
        s = re.sub(r"[\s.]", "", s).replace(":00", "")
        return {"roundtheclock": "24hours", "24x7": "24hours", "24/7": "24hours", "24hrs": "24hours"}.get(s, s)
    if kind == "day":
        return re.sub(r"s$", "", re.sub(r"\s+", " ", s)).replace("weekday", "weekday").replace("weekend", "weekend")
    if kind == "money":
        digits = re.sub(r"\D", "", s)
        return digits or "free"
    if kind == "extension":
        return match.group(1)
    return re.sub(r"s$", "", re.sub(r"\s+", " ", s))           # quantity: "2 hours" -> "2 hour"


def details(text: str, lenient: bool = False) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            found.setdefault(kind, set()).add(_canonical(kind, m.group(0), m))
    if lenient:
        found.setdefault("extension", set()).update(_BARE_NUMBER.findall(text))
        if not found["extension"]:
            del found["extension"]
    return found


def required_types(question: str) -> frozenset[str]:
    wanted: set[str] = set()
    for pattern, kinds in TRIGGERS:
        if pattern.search(question):
            wanted |= kinds
    return frozenset(wanted)


def passage(question: str, chunk_texts: list[str]) -> list[str]:
    asked = set(content_words(question))
    scored = []
    for text in chunk_texts:
        for line in _SPLIT.split(text):
            line = line.strip()
            if line:
                scored.append((len(asked & set(WORD.findall(line.lower()))), line))
    best = max((s for s, _ in scored), default=0)
    return [line for s, line in scored if s == best] if best > 0 else []


def strip_type(text: str, kind: str) -> str:
    return re.sub(r"\s{2,}", " ", PATTERNS[kind].sub("", text)).strip()


def check(question: str, answer: str, chunk_texts: list[str]) -> Coverage:
    wanted = required_types(question)
    lines = passage(question, chunk_texts) if wanted else []
    source = details(" ".join(lines))
    given = details(answer, lenient=True)
    asked = sorted(k for k in wanted if source.get(k))
    missing = tuple(k for k in asked if not given.get(k))
    strict = all(source[k] <= given.get(k, set()) for k in asked)
    return Coverage(not missing, f"missing:{','.join(missing)}" if missing else None, missing, strict)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/weir && uv run pytest tests/test_router_coverage.py -q`
Expected: PASS (12 passed). If a canonical-form assertion fails, fix `_canonical`; don't loosen the test.

- [ ] **Step 5: Commit**

```bash
git add services/weir/src/weir/router/coverage.py services/weir/tests/test_router_coverage.py
git commit -m "feat(router): rule-based answer coverage check (D79)"
```

### Task 2: Escalate on coverage, log and count it

**Files:**
- Modify: `services/weir/src/weir/config.py` (`RouterConfig`)
- Modify: `configs/weir.yaml` (router section)
- Modify: `services/weir/src/weir/pipeline.py` (`Outcome`, `_answer`, `handle`, new `_cover`)
- Modify: `services/weir/src/weir/metrics/logger.py` (`RequestLogRow`)
- Modify: `services/weir/src/weir/metrics/prometheus.py` (counter)
- Create: `db/migrations/006_coverage.sql`
- Test: `services/weir/tests/test_pipeline.py`, `services/weir/tests/test_prometheus_metrics.py`, `services/weir/tests/test_migrate.py`

**Interfaces:**
- **Consumes:** `weir.router.coverage.check`, `Coverage` (Task 1).
- **Produces:**
  - `RouterConfig.coverage_check: bool = True`
  - `RequestLogRow.coverage_passed: bool | None`, `coverage_reason: str | None`, `escalated_for: str | None` (`"grounding"` or `"coverage"`)
  - `Outcome.coverage: Coverage | None`
  - metric `weir_coverage_failures_total{tier}`

- [ ] **Step 1: Write the failing tests** (append to `services/weir/tests/test_pipeline.py`)

```python
# --- D79: coverage check. A small answer missing the asked-for kind of detail escalates once.

def camp_rag(small_answer="It is held on the first Saturday of every month [c1].",
             large_answer="First Saturday of every month, 10 am to 3 pm [c1]."):
    """A RAG client whose chunk holds q-036's source line; small and large answer differently."""
    client = fake_rag()
    orig_retrieve, orig_generate = client.retrieve, client.generate

    async def retrieve(*a, **kw):
        r = await orig_retrieve(*a, **kw)
        chunk = r.chunks[0].model_copy(update={"text": "The blood donation camp is held on the first Saturday of "
                                                        "every month, 10 am to 3 pm, in the lobby."})
        return r.model_copy(update={"chunks": [chunk], "top_score": 0.95})

    async def generate(query, namespace, chunks, model):
        g = await orig_generate(query, namespace, chunks, model)
        text = small_answer if "20b" in model else large_answer
        return g.model_copy(update={"answer": text, "cited_chunk_ids": [chunks[0].id]})
    client.retrieve, client.generate = retrieve, generate
    return client


async def test_a_small_answer_missing_the_time_escalates_once():
    h = harness(camp_rag(), **ROUTER_ON)
    resp = await h.p.handle(ask("When is the blood donation camp held?"))
    [row] = h.sink.rows
    assert resp.meta.escalated and "10 am" in resp.answer
    assert row.escalated_for == "coverage" and row.coverage_passed is True and row.model_calls == 2


async def test_coverage_off_never_escalates_and_logs_nothing():  # Review Focus 5
    h = harness(camp_rag(), **ROUTER_ON)
    h.cfg.router.coverage_check = False
    resp = await h.p.handle(ask("When is the blood donation camp held?"))
    [row] = h.sink.rows
    assert not resp.meta.escalated and row.coverage_passed is None and row.escalated_for is None


async def test_grounding_failure_is_named_first():  # Review Focus 4
    h = harness(camp_rag(small_answer="It is held on Saturdays."), **ROUTER_ON)   # no citation: fails grounding
    await h.p.handle(ask("When is the blood donation camp held?"))
    assert h.sink.rows[0].escalated_for == "grounding"


async def test_a_large_answer_missing_detail_is_logged_not_recalled():
    h = harness(camp_rag(large_answer="It is held on the first Saturday [c1]."), **{**ROUTER_ON, "kill_switch__force_large": True})
    resp = await h.p.handle(ask("When is the blood donation camp held?"))
    [row] = h.sink.rows
    assert not resp.meta.escalated and row.model_calls == 1
    assert row.coverage_passed is False and row.coverage_reason == "missing:time"
```

Before writing these, read the top of `test_pipeline.py` and use the file's existing names. Check the name of the router-on overrides (`ROUTER_ON`) and how `fake_rag`'s `generate` is called; adapt the helper to match. Make sure the question routes small: short, with a high top score. If the router keeps it large, set `features`-relevant values (`top_score=0.95`, short query) as above, or pass `options=QueryOptions(force_model=None)`.

Append to `services/weir/tests/test_prometheus_metrics.py`:

```python
def test_coverage_failures_are_counted_by_tier():
    registry, metrics = fresh()   # use this file's existing helper names
    metrics.record(row(escalated=True, escalated_for="coverage", coverage_passed=True))
    metrics.record(row(coverage_passed=False, coverage_reason="missing:time"))
    assert value(registry, "weir_coverage_failures_total", tier="small") == 1
    assert value(registry, "weir_coverage_failures_total", tier="large") == 1
```

In `services/weir/tests/test_migrate.py`, add `"006_coverage.sql"` to the expected list after `"005_shed_status.sql"`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/weir && uv run pytest tests/test_pipeline.py tests/test_prometheus_metrics.py tests/test_migrate.py -q -k "coverage or grounding_failure_is_named or migrations or applies_all"`
Expected: FAIL (unknown fields `escalated_for` / `coverage_passed`, missing migration).

- [ ] **Step 3: Implement**

`services/weir/src/weir/config.py`, in `RouterConfig` after `reasoning_words`:

```python
    coverage_check: bool = True             # escalate small answers missing the asked-for detail type (D79)
```

`configs/weir.yaml`, under `router:` after the tuned thresholds:

```yaml
  coverage_check: true      # escalate a small answer that lacks the kind of detail asked for (D79); false = off
```

`db/migrations/006_coverage.sql`:

```sql
-- D79: the answer coverage check's result, and why a small answer was escalated.
alter table weir.request_log
  add column coverage_passed boolean,
  add column coverage_reason text,
  add column escalated_for text;
```

`services/weir/src/weir/metrics/logger.py`: add after `grounding_overlap`:

```python
    coverage_passed: bool | None = None
    coverage_reason: str | None = None
    escalated_for: str | None = None     # "grounding" or "coverage": why a small answer went to the large model
```

`services/weir/src/weir/pipeline.py`:
- import: `from .router.coverage import Coverage, check as check_coverage`
- `Outcome` gains a last field: `coverage: Coverage | None = None`
- in `_answer`, replace the block from `grounding = self._ground(generated, retrieved)` to the `return`:

```python
        grounding = self._ground(generated, retrieved)
        coverage = self._cover(req, generated, retrieved)
        escalated = False
        weak = "grounding" if not grounding.passed else ("coverage" if coverage and not coverage.passed else None)
        if (adaptive and tier == "small" and weak and generated.finish_reason != "skipped"
                and row.model_calls < cap):
            row.escalated_for = weak
            try:
                large = await self._call(req, retrieved, "large", row)
            except RagError as e:
                log.warning("escalation to the large model failed (%s); returning the small answer", e.kind)
                row.error_detail = f"escalation_failed:{e.kind}"
            else:
                billed.append((self._cfg.model_for("large"), large))
                generated, grounding, escalated = large, self._ground(large, retrieved), True
                coverage = self._cover(req, large, retrieved)
        return Outcome(generated, grounding, billed, escalated, fallback, "large" if escalated else tier, coverage)
```

- add the method next to `_ground`:

```python
    def _cover(self, req: QueryRequest, generated: GenerateResult, retrieved: RetrieveResult) -> Coverage | None:
        if not self._cfg.router.coverage_check or generated.finish_reason == "skipped":
            return None
        cited = [c.text for c in retrieved.chunks if c.id in set(generated.cited_chunk_ids)]
        return check_coverage(req.query, generated.answer, cited) if cited else None
```

- in `handle`, after `row.grounding_overlap = outcome.grounding.overlap`:

```python
        if outcome.coverage is not None:
            row.coverage_passed, row.coverage_reason = outcome.coverage.passed, outcome.coverage.reason
```

`services/weir/src/weir/metrics/prometheus.py`: in `__init__` next to the grounding counter:

```python
        self.coverage_failures = Counter("weir_coverage_failures", "Answers missing the asked-for detail type (D79)",
                                         ["tier"], registry=registry)
        for tier in ("small", "large"):
            self.coverage_failures.labels(tier)
```

In `record`, at the end:

```python
        if row.escalated_for == "coverage":
            self.coverage_failures.labels("small").inc()
        if row.coverage_passed is False:
            self.coverage_failures.labels("large" if row.escalated or row.route == "large" else "small").inc()
```

- [ ] **Step 4: Run the whole Weir suite**

Run: `cd services/weir && uv run pytest -q` (Postgres must be up: `docker compose up -d postgres`).
Expected: PASS, about 300 + 12 + 6 tests.

- [ ] **Step 5: Commit**

```bash
git add configs/weir.yaml db/migrations/006_coverage.sql services/weir
git commit -m "feat: escalate small answers that miss the asked-for detail; log and count coverage (D79)"
```

### Task 3: Offline scoring of saved answers (`weir_eval coverage`)

**Files:**
- Create: `eval/src/weir_eval/coverage.py`
- Modify: `eval/src/weir_eval/cli.py` (command `coverage`)
- Test: `eval/tests/test_coverage_eval.py`

**Interfaces:**
- **Consumes:** `weir.router.coverage.check`, `details`, `passage`, `required_types`, `strip_type` (Task 1); `weir.rag.adapter.RagClient.retrieve(query, namespace, k)` and `RetrievedChunk.doc_id` and `.text` (existing).
- **Produces:**
  - `async coverage_rows(records: list[dict], queries: dict, rag, k: int) -> tuple[list[dict], list[dict]]`: per-answer rows `{id, passed, reason, strict_passed, required, passage}` and synthetic rows `{id, type, flagged}`
  - `summarize(rows, synthetic, records) -> dict`
  - files `<report>/coverage.jsonl`, `<report>/coverage-synthetic.jsonl`, `<report>/coverage-summary.json`

- [ ] **Step 1: Write the failing test**

```python
# eval/tests/test_coverage_eval.py
from types import SimpleNamespace

from weir_eval.coverage import coverage_rows, summarize

CAMP = "The blood donation camp is held on the first Saturday of every month, 10 am to 3 pm, in the lobby."


class FakeRag:
    async def retrieve(self, query, namespace, k):
        return SimpleNamespace(chunks=[SimpleNamespace(doc_id="pub-blood-bank", text=CAMP),
                                       SimpleNamespace(doc_id="pub-other", text="Parking costs ₹40.")])


def rec(id_, answer, judge=5, facts=1.0):
    return {"id": id_, "status_code": 200, "query": "When is the blood donation camp held?",
            "namespace": "weir-general/en/public", "answer": answer, "sources": [{"id": "pub-blood-bank"}],
            "judge_score": judge, "fact_score": facts}


async def test_flags_real_omissions_and_builds_synthetic_ones():
    records = [rec("q-036", "The first Saturday of every month.", judge=3, facts=0.5),
               rec("q-037", "The first Saturday of every month, 10 am to 3 pm.")]
    rows, synthetic = await coverage_rows(records, {}, FakeRag(), 4)
    assert [(r["id"], r["passed"], r["reason"]) for r in rows] == [("q-036", False, "missing:time"), ("q-037", True, None)]
    assert {(s["id"], s["type"], s["flagged"]) for s in synthetic} == {("q-037", "time", True), ("q-037", "day", True)}
    summary = summarize(rows, synthetic, records)
    assert summary["flagged"] == ["q-036"] and summary["synthetic_recall"] == 1.0
    assert summary["false_flag_rate"] == 0.0 and summary["good_answers"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd eval && uv run pytest tests/test_coverage_eval.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'weir_eval.coverage'`

- [ ] **Step 3: Implement**

```python
# eval/src/weir_eval/coverage.py
"""Offline scoring of saved answers with Weir's coverage check (D79), plus synthetic omissions.

For each answered question, re-fetch its chunks from hospital-rag (retrieval only, no model), keep the ones from
the documents the answer cited, and run the check. Synthetic omissions: every good answer (judge 5, full facts)
that passes is copied once per required detail type it contains, with every detail of that type deleted; the
check should flag each copy.
"""
from weir.router.coverage import check, details, passage, required_types, strip_type


async def coverage_rows(records: list[dict], queries: dict, rag, k: int) -> tuple[list[dict], list[dict]]:
    rows, synthetic = [], []
    for r in records:
        if r.get("status_code") != 200:
            continue
        retrieved = await rag.retrieve(r["query"], r["namespace"], k)
        cited = {s["id"] for s in (r.get("sources") or [])}
        texts = [c.text for c in retrieved.chunks if c.doc_id in cited] or [c.text for c in retrieved.chunks]
        cov = check(r["query"], r["answer"], texts)
        lines = passage(r["query"], texts)
        rows.append({"id": r["id"], "passed": cov.passed, "reason": cov.reason, "strict_passed": cov.strict_passed,
                     "required": sorted(required_types(r["query"])), "passage": lines})
        good = r.get("judge_score") == 5 and r.get("fact_score") == 1.0
        if good and cov.passed:
            source, given = details(" ".join(lines)), details(r["answer"])
            for kind in sorted(required_types(r["query"])):
                if source.get(kind) and given.get(kind):
                    stripped = check(r["query"], strip_type(r["answer"], kind), texts)
                    synthetic.append({"id": r["id"], "type": kind, "flagged": not stripped.passed})
    return rows, synthetic


def summarize(rows: list[dict], synthetic: list[dict], records: list[dict]) -> dict:
    by_id = {r["id"]: r for r in records}
    good = [x for x in rows if by_id[x["id"]].get("judge_score") == 5 and by_id[x["id"]].get("fact_score") == 1.0]
    return {
        "answers": len(rows),
        "flagged": [x["id"] for x in rows if not x["passed"]],
        "flagged_strict": [x["id"] for x in rows if not x["strict_passed"]],
        "good_answers": len(good),
        "false_flag_rate": sum(not x["passed"] for x in good) / len(good) if good else 0.0,
        "false_flag_rate_strict": sum(not x["strict_passed"] for x in good) / len(good) if good else 0.0,
        "synthetic": len(synthetic),
        "synthetic_recall": sum(s["flagged"] for s in synthetic) / len(synthetic) if synthetic else None,
        "synthetic_missed": [f'{s["id"]}:{s["type"]}' for s in synthetic if not s["flagged"]],
    }
```

In `eval/src/weir_eval/cli.py`, add near `_features`:

```python
async def _coverage(args: argparse.Namespace) -> int:
    from weir.config import load_config
    from weir.rag.adapter import RagClient

    from .coverage import coverage_rows, summarize

    cfg = load_config(CONFIGS_DIR / "weir.yaml")
    report = Path(args.report_dir)
    records = _load_results(report)
    rag = RagClient(args.rag_url, cfg.rag.timeout_seconds)
    try:
        rows, synthetic = await coverage_rows(records, {}, rag, cfg.rag.retrieve_k)
    finally:
        await rag.aclose()
    (report / "coverage.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                           encoding="utf-8")
    (report / "coverage-synthetic.jsonl").write_text("".join(json.dumps(s) + "\n" for s in synthetic), encoding="utf-8")
    summary = summarize(rows, synthetic, records)
    (report / "coverage-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0
```

Register it next to the `features` parser:

```python
    cov = sub.add_parser("coverage", help="score a report's saved answers with the coverage check (retrieval only)")
    cov.add_argument("report_dir")
    cov.add_argument("--rag-url", default=os.environ.get("RAG_URL", "http://127.0.0.1:8001"))
    cov.set_defaults(func=lambda a: asyncio.run(_coverage(a)))
```

- [ ] **Step 4: Run the eval suite**

Run: `cd eval && uv run pytest -q`
Expected: PASS (161 + 1).

- [ ] **Step 5: Commit**

```bash
git add eval/src/weir_eval/coverage.py eval/src/weir_eval/cli.py eval/tests/test_coverage_eval.py
git commit -m "feat(eval): score saved answers with the coverage check, plus synthetic omissions"
```

### Task 4: `simulate --coverage`

**Files:**
- Modify: `eval/src/weir_eval/simulate.py` (`Row`, `build_rows`, `small_passes`, `simulate`, `run_grid`)
- Modify: `eval/src/weir_eval/cli.py` (`cmd_simulate` arguments)
- Test: `eval/tests/test_simulate.py`

**Interfaces:**
- **Consumes:** `coverage.jsonl` rows `{id, passed, strict_passed}` (Task 3).
- **Produces:**
  - `Row.small_coverage: bool | None = None`
  - `build_rows(..., coverage: dict[str, dict] | None = None, coverage_mode: str = "type")`
  - `simulate()` and `run_grid()` unchanged in signature: coverage lives on the rows
  - CLI flags `--coverage PATH`, `--coverage-mode type|strict`

- [ ] **Step 1: Write the failing test** (append to `eval/tests/test_simulate.py`; reuse its row helper)

```python
def test_a_coverage_failure_escalates_in_simulation():
    from weir_eval.simulate import Row, simulate
    base = make_row()                       # the file's existing helper for a small-routed passing row
    flagged = Row(**{**base.__dict__, "small_coverage": False})
    [kept] = simulate([base], SETTING, CFG)
    [esc] = simulate([flagged], SETTING, CFG)
    assert not kept["escalated"] and esc["escalated"]
    assert esc["cost"] == base.small_cost + base.base_cost and esc["judge"] == base.base_judge
```

Read `eval/tests/test_simulate.py` first. Use its existing names for the row builder, setting and config. If it has no helper, build a `Row` the way its existing tests do.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd eval && uv run pytest tests/test_simulate.py -q`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'small_coverage'`

- [ ] **Step 3: Implement**

In `Row`, add a last field:

```python
    small_coverage: bool | None = None  # D79: False -> the coverage check flags the small answer (escalates)
```

In `small_passes`:

```python
def small_passes(row: Row, min_overlap: float) -> bool:
    return (row.small_judge is not None and row.small_reason in (None, "low_overlap")
            and row.small_overlap is not None and row.small_overlap >= min_overlap
            and row.small_coverage is not False)
```

In `build_rows`, add parameters `coverage: dict[str, dict] | None = None, coverage_mode: str = "type"` and set on each `Row(...)`:

```python
            small_coverage=(None if not coverage or q.id not in coverage
                            else coverage[q.id]["passed" if coverage_mode == "type" else "strict_passed"]),
```

In `cli.py`, in the `simulate` parser:

```python
    sim.add_argument("--coverage", help="coverage.jsonl from `weir_eval coverage` on the small trial (D79)")
    sim.add_argument("--coverage-mode", choices=["type", "strict"], default="type")
```

In `cmd_simulate`, pass `coverage=_first_by_id(_read_jsonl(Path(args.coverage))) if args.coverage else None, coverage_mode=args.coverage_mode` to `build_rows`. Add `"coverage": args.coverage_mode if args.coverage else None` to `header`.

- [ ] **Step 4: Run the eval suite**

Run: `cd eval && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/src/weir_eval/simulate.py eval/src/weir_eval/cli.py eval/tests/test_simulate.py
git commit -m "feat(eval): simulate the router with the coverage check (--coverage)"
```

### Task 5: Offline evaluation and the decision

No product code changes unless the evaluation exposes an eval-set bug: fix it in the data and record it, never tune around it.

- [ ] **Step 1: Bring up retrieval in stub mode** (no LLM calls):

```bash
docker compose up -d postgres
LLM_MODE=stub docker compose up -d --build --no-deps migrate hospital-rag
LLM_MODE=stub docker compose run --rm --no-deps migrate
curl -s http://127.0.0.1:8001/healthz        # expect "llm_mode":"stub"
```

- [ ] **Step 2: Score both saved reports:**

```bash
cd eval
uv run python -m weir_eval coverage reports/20261004T171944Z-small_only-all
uv run python -m weir_eval coverage reports/baseline-v3
```

**Check against spec §1:**
- q-036 is in `flagged` for the small report
- `synthetic_recall` ≥ 0.90
- `false_flag_rate` ≤ 0.05 on the small report

**Read every flagged good answer by hand.** For each false flag, decide whether it is:
- (a) a rule gap (fix the rule and add a unit test in Task 1's file), or
- (b) a correct catch the judge missed (record it).

Re-run after any fix.

- [ ] **Step 3: Simulate:**

```bash
uv run python -m weir_eval simulate --small reports/20261004T171944Z-small_only-all \
  --coverage reports/20261004T171944Z-small_only-all/coverage.jsonl
uv run python -m weir_eval simulate --small reports/20261004T171944Z-small_only-all \
  --coverage reports/20261004T171944Z-small_only-all/coverage.jsonl --coverage-mode strict
```

**Record:** the cheapest strict-bar setting on tune, its saving, its share routed small, its escalation rate, and its holdout result, for both modes. Compare with today's −6% and the 38% loose option.

- [ ] **Step 4: Decide.**
- **Pass:** the type mode meets the bar on tune and holdout and saves clearly more than today. Put the chosen thresholds in `configs/weir.yaml` (router section) and continue to Task 6.
- **Otherwise:** keep the current thresholds, keep `coverage_check: true` as a safety net, skip Task 6, and go to Task 7 with the negative result.

- [ ] **Step 5: Commit the evaluation artefacts** (`coverage*.json*`, the two simulate report folders, any config change):

```bash
git add eval/reports configs/weir.yaml
git commit -m "eval: coverage check offline results and router re-tune (D79, D80)"
```

### Task 6: Live confirmation with real models (approved quota)

Run only if Task 5 passed.

- [ ] **Step 1: Build and start in real mode.** This is the one time Groq is used:

```bash
docker compose build weir hospital-rag
LLM_MODE=groq docker compose up -d --no-deps --force-recreate hospital-rag
curl -s http://127.0.0.1:8001/healthz        # expect "llm_mode":"groq"
```

- [ ] **Step 2: Same-day baseline**, about 40 min at 15 s spacing:

```bash
WEIR_ABLATION=baseline LLM_MODE=groq docker compose up -d --no-deps --force-recreate weir
cd eval && uv run --env-file ../.env python -m weir_eval run --config baseline --split all --no-judge --weir-url http://127.0.0.1:8000
```

- [ ] **Step 3: Full Weir with the new setting**, cold, cache purged:

```bash
WEIR_ABLATION=full LLM_MODE=groq docker compose up -d --no-deps --force-recreate weir
cd eval && uv run --env-file ../.env python -m weir_eval run --config full --split all --no-judge --purge-cache --weir-url http://127.0.0.1:8000
```

- [ ] **Step 4: Judge both and gate:**

```bash
uv run --env-file ../.env python -m weir_eval rejudge reports/<baseline-run>
uv run --env-file ../.env python -m weir_eval rejudge reports/<full-run>
uv run --env-file ../.env python -m weir_eval gate reports/<full-run>    # check gate's real flags with --help first
```

**Pass:** the strict bar holds against the same-day baseline, with 0 wrong cache hits. Read every answer that scored lower than the baseline's by hand.

- [ ] **Step 5: Return hospital-rag to stub mode and commit the reports:**

```bash
LLM_MODE=stub docker compose up -d --no-deps --force-recreate hospital-rag
git add eval/reports
git commit -m "eval: live confirmation of the coverage check and router setting (D80)"
```

If the live run fails the bar, restore the previous thresholds in `configs/weir.yaml`, record why, and continue to Task 7.

### Task 7: Docs and wrap-up

**Files:**
- Create: `docs/results/coverage-2026-10-12.md` (the offline and live numbers; the false flags read by hand)
- Modify:
  - `docs/decisions.md` (D79 check design; D80 router setting or keep)
  - `docs/progress.md`
  - `docs/backlog.md`
  - `README.md` (Router section, results, config table, test counts, `D0–D80`)
  - `docs/writeup.md` (router paragraph, results, limitations, talking points)
- Republish the case study artifact (`https://claude.ai/artifact/Qz1NXbjKbN3NhgN8rM2nXB`) from the scratchpad source.

- [ ] **Step 1: Write the results doc and update the docs** listed above, with every number traced to a report folder.
- [ ] **Step 2: Run all suites:** weir, hospital-rag, eval, launcher (`uv run --with pytest pytest tests/test_demo.py -q` at the repo root).
- [ ] **Step 3: Commit, push to main, and check CI:**

```bash
git add README.md docs
git commit -m "docs: coverage check results (D79, D80)"
git push origin <branch>:main
```

- [ ] **Step 4: Republish the case study artifact,** then stop the containers (`docker compose stop`).
