import re
from dataclasses import dataclass

DASHES = re.compile(r"[‐-―−]")
AM_PM = re.compile(r"\b([ap])\.m\.?", re.IGNORECASE)


def norm(text: str) -> str:
    text = DASHES.sub("-", text)
    text = AM_PM.sub(lambda m: m.group(1) + "m", text)
    return " ".join(text.lower().split())


def fact_present(answer: str, fact: str) -> bool:
    haystack = norm(answer)
    return any(norm(alt) in haystack for alt in fact.split("|") if alt.strip())


@dataclass(frozen=True)
class FactResult:
    hits: int
    total: int

    @property
    def score(self) -> float:
        return self.hits / self.total if self.total else 0.0


def check_facts(answer: str, facts: list[str]) -> FactResult:
    return FactResult(sum(fact_present(answer, f) for f in facts), len(facts))
