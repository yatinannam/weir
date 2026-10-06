"""Request lists k6 replays (Phase 5 addendum §4). Questions and namespaces only: keys are never written."""
from ..dataset import EvalQuery
from ..workload import make_workload


def make_request_file(queries: list[EvalQuery], n: int, seed: int, exponent: float = 1.1) -> list[dict]:
    by_id = {q.id: q for q in queries}
    return [{"query": by_id[i].query, "namespace": by_id[i].namespace}
            for i in make_workload(list(by_id), n, seed, exponent)]


def distinct_requests(requests: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in requests:
        key = (r["query"], r["namespace"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out
