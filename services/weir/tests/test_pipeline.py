import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from weir.config import load_config
from weir.llm.pricing import PriceTable
from weir.pipeline import Pipeline, PipelineError, QueryOptions, QueryRequest
from weir.rag.adapter import RagClient

from .conftest import CONFIGS

PUBLIC = "weir-general/en/public"
STAFF = "weir-general/en/staff"
CHUNKS = [
    {"id": "pub-a#0", "doc_id": "pub-a", "title": "Visiting", "text": "t", "score": 0.9, "token_count": 3},
    {"id": "pub-a#1", "doc_id": "pub-a", "title": "Visiting", "text": "t", "score": 0.8, "token_count": 3},
    {"id": "pub-b#0", "doc_id": "pub-b", "title": "ICU", "text": "t", "score": 0.7, "token_count": 3},
]


class ListSink:
    def __init__(self):
        self.rows = []

    def submit(self, row):
        self.rows.append(row)


def fake_rag(generate_response=None, chunks=CHUNKS, seen=None):
    def handler(request):
        body = json.loads(request.content)
        if request.url.path == "/retrieve":
            return httpx.Response(200, json={"chunks": chunks, "top_score": 0.9, "score_gap": 0.1,
                                             "context_tokens": 9, "kb_version": "v1", "latency_ms": 3})
        if seen is not None:
            seen.append(body)
        if generate_response is not None:
            return generate_response
        cited = ["pub-a#1", "pub-b#0", "pub-a#0"] if body["chunks"] else []
        return httpx.Response(200, json={
            "answer": "Answer." if body["chunks"] else "Sorry, not found.", "cited_chunk_ids": cited,
            "invalid_citations": 0, "not_found": not body["chunks"],
            "finish_reason": "stop" if body["chunks"] else "skipped",
            "tokens_in": 1000 if body["chunks"] else 0, "tokens_out": 500 if body["chunks"] else 0,
            "model": body["model"], "prompt_version": "p1", "latency_ms": 7})
    return RagClient("http://rag", 5, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag"))


def pipeline(rag, overlay=None, **config_overrides):
    cfg = load_config(CONFIGS / "weir.yaml", overlay)
    for path, value in config_overrides.items():
        section, key = path.split("__")
        setattr(getattr(cfg, section), key, value)
    sink = ListSink()
    fixed_now = lambda: datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # noqa: E731
    return Pipeline(cfg, rag, PriceTable.from_yaml(CONFIGS / "prices.yaml"), sink, now=fixed_now), sink


async def test_happy_path_large_with_cost_and_log():
    p, sink = pipeline(fake_rag())
    resp = await p.handle(QueryRequest(query="  When can I visit? ", namespace=PUBLIC))
    assert resp.answer == "Answer."
    assert [s.id for s in resp.sources] == ["pub-a", "pub-b"]  # dedup by doc, citation order
    assert resp.meta.cache_status == "bypass" and resp.meta.route == "large"
    assert resp.meta.model == "openai/gpt-oss-120b"
    assert resp.meta.cost_usd == pytest.approx(0.00045)
    [row] = sink.rows
    assert row.bypass_reason == "cache_disabled" and row.status == "ok"
    assert row.cost_usd == Decimal("0.00045") == row.counterfactual_cost_usd
    assert (row.tokens_in, row.tokens_out, row.model_calls) == (1000, 500, 1)
    assert row.query_text == "When can I visit?" and row.config_label == "dev"
    assert str(row.request_id) == resp.meta.request_id


async def test_force_small_is_cheaper_than_counterfactual():
    seen = []
    p, sink = pipeline(fake_rag(seen=seen))
    resp = await p.handle(QueryRequest(query="q", namespace=PUBLIC, options=QueryOptions(force_model="small")))
    assert seen[0]["model"] == "openai/gpt-oss-20b" and resp.meta.route == "small"
    [row] = sink.rows
    # small: 1000*0.075 + 500*0.30 = 225 per 1e6; counterfactual at large prices = 450 per 1e6
    assert row.cost_usd == Decimal("0.000225") and row.counterfactual_cost_usd == Decimal("0.00045")


async def test_kill_switch_force_large_beats_force_model():
    seen = []
    p, _ = pipeline(fake_rag(seen=seen), overlay=CONFIGS / "ablations" / "baseline.yaml")
    resp = await p.handle(QueryRequest(query="q", namespace=PUBLIC, options=QueryOptions(force_model="small")))
    assert resp.meta.route == "large" and seen[0]["model"] == "openai/gpt-oss-120b"


@pytest.mark.parametrize(("request_kwargs", "overrides", "reason"), [
    ({"personalized": True}, {}, "personalized"),
    ({"options": QueryOptions(bypass_cache=True)}, {}, "request_option"),
    ({}, {"kill_switch__disable_cache": True}, "kill_switch"),
    ({}, {}, "cache_disabled"),
])
async def test_bypass_reasons(request_kwargs, overrides, reason):
    p, sink = pipeline(fake_rag(), **overrides)
    await p.handle(QueryRequest(query="q", namespace=PUBLIC, **request_kwargs))
    assert sink.rows[0].bypass_reason == reason


async def test_sensitive_namespace_logs_no_query_text():
    p, sink = pipeline(fake_rag())
    await p.handle(QueryRequest(query="How do I register a patient?", namespace=STAFF))
    assert sink.rows[0].query_text is None
    assert len(sink.rows[0].query_hash) == 64


async def test_no_chunks_returns_not_found_answer():
    p, sink = pipeline(fake_rag(chunks=[]))
    resp = await p.handle(QueryRequest(query="q", namespace=PUBLIC))
    assert resp.sources == [] and resp.answer == "Sorry, not found."
    assert sink.rows[0].model_calls == 0 and sink.rows[0].cost_usd == 0


async def test_rate_limited_generate_raises_503_and_logs_error():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    p, sink = pipeline(fake_rag(generate_response=limited))
    with pytest.raises(PipelineError) as exc:
        await p.handle(QueryRequest(query="q", namespace=PUBLIC))
    assert exc.value.status_code == 503 and exc.value.retry_after == 12.0
    assert exc.value.request_id == str(sink.rows[0].request_id)
    assert sink.rows[0].status == "error" and "rate_limited" in sink.rows[0].error_detail


async def test_timeout_maps_to_504_and_status_timeout():
    p, sink = pipeline(fake_rag(generate_response=httpx.Response(504, json={"error": "timeout"})))
    with pytest.raises(PipelineError) as exc:
        await p.handle(QueryRequest(query="q", namespace=PUBLIC))
    assert exc.value.status_code == 504 and sink.rows[0].status == "timeout"


def test_blank_query_rejected():
    with pytest.raises(ValueError):
        QueryRequest(query="   ", namespace=PUBLIC)
