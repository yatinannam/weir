from weir_eval.kb import facts_missing_from_sources, load_kb_texts

from .conftest import q


def test_facts_checked_against_source_docs(tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "pub-a.md").write_text("---\nid: pub-a\ntitle: A\n---\n\nOpen 4 pm to 8 pm.", encoding="utf-8")
    kb = load_kb_texts(tmp_path)
    assert set(kb) == {"pub-a"}
    assert facts_missing_from_sources([q("d1", "d1", facts=("4 pm",))], kb) == []
    problems = facts_missing_from_sources([q("d2", "d2", facts=("9 pm",)), q("d3", "d3", docs=("nope",))], kb)
    assert any("d2" in p and "9 pm" in p for p in problems)
    assert any("d3" in p and "nope" in p for p in problems)
