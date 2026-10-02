from dataclasses import astuple
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from weir.admin import AdminService
from weir.cache.store import CacheStore
from weir.db import open_pool
from weir.metrics.logger import INSERT_SQL, RequestLogRow

from .fakes import make_entry

pytestmark = pytest.mark.db


async def test_admin_service_roundtrip(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        store = CacheStore(pool)
        admin = AdminService(pool, store)
        entry = make_entry()
        await store.insert(entry)
        row = RequestLogRow(request_id=uuid4(), ts=datetime.now(UTC), namespace="weir-general/en/public",
                            cache_status="hit", route="none", status="ok", latency_total_ms=5,
                            query_hash="h" * 64, cache_entry_id=entry.id)
        async with pool.connection() as conn:
            await conn.execute(INSERT_SQL, astuple(row))
        ref = await admin.find_request(row.request_id)
        assert ref.namespace == "weir-general/en/public" and ref.cache_entry_id == entry.id
        assert await admin.find_request(uuid4()) is None
        await admin.add_feedback(row.request_id, -1, "wrong")
        await admin.add_feedback(uuid4(), 1, None)  # no FK any more (migration 002)
        assert await admin.evict(entry.id) is True and await admin.evict(entry.id) is False
        assert await admin.purge(namespace="weir-general/en/public") == 0
    finally:
        await pool.close()
    with psycopg.connect(migrated_db_url) as conn:
        assert conn.execute("select count(*) from weir.feedback").fetchone()[0] == 2
