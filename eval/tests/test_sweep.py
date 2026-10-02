import numpy as np

from weir_eval.sweep import Pair, build_pairs, choose_threshold, sweep, write_sweep_report

from .conftest import q


def vec(*xs):
    v = np.zeros(384, dtype=np.float32)
    v[: len(xs)] = xs
    return v / np.linalg.norm(v)


def toy():
    qs = [q("p1", "para-1", "paraphrase", "tune", facts=("A",)), q("p2", "para-1", "paraphrase", "tune", facts=("A",)),
          q("t1", "trap-1", "trap", "tune", facts=("B",)), q("t2", "trap-1", "trap", "tune", facts=("C",)),
          q("d1", "d-1", "distinct", "holdout", facts=("D",))]
    vecs = {"p1": vec(1, 0, 0), "p2": vec(1, 0.1, 0), "t1": vec(0, 1, 0), "t2": vec(0, 1, 0.2), "d1": vec(0.8, 0, 0.6)}
    return qs, vecs


def test_build_pairs_kinds_splits_and_guard():
    qs, vecs = toy()
    pairs = {(p.a, p.b): p for p in build_pairs(qs, vecs, lambda a, b: "t1" in a or "t1" in b)}
    assert pairs[("p1", "p2")].kind == "positive" and pairs[("p1", "p2")].split == "tune"
    assert pairs[("t1", "t2")].kind == "trap" and pairs[("t1", "t2")].guard_conflict
    assert pairs[("d1", "p1")].kind == "hard_negative" and pairs[("d1", "p1")].split == "cross"
    assert pairs[("p1", "p2")].similarity > 0.99


def test_hard_negatives_sharing_a_fact_are_skipped():
    qs, vecs = toy()
    qs[4] = q("d1", "d-1", "distinct", "holdout", facts=("A",))  # same answer as p1/p2
    same_answer = ({"d1", "p1"}, {"d1", "p2"})
    assert not any(p.kind == "hard_negative" and {p.a, p.b} in same_answer
                   for p in build_pairs(qs, vecs, lambda a, b: False))


def pairs_fixture():
    return [Pair("a", "b", "positive", "tune", 0.95, False), Pair("c", "d", "positive", "tune", 0.85, False),
            Pair("e", "f", "trap", "tune", 0.90, True), Pair("g", "h", "hard_negative", "tune", 0.83, False)]


def test_sweep_math_with_and_without_guard():
    on = {r["threshold"]: r for r in sweep(pairs_fixture(), [0.82, 0.84, 0.90], use_guard=True)}
    off = {r["threshold"]: r for r in sweep(pairs_fixture(), [0.84], use_guard=False)}
    assert on[0.84]["hit_rate"] == 1.0 and on[0.84]["false_hit_rate"] == 0.0
    assert abs(on[0.82]["false_hit_rate"] - 1 / 3) < 1e-9
    assert off[0.84]["trap_false_hits"] == 1 and abs(off[0.84]["false_hit_rate"] - 1 / 3) < 1e-9
    assert on[0.90]["hit_rate"] == 0.5


def test_choose_threshold_lowest_passing():
    rows = sweep(pairs_fixture(), [0.82, 0.84, 0.90], use_guard=True)
    assert choose_threshold(rows) == 0.84
    assert choose_threshold(sweep(pairs_fixture(), [0.82], use_guard=False)) is None


def test_report_files(tmp_path):
    rows = sweep(pairs_fixture(), [0.82, 0.84], use_guard=True)
    results = {("tune", True): rows, ("tune", False): rows, ("holdout", True): rows, ("holdout", False): rows,
               ("all", True): rows, ("all", False): rows}
    write_sweep_report(tmp_path, results, 0.84, pairs_fixture())
    assert {"sweep.csv", "summary.md", "threshold.png"} <= {p.name for p in tmp_path.iterdir()}
    assert "0.84" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_same_answer_detected_by_any_shared_alternative():
    qs, vecs = toy()
    qs[4] = q("d1", "d-1", "distinct", "holdout", facts=("Rs 9|A",))  # differently formatted, same answer as p1/p2
    same_answer = ({"d1", "p1"}, {"d1", "p2"})
    assert not any(p.kind == "hard_negative" and {p.a, p.b} in same_answer
                   for p in build_pairs(qs, vecs, lambda a, b: False))
