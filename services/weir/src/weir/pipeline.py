"""Request pipeline (main spec §5.3, Phase 2 addendum §2).

bypass rules → embed → cache lookup → entity guard → HIT: replay the stored answer
                                                    → MISS/BYPASS: retrieve → generate → store if eligible
Phase 3 replaces _choose_tier with the router.
"""
import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .cache.entities import Lexicon
from .cache.guards import BypassRules, bypass_reason, store_block_reason
from .cache.store import CacheEntry, Candidate
from .cache.versions import VersionCache
from .config import WeirConfig
from .llm.pricing import PriceTable
from .metrics.logger import LogSink, RequestLogRow
from .rag.adapter import RagClient, RagError, RetrievedChunk
from .text import normalize, query_hash

log = logging.getLogger("weir.pipeline")

Tier = Literal["small", "large"]
ERROR_STATUS = {"rate_limited": 503, "timeout": 504, "unavailable": 502, "bad_response": 502}


class QueryOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bypass_cache: bool = False
    force_model: Tier | None = None


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    namespace: str
    session_id: str | None = None
    personalized: bool = False
    options: QueryOptions = QueryOptions()

    @field_validator("query")
    @classmethod
    def strip_and_require(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query is blank")
        return v.strip()


class Source(BaseModel):
    id: str
    title: str


class QueryMeta(BaseModel):
    request_id: str
    cache_status: Literal["hit", "miss", "bypass"]
    similarity: float | None
    route: Literal["none", "small", "large"]
    escalated: bool
    model: str | None
    latency_ms: int
    cost_usd: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    meta: QueryMeta


class PipelineError(Exception):
    def __init__(self, status_code: int, error: str, request_id: str, retry_after: float | None = None):
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.request_id = request_id
        self.retry_after = retry_after


@dataclass
class CacheDeps:
    embedder: Any          # .embed(text) -> np.ndarray, .count_tokens(text) -> int
    versions: VersionCache
    store: Any             # CacheStore or a test double
    writer: Any            # .submit(job)
    lexicon: Lexicon
    rules: BypassRules


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class Pipeline:
    def __init__(self, cfg: WeirConfig, rag: RagClient, prices: PriceTable, log: LogSink, cache: CacheDeps,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._cfg = cfg
        self._rag = rag
        self._prices = prices
        self._log = log
        self._cache = cache
        self._now = now

    async def handle(self, req: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        now = self._now()
        today = now.date()
        normalized = normalize(req.query)
        row = RequestLogRow(
            request_id=uuid4(), ts=now, namespace=req.namespace,
            cache_status="bypass", route="none", status="ok", latency_total_ms=0,
            query_hash=query_hash(req.query),
            query_text=None if self._cfg.is_sensitive(req.namespace) else req.query,
            config_label=self._cfg.config_label,
        )
        reason = bypass_reason(query=req.query, namespace=req.namespace, session_id=req.session_id,
                               personalized=req.personalized, bypass_cache=req.options.bypass_cache,
                               cfg=self._cfg, rules=self._cache.rules)
        versions = None
        if reason is None:
            versions = self._cache.versions.get(req.namespace)
            if versions is None:
                reason = "no_version"
        vector = None
        if reason is None:
            try:
                hit, vector = await asyncio.wait_for(
                    self._lookup(req.namespace, normalized, versions, row),
                    self._cfg.cache.lookup_timeout_ms / 1000)
            except Exception:  # noqa: BLE001 - a cache outage must never become a user outage
                log.exception("cache lookup failed; bypassing the cache")
                reason = "error"
            else:
                if hit is not None:
                    return self._serve_hit(hit, row, started, today)
                row.cache_status = "miss"
        row.bypass_reason = reason

        try:
            t = time.perf_counter()
            retrieved = await self._rag.retrieve(req.query, req.namespace, self._cfg.rag.retrieve_k)
            row.latency_retrieval_ms = _ms(t)
            row.retrieval_top_score = retrieved.top_score
            tier = self._choose_tier(req)
            model = self._cfg.model_for(tier)
            row.route = tier
            t = time.perf_counter()
            generated = await self._rag.generate(req.query, req.namespace, retrieved.chunks, model)
            row.latency_llm_ms = _ms(t)
        except RagError as e:
            row.status = "timeout" if e.kind == "timeout" else "error"
            row.error_detail = str(e)[:500]
            row.latency_total_ms = _ms(started)
            self._log.submit(row)
            raise PipelineError(ERROR_STATUS[e.kind], e.kind, str(row.request_id), e.retry_after) from e
        except Exception as e:  # noqa: BLE001 - any failure still gets a request_id and a log row
            row.status = "error"
            row.error_detail = f"internal: {type(e).__name__}"
            row.latency_total_ms = _ms(started)
            self._log.submit(row)
            raise PipelineError(500, "internal", str(row.request_id)) from e

        if retrieved.kb_version and generated.finish_reason != "skipped":
            # A document edit shows up here first: switch the cache key now, not at the next /info refresh.
            self._cache.versions.observe(req.namespace, retrieved.kb_version, generated.prompt_version)
        row.model = generated.model
        row.model_calls = 0 if generated.finish_reason == "skipped" else 1
        row.tokens_in, row.tokens_out = generated.tokens_in, generated.tokens_out
        row.cost_usd = (self._prices.cost(model, generated.tokens_in, generated.tokens_out, today)
                        + self._embed_cost(row, today))
        row.counterfactual_cost_usd = self._prices.cost(
            self._cfg.router.large_model, generated.tokens_in, generated.tokens_out, today)
        row.answer_len = len(generated.answer)
        sources = _sources(retrieved.chunks, generated.cited_chunk_ids)
        if row.cache_status == "miss":
            row.cache_entry_id = self._maybe_store(req, normalized, vector, versions, retrieved, generated,
                                                   sources, now)
        row.latency_total_ms = _ms(started)
        self._log.submit(row)

        return QueryResponse(
            answer=generated.answer, sources=sources,
            meta=QueryMeta(request_id=str(row.request_id), cache_status=row.cache_status,
                           similarity=row.similarity, route=row.route, escalated=False, model=row.model,
                           latency_ms=row.latency_total_ms, cost_usd=float(row.cost_usd)),
        )

    async def _lookup(self, namespace: str, normalized: str, versions: tuple[str, str],
                      row: RequestLogRow) -> tuple[Candidate | None, Any]:
        kb_version, prompt_version = versions
        t = time.perf_counter()
        vector = await asyncio.to_thread(self._cache.embedder.embed, normalized)
        row.latency_embed_ms = _ms(t)
        row.embed_tokens = self._cache.embedder.count_tokens(normalized)
        t = time.perf_counter()
        candidates = await self._cache.store.lookup(namespace, kb_version, prompt_version, vector,
                                                    self._cfg.cache.candidates)
        row.latency_cache_ms = _ms(t)
        if candidates:
            row.similarity = candidates[0].similarity
        wanted = self._cache.lexicon.extract(normalized)
        for candidate in candidates:  # best first
            if candidate.similarity < self._cfg.cache.threshold:
                break
            if self._cache.lexicon.extract(candidate.query_text) == wanted:
                return candidate, vector
        return None, vector

    def _serve_hit(self, hit: Candidate, row: RequestLogRow, started: float, today) -> QueryResponse:
        row.cache_status = "hit"
        row.similarity = hit.similarity
        row.cache_entry_id = hit.id
        row.route = "none"
        row.model = hit.model
        row.model_calls = 0
        row.cost_usd = self._embed_cost(row, today)
        row.counterfactual_cost_usd = self._prices.cost(self._cfg.router.large_model, hit.tokens_in,
                                                        hit.tokens_out, today)
        row.answer_len = len(hit.answer)
        row.latency_total_ms = _ms(started)
        store, entry_id = self._cache.store, hit.id
        self._cache.writer.submit(lambda: store.increment_hits(entry_id))
        self._log.submit(row)
        return QueryResponse(
            answer=hit.answer, sources=[Source(**s) for s in hit.sources],
            meta=QueryMeta(request_id=str(row.request_id), cache_status="hit", similarity=hit.similarity,
                           route="none", escalated=False, model=hit.model, latency_ms=row.latency_total_ms,
                           cost_usd=float(row.cost_usd)),
        )

    def _maybe_store(self, req, normalized, vector, versions, retrieved, generated, sources, now) -> UUID | None:
        block = store_block_reason(generated=generated, top_score=retrieved.top_score, query=req.query,
                                   min_retrieval_score=self._cfg.cache.min_retrieval_score)
        if block is not None:
            return None
        entry = CacheEntry(
            id=uuid4(), namespace=req.namespace,
            kb_version=retrieved.kb_version or versions[0], prompt_version=generated.prompt_version,
            query_text=normalized, embedding=vector, answer=generated.answer,
            sources=[s.model_dump() for s in sources], source_ids=[s.id for s in sources],
            model=generated.model, tokens_in=generated.tokens_in, tokens_out=generated.tokens_out,
            expires_at=now + timedelta(hours=self._cfg.ttl_hours_for(req.namespace)),
        )
        store = self._cache.store
        self._cache.writer.submit(lambda: store.insert(entry))
        return entry.id

    def _embed_cost(self, row: RequestLogRow, today) -> Decimal:
        if row.embed_tokens is None:
            return Decimal(0)
        return self._prices.cost(self._cfg.cache.embed_model, row.embed_tokens, 0, today)

    def _choose_tier(self, req: QueryRequest) -> Tier:
        if self._cfg.kill_switch.force_large:
            return "large"
        return req.options.force_model or "large"


def _sources(chunks: list[RetrievedChunk], cited_ids: list[str]) -> list[Source]:
    by_id = {c.id: c for c in chunks}
    sources: list[Source] = []
    seen: set[str] = set()
    for chunk_id in cited_ids:
        chunk = by_id.get(chunk_id)
        if chunk and chunk.doc_id not in seen:
            seen.add(chunk.doc_id)
            sources.append(Source(id=chunk.doc_id, title=chunk.title))
    return sources
