"""Skewed traffic replay (main spec §11.3): a few questions are asked constantly, most rarely."""
import random


def make_workload(query_ids: list[str], n: int, seed: int, exponent: float = 1.1) -> list[str]:
    rng = random.Random(seed)
    order = sorted(query_ids)
    rng.shuffle(order)
    weights = [1 / rank ** exponent for rank in range(1, len(order) + 1)]
    return rng.choices(order, weights=weights, k=n)


def repeat_rate(ids: list[str]) -> float:
    return 1 - len(set(ids)) / len(ids) if ids else 0.0
