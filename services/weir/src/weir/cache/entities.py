"""Entity guard (Phase 2 addendum §3.1).

Two questions may share a cached answer only if they mention the same numbers, the same
negation and the same lexicon terms. Embedding similarity alone can't tell "ICU visiting
hours" from "general ward visiting hours"; this guard can.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..text import normalize

UNIT_CANON = {
    "am": "am", "pm": "pm", "km": "km", "%": "%", "percent": "%",
    "hour": "hour", "hours": "hour", "hr": "hour", "hrs": "hour",
    "day": "day", "days": "day", "minute": "minute", "minutes": "minute", "min": "minute", "mins": "minute",
    "week": "week", "weeks": "week", "month": "month", "months": "month", "year": "year", "years": "year",
    "bed": "bed", "beds": "bed",
}
_UNITS = "|".join(sorted((re.escape(u) for u in UNIT_CANON), key=len, reverse=True))
NUMBER = re.compile(rf"(?<![\w.])(\d+(?:[.,:]\d+)*)(?:\s*({_UNITS}))?(?!\w)")
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
NEGATIONS = frozenset({"no", "not", "without", "except", "non", "never", "cannot", "none", "neither", "nor"})


@dataclass(frozen=True)
class Entities:
    numbers: frozenset[str]
    negated: bool
    terms: frozenset[str]


class Lexicon:
    def __init__(self, groups: dict[str, dict[str, list[str]]]):
        self._term_of: dict[str, str] = {}
        for group, entries in groups.items():
            for canonical, synonyms in entries.items():
                term = f"{group}:{canonical}"
                for phrase in [canonical, *synonyms]:
                    key = normalize(phrase)
                    if self._term_of.get(key, term) != term:
                        raise ValueError(f"lexicon phrase {phrase!r} maps to two terms: {self._term_of[key]} and {term}")
                    self._term_of[key] = term
        phrases = sorted(self._term_of, key=len, reverse=True)
        self._pattern = (re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in phrases) + r")(?!\w)")
                         if phrases else None)

    @classmethod
    def from_yaml(cls, path: Path) -> "Lexicon":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8"))["groups"])

    def extract(self, text: str) -> Entities:
        text = normalize(text).replace("’", "'")
        numbers = frozenset(_number_key(m) for m in NUMBER.finditer(text))
        negated = any(w in NEGATIONS or w.endswith("n't") for w in WORD.findall(text))
        terms = (frozenset(self._term_of[m.group(0)] for m in self._pattern.finditer(text))
                 if self._pattern else frozenset())
        return Entities(numbers, negated, terms)

    def conflicts(self, a_text: str, b_text: str) -> bool:
        return self.extract(a_text) != self.extract(b_text)


def _number_key(match: re.Match) -> str:
    value = match.group(1).replace(",", "")
    unit = UNIT_CANON.get(match.group(2) or "", "")
    return f"{value} {unit}".strip()
