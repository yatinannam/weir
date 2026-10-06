import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from weir.cache.entities import Lexicon
from weir.cache.guards import BypassRules
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
                      writer=writer, lexicon=Lexicon.from_yaml(CONFIGS / "entities.yaml"), rules=BypassRules(cfg.bypass))
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
    await h.writer.drain()
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
