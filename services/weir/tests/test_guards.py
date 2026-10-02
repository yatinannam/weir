import pytest

from weir.cache.guards import BypassRules, bypass_reason, contains_personal_data, store_block_reason
from weir.config import load_config
from weir.rag.adapter import GenerateResult

from .conftest import CONFIGS

PUBLIC = "weir-general/en/public"


def cfg(**cache):
    c = load_config(CONFIGS / "weir.yaml", CONFIGS / "ablations" / "cache_only.yaml")
    for k, v in cache.items():
        setattr(c.cache, k, v)
    return c


def reason(query="When can I visit?", namespace=PUBLIC, session_id=None, personalized=False, bypass_cache=False, config=None):
    c = config or cfg()
    return bypass_reason(query=query, namespace=namespace, session_id=session_id, personalized=personalized,
                         bypass_cache=bypass_cache, cfg=c, rules=BypassRules(c.bypass))


def test_plain_question_is_cacheable():
    assert reason() is None


def test_reason_order_and_each_rule():
    assert reason(personalized=True, bypass_cache=True) == "personalized"
    assert reason(bypass_cache=True) == "request_option"
    c = cfg(); c.kill_switch.disable_cache = True
    assert reason(config=c) == "kill_switch"
    assert reason(config=cfg(enabled=False)) == "cache_disabled"
    assert reason(namespace="unknown/ns") == "namespace_disabled"
    assert reason(query="What dosage of paracetamol is safe?") == "clinical"
    assert reason(query="Is the pharmacy open now?") == "time_sensitive"
    assert reason(query="what about weekends?", session_id="s1") == "followup"


@pytest.mark.parametrize("query", [
    "What does a diagnosis report cost?", "Who gives the treatment plan?", "Any side effects of the vaccine?",
])
def test_clinical_prefix_terms(query):
    assert reason(query=query) == "clinical"


def test_word_boundaries():
    assert reason(query="Do you know the visiting hours?") is None      # "know" is not "now"
    assert reason(query="Android app for appointments?", session_id="s1") is None  # "and" only as a whole leading word


def test_followup_needs_session_and_short_pronoun_or_prefix():
    assert reason(query="what about weekends?") is None                  # no session: a fresh question
    assert reason(query="is it open?", session_id="s1") == "followup"
    assert reason(query="Is the main pharmacy open on Sundays and public holidays?", session_id="s1") is None


@pytest.mark.parametrize(("text", "personal"), [
    ("Mail me at ravi@example.com", True),
    ("Call 98765 43210", True),
    ("My patient ID is 4471209", True),
    ("When is my appointment?", True),
    ("Call ext. 2140 for cardiology", False),
    ("The deposit is ₹25,000", False),
    ("Visiting is 4 pm to 7 pm", False),
])
def test_personal_data(text, personal):
    assert contains_personal_data(text) is personal


def gen(**over):
    base = dict(answer="Open 4 pm to 7 pm.", cited_chunk_ids=["pub-a#0"], invalid_citations=0, not_found=False,
                finish_reason="stop", tokens_in=500, tokens_out=60, model="m", prompt_version="p1", latency_ms=5)
    return GenerateResult(**{**base, **over})


@pytest.mark.parametrize(("over", "top", "query", "expected"), [
    ({}, 0.9, "When can I visit?", None),
    ({"not_found": True}, 0.9, "q", "not_found"),
    ({"finish_reason": "length"}, 0.9, "q", "finish_reason:length"),
    ({"cited_chunk_ids": []}, 0.9, "q", "no_citations"),
    ({"invalid_citations": 1}, 0.9, "q", "invalid_citations"),
    ({}, 0.1, "q", "low_retrieval"),
    ({"answer": "Call 98765 43210."}, 0.9, "q", "personal_data"),
    ({}, 0.9, "When is my bill due?", "personal_data"),
])
def test_store_block_reason(over, top, query, expected):
    assert store_block_reason(generated=gen(**over), top_score=top, query=query, min_retrieval_score=0.3) == expected


def test_partial_answer_with_stray_not_found_is_not_stored():
    partial = gen(answer="The fee is ₹1,200.\nNOT_FOUND")
    assert store_block_reason(generated=partial, top_score=0.9, query="q", min_retrieval_score=0.3) == "partial_answer"
