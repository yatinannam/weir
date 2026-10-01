"""Load the Markdown knowledge base. Folder name picks the namespace."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

NAMESPACE_DIRS = {
    "public": "weir-general/en/public",
    "staff": "weir-general/en/staff",
}


@dataclass(frozen=True)
class KbDoc:
    namespace: str
    id: str
    title: str
    path: str
    body: str
    content_hash: str


def parse_doc(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("document must start with YAML frontmatter ('---')")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("frontmatter is not closed with '---'")
    meta = yaml.safe_load(text[4:end]) or {}
    for key in ("id", "title"):
        if not meta.get(key):
            raise ValueError(f"frontmatter is missing '{key}'")
    body = text[end + 4 :].lstrip("\n")
    return {"id": str(meta["id"]), "title": str(meta["title"])}, body


def load_kb(kb_dir: Path) -> list[KbDoc]:
    docs: list[KbDoc] = []
    seen: set[str] = set()
    for folder, namespace in NAMESPACE_DIRS.items():
        for path in sorted((kb_dir / folder).glob("*.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = parse_doc(text)
            if meta["id"] in seen:
                raise ValueError(f"duplicate document id: {meta['id']}")
            seen.add(meta["id"])
            docs.append(KbDoc(
                namespace=namespace,
                id=meta["id"],
                title=meta["title"],
                path=f"{folder}/{path.name}",
                body=body,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ))
    return docs


def kb_version(docs: list[KbDoc]) -> str:
    digest = hashlib.sha256()
    for doc in sorted(docs, key=lambda d: d.id):
        digest.update(f"{doc.id}:{doc.content_hash}\n".encode())
    return digest.hexdigest()[:12]
