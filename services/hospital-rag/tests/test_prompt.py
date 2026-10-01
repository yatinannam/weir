from hospital_rag.prompt import NOT_FOUND_MESSAGE, build_messages, parse_answer

LABELS = {"c1": "pub-a#0", "c2": "pub-b#1", "c3": "pub-c#0"}


def test_build_messages_numbers_passages():
    messages, labels = build_messages("When?", [("pub-a#0", "Alpha text"), ("pub-b#1", "Beta text")])
    assert labels == {"c1": "pub-a#0", "c2": "pub-b#1"}
    assert messages[0]["role"] == "system" and "NOT_FOUND" in messages[0]["content"]
    assert "[c1] Alpha text" in messages[1]["content"]
    assert messages[1]["content"].rstrip().endswith("Question: When?")


def test_parse_strips_citations_and_maps_ids():
    p = parse_answer("Visiting is 4 pm to 8 pm [c1]. Two visitors [c2].", LABELS)
    assert p.answer == "Visiting is 4 pm to 8 pm. Two visitors."
    assert p.cited_chunk_ids == ["pub-a#0", "pub-b#1"]
    assert p.not_found is False and p.invalid_citations == 0


def test_parse_grouped_and_duplicate_citations():
    p = parse_answer("Yes [c1, c3] and again [c1].", LABELS)
    assert p.cited_chunk_ids == ["pub-a#0", "pub-c#0"]


def test_parse_counts_invalid_labels():
    p = parse_answer("Answer [c9] [c2].", LABELS)
    assert p.cited_chunk_ids == ["pub-b#1"]
    assert p.invalid_citations == 1


def test_parse_no_citations():
    p = parse_answer("Plain answer.", LABELS)
    assert p.cited_chunk_ids == [] and p.answer == "Plain answer."


def test_parse_not_found_and_empty():
    for raw in ("NOT_FOUND", "  not_found.", ""):
        p = parse_answer(raw, LABELS)
        assert p.not_found is True
        assert p.answer == NOT_FOUND_MESSAGE
        assert p.cited_chunk_ids == []


import pytest  # noqa: E402


@pytest.mark.parametrize(("raw", "expected_ids"), [
    ("ICU visiting is 11 am – 11:30 am【c1】.", ["pub-a#0"]),          # gpt-oss native style
    ("Open daily【c2†L3-L5】.", ["pub-b#1"]),                           # with line refs
    ("Yes [c1; c3].", ["pub-a#0", "pub-c#0"]),
    ("Yes [c1 and c2].", ["pub-a#0", "pub-b#1"]),
    ("Yes [c1],[c2].", ["pub-a#0", "pub-b#1"]),
])
def test_parse_other_citation_styles(raw, expected_ids):
    p = parse_answer(raw, LABELS)
    assert p.cited_chunk_ids == expected_ids
    assert "c1" not in p.answer and "c2" not in p.answer and "【" not in p.answer
    assert ",." not in p.answer and " ." not in p.answer


def test_parse_bold_not_found():
    assert parse_answer("**NOT_FOUND**", LABELS).not_found is True
