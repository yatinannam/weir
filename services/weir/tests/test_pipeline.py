import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from weir.cache.entities import Lexicon
from weir.cache.guards import BypassRules
from weir.cache.hits import HitCounter
from weir.cache.versions import VersionCache
from weir.config import WeirConfig, load_config
from weir.llm.pricing import PriceTable
from weir.pipeline import CacheDeps, Pipeline, PipelineError, QueryOptions, QueryRequest
from weir.rag.adapter import RagClient

from .conftest import CONFIGS
from .fakes import FakeEmbedder, FakeStore, InlineQueue, ListSink

PUBLIC = "weir-general/en/public"
STAFF = "weir-general/en/staff"
CHUNKS = [
    {"id": "pub-a#0", "doc_id": "pub-a", "title": "Visiting", "text": "Answer text", "score": 0.9, "token_count": 3},
    {"id": "pub-a#1", "doc_id": "pub-a", "title": "Visiting", "text": "Answer text", "score": 0.8, "token_count": 3},
    {"id": "pub-b#0", "doc_id": "pub-b", "title": "ICU", "text": "Answer text", "score": 0.7, "token_count": 3},
]
SMALL, LARGE = "openai/gpt-oss-20b", "openai/gpt-oss-120b"
UNGROUNDED = "Something unrelated entirely."
LIMITED = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
# Router on, with cut-offs pinned so offline tuning (Task 10) never changes these tests.
ROUTER_ON = dict(router__enabled=True, router__short_query_tokens=20, router__high_confidence=0.75,
                 router__low_confidence=0.40, router__max_model_calls=2, grounding__min_overlap=0.5)
VERSIONS = {PUBLIC: ("v1", "p1"), STAFF: ("v1", "p1")}
FIXED_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def fake_rag(generate_response=None, chunks=CHUNKS, seen=None, calls=None, top_score=0.9, cited=None, answer="Answer.",
             answers=None, responses=None):
    def handler(request):
        if calls is not None:
            calls.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path == "/retrieve":
            return httpx.Response(200, json={"chunks": chunks, "top_score": top_score if chunks else 0.0,
                                             "score_gap": 0.1, "context_tokens": 9,
                                             "kb_version": "v1" if chunks else None, "latency_ms": 3})
        if seen is not None:
            seen.append(body)
        per_model = (responses or {}).get(body["model"])
        if isinstance(per_model, Exception):
            raise per_model
        if per_model is not None:  # a fresh copy: one Response object must not be served twice
            return httpx.Response(per_model.status_code, content=per_model.content, headers=per_model.headers)
        if generate_response is not None:
            return generate_response
        has = bool(body["chunks"])
        ids = (["pub-a#1", "pub-b#0", "pub-a#0"] if cited is None else cited) if has else []
        text = (answers or {}).get(body["model"], answer)
        return httpx.Response(200, json={
            "answer": text if has else "Sorry, not found.", "cited_chunk_ids": ids, "invalid_citations": 0,
            "not_found": not has, "finish_reason": "stop" if has else "skipped",
            "tokens_in": 1000 if has else 0, "tokens_out": 500 if has else 0,
            "model": body["model"], "prompt_version": "p1", "latency_ms": 7})
    return RagClient("http://rag", 5, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag"))


@dataclass
class Harness:
    p: Pipeline
    sink: ListSink
    store: FakeStore
    writer: InlineQueue
    embedder: FakeEmbedder
    cfg: WeirConfig


def harness(rag, overlay=None, versions=VERSIONS, aliases=None, **config_overrides) -> Harness:
    config_overrides.setdefault("router__enabled", False)  # Phase 2 tests; router tests pass ROUTER_ON
    cfg = load_config(CONFIGS / "weir.yaml", overlay)
    for path, value in config_overrides.items():
        section, key = path.split("__")
        setattr(getattr(cfg, section), key, value)
    sink, store, writer, embedder = ListSink(), FakeStore(now=lambda: FIXED_NOW), InlineQueue(), FakeEmbedder(aliases)
    cache = CacheDeps(embedder=embedder, versions=VersionCache(fetch=None, initial=versions), store=store,
                      writer=writer, lexicon=Lexicon.from_yaml(CONFIGS / "entities.yaml"), rules=BypassRules(cfg.bypass),
                      hits=HitCounter(store))
    p = Pipeline(cfg, rag, PriceTable.from_yaml(CONFIGS / "prices.yaml"), sink, cache, now=lambda: FIXED_NOW)
    return Harness(p, sink, store, writer, embedder, cfg)


def ask(query, namespace=PUBLIC, **kwargs):
    return QueryRequest(query=query, namespace=namespace, **kwargs)


# --- miss / hit -------------------------------------------------------------------------------

async def test_first_ask_is_a_miss_with_cost_log_and_store():
    h = harness(fake_rag())
    resp = await h.p.handle(ask("  When can I visit? "))
    assert resp.answer == "Answer." and [s.id for s in resp.sources] == ["pub-a", "pub-b"]
    assert resp.meta.cache_status == "miss" and resp.meta.route == "large"
    [row] = h.sink.rows
    assert row.route_reason == "router_disabled" and row.model_calls == 1 and row.escalated is False
    assert row.grounding_passed is True and row.grounding_reason is None and row.grounding_overlap == 1.0
    assert row.bypass_reason is None and row.status == "ok" and row.embed_tokens == 4
    assert row.cost_usd == Decimal("0.00045") == row.counterfactual_cost_usd
    assert row.query_text == "When can I visit?" and row.config_label == "dev"
    await h.writer.drain()
    [entry] = h.store.entries
    assert row.cache_entry_id == entry.id and entry.query_text == "when can i visit?"
    assert entry.source_ids == ["pub-a", "pub-b"] and (entry.tokens_in, entry.tokens_out) == (1000, 500)
    assert entry.kb_version == "v1" and entry.prompt_version == "p1"


async def test_identical_question_hits_without_calling_rag():
    calls = []
    h = harness(fake_rag(calls=calls))
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    resp = await h.p.handle(ask("when can i VISIT?"))
    assert resp.meta.cache_status == "hit" and resp.meta.route == "none" and resp.answer == "Answer."
    assert resp.meta.similarity == pytest.approx(1.0) and [s.id for s in resp.sources] == ["pub-a", "pub-b"]
    assert calls.count("/retrieve") == 1 and calls.count("/generate") == 1
    hit = h.sink.rows[1]
    assert hit.cost_usd == 0 and hit.counterfactual_cost_usd == Decimal("0.00045")
    assert hit.model_calls == 0 and hit.cache_entry_id == h.store.entries[0].id
    await h.p._cache.hits.flush()
    assert h.store.hits == {h.store.entries[0].id: 1}


async def test_paraphrase_with_same_entities_hits():
    h = harness(fake_rag(), aliases={"what are the visiting hours?": "when can i visit?"})
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    assert (await h.p.handle(ask("What are the visiting hours?"))).meta.cache_status == "hit"


async def test_look_alike_with_different_entities_misses():
    calls = []
    h = harness(fake_rag(calls=calls),
                aliases={"what are the icu visiting hours?": "what are the general ward visiting hours?"})
    await h.p.handle(ask("What are the general ward visiting hours?"))
    await h.writer.drain()
    resp = await h.p.handle(ask("What are the ICU visiting hours?"))
    assert resp.meta.cache_status == "miss" and calls.count("/generate") == 2
    assert h.sink.rows[1].similarity == pytest.approx(1.0)  # embedding said "same"; the guard said no


async def test_below_threshold_misses_and_logs_similarity():
    h = harness(fake_rag())
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    resp = await h.p.handle(ask("How much is parking?"))
    assert resp.meta.cache_status == "miss" and h.sink.rows[1].similarity < 0.5


async def test_version_change_misses():
    h = harness(fake_rag())
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    h.p._cache.versions = VersionCache(fetch=None, initial={PUBLIC: ("v2", "p1")})
    assert (await h.p.handle(ask("When can I visit?"))).meta.cache_status == "miss"


async def test_sensitive_namespace_hit_logs_no_query_text():
    h = harness(fake_rag())
    await h.p.handle(ask("How do I register a patient?", namespace=STAFF))
    await h.writer.drain()
    await h.p.handle(ask("How do I register a patient?", namespace=STAFF))
    assert [r.cache_status for r in h.sink.rows] == ["miss", "hit"]
    assert all(r.query_text is None and len(r.query_hash) == 64 for r in h.sink.rows)


# --- bypass -----------------------------------------------------------------------------------

@pytest.mark.parametrize(("request_kwargs", "overrides", "reason"), [
    ({"personalized": True}, {}, "personalized"),
    ({"options": QueryOptions(bypass_cache=True)}, {}, "request_option"),
    ({}, {"kill_switch__disable_cache": True}, "kill_switch"),
    ({}, {"cache__enabled": False}, "cache_disabled"),
])
async def test_bypass_reasons_from_request_and_config(request_kwargs, overrides, reason):
    h = harness(fake_rag(), **overrides)
    resp = await h.p.handle(ask("When can I visit?", **request_kwargs))
    assert resp.meta.cache_status == "bypass" and h.sink.rows[0].bypass_reason == reason
    await h.writer.drain()
    assert h.store.entries == []


@pytest.mark.parametrize(("query", "kwargs", "reason"), [
    ("What dosage of paracetamol is safe?", {}, "clinical"),
    ("Is the pharmacy open now?", {}, "time_sensitive"),
    ("what about weekends?", {"session_id": "s1"}, "followup"),
])
async def test_bypass_reasons_from_question_text(query, kwargs, reason):
    h = harness(fake_rag())
    await h.p.handle(ask(query, **kwargs))
    assert h.sink.rows[0].bypass_reason == reason


async def test_namespace_disabled():
    h = harness(fake_rag())
    h.cfg.namespaces[PUBLIC].cache.enabled = False
    await h.p.handle(ask("When can I visit?"))
    assert h.sink.rows[0].bypass_reason == "namespace_disabled"


async def test_no_version_bypasses_cache():
    h = harness(fake_rag(), versions={})
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and h.sink.rows[0].bypass_reason == "no_version"


async def test_embedder_failure_bypasses():
    h = harness(fake_rag())
    h.embedder.fail = True
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and h.sink.rows[0].bypass_reason == "error"


async def test_lookup_failure_bypasses():
    h = harness(fake_rag())
    h.store.fail_lookup = True
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and h.sink.rows[0].bypass_reason == "error"


# --- write-back eligibility -------------------------------------------------------------------

@pytest.mark.parametrize("rag_kwargs", [
    {"chunks": []},                       # not found
    {"cited": []},                        # no citations
    {"top_score": 0.1},                   # weak retrieval
    {"answer": "Call 98765 43210."},      # personal data
])
async def test_ineligible_answers_are_not_stored(rag_kwargs):
    h = harness(fake_rag(**rag_kwargs))
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    assert h.store.entries == [] and h.sink.rows[0].cache_entry_id is None


# --- Phase 1 behaviour kept -------------------------------------------------------------------

async def test_force_small_is_cheaper_than_counterfactual_and_bypasses_cache():
    seen = []
    h = harness(fake_rag(seen=seen))
    resp = await h.p.handle(ask("q", options=QueryOptions(force_model="small")))
    assert seen[0]["model"] == SMALL and resp.meta.route == "small"
    row = h.sink.rows[0]
    assert row.cost_usd == Decimal("0.000225") and row.counterfactual_cost_usd == Decimal("0.00045")
    assert row.bypass_reason == "force_model" and row.route_reason == "force_model"
    await h.writer.drain()
    assert h.store.entries == []  # D35: forced answers are never cached (backlog M9)


async def test_kill_switch_force_large_beats_force_model():
    seen = []
    h = harness(fake_rag(seen=seen), overlay=CONFIGS / "ablations" / "baseline.yaml")
    resp = await h.p.handle(ask("q", options=QueryOptions(force_model="small")))
    assert resp.meta.route == "large" and seen[0]["model"] == "openai/gpt-oss-120b"
    assert h.sink.rows[0].bypass_reason == "force_model" and h.sink.rows[0].route_reason == "kill_switch"


async def test_no_chunks_returns_not_found_answer():
    h = harness(fake_rag(chunks=[]))
    resp = await h.p.handle(ask("q"))
    assert resp.sources == [] and resp.answer == "Sorry, not found."
    assert h.sink.rows[0].model_calls == 0 and h.sink.rows[0].cost_usd == 0


async def test_rate_limited_generate_raises_503_and_logs_error():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    h = harness(fake_rag(generate_response=limited))
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("q"))
    assert exc.value.status_code == 503 and exc.value.retry_after == 12.0
    assert exc.value.request_id == str(h.sink.rows[0].request_id)
    assert h.sink.rows[0].status == "error" and "rate_limited" in h.sink.rows[0].error_detail


async def test_timeout_maps_to_504_and_status_timeout():
    h = harness(fake_rag(generate_response=httpx.Response(504, json={"error": "timeout"})))
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("q"))
    assert exc.value.status_code == 504 and h.sink.rows[0].status == "timeout"


class ExplodingRag:
    async def retrieve(self, *args):
        raise RuntimeError("boom")


async def test_unexpected_error_returns_500_with_request_id_and_logs():
    h = harness(ExplodingRag())
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("q"))
    assert exc.value.status_code == 500 and exc.value.error == "internal"
    [row] = h.sink.rows
    assert row.status == "error" and row.error_detail == "internal: RuntimeError"


def test_blank_query_rejected():
    with pytest.raises(ValueError):
        QueryRequest(query="   ", namespace=PUBLIC)


async def test_hung_lookup_times_out_and_bypasses_quickly():  # final-review finding I2
    import time

    h = harness(fake_rag())
    h.store.hang_lookup = True
    h.cfg.cache.lookup_timeout_ms = 50
    started = time.perf_counter()
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and h.sink.rows[0].bypass_reason == "error"
    assert time.perf_counter() - started < 2


async def test_miss_reveals_new_kb_version_and_stops_old_hits():  # final-review finding I3
    def rag_v(kb):
        client = fake_rag()
        orig = client.retrieve

        async def retrieve(*a, **kw):
            r = await orig(*a, **kw)
            return r.model_copy(update={"kb_version": kb})
        client.retrieve = retrieve
        return client

    h = harness(rag_v("v1"))
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()                                   # entry stored under v1
    h.p._rag = rag_v("v2")                                   # documents re-ingested
    await h.p.handle(ask("How much is parking?"))            # any miss reveals v2
    assert h.p._cache.versions.get(PUBLIC) == ("v2", "p1")
    assert (await h.p.handle(ask("When can I visit?"))).meta.cache_status == "miss"


# --- router (Phase 3) -------------------------------------------------------------------------

async def test_simple_question_goes_small_and_is_cached():
    seen = []
    h = harness(fake_rag(seen=seen), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL]
    assert resp.meta.route == "small" and resp.meta.model == SMALL and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.route_reason == "simple" and row.model_calls == 1 and row.grounding_passed is True
    assert row.cost_usd == Decimal("0.000225") and row.counterfactual_cost_usd == Decimal("0.00045")
    await h.writer.drain()
    [entry] = h.store.entries
    assert entry.model == SMALL


async def test_ungrounded_small_answer_escalates_to_large():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL, LARGE]
    assert resp.answer == "Answer." and resp.meta.route == "small" and resp.meta.escalated is True
    assert resp.meta.model == LARGE
    row = h.sink.rows[0]
    assert row.route_reason == "simple" and row.escalated is True and row.model_calls == 2
    assert (row.tokens_in, row.tokens_out) == (2000, 1000)
    assert row.cost_usd == Decimal("0.000675")                 # small + large calls
    assert row.counterfactual_cost_usd == Decimal("0.00045")   # the answering (large) call at the large price
    assert row.grounding_passed is True                        # the large answer's check


async def test_answer_that_fails_grounding_is_returned_but_never_cached():
    h = harness(fake_rag(answer=UNGROUNDED), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == UNGROUNDED and resp.meta.escalated is True
    row = h.sink.rows[0]
    assert row.grounding_passed is False and row.grounding_reason == "low_overlap" and row.grounding_overlap == 0.0
    await h.writer.drain()
    assert h.store.entries == [] and row.cache_entry_id is None


@pytest.mark.parametrize("query", [
    "Why are ICU visits limited to two people?",          # reasoning word
    "When can I visit and how much is parking?",          # two questions
])
async def test_harder_questions_go_large(query):
    seen = []
    h = harness(fake_rag(seen=seen), **ROUTER_ON)
    resp = await h.p.handle(ask(query))
    assert [b["model"] for b in seen] == [LARGE] and resp.meta.route == "large"
    assert h.sink.rows[0].route_reason == "default_large"


async def test_weak_retrieval_goes_large():
    h = harness(fake_rag(top_score=0.3), **ROUTER_ON)
    await h.p.handle(ask("When can I visit?"))
    assert h.sink.rows[0].route == "large" and h.sink.rows[0].route_reason == "weak_retrieval"


async def test_clinical_question_goes_large():
    h = harness(fake_rag(), **ROUTER_ON)
    await h.p.handle(ask("What dosage of paracetamol is safe?"))
    row = h.sink.rows[0]
    assert row.route == "large" and row.route_reason == "clinical" and row.bypass_reason == "clinical"


async def test_skipped_small_call_never_escalates():  # Review Focus 3
    calls = []
    h = harness(fake_rag(chunks=[], calls=calls), **{**ROUTER_ON, "router__low_confidence": 0.0,
                                                     "router__high_confidence": 0.0})
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.meta.route == "small" and resp.meta.escalated is False and calls.count("/generate") == 1
    row = h.sink.rows[0]
    assert row.model_calls == 0 and row.cost_usd == 0 and row.grounding_reason == "not_found"


async def test_rate_limited_small_falls_back_to_large():  # Review Focus 1
    seen = []
    h = harness(fake_rag(seen=seen, responses={SMALL: LIMITED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL, LARGE]
    assert resp.answer == "Answer." and resp.meta.model == LARGE and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.route == "small" and row.route_reason == "simple+fallback" and row.model_calls == 2
    assert row.cost_usd == Decimal("0.00045") and row.status == "ok"   # only the answering call is billed


async def test_fallback_to_small_never_makes_a_third_call():
    seen = []
    h = harness(fake_rag(seen=seen, top_score=0.3, responses={LARGE: LIMITED}, answers={SMALL: UNGROUNDED}),
                **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [LARGE, SMALL]          # cap of 2: no escalation after the fallback
    assert resp.answer == UNGROUNDED and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.route_reason == "weak_retrieval+fallback" and row.model_calls == 2
    await h.writer.drain()
    assert h.store.entries == []


async def test_both_tiers_failing_returns_503_with_request_id():
    seen = []
    h = harness(fake_rag(seen=seen, responses={SMALL: LIMITED, LARGE: LIMITED}), **ROUTER_ON)
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("When can I visit?"))
    assert exc.value.status_code == 503 and exc.value.retry_after == 12.0
    assert len(seen) == 2 and exc.value.request_id == str(h.sink.rows[0].request_id)
    row = h.sink.rows[0]
    assert row.status == "error" and row.model_calls == 2
    assert row.route_reason == "simple+fallback"                 # final review I1: the attempt is visible
    assert "fallback_after:rate_limited" in row.error_detail      # and the first tier's error is kept


async def test_failed_escalation_returns_the_small_answer():  # Review Focus 2
    h = harness(fake_rag(answers={SMALL: UNGROUNDED}, responses={LARGE: LIMITED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == UNGROUNDED and resp.meta.model == SMALL and resp.meta.escalated is False
    row = h.sink.rows[0]
    assert row.status == "ok" and row.error_detail == "escalation_failed:rate_limited" and row.model_calls == 2
    assert row.cost_usd == Decimal("0.000225")
    await h.writer.drain()
    assert h.store.entries == []


async def test_max_model_calls_one_disables_fallback_and_escalation():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), **{**ROUTER_ON, "router__max_model_calls": 1})
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL] and resp.meta.escalated is False


async def test_unreachable_rag_does_not_fall_back():
    seen = []
    h = harness(fake_rag(seen=seen, responses={SMALL: httpx.ConnectError("down")}), **ROUTER_ON)
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("When can I visit?"))
    assert exc.value.status_code == 502 and len(seen) == 1


async def test_force_model_small_with_router_on_never_escalates():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?", options=QueryOptions(force_model="small")))
    assert [b["model"] for b in seen] == [SMALL] and resp.meta.escalated is False
    assert h.sink.rows[0].route_reason == "force_model" and h.sink.rows[0].bypass_reason == "force_model"


async def test_kill_switch_force_large_never_falls_back():
    seen = []
    h = harness(fake_rag(seen=seen, responses={LARGE: LIMITED}), **{**ROUTER_ON, "kill_switch__force_large": True})
    with pytest.raises(PipelineError):
        await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [LARGE] and h.sink.rows[0].route_reason == "kill_switch"


async def test_disabled_router_uses_default_tier_without_escalation():
    seen = []
    h = harness(fake_rag(seen=seen, answers={SMALL: UNGROUNDED}), router__default_tier="small")
    resp = await h.p.handle(ask("When can I visit?"))
    assert [b["model"] for b in seen] == [SMALL] and resp.answer == UNGROUNDED
    row = h.sink.rows[0]
    assert row.route_reason == "router_disabled" and row.grounding_reason == "low_overlap"


async def test_fallback_down_to_small_is_not_cached():  # D40: a degraded answer must not outlive the outage
    h = harness(fake_rag(top_score=0.3, responses={LARGE: LIMITED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.answer == "Answer." and resp.meta.model == SMALL and h.sink.rows[0].grounding_passed is True
    await h.writer.drain()
    assert h.store.entries == [] and h.sink.rows[0].cache_entry_id is None


async def test_fallback_up_to_large_is_cached():
    h = harness(fake_rag(responses={SMALL: LIMITED}), **ROUTER_ON)
    resp = await h.p.handle(ask("When can I visit?"))
    assert resp.meta.model == LARGE
    await h.writer.drain()
    [entry] = h.store.entries
    assert entry.model == LARGE


# --- Phase 6A: response additions for the demo page -----------------------------------------------

async def test_meta_carries_the_counterfactual_cost_on_miss_and_hit():
    h = harness(fake_rag())
    miss = await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    hit = await h.p.handle(ask("When can I visit?"))
    assert miss.meta.counterfactual_cost_usd == pytest.approx(0.00045) == miss.meta.cost_usd   # router off: large
    assert hit.meta.cost_usd == 0 and hit.meta.counterfactual_cost_usd == pytest.approx(0.00045)


async def test_guard_refused_only_for_a_look_alike_at_or_above_the_threshold():
    h = harness(fake_rag(), aliases={"what are the icu visiting hours?": "what are the general ward visiting hours?"})
    first = await h.p.handle(ask("What are the general ward visiting hours?"))           # empty cache
    await h.writer.drain()
    refused = await h.p.handle(ask("What are the ICU visiting hours?"))                    # same vector, other ward
    await h.writer.drain()
    unrelated = await h.p.handle(ask("How much is parking?"))                              # below the threshold
    hit = await h.p.handle(ask("What are the general ward visiting hours?"))
    skipped = await h.p.handle(ask("What are the ICU visiting hours?", options=QueryOptions(bypass_cache=True)))
    assert refused.meta.cache_status == "miss" and refused.meta.guard_refused is True
    assert refused.meta.similarity == pytest.approx(1.0)
    for resp in (first, unrelated, hit, skipped):
        assert resp.meta.guard_refused is False


async def test_meta_flags_an_answer_from_the_fallback_tier():  # Phase 6A final review I2
    # route stays the router's decision; without the flag the demo page labelled a fallback as the routed tier
    fell_back = await harness(fake_rag(responses={SMALL: LIMITED}), **ROUTER_ON).p.handle(ask("When can I visit?"))
    normal = await harness(fake_rag(), **ROUTER_ON).p.handle(ask("When can I visit?"))
    assert fell_back.meta.route == "small" and fell_back.meta.model == LARGE and fell_back.meta.fallback is True
    assert normal.meta.route == "small" and normal.meta.fallback is False


# --- M31: overload. A failed cache lookup normally falls through to retrieval and a model, but when many
# requests are already on that path the machine is saturated, and falling through feeds the overload.

def slow_rag():
    """A RAG client whose retrieval waits until released, so requests stay on the model path."""
    client = fake_rag()
    client.release = asyncio.Event()
    orig = client.retrieve

    async def retrieve(*a, **kw):
        await client.release.wait()
        return await orig(*a, **kw)
    client.retrieve = retrieve
    return client


async def test_a_failed_lookup_bypasses_while_the_model_path_is_quiet():  # D51: a slow cache stays invisible
    h = harness(fake_rag())
    h.cfg.cache.lookup_timeout_ms = 50
    h.store.hang_lookup = True
    resp = await h.p.handle(ask("When can I visit?"))
    [row] = h.sink.rows
    assert resp.answer == "Answer." and row.bypass_reason == "error" and row.status == "ok"


async def test_failed_lookups_are_shed_once_the_model_path_is_full():
    rag = slow_rag()
    h = harness(rag)
    h.cfg.cache.overload_inflight = 2
    h.store.fail_lookup = True
    waiting = [asyncio.create_task(h.p.handle(ask(q))) for q in ("When can I visit?", "How much is parking?")]
    await asyncio.sleep(0.05)                                   # both bypassed and are now retrieving
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("Where is the ICU?"))
    assert (exc.value.status_code, exc.value.error, exc.value.retry_after) == (503, "overloaded", 1)
    shed = h.sink.rows[-1]
    assert shed.status == "shed" and shed.bypass_reason == "overloaded" and shed.route == "none"
    assert shed.latency_retrieval_ms is None and shed.model_calls == 0 and shed.cost_usd == 0
    assert exc.value.request_id == str(shed.request_id)
    rag.release.set()
    assert [r.answer for r in await asyncio.gather(*waiting)] == ["Answer.", "Answer."]
    assert h.p._model_path == 0


async def test_cache_hits_are_served_when_the_model_path_is_full():  # shedding never touches a working cache
    h = harness(fake_rag())
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()
    h.cfg.cache.overload_inflight = 1
    h.p._model_path = 5
    assert (await h.p.handle(ask("When can I visit?"))).meta.cache_status == "hit"


async def test_zero_turns_shedding_off():
    h = harness(fake_rag())
    h.cfg.cache.overload_inflight = 0
    h.store.fail_lookup = True
    h.p._model_path = 1000
    assert (await h.p.handle(ask("When can I visit?"))).answer == "Answer."
    h.p._model_path = 0


async def test_the_model_path_count_goes_back_down_after_errors():
    h = harness(fake_rag(generate_response=httpx.Response(504, json={"error": "timeout"})))
    with pytest.raises(PipelineError):
        await h.p.handle(ask("When can I visit?"))
    assert h.p._model_path == 0


async def test_lookups_beyond_the_cap_are_shed_before_any_embedding():  # the front door (D75)
    h = harness(fake_rag())
    h.cfg.cache.max_lookups = 2
    h.p._lookups = 2                                             # two lookups already running
    with pytest.raises(PipelineError) as exc:
        await h.p.handle(ask("When can I visit?"))
    assert (exc.value.status_code, exc.value.error) == (503, "overloaded")
    [row] = h.sink.rows
    assert row.status == "shed" and row.error_detail == "overloaded: too many cache lookups running"
    assert row.latency_embed_ms is None and row.embed_tokens is None and row.latency_retrieval_ms is None
    h.p._lookups = 0


async def test_the_lookup_count_goes_back_down_after_hits_misses_and_timeouts():
    h = harness(fake_rag())
    h.cfg.cache.max_lookups = 1                                  # one at a time: a leak would shed the next one
    await h.p.handle(ask("When can I visit?"))                   # miss
    await h.writer.drain()
    await h.p.handle(ask("When can I visit?"))                   # hit
    h.cfg.cache.lookup_timeout_ms = 50
    h.store.hang_lookup = True
    await h.p.handle(ask("How much is parking?"))                # timeout, bypass
    assert h.p._lookups == 0 and [r.status for r in h.sink.rows] == ["ok", "ok", "ok"]


async def test_requests_that_skip_the_cache_by_rule_are_never_shed_at_the_door():
    h = harness(fake_rag())
    h.cfg.cache.max_lookups = 1
    h.p._lookups = 1
    resp = await h.p.handle(ask("When can I visit?", options=QueryOptions(bypass_cache=True)))
    assert resp.answer == "Answer." and h.sink.rows[0].status == "ok"
    h.p._lookups = 0


async def test_hits_on_one_entry_coalesce_into_one_write():  # D76: no per-hit UPDATE, nothing queued per hit
    h = harness(fake_rag())
    await h.p.handle(ask("When can I visit?"))
    await h.writer.drain()                                       # the miss stored its entry
    for _ in range(5):
        await h.p.handle(ask("When can I visit?"))
    assert h.writer.jobs == []                                   # hits queue nothing
    await h.p._cache.hits.flush()
    await h.p._cache.hits.flush()                                # nothing pending: no second write
    assert h.store.hits == {h.store.entries[0].id: 5}


# --- D79: coverage check. A small answer missing the asked-for kind of detail escalates once.

CAMP_CHUNKS = [{"id": "pub-blood-bank#0", "doc_id": "pub-blood-bank", "title": "Blood bank",
                "text": "The blood donation camp is held on the first Saturday of every month, 10 am to 3 pm, "
                        "in the lobby.", "score": 0.95, "token_count": 25}]
CAMP_Q = "When is the blood donation camp held?"
DAY_ONLY = "It is held on the first Saturday of every month [c1]."
FULL = "First Saturday of every month, 10 am to 3 pm [c1]."


def camp_rag(small=DAY_ONLY, large=FULL):
    return fake_rag(chunks=CAMP_CHUNKS, top_score=0.95, cited=["pub-blood-bank#0"], answers={SMALL: small, LARGE: large})


async def test_a_small_answer_missing_the_time_escalates_once():
    h = harness(camp_rag(), **ROUTER_ON)
    resp = await h.p.handle(ask(CAMP_Q))
    [row] = h.sink.rows
    assert row.route == "small" and resp.meta.escalated and "10 am" in resp.answer
    assert row.escalated_for == "coverage" and row.coverage_passed is True and row.model_calls == 2


async def test_coverage_off_never_escalates_and_logs_nothing():  # Review Focus 5
    h = harness(camp_rag(), **ROUTER_ON)
    h.cfg.router.coverage_check = False
    resp = await h.p.handle(ask(CAMP_Q))
    [row] = h.sink.rows
    assert not resp.meta.escalated and row.coverage_passed is None and row.escalated_for is None


async def test_grounding_failure_is_named_first():  # Review Focus 4
    h = harness(camp_rag(small=UNGROUNDED), **ROUTER_ON)
    await h.p.handle(ask(CAMP_Q))
    assert h.sink.rows[0].escalated_for == "grounding"


async def test_a_large_answer_missing_detail_is_logged_not_recalled():
    h = harness(camp_rag(large="It is held on the first Saturday [c1]."), **ROUTER_ON)
    h.cfg.kill_switch.force_large = True
    resp = await h.p.handle(ask(CAMP_Q))
    [row] = h.sink.rows
    assert not resp.meta.escalated and row.model_calls == 1
    assert row.coverage_passed is False and row.coverage_reason == "missing:time"


async def test_a_not_found_answer_is_left_to_grounding():  # D79: coverage never judges a refusal
    h = harness(camp_rag(), **ROUTER_ON)
    h.p._rag = fake_rag(chunks=CAMP_CHUNKS, top_score=0.95, cited=[], generate_response=httpx.Response(200, json={
        "answer": "Sorry, I couldn't find that in Weir General Hospital's information.", "cited_chunk_ids": [],
        "invalid_citations": 0, "not_found": True, "finish_reason": "stop", "tokens_in": 100, "tokens_out": 10,
        "model": SMALL, "prompt_version": "p1", "latency_ms": 5}))
    await h.p.handle(ask(CAMP_Q))
    [row] = h.sink.rows
    assert row.escalated_for == "grounding" and row.coverage_passed is None
