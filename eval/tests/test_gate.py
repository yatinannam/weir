import pytest

from weir_eval.gate import gate


def rec(id, route, judge, facts, cost, status="miss"):
    return {"id": id, "group": "distinct", "difficulty": "easy", "status_code": 200, "client_latency_ms": 100,
            "judge_score": judge, "fact_score": facts,
            "meta": {"route": route, "escalated": False, "cost_usd": cost, "cache_status": status}}


BASE = {"q-1": rec("q-1", "large", 5, 1.0, 0.0004), "q-2": rec("q-2", "large", 5, 1.0, 0.0004)}


def test_gate_passes_when_cheaper_and_no_worse():
    g = gate([rec("q-1", "small", 5, 1.0, 0.0002), rec("q-2", "large", 5, 1.0, 0.0004)], BASE)
    assert g["passed"] is True and g["small_route_judge"] == 5 and g["small_route_base_judge"] == 5
    assert g["cost_per_1k"] == pytest.approx(0.3) and g["base_cost_per_1k"] == pytest.approx(0.4)


def test_gate_compares_repeats_against_the_same_question():
    g = gate([rec("q-1", "none", 5, 1.0, 0.0, status="hit")] * 3, BASE)
    assert g["base_cost_per_1k"] == pytest.approx(0.4) and g["checks"]["cost_lower"] is True


@pytest.mark.parametrize(("records", "failed"), [
    ([rec("q-1", "small", 4, 1.0, 0.0002), rec("q-2", "large", 5, 1.0, 0.0004)], "small_route_ok"),
    ([rec("q-1", "large", 5, 0.5, 0.0003), rec("q-2", "large", 5, 1.0, 0.0003)], "facts_no_lower"),
    ([rec("q-1", "large", 5, 1.0, 0.0005), rec("q-2", "large", 5, 1.0, 0.0004)], "cost_lower"),
    ([rec("q-1", "none", 2, 1.0, 0.0, status="hit"), rec("q-2", "large", 5, 1.0, 0.0001)], "zero_wrong_hits"),
])
def test_gate_failures(records, failed):
    g = gate(records, BASE)
    assert g["checks"][failed] is False and g["passed"] is False


def test_gate_requires_judged_rows():
    with pytest.raises(ValueError, match="rejudge"):
        gate([rec("q-1", "large", None, 1.0, 0.0004)], BASE)
