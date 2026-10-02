from weir_eval.dataset import assign_splits, load_queries, save_queries, validate

from .conftest import q


def valid_set():
    return (
        [q(f"d{i}", f"d{i}") for i in range(10)]
        + [q(f"p{i}", "para-1", group="paraphrase") for i in range(4)]
        + [q("t1", "trap-1", group="trap", facts=("4 pm",)), q("t2", "trap-1", group="trap", facts=("11 am",))]
    )


def test_round_trip(tmp_path):
    path = tmp_path / "q.jsonl"
    save_queries(path, valid_set())
    assert load_queries(path) == valid_set()


def test_valid_set_has_no_problems():
    assert validate(valid_set()) == []


def test_problems_detected():
    bad = valid_set() + [q("d0", "dup")]  # duplicate id
    bad += [q("p9", "para-2", group="paraphrase")]  # cluster too small
    bad += [q("t3", "trap-2", group="trap"), q("t4", "trap-2", group="trap")]  # same facts in a trap pair
    problems = "\n".join(validate(bad))
    assert "duplicate id d0" in problems
    assert "para-2" in problems
    assert "trap-2" in problems


def test_split_by_cluster_never_splits_a_cluster():
    queries = assign_splits(valid_set() * 1, holdout_frac=0.3, seed=7)
    by_cluster = {}
    for x in queries:
        by_cluster.setdefault(x.cluster_id, set()).add(x.split)
    assert all(len(s) == 1 for s in by_cluster.values())
    assert {x.split for x in queries} == {"tune", "holdout"}
    assert validate(queries) == []


def test_split_is_deterministic():
    assert assign_splits(valid_set(), seed=7) == assign_splits(valid_set(), seed=7)


def test_mixed_split_in_cluster_is_a_problem():
    qs = [q("p1", "para-1", "paraphrase", "tune")] + [q(f"p{i}", "para-1", "paraphrase", "holdout") for i in range(2, 5)]
    assert any("para-1" in p for p in validate(qs))


import pytest  # noqa: E402

from weir_eval.dataset import EvalQuery  # noqa: E402


def test_unanswerable_rules():
    ok = EvalQuery(id="u1", namespace="weir-general/en/public", query="Do you have a helipad?", group="unanswerable",
                   cluster_id="u-01", difficulty="easy", required_facts=["couldn't find"])
    assert ok.source_docs == [] and validate([ok]) == []
    with pytest.raises(ValueError, match="no source_docs"):
        EvalQuery(**{**ok.model_dump(), "source_docs": ["pub-a"]})
    with pytest.raises(ValueError, match="at least one source_doc"):
        EvalQuery(**{**ok.model_dump(), "group": "distinct", "cluster_id": "d-x"})


def test_existing_splits_are_kept():
    old = [q("d0", "d0", split="holdout"), q("d1", "d1", split="tune")]
    new = [q(f"n{i}", f"n{i}") for i in range(10)]
    out = {x.id: x.split for x in assign_splits(old + new)}
    assert out["d0"] == "holdout" and out["d1"] == "tune"
    assert sum(out[f"n{i}"] == "holdout" for i in range(10)) == 3
