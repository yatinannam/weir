import pytest

from weir.cache.guards import BypassRules
from weir.config import load_config
from weir.rag.adapter import RetrieveResult
from weir.router.features import FeatureExtractor, Features, count_questions

from .conftest import CONFIGS

CFG = load_config(CONFIGS / "weir.yaml")
RETRIEVED = RetrieveResult(chunks=[], top_score=0.82, score_gap=0.11, context_tokens=640, kb_version="v1",
                           latency_ms=3)


def extractor(words=("why", "compare", "pros and cons", "vs")):
    return FeatureExtractor(lambda text: len(text.split()), BypassRules(CFG.bypass), list(words))


def test_extracts_every_feature():
    f = extractor().extract("  When can I   VISIT the ICU? ", RETRIEVED)
    assert f == Features(tokens=6, has_reasoning_words=False, num_questions=1, top_score=0.82, score_gap=0.11,
                         context_tokens=640, is_clinical=False, forced_tier=None)


def test_forced_tier_passes_through():
    assert extractor().extract("q", RETRIEVED, forced_tier="small").forced_tier == "small"


@pytest.mark.parametrize(("query", "expected"), [
    ("Why is the ICU closed on Sundays?", True),
    ("Compare the two parking options", True),
    ("What are the pros and cons of the private ward?", True),
    ("General ward vs private ward price?", True),
    ("Who is Dr Whyte?", False),            # word boundary: "whyte" is not "why"
    ("When can I visit?", False),
])
def test_reasoning_words(query, expected):
    assert extractor().extract(query, RETRIEVED).has_reasoning_words is expected


def test_no_reasoning_words_configured():
    assert extractor(words=()).extract("Why?", RETRIEVED).has_reasoning_words is False


@pytest.mark.parametrize(("query", "expected"), [
    ("When can I visit?", 1),
    ("visiting hours", 1),                                          # no "?" still counts as one
    ("When does it open and when does it close?", 2),
    ("When does it open? And when does it close?", 2),              # "? and when" is not counted twice
    ("What is the MRI price and is parking free?", 2),
    ("Where is it? When is it open? How much is it?", 3),
])
def test_count_questions(query, expected):
    assert count_questions(query) == expected


def test_clinical_uses_the_bypass_keywords():
    assert extractor().extract("What dosage of paracetamol is safe?", RETRIEVED).is_clinical is True
