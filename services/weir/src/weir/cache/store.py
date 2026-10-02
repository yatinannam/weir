"""weir.cache_entries reads and writes (main spec §6.2, §10)."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import numpy as np
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class CacheEntry:
    id: UUID
    namespace: str
    kb_version: str
    prompt_version: str
    query_text: str
    embedding: np.ndarray
    answer: str
    sources: list[dict]
    source_ids: list[str]
    model: str
    tokens_in: int
    tokens_out: int
    expires_at: datetime


@dataclass(frozen=True)
class Candidate:
    id: UUID
    query_text: str
    answer: str
    sources: list[dict]
    model: str
    tokens_in: int
    tokens_out: int
    similarity: float


DELETE_SQL = {
    "namespace": "delete from weir.cache_entries where namespace = %s",
    "source_id": "delete from weir.cache_entries where %s = any(source_ids)",
    "entry_id": "delete from weir.cache_entries where id = %s",
}


class CacheStore:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def lookup(self, namespace: str, kb_version: str, prompt_version: str,
                     embedding: np.ndarray, k: int) -> list[Candidate]:
        async with self._pool.connection() as conn, conn.transaction():
            # Filtered HNSW can under-return; iterative scan keeps going until k rows match.
            await conn.execute("set local hnsw.iterative_scan = relaxed_order")
            rows = await (await conn.execute(
                "select id, query_text, answer, sources, model, tokens_in, tokens_out,"
                " 1 - (embedding <=> %s) as similarity"
                " from weir.cache_entries"
                " where namespace = %s and kb_version = %s and prompt_version = %s and expires_at > now()"
                " order by embedding <=> %s limit %s",
                (embedding, namespace, kb_version, prompt_version, embedding, k),
            )).fetchall()
        found = [Candidate(r[0], r[1], r[2], r[3], r[4], r[5], r[6], float(r[7])) for r in rows]
        return sorted(found, key=lambda c: c.similarity, reverse=True)  # relaxed_order may be unordered

    async def insert(self, e: CacheEntry) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "insert into weir.cache_entries (id, namespace, kb_version, prompt_version, query_text, embedding,"
                " answer, sources, source_ids, model, tokens_in, tokens_out, expires_at)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (e.id, e.namespace, e.kb_version, e.prompt_version, e.query_text, e.embedding, e.answer,
                 Jsonb(e.sources), e.source_ids, e.model, e.tokens_in, e.tokens_out, e.expires_at),
            )

    async def increment_hits(self, entry_id: UUID) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("update weir.cache_entries set hit_count = hit_count + 1 where id = %s", (entry_id,))

    async def delete(self, *, namespace: str | None = None, source_id: str | None = None,
                     entry_id: UUID | None = None) -> int:
        given = [(k, v) for k, v in (("namespace", namespace), ("source_id", source_id), ("entry_id", entry_id))
                 if v is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of namespace, source_id, entry_id")
        column, value = given[0]
        async with self._pool.connection() as conn:
            return (await conn.execute(DELETE_SQL[column], (value,))).rowcount

    async def delete_expired(self) -> int:
        async with self._pool.connection() as conn:
            return (await conn.execute("delete from weir.cache_entries where expires_at <= now()")).rowcount
