import json

import httpx
import pytest

from weir.rag.adapter import RagClient, RagError, RetrievedChunk

CHUNK = {"id": "pub-a#0", "doc_id": "pub-a", "title": "A", "text": "t", "score": 0.8, "token_count": 3}
RETRIEVE = {"chunks": [CHUNK], "top_score": 0.8, "score_gap": 0.8, "context_tokens": 3, "kb_version": "v1", "latency_ms": 4}
GENERATE = {"answer": "x", "cited_chunk_ids": ["pub-a#0"], "invalid_citations": 0, "not_found": False,
            "finish_reason": "stop", "tokens_in": 10, "tokens_out": 2, "model": "m", "prompt_version": "p1", "latency_ms": 5}


def client(handler):
    return RagClient("http://rag", 5, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag"))


async def test_retrieve_parses_result():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=RETRIEVE)

    result = await client(handler).retrieve("q", "ns", 4)
    assert seen == {"query": "q", "namespace": "ns", "k": 4}
    assert result.chunks[0].id == "pub-a#0" and result.kb_version == "v1"


async def test_generate_sends_chunks_and_model():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=GENERATE)

    result = await client(handler).generate("q", "ns", [RetrievedChunk(**CHUNK)], "m")
    assert seen["model"] == "m" and seen["chunks"][0]["id"] == "pub-a#0"
    assert result.tokens_in == 10


@pytest.mark.parametrize(("response", "kind"), [
    (httpx.Response(503, json={"error": "rate_limited", "retry_after": 9.0}), "rate_limited"),
    (httpx.Response(504, json={"error": "timeout"}), "timeout"),
    (httpx.Response(502, json={"error": "llm_error", "detail": "x"}), "bad_response"),
    (httpx.Response(500, text="oops"), "bad_response"),
    (httpx.Response(503, text="not json"), "bad_response"),
])
async def test_error_statuses_map_to_kinds(response, kind):
    with pytest.raises(RagError) as exc:
        await client(lambda r: response).generate("q", "ns", [], "m")
    assert exc.value.kind == kind
    if kind == "rate_limited":
        assert exc.value.retry_after == 9.0


async def test_transport_errors():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(RagError) as exc:
        await client(timeout).retrieve("q", "ns", 4)
    assert exc.value.kind == "timeout"
    with pytest.raises(RagError) as exc:
        await client(refused).retrieve("q", "ns", 4)
    assert exc.value.kind == "unavailable"


async def test_health():
    assert await client(lambda r: httpx.Response(200, json={"status": "ok"})).health() is True
    assert await client(lambda r: httpx.Response(503, json={})).health() is False


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"unexpected": "schema"}),
])
async def test_malformed_200_is_bad_response(response):
    with pytest.raises(RagError) as exc:
        await client(lambda r: response).retrieve("q", "ns", 4)
    assert exc.value.kind == "bad_response"


async def test_info_parses_versions():
    body = {"namespaces": {"ns": {"kb_version": "v1", "prompt_version": "p1"}}}
    assert await client(lambda r: httpx.Response(200, json=body)).info() == {"ns": ("v1", "p1")}


@pytest.mark.parametrize("response", [httpx.Response(500, text="x"), httpx.Response(200, json={"oops": 1})])
async def test_info_errors_are_rag_errors(response):
    with pytest.raises(RagError):
        await client(lambda r: response).info()
