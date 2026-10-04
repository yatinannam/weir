"""Key-fact matching: is each required fact present in an answer?

Both the answer and the fact are canonicalised so formatting differences (4:00 PM vs 4 pm,
"4-7 pm" vs "4 pm to 7 pm", 12 pm vs noon, "90 %" vs "90 percent", "extension is 2171" vs "ext. 2171") don't
count as misses, and numbers only match whole numbers (₹50 never matches inside ₹500).
"""
import re
from dataclasses import dataclass

DASHES = re.compile(r"[‐-―−]")
AM_PM = re.compile(r"\b([ap])\.m\.?", re.IGNORECASE)
GLUED_MERIDIEM = re.compile(r"(\d)(am|pm)\b")
ZERO_MINUTES = re.compile(r"\b(\d{1,2}):00\b")
NOON = re.compile(r"\b(?:12 noon|12 pm)\b")
MIDNIGHT = re.compile(r"\b(?:12 midnight|12 am)\b")
TIME_DASH = re.compile(r"(\d|am|pm|noon|midnight) ?- ?(?=\d|noon|midnight)")
SHARED_MERIDIEM = re.compile(r"\b(\d{1,2}) to (\d{1,2}) (am|pm)\b")
# D38: "90 %" = "90%" = "90 percent"; "ext. 2171" = "extension is 2171" = "2171" (whole-number matching still applies)
PERCENT = re.compile(r"(\d) ?(?:%|percent\b|per cent\b)")
EXTENSION = re.compile(r"\b(?:ext\.?|extension)(?: (?:number|no\.?|is))*:? ?(?=\d)")


def norm(text: str) -> str:
    text = DASHES.sub("-", text)
    text = AM_PM.sub(lambda m: m.group(1) + "m", text)
    return " ".join(text.lower().split())


def canonical(text: str) -> str:
    text = norm(text)
    text = GLUED_MERIDIEM.sub(r"\1 \2", text)
    text = ZERO_MINUTES.sub(r"\1", text)
    text = NOON.sub("noon", text)
    text = MIDNIGHT.sub("midnight", text)
    text = TIME_DASH.sub(r"\1 to ", text)
    text = PERCENT.sub(r"\1%", text)
    text = EXTENSION.sub("", text)
    return SHARED_MERIDIEM.sub(_expand_shared_meridiem, text)


def _expand_shared_meridiem(m: re.Match) -> str:
    start, end, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
    if start < end < 12:  # "4 to 7 pm" -> "4 pm to 7 pm"; "11 to 1 pm" is ambiguous, leave it
        return f"{start} {meridiem} to {end} {meridiem}"
    return m.group(0)


def _pattern(alt: str) -> re.Pattern:
    body = re.escape(alt)
    if alt[:1].isdigit():
        body = r"(?<![\d.])(?<!\d,)" + body
    if alt[-1:].isdigit():
        body += r"(?!\d|[.,]\d)"
    return re.compile(body)


def fact_present(answer: str, fact: str) -> bool:
    haystack = canonical(answer)
    return any(_pattern(canonical(alt)).search(haystack) for alt in fact.split("|") if alt.strip())


@dataclass(frozen=True)
class FactResult:
    hits: int
    total: int

    @property
    def score(self) -> float:
        return self.hits / self.total if self.total else 0.0


def check_facts(answer: str, facts: list[str]) -> FactResult:
    return FactResult(sum(fact_present(answer, f) for f in facts), len(facts))
