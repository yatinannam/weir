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


def test_onnx_threads_sleep_between_runs_and_are_capped():  # M33: spinning threads keep cores busy when idle
    import onnxruntime as ort

    before = ort.SessionOptions
    capped = Embedder("BAAI/bge-small-en-v1.5", threads=2)
    options = capped._model.model.model.get_session_options()
    assert options.get_session_config_entry("session.intra_op.allow_spinning") == "0"
    assert options.get_session_config_entry("session.inter_op.allow_spinning") == "0"
    assert options.intra_op_num_threads == 2
    assert ort.SessionOptions is before                 # the swap is undone once the model is loaded
    [v] = capped.embed(["visiting hours"])
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_spin_true_keeps_onnx_runtimes_default():  # D74: the faster, busier option stays available
    spinning = Embedder("BAAI/bge-small-en-v1.5", threads=2, spin=True)
    options = spinning._model.model.model.get_session_options()
    with pytest.raises(RuntimeError):  # never set, so ONNX Runtime's default (spinning) applies
        options.get_session_config_entry("session.intra_op.allow_spinning")
