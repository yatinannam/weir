"""Load kb/, chunk, embed and replace each namespace's chunks.

Usage: python -m hospital_rag.ingest --kb /app/kb
"""
import argparse
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from .aio import run
from .chunking import chunk_document
from .db import open_pool
from .embedding import Embedder
from .kb import kb_version, load_kb
from .settings import Settings
from .store import ChunkRecord, replace_namespace


async def ingest(kb_dir: Path, pool: AsyncConnectionPool, embedder: Embedder, max_tokens: int) -> dict[str, str]:
    docs = load_kb(kb_dir)
    result: dict[str, str] = {}
    for namespace in sorted({d.namespace for d in docs}):
        ns_docs = [d for d in docs if d.namespace == namespace]
        version = kb_version(ns_docs)
        records: list[ChunkRecord] = []
        for doc in ns_docs:
            chunks = chunk_document(doc.title, doc.body, embedder.count_tokens, max_tokens)
            vectors = embedder.embed([c.text for c in chunks])
            records.extend(ChunkRecord(doc.id, c, v) for c, v in zip(chunks, vectors, strict=True))
        await replace_namespace(pool, namespace, version, ns_docs, records)
        result[namespace] = version
        print(f"{namespace}: {len(ns_docs)} docs, {len(records)} chunks, kb_version={version}")
    return result


async def _main(kb_dir: Path) -> None:
    settings = Settings()
    embedder = Embedder(settings.embed_model, settings.embed_cache_dir)
    pool = await open_pool(settings.database_url)
    try:
        await ingest(kb_dir, pool, embedder, settings.chunk_max_tokens)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb", type=Path, default=Path("/app/kb"))
    run(_main(parser.parse_args().kb))


if __name__ == "__main__":
    main()
