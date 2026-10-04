from weir_eval.workload import make_workload, repeat_rate


def test_workload_is_deterministic_skewed_and_sized():
    ids = [f"q-{i:03d}" for i in range(150)]
    a = make_workload(ids, 300, seed=7)
    assert a == make_workload(ids, 300, seed=7) and len(a) == 300 and set(a) <= set(ids)
    assert 0.3 < repeat_rate(a) < 0.95
    top = max(set(a), key=a.count)
    assert a.count(top) >= 30  # a few questions dominate


def test_repeat_rate_edges():
    assert repeat_rate([]) == 0.0 and repeat_rate(["a", "a", "b", "c"]) == 0.25


def test_project_onto_workload_keeps_order_and_repeats():
    import pytest

    from weir_eval.workload import project_onto_workload

    records = [{"id": "a", "x": 1}, {"id": "b", "x": 2}, {"id": "a", "x": 9}]  # first occurrence wins
    assert project_onto_workload(records, ["b", "a", "a"]) == [{"id": "b", "x": 2}, {"id": "a", "x": 1},
                                                               {"id": "a", "x": 1}]
    with pytest.raises(KeyError):
        project_onto_workload(records, ["c"])
