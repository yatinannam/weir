import numpy as np
import pytest

from hospital_rag.chunking import ChunkText
from hospital_rag.db import open_pool
from hospital_rag.kb import KbDoc
from hospital_rag.store import ChunkRecord, replace_namespace, search, versions

pytestmark = pytest.mark.db
NS = "weir-general/en/public"


def unit(i: int) -> np.ndarray:
    v = np.zeros(384, dtype=np.float32)
    v[i] = 1.0
    return v


def doc(doc_id: str) -> KbDoc:
    return KbDoc(NS, doc_id, f"Title {doc_id}", f"public/{doc_id}.md", "body", "hash")


def records(doc_id: str, axes: list[int]) -> list[ChunkRecord]:
    return [ChunkRecord(doc_id, ChunkText(i, f"{doc_id} chunk {i}", 5), unit(a)) for i, a in enumerate(axes)]


async def test_search_returns_nearest_first(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        await replace_namespace(pool, NS, "v1", [doc("a"), doc("b")], records("a", [0, 1]) + records("b", [2]))
        version, chunks = await search(pool, NS, unit(2), k=2)
        assert version == "v1"
        assert chunks[0].id == "b#0" and chunks[0].title == "Title b"
        assert chunks[0].score == pytest.approx(1.0)
        assert chunks[0].score >= chunks[1].score
    finally:
        await pool.close()


async def test_replace_removes_old_chunks_and_updates_version(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        await replace_namespace(pool, NS, "v1", [doc("a")], records("a", [0]))
        await replace_namespace(pool, NS, "v2", [doc("c")], records("c", [0]))
        version, chunks = await search(pool, NS, unit(0), k=4)
        assert version == "v2"
        assert [c.doc_id for c in chunks] == ["c"]
        assert await versions(pool) == {NS: "v2"}
    finally:
        await pool.close()


async def test_unknown_namespace_returns_nothing(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        assert await search(pool, "nope/en/x", unit(0), k=4) == (None, [])
    finally:
        await pool.close()
