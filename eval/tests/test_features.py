from pathlib import Path

from weir.cache.guards import BypassRules
from weir.config import load_config
from weir.rag.adapter import RetrieveResult
from weir.router.features import FeatureExtractor, Features

from weir_eval.features import FEATURE_KEYS, collect_features, features_row

from .conftest import q

CFG = load_config(Path(__file__).resolve().parents[2] / "configs" / "weir.yaml")
EXTRACTOR = FeatureExtractor(lambda t: len(t.split()), BypassRules(CFG.bypass), ["why"])


def retrieved(top=0.8):
    return RetrieveResult(chunks=[], top_score=top, score_gap=0.2, context_tokens=300, kb_version="v1", latency_ms=1)


def test_features_row_has_id_split_group_and_every_feature():
    row = features_row(q("q-001", "d-01", split="tune"), retrieved(), EXTRACTOR)
    assert row == {"id": "q-001", "split": "tune", "group": "distinct", "tokens": 2, "has_reasoning_words": False,
                   "num_questions": 1, "top_score": 0.8, "score_gap": 0.2, "context_tokens": 300,
                   "is_clinical": False}
    assert Features(**{k: row[k] for k in FEATURE_KEYS}).tokens == 2  # rows rebuild into Features


class FakeRag:
    def __init__(self):
        self.asked = []

    async def retrieve(self, query, namespace, k):
        self.asked.append((query, namespace, k))
        return retrieved(top=0.5)


async def test_collect_features_retrieves_each_question_once():
    rag = FakeRag()
    rows = await collect_features([q("q-001", "d-01"), q("q-002", "d-02")], rag, EXTRACTOR, 4)
    assert [r["id"] for r in rows] == ["q-001", "q-002"] and all(r["top_score"] == 0.5 for r in rows)
    assert rag.asked == [("question q-001", "weir-general/en/public", 4),
                         ("question q-002", "weir-general/en/public", 4)]
