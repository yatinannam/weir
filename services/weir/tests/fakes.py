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
