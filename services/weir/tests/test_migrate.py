import psycopg
import pytest

from weir.migrate import apply_migrations

from .conftest import MIGRATIONS

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "rag.documents", "rag.chunks", "rag.kb_versions",
    "weir.cache_entries", "weir.model_prices", "weir.request_log", "weir.feedback",
}


def test_applies_all_then_is_idempotent(clean_db_url):
    assert apply_migrations(clean_db_url, MIGRATIONS) == ["001_init.sql"]
    assert apply_migrations(clean_db_url, MIGRATIONS) == []


def test_creates_schema_and_pgvector_0_8(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(clean_db_url) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "select schemaname || '.' || tablename from pg_tables "
                "where schemaname in ('rag', 'weir')"
            )
        }
        version = conn.execute(
            "select extversion from pg_extension where extname = 'vector'"
        ).fetchone()[0]
    assert EXPECTED_TABLES <= tables
    major, minor = (int(x) for x in version.split(".")[:2])
    assert (major, minor) >= (0, 8)  # needed for hnsw.iterative_scan
