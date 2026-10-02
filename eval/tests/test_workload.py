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
