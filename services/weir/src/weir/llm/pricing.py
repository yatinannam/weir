"""Versioned list prices and per-request cost (spec §8)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from psycopg_pool import AsyncConnectionPool

PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    model: str
    usd_per_m_input: Decimal
    usd_per_m_output: Decimal
    effective_from: date


class UnknownModelPrice(KeyError):
    pass


class PriceTable:
    def __init__(self, prices: list[Price]):
        self.prices = sorted(prices, key=lambda p: (p.model, p.effective_from))

    @classmethod
    def from_yaml(cls, path: Path) -> "PriceTable":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls([
            Price(
                model=row["model"],
                usd_per_m_input=Decimal(str(row["usd_per_m_input"])),
                usd_per_m_output=Decimal(str(row["usd_per_m_output"])),
                effective_from=row["effective_from"],
            )
            for row in data["prices"]
        ])

    def price_for(self, model: str, on: date) -> Price:
        candidates = [p for p in self.prices if p.model == model and p.effective_from <= on]
        if not candidates:
            raise UnknownModelPrice(f"no price for {model!r} on {on}")
        return candidates[-1]

    def cost(self, model: str, tokens_in: int, tokens_out: int, on: date) -> Decimal:
        p = self.price_for(model, on)
        return (Decimal(tokens_in) * p.usd_per_m_input + Decimal(tokens_out) * p.usd_per_m_output) / PER_MILLION


async def sync_prices(pool: AsyncConnectionPool, table: PriceTable) -> None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.executemany(
            "insert into weir.model_prices (model, usd_per_m_input, usd_per_m_output, effective_from)"
            " values (%s, %s, %s, %s) on conflict (model, effective_from) do update"
            " set usd_per_m_input = excluded.usd_per_m_input, usd_per_m_output = excluded.usd_per_m_output",
            [(p.model, p.usd_per_m_input, p.usd_per_m_output, p.effective_from) for p in table.prices],
        )
