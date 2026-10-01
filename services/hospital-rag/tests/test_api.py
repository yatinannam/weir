import httpx
import numpy as np
import pytest

from hospital_rag.chunking import ChunkText
from hospital_rag.db import open_pool
from hospital_rag.kb import KbDoc
from hospital_rag.llm import LLMResult, RateLimited
from hospital_rag.main import Deps, create_app
from hospital_rag.store import ChunkRecord, replace_namespace

NS = "weir-general/en/public"


class FakeLLM:
    def __init__(self, text="Open 4 pm to 8 pm [c1].", error=None):
        self.text, self.error, self.calls = text, error, 0

    async def complete(self, messages, model):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResult(self.text, 100, 20, "stop", model, 5)


class FakeEmbedder:
    def embed(self, texts):
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        return [v for _ in texts]

    def count_tokens(self, text):
        return len(text.split())


def client_for(deps):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://t")


GEN_BODY = {"query": "When?", "namespace": NS, "model": "m", "chunks": [{"id": "pub-a#0", "text": "Open 4 pm to 8 pm"}]}


async def test_generate_parses_answer():
    async with client_for(Deps(None, FakeEmbedder(), FakeLLM(), 4)) as c:
        r = await c.post("/generate", json=GEN_BODY)
    body = r.json()
    assert r.status_code == 200
    assert body["answer"] == "Open 4 pm to 8 pm."
    assert body["cited_chunk_ids"] == ["pub-a#0"]
    assert body["tokens_in"] == 100 and body["prompt_version"] == "p1"


async def test_generate_with_no_chunks_skips_llm():
    llm = FakeLLM()
    async with client_for(Deps(None, FakeEmbedder(), llm, 4)) as c:
        r = await c.post("/generate", json={**GEN_BODY, "chunks": []})
    body = r.json()
    assert r.status_code == 200 and llm.calls == 0
    assert body["not_found"] is True and body["finish_reason"] == "skipped"
    assert body["tokens_in"] == 0 and body["tokens_out"] == 0


async def test_generate_rate_limited_returns_503():
    async with client_for(Deps(None, FakeEmbedder(), FakeLLM(error=RateLimited(12.0)), 4)) as c:
        r = await c.post("/generate", json=GEN_BODY)
    assert r.status_code == 503
    assert r.json() == {"error": "rate_limited", "retry_after": 12.0}


async def test_retrieve_rejects_blank_query():
    async with client_for(Deps(None, FakeEmbedder(), FakeLLM(), 4)) as c:
        r = await c.post("/retrieve", json={"query": "", "namespace": NS})
    assert r.status_code == 422


@pytest.mark.db
async def test_retrieve_and_info_against_db(migrated_db_url):
    pool = await open_pool(migrated_db_url)
    try:
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        doc = KbDoc(NS, "pub-a", "Visiting", "public/pub-a.md", "b", "h")
        await replace_namespace(pool, NS, "v1", [doc], [ChunkRecord("pub-a", ChunkText(0, "Visiting: 4 pm", 3), v)])
        async with client_for(Deps(pool, FakeEmbedder(), FakeLLM(), 4)) as c:
            r = await c.post("/retrieve", json={"query": "visiting?", "namespace": NS})
            info = await c.get("/info")
        body = r.json()
        assert body["kb_version"] == "v1"
        assert body["chunks"][0]["id"] == "pub-a#0"
        assert body["top_score"] == pytest.approx(1.0)
        assert body["score_gap"] == pytest.approx(1.0)  # single chunk: gap = top score
        assert body["context_tokens"] == 3
        assert info.json() == {"namespaces": {NS: {"kb_version": "v1", "prompt_version": "p1"}}}
    finally:
        await pool.close()
