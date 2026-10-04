from pathlib import Path

import pytest

from weir.config import load_config
from weir.router.features import Features

from weir_eval.simulate import (GRID, Row, Setting, build_rows, choose, meets_bar, metrics, render, run_grid,
                                settings, simulate, small_passes)

from .conftest import q

CFG = load_config(Path(__file__).resolve().parents[2] / "configs" / "weir.yaml")
SET = Setting(short_query_tokens=20, high_confidence=0.75, low_confidence=0.40, min_overlap=0.5)


def feats(**over):
    base = dict(tokens=8, has_reasoning_words=False, num_questions=1, top_score=0.9, score_gap=0.1,
                context_tokens=500, is_clinical=False)
    return Features(**{**base, **over})


def row(id="q-1", split="tune", f=None, base=(5, 1.0, 0.0004), small=(5, 1.0, 0.0002), reason=None, overlap=0.9):
    return Row(id=id, split=split, features=f or feats(), base_judge=base[0], base_facts=base[1], base_cost=base[2],
               small_judge=small[0], small_facts=small[1], small_cost=small[2], small_reason=reason,
               small_overlap=overlap)


@pytest.mark.parametrize(("reason", "overlap", "m", "expected"), [
    (None, 0.9, 0.5, True),
    (None, 0.55, 0.6, False),          # passed live at 0.5 but not at a stricter setting
    ("low_overlap", 0.35, 0.3, True),  # failed live at 0.5 but passes at a looser setting
    ("no_citations", 0.9, 0.3, False), # a rule failure fails at every setting
    ("empty_answer", None, 0.3, False),
])
def test_small_passes(reason, overlap, m, expected):
    assert small_passes(row(reason=reason, overlap=overlap), m) is expected


def test_small_without_usable_answer_never_passes():
    assert small_passes(row(small=(None, None, 0.0)), 0.3) is False


def test_simulate_large_small_and_escalated_paths():
    rows = [row("q-1", f=feats(tokens=99)),                              # long -> large
            row("q-2", small=(4, 1.0, 0.0002)),                          # small, grounded
            row("q-3", reason="low_overlap", overlap=0.2)]               # small, fails -> escalated
    sim = {s["id"]: s for s in simulate(rows, SET, CFG)}
    assert sim["q-1"] == {**sim["q-1"], "tier": "large", "reason": "default_large", "escalated": False,
                          "judge": 5, "cost": 0.0004}
    assert sim["q-2"] == {**sim["q-2"], "tier": "small", "escalated": False, "judge": 4, "cost": 0.0002}
    assert sim["q-3"] == {**sim["q-3"], "tier": "small", "escalated": True, "judge": 5,
                          "cost": pytest.approx(0.0006)}


def test_metrics():
    rows = [row("q-1", f=feats(tokens=99)), row("q-2", small=(4, 1.0, 0.0002)),
            row("q-3", reason="low_overlap", overlap=0.2)]
    m = metrics(simulate(rows, SET, CFG))
    assert m["n"] == 3 and m["share_small"] == pytest.approx(2 / 3) and m["escalation_rate"] == 0.5
    assert m["cost_per_1k"] == pytest.approx(0.0012 / 3 * 1000)
    assert m["base_cost_per_1k"] == pytest.approx(0.0012 / 3 * 1000)
    assert m["judge"] == pytest.approx(14 / 3) and m["base_judge"] == 5
    assert m["small_route_judge"] == 4.5 and m["small_route_base_judge"] == 5


def _m(**over):
    base = dict(n=10, share_small=0.3, escalation_rate=0.1, cost_per_1k=0.08, base_cost_per_1k=0.1, judge=4.85,
                base_judge=4.9, facts=0.98, base_facts=0.98, small_route_judge=4.9, small_route_base_judge=4.9)
    return {**base, **over}


def test_bar_passes_within_limits():
    assert meets_bar(_m()) is True


def test_bar_requires_some_small_routes():  # Review Focus 5
    assert meets_bar(_m(share_small=0.0, small_route_judge=None, small_route_base_judge=None,
                        cost_per_1k=0.1)) is False


@pytest.mark.parametrize("over", [
    {"judge": 4.79},                                   # more than 0.1 below baseline
    {"facts": 0.97},                                   # facts dropped
    {"small_route_judge": 4.8},                        # small route worse than large on the same questions
    {"cost_per_1k": 0.1},                              # no saving
])
def test_bar_fails(over):
    assert meets_bar(_m(**over)) is False


def test_grid_and_choice_pick_the_cheapest_passing_setting():
    assert len(settings()) == len(GRID["short_query_tokens"]) * len(GRID["high_confidence"]) * \
        len(GRID["low_confidence"]) * len(GRID["min_overlap"])
    rows = [row("q-1", f=feats(tokens=10)), row("q-2", f=feats(tokens=30)),
            row("q-3", split="holdout", f=feats(tokens=10))]
    results = run_grid(rows, CFG)
    chosen, m = choose(results)
    assert chosen.short_query_tokens >= 30                       # routing both tune questions small is cheapest
    assert m["tune"]["share_small"] == 1.0 and m["holdout"]["n"] == 1


def test_choice_is_none_when_nothing_passes():
    rows = [row("q-1", small=(2, 0.0, 0.0002))]                 # the small model is bad everywhere
    assert choose(run_grid(rows, CFG)) is None


def test_build_rows_joins_reports_and_requires_judging():
    queries = [q("q-1", "d-1", split="tune"), q("q-2", "d-2", split="holdout")]
    features = {i: {"id": i, "tokens": 5, "has_reasoning_words": False, "num_questions": 1, "top_score": 0.9,
                    "score_gap": 0.1, "context_tokens": 100, "is_clinical": False} for i in ("q-1", "q-2")}
    base = {i: {"id": i, "status_code": 200, "judge_score": 5, "fact_score": 1.0, "meta": {"cost_usd": 0.0004}}
            for i in ("q-1", "q-2")}
    small = {"q-1": {"id": "q-1", "status_code": 200, "judge_score": 4, "fact_score": 1.0,
                     "meta": {"cost_usd": 0.0002, "model": "small-m", "request_id": "r1"}},
             "q-2": {"id": "q-2", "status_code": 200, "judge_score": 5, "fact_score": 1.0,
                     "meta": {"cost_usd": 0.0003, "model": "large-m", "request_id": "r2"}}}  # not the small model
    grounding = {"q-1": {"grounding_reason": None, "grounding_overlap": 0.8}}
    rows = {r.id: r for r in build_rows(queries, features, base, small, grounding, "small-m")}
    assert rows["q-1"].small_judge == 4 and rows["q-1"].small_overlap == 0.8 and rows["q-1"].split == "tune"
    assert rows["q-2"].small_judge is None and rows["q-2"].small_reason == "unavailable"
    base["q-1"]["judge_score"] = None
    with pytest.raises(ValueError, match="rejudge"):
        build_rows(queries, features, base, small, grounding, "small-m")


def test_render_reports_the_choice_or_that_none_passed():
    rows = [row("q-1"), row("q-2", split="holdout")]
    results = run_grid(rows, CFG)
    assert "Chosen setting" in render(choose(results), results, {"baseline": "b", "small": "s"})
    assert "router ships disabled" in render(None, results, {"baseline": "b", "small": "s"})


def test_grid_reaches_strict_cut_offs():  # D37: q-036 (top 0.855) must be keepable off the small route
    assert max(GRID["high_confidence"]) >= 0.95 and min(GRID["high_confidence"]) <= 0.60
    steps = GRID["high_confidence"]
    assert all(round(b - a, 2) == 0.01 for a, b in zip(steps, steps[1:], strict=False))


def test_dump_keeps_only_passing_settings_and_counts():
    from weir_eval.simulate import dump

    rows = [row("q-1"), row("q-2", f=feats(tokens=99))]
    results = run_grid(rows, CFG)
    out = dump(results, choose(results), {"baseline": "b", "small": "s"})
    assert out["settings_total"] == len(results) and out["settings_passing"] == len(out["passing"]) > 0
    assert out["chosen"]["setting"]["short_query_tokens"] in GRID["short_query_tokens"]
    assert all("_sim" not in p and p["tune"]["share_small"] > 0 for p in out["passing"])
    assert dump(results, None, {})["chosen"] is None
