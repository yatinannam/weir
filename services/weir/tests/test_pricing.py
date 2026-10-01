from datetime import date
from decimal import Decimal

import psycopg
import pytest

from weir.db import open_pool
from weir.llm.pricing import Price, PriceTable, UnknownModelPrice, sync_prices

from .conftest import CONFIGS

D = Decimal


def table():
    return PriceTable([
        Price("m", D("0.10"), D("0.40"), date(2026, 1, 1)),
        Price("m", D("0.20"), D("0.80"), date(2026, 6, 1)),
    ])


def test_repo_prices_load():
    t = PriceTable.from_yaml(CONFIGS / "prices.yaml")
    p = t.price_for("openai/gpt-oss-120b", date(2026, 10, 1))
    assert (p.usd_per_m_input, p.usd_per_m_output) == (D("0.15"), D("0.60"))


def test_cost_math_exact():
    t = PriceTable.from_yaml(CONFIGS / "prices.yaml")
    # 1000/1e6*0.15 + 500/1e6*0.60 = 0.00015 + 0.0003
    assert t.cost("openai/gpt-oss-120b", 1000, 500, date(2026, 10, 1)) == D("0.00045")


def test_price_by_effective_date():
    assert table().price_for("m", date(2026, 3, 1)).usd_per_m_input == D("0.10")
    assert table().price_for("m", date(2026, 6, 1)).usd_per_m_input == D("0.20")


def test_unknown_model_or_date_raises():
    with pytest.raises(UnknownModelPrice):
        table().price_for("other", date(2026, 3, 1))
    with pytest.raises(UnknownModelPrice):
        table().price_for("m", date(2025, 12, 31))


@pytest.mark.db
async def test_sync_prices_upserts(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        await sync_prices(pool, table())
        await sync_prices(pool, table())  # idempotent
    finally:
        await pool.close()
    with psycopg.connect(migrated_db_url) as conn:
        assert conn.execute("select count(*) from weir.model_prices").fetchone()[0] == 2
