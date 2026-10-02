import re
from pathlib import Path

from .dataset import EvalQuery
from .keyfacts import fact_present

ID_LINE = re.compile(r"^id:\s*(.+)$", re.MULTILINE)


def load_kb_texts(kb_dir: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    for path in sorted(kb_dir.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        match = ID_LINE.search(text)
        if match:
            texts[match.group(1).strip()] = text
    return texts


def facts_missing_from_sources(queries: list[EvalQuery], kb: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for q in queries:
        if q.group == "unanswerable":
            continue
        missing_docs = [d for d in q.source_docs if d not in kb]
        if missing_docs:
            problems.append(f"{q.id}: unknown source docs {missing_docs}")
            continue
        corpus = "\n".join(kb[d] for d in q.source_docs)
        for fact in q.required_facts:
            if not fact_present(corpus, fact):
                problems.append(f"{q.id}: fact {fact!r} not found in {q.source_docs}")
    return problems
