"""Request pipeline. Phase 0/1: no cache, no router — retrieve, generate, log (spec §5.3).

Phase 2 inserts the cache before retrieval; Phase 3 replaces _choose_tier with the router.
"""
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import WeirConfig
from .llm.pricing import PriceTable
from .metrics.logger import LogSink, RequestLogRow
from .rag.adapter import RagClient, RagError, RetrievedChunk
from .text import query_hash

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


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class Pipeline:
    def __init__(self, cfg: WeirConfig, rag: RagClient, prices: PriceTable, log: LogSink,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._cfg = cfg
        self._rag = rag
        self._prices = prices
        self._log = log
        self._now = now

    async def handle(self, req: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        now = self._now()
        row = RequestLogRow(
            request_id=uuid4(), ts=now, namespace=req.namespace,
            cache_status="bypass", bypass_reason=self._bypass_reason(req),
            route="none", status="ok", latency_total_ms=0,
            query_hash=query_hash(req.query),
            query_text=None if self._cfg.is_sensitive(req.namespace) else req.query,
            config_label=self._cfg.config_label,
        )
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

        today = now.date()
        row.model = generated.model
        row.model_calls = 0 if generated.finish_reason == "skipped" else 1
        row.tokens_in, row.tokens_out = generated.tokens_in, generated.tokens_out
        row.cost_usd = self._prices.cost(model, generated.tokens_in, generated.tokens_out, today)
        row.counterfactual_cost_usd = self._prices.cost(
            self._cfg.router.large_model, generated.tokens_in, generated.tokens_out, today)
        row.answer_len = len(generated.answer)
        row.latency_total_ms = _ms(started)
        self._log.submit(row)

        return QueryResponse(
            answer=generated.answer,
            sources=_sources(retrieved.chunks, generated.cited_chunk_ids),
            meta=QueryMeta(
                request_id=str(row.request_id), cache_status=row.cache_status, similarity=None,
                route=row.route, escalated=False, model=row.model,
                latency_ms=row.latency_total_ms, cost_usd=float(row.cost_usd),
            ),
        )

    def _bypass_reason(self, req: QueryRequest) -> str:
        if req.personalized:
            return "personalized"
        if req.options.bypass_cache:
            return "request_option"
        if self._cfg.kill_switch.disable_cache:
            return "kill_switch"
        return "cache_disabled"

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
