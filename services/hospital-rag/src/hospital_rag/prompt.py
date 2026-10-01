"""Prompt contract: numbered passages in, cited answer or NOT_FOUND out.

Bump PROMPT_VERSION on any change to SYSTEM or the message layout; Weir keys its
cache on it.
"""
import re
from dataclasses import dataclass

PROMPT_VERSION = "p1"
NOT_FOUND = "NOT_FOUND"
NOT_FOUND_MESSAGE = "Sorry, I couldn't find that in Weir General Hospital's information."

SYSTEM = """You are the help desk assistant for Weir General Hospital.
Answer ONLY from the numbered context passages. Keep answers short (1-4 sentences).
After each fact, cite the passage it came from, like [c1] or [c2].
If the passages do not contain the answer, reply with exactly: NOT_FOUND
Never give medical advice beyond what the passages state."""

# [c1], [c1, c3], [c1; c3], [c1 and c2], and gpt-oss's native 【c1】 / 【c2†L3-L5】.
CITATION = re.compile(
    r"[\[【]\s*(c\d+(?:\s*(?:,|;|and)\s*c\d+)*)(?:†[^\]】]*)?\s*[\]】]",
    re.IGNORECASE,
)
LABEL_SEPARATOR = re.compile(r"\s*(?:,|;|and)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedAnswer:
    answer: str
    cited_chunk_ids: list[str]
    invalid_citations: int
    not_found: bool


def build_messages(query: str, chunks: list[tuple[str, str]]) -> tuple[list[dict], dict[str, str]]:
    labels = {f"c{i + 1}": chunk_id for i, (chunk_id, _) in enumerate(chunks)}
    context = "\n\n".join(f"[c{i + 1}] {text}" for i, (_, text) in enumerate(chunks))
    user = f"Context passages:\n\n{context}\n\nQuestion: {query}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], labels


def parse_answer(raw: str, labels: dict[str, str]) -> ParsedAnswer:
    text = raw.strip()
    if not text or text.strip("*_` ").upper().startswith(NOT_FOUND):
        return ParsedAnswer(NOT_FOUND_MESSAGE, [], 0, True)
    cited: list[str] = []
    invalid = 0
    for match in CITATION.finditer(text):
        for label in LABEL_SEPARATOR.split(match.group(1).lower()):
            if label in labels:
                if labels[label] not in cited:
                    cited.append(labels[label])
            else:
                invalid += 1
    clean = CITATION.sub("", text)
    clean = re.sub(r"\s+([.,;:!?])", r"\1", clean)
    clean = re.sub(r"[,;]+([.!?])", r"\1", clean)  # "[c1],[c2]." leaves ",." behind
    clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
    return ParsedAnswer(clean, cited, invalid, False)
