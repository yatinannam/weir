"""Test doubles shared by the cache, pipeline and API tests."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np

from weir.cache.store import CacheEntry


def unit(i: int) -> np.ndarray:
    v = np.zeros(384, dtype=np.float32)
    v[i] = 1.0
    return v


def make_entry(**over) -> CacheEntry:
    base = dict(id=uuid4(), namespace="weir-general/en/public", kb_version="v1", prompt_version="p1",
                query_text="when can i visit?", embedding=unit(0), answer="Answer.",
                sources=[{"id": "pub-a", "title": "Visiting"}], source_ids=["pub-a"], model="openai/gpt-oss-120b",
                tokens_in=1000, tokens_out=500, expires_at=datetime.now(UTC) + timedelta(hours=24))
    return CacheEntry(**{**base, **over})


import hashlib  # noqa: E402

from weir.cache.store import Candidate  # noqa: E402
from weir.text import normalize  # noqa: E402


class ListSink:
    def __init__(self):
        self.rows = []

    def submit(self, row):
        self.rows.append(row)


class FakeEmbedder:
    """Deterministic pseudo-random unit vectors per text; `aliases` make two texts embed identically."""

    def __init__(self, aliases: dict[str, str] | None = None):
        self.aliases = {normalize(k): normalize(v) for k, v in (aliases or {}).items()}
        self.fail = False

    def embed(self, text: str) -> np.ndarray:
        if self.fail:
            raise RuntimeError("embedder down")
        text = self.aliases.get(text, text)
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).standard_normal(384).astype(np.float32)
        return v / np.linalg.norm(v)

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeStore:
    def __init__(self, now):
        self._now = now
        self.entries = []
        self.hits = {}
        self.fail_lookup = False

    async def lookup(self, namespace, kb_version, prompt_version, embedding, k):
        if self.fail_lookup:
            raise RuntimeError("db down")
        found = [Candidate(e.id, e.query_text, e.answer, e.sources, e.model, e.tokens_in, e.tokens_out,
                           float(e.embedding @ embedding))
                 for e in self.entries
                 if (e.namespace, e.kb_version, e.prompt_version) == (namespace, kb_version, prompt_version)
                 and e.expires_at > self._now()]
        return sorted(found, key=lambda c: c.similarity, reverse=True)[:k]

    async def insert(self, entry):
        self.entries.append(entry)

    async def increment_hits(self, entry_id):
        self.hits[entry_id] = self.hits.get(entry_id, 0) + 1

    async def delete(self, *, namespace=None, source_id=None, entry_id=None):
        before = len(self.entries)
        self.entries = [e for e in self.entries if not (
            e.namespace == namespace or source_id in e.source_ids or e.id == entry_id)]
        return before - len(self.entries)


class InlineQueue:
    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)

    async def drain(self):
        while self.jobs:
            await self.jobs.pop(0)()
