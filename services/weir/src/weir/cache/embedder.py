from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
import onnxruntime as ort
from fastembed import TextEmbedding
from tokenizers import Tokenizer


@contextmanager
def _no_spin_sessions(spin: bool) -> Iterator[None]:
    """While fastembed builds its ONNX session, make the session's worker threads sleep between runs.

    ONNX Runtime's threads spin-wait for the next run by default, so an idle container that embeds
    reads several cores busy (about 600% at 10 req/s, backlog M33). fastembed exposes the thread
    count but not this option, so its SessionOptions are swapped for the duration of the load.
    Spinning buys about 9 ms per embedding on an otherwise idle machine at one core per extra thread
    (D74); `spin=True` keeps ONNX Runtime's default.
    """
    if spin:
        yield
        return
    original = ort.SessionOptions

    class NoSpin(original):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__()
            self.add_session_config_entry("session.intra_op.allow_spinning", "0")
            self.add_session_config_entry("session.inter_op.allow_spinning", "0")

    ort.SessionOptions = NoSpin
    try:
        yield
    finally:
        ort.SessionOptions = original


class Embedder:
    """Local bge-small embeddings (free, CPU), the same model hospital-rag uses for retrieval."""

    dim = 384

    def __init__(self, model_name: str, cache_dir: str | None = None, threads: int | None = None,
                 spin: bool = False):
        with _no_spin_sessions(spin):
            self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir, threads=threads)
        self._tokenizer = Tokenizer.from_pretrained(model_name)

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        vectors = []
        for raw in self._model.embed(texts):
            v = np.asarray(raw, dtype=np.float32)
            vectors.append(v / np.linalg.norm(v))
        return vectors

    def embed(self, text: str) -> np.ndarray:
        return self.embed_many([text])[0]

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
