import asyncio
import os
import sys
from pathlib import Path

import psycopg
import pytest

if sys.platform == "win32":  # psycopg async cannot use the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO / "db" / "migrations"
TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://weir:weir@localhost:5432/weir_test")


@pytest.fixture
def migrated_db_url() -> str:
    """Fresh weir_test with every migration applied (plain replay, no tracking table)."""
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute(
            "drop schema if exists rag cascade; drop schema if exists weir cascade; "
            "drop table if exists public.schema_migrations"
        )
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
    return TEST_DB


def word_count(text: str) -> int:
    return len(text.split())
