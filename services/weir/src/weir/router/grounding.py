"""Rule-based grounding check for generated answers (main spec §7.4, addendum §3.3, decision D6).

An answer passes when it is a finished, cited answer whose content words mostly appear in the cited chunks.
"""
import re
from dataclasses import dataclass

from ..rag.adapter import GenerateResult, RetrievedChunk

# [c1], [c1, c3], [c1 and c2] and gpt-oss's 【c1】 / 【c2†L3-L5】 (same shapes hospital-rag parses).
CITATION = re.compile(r"[\[【]\s*c\d+[^\]】]*[\]】]", re.IGNORECASE)
WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset("""
a an the and or but if then than so of to in on at by for from with without about into over under per via
is are was were be been being am do does did done have has had having can could will would shall should may
might must it its this that these those there here they them their you your we our us he she his her i me my
as also only just very more most less any all each up out what when where which who whom whose why how please
""".split())


@dataclass(frozen=True)
class Grounding:
    passed: bool
    reason: str | None       # the first failing rule; None when passed
    overlap: float | None    # share of the answer's content words found in the cited chunks


def content_words(text: str) -> list[str]:
    return [w for w in WORD.findall(CITATION.sub(" ", text).lower()) if w not in STOPWORDS]


def overlap(answer: str, source_text: str) -> float | None:
    words = set(content_words(answer))
    if not words:
        return None
    source = set(WORD.findall(source_text.lower()))
    return len(words & source) / len(words)


def check(generated: GenerateResult, chunks: list[RetrievedChunk], min_overlap: float) -> Grounding:
    by_id = {c.id: c for c in chunks}
    cited = [by_id.get(i) for i in generated.cited_chunk_ids]
    known = bool(cited) and all(c is not None for c in cited)
    measured = overlap(generated.answer, " ".join(c.text for c in cited)) if known else None
    reason = _first_failure(generated, known, measured, min_overlap)
    return Grounding(reason is None, reason, measured)


def _first_failure(g: GenerateResult, known: bool, measured: float | None, min_overlap: float) -> str | None:
    if g.not_found:
        return "not_found"
    if g.finish_reason != "stop":
        return f"finish_reason:{g.finish_reason}"
    if not g.cited_chunk_ids:
        return "no_citations"
    if g.invalid_citations:
        return "invalid_citations"
    if "not_found" in g.answer.lower():  # answered part, then gave up on the rest (D27)
        return "partial_answer"
    if not known:
        return "unknown_citations"
    if measured is None:
        return "empty_answer"
    if measured < min_overlap:
        return "low_overlap"
    return None
