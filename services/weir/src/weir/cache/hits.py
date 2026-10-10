"""Cache hit counts, coalesced in memory and written once a second (D76).

A hit used to queue one UPDATE on its cache entry. Traffic is skewed, so most hits land on a few entries,
and at about 250 req/s the single cache-job worker fell behind: the queue filled and dropped not only hit
counts but new cache entries waiting behind them. Counts are bookkeeping, so they are added up here and
flushed as one statement by a periodic task; the job queue is left for real cache writes.
"""
from collections import Counter
from uuid import UUID


class HitCounter:
    def __init__(self, store):
        self._store = store            # .add_hits({entry_id: n})
        self._pending: Counter[UUID] = Counter()

    def add(self, entry_id: UUID) -> None:
        self._pending[entry_id] += 1

    async def flush(self) -> None:
        if not self._pending:
            return
        pending, self._pending = self._pending, Counter()
        await self._store.add_hits(pending)
