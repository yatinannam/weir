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


def test_onnx_threads_sleep_between_runs_and_are_capped():  # M33: spinning threads read ~600% CPU at 10 req/s
    import onnxruntime as ort

    before = ort.SessionOptions
    capped = Embedder("BAAI/bge-small-en-v1.5", threads=2)
    options = capped._model.model.model.get_session_options()
    assert options.get_session_config_entry("session.intra_op.allow_spinning") == "0"
    assert options.get_session_config_entry("session.inter_op.allow_spinning") == "0"
    assert options.intra_op_num_threads == 2
    assert ort.SessionOptions is before                 # the swap is undone once the model is loaded
    assert float(capped.embed("icu visiting hours") @ capped.embed("icu visiting hours")) == pytest.approx(1.0)


def test_spin_true_keeps_onnx_runtimes_default():  # D74: the faster, busier option stays available
    spinning = Embedder("BAAI/bge-small-en-v1.5", threads=2, spin=True)
    options = spinning._model.model.model.get_session_options()
    with pytest.raises(RuntimeError):  # never set, so ONNX Runtime's default (spinning) applies
        options.get_session_config_entry("session.intra_op.allow_spinning")
