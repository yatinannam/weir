import pytest

from hospital_rag.kb import kb_version, load_kb, parse_doc


def write(path, doc_id, title, body="## A\n\nText."):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {doc_id}\ntitle: {title}\n---\n\n{body}\n", encoding="utf-8")


def test_parse_doc_reads_frontmatter():
    meta, body = parse_doc("---\nid: x\ntitle: Hello\n---\n\n## S\n\nBody")
    assert meta == {"id": "x", "title": "Hello"}
    assert body.startswith("## S")


def test_parse_doc_rejects_missing_id():
    with pytest.raises(ValueError, match="id"):
        parse_doc("---\ntitle: Hello\n---\nBody")


def test_load_kb_maps_folders_to_namespaces(tmp_path):
    write(tmp_path / "public" / "pub-a.md", "pub-a", "A")
    write(tmp_path / "staff" / "staff-b.md", "staff-b", "B")
    (tmp_path / "README.md").write_text("not ingested", encoding="utf-8")
    docs = {d.id: d for d in load_kb(tmp_path)}
    assert docs["pub-a"].namespace == "weir-general/en/public"
    assert docs["staff-b"].namespace == "weir-general/en/staff"
    assert len(docs) == 2


def test_load_kb_rejects_duplicate_ids(tmp_path):
    write(tmp_path / "public" / "one.md", "same", "A")
    write(tmp_path / "public" / "two.md", "same", "B")
    with pytest.raises(ValueError, match="duplicate"):
        load_kb(tmp_path)


def test_kb_version_changes_only_when_content_changes(tmp_path):
    write(tmp_path / "public" / "pub-a.md", "pub-a", "A")
    v1 = kb_version(load_kb(tmp_path))
    assert v1 == kb_version(load_kb(tmp_path))
    write(tmp_path / "public" / "pub-a.md", "pub-a", "A", body="## A\n\nChanged.")
    v2 = kb_version(load_kb(tmp_path))
    assert v1 != v2 and len(v2) == 12
