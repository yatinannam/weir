import pytest

from weir.config import load_config
from weir.router.features import Features
from weir.router.rules import ROUTER_DECISIONS, route

from .conftest import CONFIGS


def cfg(**router):
    c = load_config(CONFIGS / "weir.yaml")
    for k, v in {"enabled": True, "short_query_tokens": 20, "high_confidence": 0.75, "low_confidence": 0.40,
                 **router}.items():
        setattr(c.router, k, v)
    return c


def feats(**over):
    base = dict(tokens=8, has_reasoning_words=False, num_questions=1, top_score=0.9, score_gap=0.1,
                context_tokens=500, is_clinical=False, forced_tier=None)
    return Features(**{**base, **over})


def test_simple_question_goes_small():
    assert route(feats(), cfg()) == ("small", "simple")


@pytest.mark.parametrize(("over", "expected"), [
    ({"tokens": 21}, ("large", "default_large")),
    ({"has_reasoning_words": True}, ("large", "default_large")),
    ({"num_questions": 2}, ("large", "default_large")),
    ({"top_score": 0.74}, ("large", "default_large")),
    ({"top_score": 0.39}, ("large", "weak_retrieval")),
    ({"is_clinical": True}, ("large", "clinical")),
])
def test_each_large_branch(over, expected):
    assert route(feats(**over), cfg()) == expected


def test_boundaries_are_inclusive():
    assert route(feats(tokens=20, top_score=0.75), cfg()) == ("small", "simple")
    assert route(feats(top_score=0.40), cfg(high_confidence=0.40)) == ("small", "simple")  # not weak at exactly low


def test_order_kill_switch_then_force_then_disabled():
    c = cfg(enabled=False)
    c.kill_switch.force_large = True
    assert route(feats(forced_tier="small"), c) == ("large", "kill_switch")
    c.kill_switch.force_large = False
    assert route(feats(forced_tier="small", is_clinical=True), c) == ("small", "force_model")
    assert route(feats(), c) == ("large", "router_disabled")
    c.router.default_tier = "small"
    assert route(feats(is_clinical=True), c) == ("small", "router_disabled")


def test_clinical_beats_weak_retrieval_and_simple():
    assert route(feats(is_clinical=True, top_score=0.1), cfg()) == ("large", "clinical")


def test_router_decisions_exclude_forced_and_disabled():
    assert ROUTER_DECISIONS == {"clinical", "weak_retrieval", "simple", "default_large"}
