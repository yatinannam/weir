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
    assert apply_migrations(clean_db_url, MIGRATIONS) == ["001_init.sql", "002_phase2_cache.sql",
                                                          "003_phase3_router.sql", "004_phase4_monitoring.sql"]
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


def test_feedback_fk_dropped(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(clean_db_url) as conn:
        fks = conn.execute(
            "select count(*) from pg_constraint where conrelid = 'weir.feedback'::regclass and contype = 'f'"
        ).fetchone()[0]
    assert fks == 0


def test_phase3_router_columns(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(clean_db_url) as conn:
        cols = dict(conn.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'weir' and table_name = 'request_log' "
            "and column_name in ('route_reason', 'grounding_reason', 'grounding_overlap')").fetchall())
    assert cols == {"route_reason": "text", "grounding_reason": "text", "grounding_overlap": "real"}


READ_TABLES = ("weir.request_log", "weir.cache_entries", "weir.model_prices", "weir.feedback")


def _reader(url: str) -> str:
    return url.replace("weir:weir@", "weir_reader:weir_reader@", 1)


def test_weir_reader_can_read_the_four_tables(clean_db_url):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(_reader(clean_db_url)) as conn:
        for table in READ_TABLES:
            conn.execute(f"select count(*) from {table}").fetchone()


@pytest.mark.parametrize("statement", [
    "insert into weir.feedback (request_id, rating) values (gen_random_uuid(), 1)",
    "update weir.request_log set status = 'ok'",
    "delete from weir.cache_entries",
    "select count(*) from rag.chunks",
    "create table weir.x (id int)",
])
def test_weir_reader_cannot_write_or_read_rag(clean_db_url, statement):
    apply_migrations(clean_db_url, MIGRATIONS)
    with psycopg.connect(_reader(clean_db_url)) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)
