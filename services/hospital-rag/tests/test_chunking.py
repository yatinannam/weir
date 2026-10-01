from hospital_rag.chunking import chunk_document, split_sections

from .conftest import word_count

DOC = """Intro line before any heading.

## Weekdays

Visiting is from 4 pm to 8 pm.

Two visitors at a time.

## Weekends

Visiting is from 11 am to 8 pm.
"""


def test_split_sections_keeps_preamble_and_headings():
    sections = split_sections(DOC)
    assert [h for h, _ in sections] == ["", "Weekdays", "Weekends"]
    assert "4 pm to 8 pm" in sections[1][1]


def test_chunks_carry_title_and_heading_prefix():
    chunks = chunk_document("General ward visiting hours", DOC, word_count, max_tokens=250)
    assert chunks[1].text.startswith("General ward visiting hours: Weekdays\n")
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_every_chunk_within_budget_and_counts_match():
    long_para = " ".join(f"word{i}" for i in range(700))
    body = f"## Big\n\n{long_para}\n\n## Small\n\nshort text"
    chunks = chunk_document("T", body, word_count, max_tokens=100, overlap_words=10)
    assert all(c.token_count <= 100 for c in chunks)
    assert all(c.token_count == word_count(c.text) for c in chunks)


def test_long_paragraph_windows_overlap():
    long_para = " ".join(f"w{i}" for i in range(300))
    chunks = chunk_document("T", f"## S\n\n{long_para}", word_count, max_tokens=60, overlap_words=10)
    first = chunks[0].text.split()
    second = chunks[1].text.split()
    assert first[-1] in second  # consecutive windows share words


def test_paragraphs_packed_together_when_they_fit():
    chunks = chunk_document("T", DOC, word_count, max_tokens=250)
    weekdays = [c for c in chunks if "Weekdays" in c.text]
    assert len(weekdays) == 1
    assert "Two visitors" in weekdays[0].text
