"""Split a Markdown document into retrieval chunks of at most `max_tokens` tokens.

Sections are cut at headings; each chunk is prefixed with "<title>: <heading>" so it
stands alone. Paragraphs are packed greedily; a paragraph larger than the budget is
cut into overlapping word windows.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass

HEADING = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass(frozen=True)
class ChunkText:
    index: int
    text: str
    token_count: int


def split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading, lines = "", []
    for line in body.splitlines():
        match = HEADING.match(line)
        if match:
            if any(l.strip() for l in lines):
                sections.append((heading, "\n".join(lines).strip()))
            heading, lines = match.group(1).strip(), []
        else:
            lines.append(line)
    if any(l.strip() for l in lines):
        sections.append((heading, "\n".join(lines).strip()))
    return sections


def chunk_document(
    title: str,
    body: str,
    count_tokens: Callable[[str], int],
    max_tokens: int = 250,
    overlap_words: int = 30,
) -> list[ChunkText]:
    texts: list[str] = []
    for heading, text in split_sections(body):
        prefix = f"{title}: {heading}\n" if heading else f"{title}\n"
        budget = max_tokens - count_tokens(prefix)
        for part in _pack_paragraphs(text, count_tokens, budget, overlap_words):
            texts.append(prefix + part)
    return [ChunkText(i, t, count_tokens(t)) for i, t in enumerate(texts)]


def _pack_paragraphs(
    text: str, count_tokens: Callable[[str], int], budget: int, overlap_words: int
) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    current = ""
    for para in paragraphs:
        if count_tokens(para) > budget:
            if current:
                out.append(current)
                current = ""
            out.extend(_word_windows(para, count_tokens, budget, overlap_words))
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if count_tokens(candidate) <= budget:
            current = candidate
        else:
            out.append(current)
            current = para
    if current:
        out.append(current)
    return out


def _word_windows(
    text: str, count_tokens: Callable[[str], int], budget: int, overlap_words: int
) -> list[str]:
    words = text.split()
    out: list[str] = []
    start = 0
    while start < len(words):
        end = start + 1
        while end < len(words) and count_tokens(" ".join(words[start : end + 1])) <= budget:
            end += 1
        out.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = max(end - overlap_words, start + 1)
    return out
