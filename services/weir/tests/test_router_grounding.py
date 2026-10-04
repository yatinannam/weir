import pytest

from weir.rag.adapter import GenerateResult, RetrievedChunk
from weir.router.grounding import Grounding, check, content_words, overlap

CHUNKS = [
    RetrievedChunk(id="a#0", doc_id="a", title="ICU", text="ICU visiting begins at 11 am.", score=0.9, token_count=8),
    RetrievedChunk(id="b#0", doc_id="b", title="Parking", text="Parking: 50 rupees per day.", score=0.8,
                   token_count=7),
]


def gen(**over):
    base = dict(answer="ICU visiting starts at 11 am 【c1】.", cited_chunk_ids=["a#0"], invalid_citations=0,
                not_found=False, finish_reason="stop", tokens_in=100, tokens_out=20, model="m", prompt_version="p1",
                latency_ms=5)
    return GenerateResult(**{**base, **over})


def test_grounded_answer_passes_with_measured_overlap():
    # content words {icu, visiting, starts, 11}; the chunk has icu, visiting, 11 -> 3/4
    assert check(gen(), CHUNKS, 0.5) == Grounding(True, None, 0.75)


def test_low_overlap_fails_but_keeps_the_measurement():
    assert check(gen(), CHUNKS, 0.8) == Grounding(False, "low_overlap", 0.75)


@pytest.mark.parametrize(("over", "reason"), [
    ({"not_found": True, "answer": "NOT_FOUND", "cited_chunk_ids": []}, "not_found"),
    ({"finish_reason": "length"}, "finish_reason:length"),
    ({"finish_reason": "skipped"}, "finish_reason:skipped"),
    ({"cited_chunk_ids": []}, "no_citations"),
    ({"invalid_citations": 1}, "invalid_citations"),
    ({"answer": "ICU visiting starts at 11 am [c1]. Parking: NOT_FOUND"}, "partial_answer"),
    ({"cited_chunk_ids": ["zz#9"]}, "unknown_citations"),
])
def test_each_failure_rule(over, reason):
    result = check(gen(**over), CHUNKS, 0.5)
    assert result.passed is False and result.reason == reason


def test_first_failing_rule_wins():
    assert check(gen(finish_reason="length", cited_chunk_ids=[]), CHUNKS, 0.5).reason == "finish_reason:length"


def test_answer_without_content_words_is_empty_answer():  # Review Focus 4: no division by zero
    result = check(gen(answer="It is [c1]."), CHUNKS, 0.5)
    assert result == Grounding(False, "empty_answer", None)


def test_citation_markers_and_stopwords_are_not_content_words():
    assert content_words("Parking costs 50 [c1] 【c2†L3-L5】 per the [c1, c2] page.") == ["parking", "costs", "50",
                                                                                     "page"]


def test_overlap_uses_only_the_cited_chunks():
    # cites the parking chunk only, so the ICU words are missing
    result = check(gen(answer="Parking is 50 rupees [c2].", cited_chunk_ids=["b#0"]), CHUNKS, 0.5)
    assert result.passed and result.overlap == 1.0
    assert check(gen(cited_chunk_ids=["b#0"]), CHUNKS, 0.5).reason == "low_overlap"


def test_overlap_counts_each_word_once():
    assert overlap("icu icu icu parking", "icu") == 0.5
    assert overlap("the and of", "anything") is None
