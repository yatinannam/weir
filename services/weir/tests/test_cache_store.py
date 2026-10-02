from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from weir.cache.store import CacheStore
from weir.db import open_pool

from .fakes import make_entry, unit

pytestmark = pytest.mark.db
PUBLIC, STAFF = "weir-general/en/public", "weir-general/en/staff"


@pytest.fixture
async def store(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    yield CacheStore(pool)
    await pool.close()


async def test_insert_then_lookup_returns_best_first(store):
    near, far = make_entry(embedding=unit(0)), make_entry(embedding=unit(1), query_text="other")
    await store.insert(near)
    await store.insert(far)
    found = await store.lookup(PUBLIC, "v1", "p1", unit(0), 3)
    assert [c.id for c in found][0] == near.id
    assert found[0].similarity == pytest.approx(1.0) and found[0].sources == [{"id": "pub-a", "title": "Visiting"}]
    assert found[0].tokens_in == 1000 and found[0].model == "openai/gpt-oss-120b"


async def test_lookup_is_isolated_by_namespace(store):
    await store.insert(make_entry(namespace=STAFF))
    assert await store.lookup(PUBLIC, "v1", "p1", unit(0), 3) == []


async def test_lookup_filters_versions_and_expiry(store):
    await store.insert(make_entry(kb_version="v0"))
    await store.insert(make_entry(prompt_version="p0"))
    await store.insert(make_entry(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert await store.lookup(PUBLIC, "v1", "p1", unit(0), 3) == []


async def test_iterative_scan_fills_k_under_selective_filter(store):
    for i in range(40):  # many closer rows in another namespace
        await store.insert(make_entry(namespace=STAFF, embedding=unit(0)))
    for i in range(3):
        await store.insert(make_entry(embedding=unit(1 + i)))
    assert len(await store.lookup(PUBLIC, "v1", "p1", unit(0), 3)) == 3


async def test_increment_and_deletes(store, migrated_db_url):
    a = make_entry(source_ids=["pub-a", "pub-x"])
    b = make_entry(source_ids=["pub-b"])
    c = make_entry(namespace=STAFF, source_ids=["staff-c"])
    old = make_entry(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    for e in (a, b, c, old):
        await store.insert(e)
    await store.increment_hits(a.id)
    await store.increment_hits(a.id)
    with psycopg.connect(migrated_db_url) as conn:
        assert conn.execute("select hit_count from weir.cache_entries where id = %s", (a.id,)).fetchone()[0] == 2
    assert await store.delete_expired() == 1
    assert await store.delete(source_id="pub-x") == 1
    assert await store.delete(entry_id=b.id) == 1
    assert await store.delete(namespace=STAFF) == 1
    with pytest.raises(ValueError, match="exactly one"):
        await store.delete(namespace=PUBLIC, entry_id=b.id)
    with pytest.raises(ValueError, match="exactly one"):
        await store.delete()
