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
