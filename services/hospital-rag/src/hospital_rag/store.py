from dataclasses import dataclass

import numpy as np
from psycopg_pool import AsyncConnectionPool

from .chunking import ChunkText
from .kb import KbDoc


@dataclass(frozen=True)
class ChunkRecord:
    doc_id: str
    chunk: ChunkText
    embedding: np.ndarray


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    doc_id: str
    title: str
    text: str
    score: float
    token_count: int


async def replace_namespace(
    pool: AsyncConnectionPool,
    namespace: str,
    kb_version: str,
    docs: list[KbDoc],
    records: list[ChunkRecord],
) -> None:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("delete from rag.documents where namespace = %s", (namespace,))
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into rag.documents (id, namespace, title, path, kb_version, content_hash)"
                " values (%s, %s, %s, %s, %s, %s)",
                [(d.id, namespace, d.title, d.path, kb_version, d.content_hash) for d in docs],
            )
            await cur.executemany(
                "insert into rag.chunks"
                " (id, doc_id, namespace, kb_version, chunk_index, text, token_count, embedding)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (f"{r.doc_id}#{r.chunk.index}", r.doc_id, namespace, kb_version,
                     r.chunk.index, r.chunk.text, r.chunk.token_count, r.embedding)
                    for r in records
                ],
            )
        await conn.execute(
            "insert into rag.kb_versions (namespace, kb_version) values (%s, %s)"
            " on conflict (namespace) do update"
            " set kb_version = excluded.kb_version, updated_at = now()",
            (namespace, kb_version),
        )


async def search(
    pool: AsyncConnectionPool, namespace: str, embedding: np.ndarray, k: int
) -> tuple[str | None, list[RetrievedChunk]]:
    async with pool.connection() as conn, conn.transaction():
        row = await (await conn.execute(
            "select kb_version from rag.kb_versions where namespace = %s", (namespace,)
        )).fetchone()
        if row is None:
            return None, []
        version = row[0]
        # Filtered HNSW can under-return; iterative scan keeps searching until k rows match.
        await conn.execute("set local hnsw.iterative_scan = relaxed_order")
        rows = await (await conn.execute(
            "select c.id, c.doc_id, d.title, c.text, 1 - (c.embedding <=> %s) as score, c.token_count"
            " from rag.chunks c join rag.documents d on d.id = c.doc_id"
            " where c.namespace = %s and c.kb_version = %s"
            " order by c.embedding <=> %s limit %s",
            (embedding, namespace, version, embedding, k),
        )).fetchall()
    chunks = [RetrievedChunk(r[0], r[1], r[2], r[3], float(r[4]), r[5]) for r in rows]
    chunks.sort(key=lambda c: c.score, reverse=True)  # relaxed_order may be slightly unordered
    return version, chunks


async def versions(pool: AsyncConnectionPool) -> dict[str, str]:
    async with pool.connection() as conn:
        rows = await (await conn.execute("select namespace, kb_version from rag.kb_versions")).fetchall()
    return {ns: v for ns, v in rows}
