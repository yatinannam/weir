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
# Numbers written as words or ordinals count as the same number ("three days" = "3 days",
# "2nd floor" = "second floor"); final-review finding C1.
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10,
}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b")
_ORDINAL = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b")


def _digits(text: str) -> str:
    text = _ORDINAL.sub(r"\1", text)
    return _NUMBER_WORD.sub(lambda m: str(NUMBER_WORDS[m.group(1)]), text)
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
        # Numbers are read outside lexicon phrases, so "two-wheeler" stays a vehicle, not the number 2.
        outside_terms = self._pattern.sub(" ", text) if self._pattern else text
        numbers = frozenset(_number_key(m) for m in NUMBER.finditer(_digits(outside_terms)))
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
