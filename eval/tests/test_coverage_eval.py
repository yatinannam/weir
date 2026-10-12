from types import SimpleNamespace

from weir_eval.coverage import coverage_rows, summarize

CAMP = "The blood donation camp is held on the first Saturday of every month, 10 am to 3 pm, in the lobby."


class FakeRag:
    async def retrieve(self, query, namespace, k):
        return SimpleNamespace(chunks=[SimpleNamespace(doc_id="pub-blood-bank", text=CAMP),
                                       SimpleNamespace(doc_id="pub-other", text="Parking costs ₹40.")])


def rec(id_, answer, judge=5, facts=1.0):
    return {"id": id_, "status_code": 200, "query": "When is the blood donation camp held?",
            "namespace": "weir-general/en/public", "answer": answer, "sources": [{"id": "pub-blood-bank"}],
            "judge_score": judge, "fact_score": facts}


async def test_flags_real_omissions_and_builds_synthetic_ones():
    records = [rec("q-036", "The first Saturday of every month.", judge=3, facts=0.5),
               rec("q-037", "The first Saturday of every month, 10 am to 3 pm.")]
    rows, synthetic = await coverage_rows(records, FakeRag(), 4)
    assert [(r["id"], r["passed"], r["reason"]) for r in rows] == [("q-036", False, "missing:time"),
                                                                    ("q-037", True, None)]
    assert {(s["id"], s["type"], s["flagged"]) for s in synthetic} == {("q-037", "time", True), ("q-037", "day", True)}
    summary = summarize(rows, synthetic, records)
    assert summary["flagged"] == ["q-036"] and summary["synthetic_recall"] == 1.0
    assert summary["false_flag_rate"] == 0.0 and summary["good_answers"] == 1


async def test_errored_rows_are_skipped():
    rows, synthetic = await coverage_rows([{**rec("q-1", "x"), "status_code": 503}], FakeRag(), 4)
    assert rows == [] and synthetic == []
