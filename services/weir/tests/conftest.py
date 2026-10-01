import asyncio
import os
import sys
from pathlib import Path

import psycopg
import pytest

from weir.migrate import apply_migrations

if sys.platform == "win32":  # psycopg async cannot use the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO / "db" / "migrations"
CONFIGS = REPO / "configs"
TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://weir:weir@localhost:5432/weir_test")


def _reset(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "drop schema if exists rag cascade; drop schema if exists weir cascade; "
            "drop table if exists public.schema_migrations"
        )


@pytest.fixture
def clean_db_url() -> str:
    _reset(TEST_DB)
    return TEST_DB


@pytest.fixture
def migrated_db_url(clean_db_url: str) -> str:
    apply_migrations(clean_db_url, MIGRATIONS)
    return clean_db_url
