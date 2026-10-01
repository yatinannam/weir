from weir.text import normalize, query_hash


def test_normalize_trims_collapses_lowercases():
    assert normalize("  What are\tthe  ICU\nhours? ") == "what are the icu hours?"


def test_query_hash_ignores_case_and_spacing():
    assert query_hash("ICU  hours") == query_hash("icu hours")
    assert len(query_hash("x")) == 64
