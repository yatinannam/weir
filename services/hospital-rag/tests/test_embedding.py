import numpy as np
import pytest

from hospital_rag.embedding import Embedder


@pytest.fixture(scope="module")
def embedder():
    return Embedder("BAAI/bge-small-en-v1.5")  # first run downloads ~70 MB


def test_vectors_are_384_dim_unit_norm(embedder):
    [v] = embedder.embed(["What are the ICU visiting hours?"])
    assert v.shape == (384,)
    assert v.dtype == np.float32
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_paraphrase_closer_than_unrelated(embedder):
    a, b, c = embedder.embed([
        "When can I visit a patient in the ICU?",
        "What are the visiting hours for the intensive care unit?",
        "How much does parking cost for a car?",
    ])
    assert float(a @ b) > float(a @ c)


def test_count_tokens(embedder):
    assert embedder.count_tokens("visiting hours") >= 2
    assert embedder.count_tokens("") == 0
