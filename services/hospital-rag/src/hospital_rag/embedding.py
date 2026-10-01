import numpy as np
from fastembed import TextEmbedding
from tokenizers import Tokenizer


class Embedder:
    """Local bge-small embeddings (free, CPU) plus the matching tokenizer for counts."""

    dim = 384

    def __init__(self, model_name: str, cache_dir: str | None = None):
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self._tokenizer = Tokenizer.from_pretrained(model_name)

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        vectors = []
        for raw in self._model.embed(texts):
            v = np.asarray(raw, dtype=np.float32)
            vectors.append(v / np.linalg.norm(v))
        return vectors

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
