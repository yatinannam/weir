from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from weir.db import open_pool
from weir.metrics.logger import LogWriter, RequestLogRow


def row(**overrides):
    base = dict(request_id=uuid4(), ts=datetime.now(UTC), namespace="weir-general/en/public",
                cache_status="bypass", route="large", status="ok", latency_total_ms=120,
                query_hash="h" * 64, cost_usd=Decimal("0.00045"), config_label="test")
    return RequestLogRow(**{**base, **overrides})


@pytest.mark.db
async def test_rows_are_written_on_stop(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    writer = LogWriter(pool, flush_interval_s=0.05)
    writer.start()
    for _ in range(3):
        writer.submit(row(bypass_reason="cache_disabled"))
    await writer.stop()
    await pool.close()
    with psycopg.connect(migrated_db_url) as conn:
        count, cost = conn.execute("select count(*), sum(cost_usd) from weir.request_log").fetchone()
    assert count == 3 and cost == Decimal("0.00135")
    assert writer.failed == 0 and writer.dropped == 0


class BrokenPool:
    @asynccontextmanager
    async def connection(self):
        raise RuntimeError("db down")
        yield  # pragma: no cover


async def test_write_failure_is_counted_not_raised():
    writer = LogWriter(BrokenPool(), flush_interval_s=0.01)
    writer.start()
    writer.submit(row())
    await writer.stop()
    assert writer.failed == 1


async def test_full_queue_drops_instead_of_blocking():
    writer = LogWriter(BrokenPool(), max_queue=1)  # not started: nothing drains the queue
    writer.submit(row())
    writer.submit(row())
    assert writer.dropped == 1
