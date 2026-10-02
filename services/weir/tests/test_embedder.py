import numpy as np
import pytest

from weir.cache.embedder import Embedder


@pytest.fixture(scope="module")
def embedder():
    return Embedder("BAAI/bge-small-en-v1.5")


def test_single_and_batch_agree_and_are_unit_norm(embedder):
    one = embedder.embed("icu visiting hours")
    [batch] = embedder.embed_many(["icu visiting hours"])
    assert one.shape == (384,) and one.dtype == np.float32
    assert abs(float(np.linalg.norm(one)) - 1.0) < 1e-5
    assert float(one @ batch) == pytest.approx(1.0, abs=1e-5)


def test_paraphrase_closer_than_look_alike_topic_shift(embedder):
    a, b, c = embedder.embed_many(["when can i visit the icu?", "what are icu visiting hours?",
                                   "how much is car parking?"])
    assert float(a @ b) > float(a @ c)
    assert embedder.count_tokens("icu visiting hours") >= 3
