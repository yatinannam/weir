"""Answer coverage check (D79): does the answer give the kind of detail the question asks for?

Grounding checks that an answer's words come from the source; it can't see what the answer leaves out. Asked
when the blood donation camp is held, the small model said "the first Saturday of every month" and dropped
"10 am to 3 pm" (q-036). This check maps the question to the detail types it asks for, finds the source line
that best matches the question, and fails when that line has a detail of a wanted type and the answer has
none of that type. One detail per type is enough (type coverage): a morning-only question answered with the
morning time passes. `strict_passed` (every detail) is reported for comparison only.
"""
import re
from dataclasses import dataclass

from .grounding import WORD, content_words

_NUM = r"\d[\d,]*"
PATTERNS: dict[str, re.Pattern[str]] = {
    "time": re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)(?![a-z])|\bnoon\b|\bmidnight\b"
                       r"|\b24\s?(?:hours|hrs)\b|\b24\s?x\s?7\b|\b24/7\b|\bround the clock\b", re.I),
    "day": re.compile(r"\b(?:(?:first|second|third|fourth|last)\s+)?(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b"
                      r"|\bweekdays?\b|\bweekends?\b", re.I),
    "money": re.compile(rf"₹\s?{_NUM}|\brs\.?\s?{_NUM}|\binr\s?{_NUM}|\bfree of charge\b|\bno charge\b", re.I),
    "extension": re.compile(r"\b(?:ext\.?|extension)\s*(?:no\.?|number|is)?\s*:?\s*(\d{3,5})\b", re.I),
    "quantity": re.compile(r"\b\d+\s?(?:hours?|hrs?|minutes?|mins?|days?|weeks?|months?|years?|visitors?"
                           r"|people|persons?|beds?)\b", re.I),
}
_BARE_NUMBER = re.compile(r"\b\d{3,5}\b")      # answer side only: "the extension is 2171"

# Question wording -> the detail types it asks for (word-boundary, case-insensitive).
TRIGGERS: list[tuple[re.Pattern[str], frozenset[str]]] = [
    (re.compile(r"\bwhen\b|\bheld\b|\bschedule\b", re.I), frozenset({"time", "day"})),
    # "hours" asks for a time ("visiting hours") unless it's a quantity ("for 2 hours")
    (re.compile(r"\bwhat time\b|\btimings?\b|(?<!\d )(?<!\d)\bhours\b|\bopens?\b|\bcloses?\b|\bstarts?\b|\bends?\b"
                r"|\b(?:visiting|opening|closing|working|office)\s+times?\b", re.I), frozenset({"time"})),
    (re.compile(r"\bwhich days?\b|\bwhat days?\b", re.I), frozenset({"day"})),
    (re.compile(r"\bhow much\b|\bcosts?\b|\bfees?\b|\bcharges?\b|\bprices?\b|\brates?\b|\bpay\b", re.I),
     frozenset({"money"})),
    (re.compile(r"\bextension\b|\bext\b|\bphone\b|\bnumber to call\b|\bcontact\b|\bdial\b", re.I),
     frozenset({"extension"})),
    (re.compile(r"\bhow long\b|\bhow many\b|\bduration\b", re.I), frozenset({"quantity"})),
]
_SPLIT = re.compile(r"\n+|(?<=[.!?])\s+(?=[A-Z])")   # not inside "ext. 2171" or "10 a.m. to"


@dataclass(frozen=True)
class Coverage:
    passed: bool
    reason: str | None          # "missing:time" or "missing:money,time"; None when passed
    missing: tuple[str, ...]
    strict_passed: bool         # every required detail on the passage is in the answer (comparison only)


def _canonical(kind: str, match: re.Match[str]) -> str:
    s = match.group(0).lower().strip()
    if kind == "time":
        s = re.sub(r"[\s.]", "", s).replace(":00", "")
        return {"roundtheclock": "24hours", "24x7": "24hours", "24/7": "24hours", "24hrs": "24hours"}.get(s, s)
    if kind == "money":
        return re.sub(r"\D", "", s) or "free"
    if kind == "extension":
        return match.group(1)
    return re.sub(r"s$", "", re.sub(r"\s+", " ", s))   # days and quantities: "saturdays" -> "saturday"


def details(text: str, lenient: bool = False) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            found.setdefault(kind, set()).add(_canonical(kind, m))
    if lenient and (bare := set(_BARE_NUMBER.findall(text))):
        found.setdefault("extension", set()).update(bare)
    return found


def required_types(question: str) -> frozenset[str]:
    wanted: set[str] = set()
    for pattern, kinds in TRIGGERS:
        if pattern.search(question):
            wanted |= kinds
    return frozenset(wanted)


def passage(question: str, chunk_texts: list[str]) -> list[str]:
    """The lines of the cited chunks that best match the question. hospital-rag starts every chunk with a
    "<title>: <heading>" line (chunking.py): it carries the topic words but no details, so it is never a candidate on
    its own; instead every line under it borrows its words when scored."""
    asked = set(content_words(question))
    scored = []
    for text in chunk_texts:
        first, _, rest = text.strip().partition("\n")
        heading = set(WORD.findall(first.lower())) if rest.strip() else set()
        body = [line.strip() for line in _SPLIT.split(rest if rest.strip() else first) if line.strip()]
        for line in body:
            scored.append((len(asked & (heading | set(WORD.findall(line.lower())))), line))
    best = max((s for s, _ in scored), default=0)
    return [line for s, line in scored if s == best] if best > 0 else []


def strip_type(text: str, kind: str) -> str:
    return re.sub(r"\s{2,}", " ", PATTERNS[kind].sub("", text)).strip()


def check(question: str, answer: str, chunk_texts: list[str]) -> Coverage:
    wanted = required_types(question)
    source = details(" ".join(passage(question, chunk_texts))) if wanted else {}
    given = details(answer, lenient=True)
    asked = sorted(k for k in wanted if source.get(k))
    missing = tuple(k for k in asked if not given.get(k))
    strict = all(source[k] <= given.get(k, set()) for k in asked)
    return Coverage(not missing, f"missing:{','.join(missing)}" if missing else None, missing, strict)
