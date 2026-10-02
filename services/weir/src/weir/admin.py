"""Feedback and cache administration (Phase 2 addendum §6)."""
from dataclasses import dataclass
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from .cache.store import CacheStore


@dataclass(frozen=True)
class RequestRef:
    namespace: str
    cache_entry_id: UUID | None


class AdminService:
    def __init__(self, pool: AsyncConnectionPool, store: CacheStore):
        self._pool = pool
        self._store = store

    async def find_request(self, request_id: UUID) -> RequestRef | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "select namespace, cache_entry_id from weir.request_log where request_id = %s", (request_id,)
            )).fetchone()
        return RequestRef(row[0], row[1]) if row else None

    async def add_feedback(self, request_id: UUID, rating: int, comment: str | None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("insert into weir.feedback (request_id, rating, comment) values (%s, %s, %s)",
                               (request_id, rating, comment))

    async def evict(self, entry_id: UUID) -> bool:
        return await self._store.delete(entry_id=entry_id) > 0

    async def purge(self, *, namespace: str | None = None, source_id: str | None = None,
                    entry_id: UUID | None = None) -> int:
        return await self._store.delete(namespace=namespace, source_id=source_id, entry_id=entry_id)
