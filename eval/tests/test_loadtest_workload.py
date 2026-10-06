import json

from weir_eval.loadtest.workload import distinct_requests, make_request_file
from weir_eval.workload import repeat_rate

from .conftest import q

QUERIES = [q(f"q-{i:03d}", f"c{i}") for i in range(30)]


def test_request_file_is_sized_ordered_and_deterministic():
    a = make_request_file(QUERIES, 500, seed=11)
    assert len(a) == 500 and a == make_request_file(QUERIES, 500, seed=11)
    assert a != make_request_file(QUERIES, 500, seed=12)
    assert all(set(r) == {"query", "namespace"} for r in a)
    assert repeat_rate([r["query"] for r in a]) > 0.8                     # Zipf-skewed: mostly repeats


def test_request_file_has_no_keys():  # Review Focus 5
    text = json.dumps(make_request_file(QUERIES, 200, seed=11))
    assert "X-API-Key" not in text and "key" not in text.lower()


def test_distinct_keeps_first_occurrence_order():
    reqs = [{"query": "a", "namespace": "n"}, {"query": "b", "namespace": "n"}, {"query": "a", "namespace": "n"}]
    assert distinct_requests(reqs) == reqs[:2]
