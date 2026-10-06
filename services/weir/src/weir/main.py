import asyncio
import logging
import math
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from .admin import AdminService
from .auth import TenantRegistry
from .background import BackgroundQueue, Periodic
from .cache.embedder import Embedder
from .cache.entities import Lexicon
from .cache.guards import BypassRules
from .cache.store import CacheStore
from .cache.versions import VersionCache
from .config import WeirConfig, load_config
from .db import open_pool
from .llm.pricing import PriceTable, sync_prices
from .metrics.logger import LogWriter
from .metrics.prometheus import LossCollector, MetricsSink, WeirMetrics
from .pipeline import CacheDeps, Pipeline, PipelineError, QueryRequest, QueryResponse
from .rag.adapter import RagClient
from .settings import Settings

logging.basicConfig(level=logging.INFO)


@dataclass
class AppDeps:
    pipeline: Pipeline
    tenants: TenantRegistry
    config: WeirConfig
    health: Callable[[], Awaitable[dict[str, bool]]]
    admin: Any                      # AdminService or a test double
    feedback_lookup_attempts: int = 5
    feedback_lookup_delay_s: float = 0.2
    metrics: WeirMetrics | None = None


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)


def create_app(deps: AppDeps | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is not None:
            yield
            return
        s = Settings()
        cfg = load_config(s.config_path(), s.overlay_path())
        tenants = TenantRegistry.from_yaml(s.weir_configs_dir / "tenants.yaml", os.environ)
        prices = PriceTable.from_yaml(s.weir_configs_dir / "prices.yaml")
        today = datetime.now(UTC).date()
        for model in (cfg.router.small_model, cfg.router.large_model, cfg.cache.embed_model):
            prices.price_for(model, today)  # fail fast: every model we may bill must be priced
        pool = await open_pool(s.database_url)
        await sync_prices(pool, prices)
        writer = LogWriter(pool)
        writer.start()
        rag = RagClient(cfg.rag.base_url, cfg.rag.timeout_seconds)
        store = CacheStore(pool)
        cache_jobs = BackgroundQueue("cache")
        cache_jobs.start()
        versions = VersionCache(rag.info)
        refresher = Periodic(versions.refresh, cfg.rag.info_refresh_seconds, "kb-version-refresh")
        refresher.start()
        cleanup = Periodic(store.delete_expired, cfg.cache.cleanup_interval_minutes * 60, "cache-cleanup")
        cleanup.start()
        embedder = await asyncio.to_thread(Embedder, cfg.cache.embed_model, s.embed_cache_dir)
        cache = CacheDeps(embedder=embedder, versions=versions, store=store, writer=cache_jobs,
                          lexicon=Lexicon.from_yaml(s.weir_configs_dir / "entities.yaml"),
                          rules=BypassRules(cfg.bypass))

        async def health() -> dict[str, bool]:
            try:
                async with pool.connection() as conn:
                    await conn.execute("select 1")
                db_ok = True
            except Exception:  # noqa: BLE001
                db_ok = False
            return {"db": db_ok, "rag": await rag.health()}

        registry = CollectorRegistry()
        metrics = WeirMetrics(registry, cfg.config_label, namespaces=cfg.namespaces.keys())
        registry.register(LossCollector({"log_rows": writer, "cache_jobs": cache_jobs}))
        app.state.deps = AppDeps(Pipeline(cfg, rag, prices, MetricsSink(writer, metrics), cache), tenants, cfg,
                                 health, AdminService(pool, store), metrics=metrics)
        try:
            yield
        finally:
            await refresher.stop()
            await cleanup.stop()
            await cache_jobs.stop()
            await writer.stop()
            await rag.aclose()
            await pool.close()

    app = FastAPI(title="Weir", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps

    @app.post("/v1/query", response_model=QueryResponse)
    async def query(body: QueryRequest, request: Request, response: Response,
                    x_api_key: str | None = Header(default=None)):
        d: AppDeps = request.app.state.deps
        tenant = d.tenants.authenticate(x_api_key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        if not tenant.allows(body.namespace):
            raise HTTPException(status_code=403, detail="namespace not allowed for this API key")
        try:
            result = await d.pipeline.handle(body)
        except PipelineError as e:
            headers = {"X-Request-ID": e.request_id}
            if e.retry_after is not None:
                headers["Retry-After"] = str(math.ceil(e.retry_after))
            return JSONResponse(status_code=e.status_code, headers=headers,
                                content={"error": e.error, "request_id": e.request_id})
        response.headers["X-Request-ID"] = result.meta.request_id
        return result

    @app.post("/v1/feedback")
    async def feedback(body: FeedbackIn, request: Request, x_api_key: str | None = Header(default=None)):
        d: AppDeps = request.app.state.deps
        tenant = d.tenants.authenticate(x_api_key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        ref = None
        for attempt in range(d.feedback_lookup_attempts):  # the log row is written asynchronously
            ref = await d.admin.find_request(body.request_id)
            if ref is not None:
                break
            if attempt < d.feedback_lookup_attempts - 1:
                await asyncio.sleep(d.feedback_lookup_delay_s)
        if ref is None or not tenant.allows(ref.namespace):
            raise HTTPException(status_code=404, detail="unknown request_id")
        await d.admin.add_feedback(body.request_id, body.rating, body.comment)
        evicted = body.rating == -1 and ref.cache_entry_id is not None and await d.admin.evict(ref.cache_entry_id)
        return {"evicted": bool(evicted)}

    @app.delete("/v1/cache")
    async def purge_cache(request: Request, namespace: str | None = None, source_id: str | None = None,
                          entry_id: UUID | None = None, x_api_key: str | None = Header(default=None)):
        d: AppDeps = request.app.state.deps
        tenant = d.tenants.authenticate(x_api_key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        if not tenant.admin:
            raise HTTPException(status_code=403, detail="admin key required")
        if sum(v is not None for v in (namespace, source_id, entry_id)) != 1:
            return JSONResponse(status_code=422,
                                content={"error": "give exactly one of namespace, source_id, entry_id"})
        deleted = await d.admin.purge(namespace=namespace, source_id=source_id, entry_id=entry_id)
        return {"deleted": deleted}

    @app.get("/healthz")
    async def healthz(request: Request):
        d: AppDeps = request.app.state.deps
        checks = await d.health()
        ok = all(checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={
            "status": "ok" if ok else "degraded", "checks": checks, "config_label": d.config.config_label})

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(request: Request):
        d: AppDeps = request.app.state.deps
        if d.metrics is None:
            raise HTTPException(status_code=404, detail="metrics are off")
        return Response(generate_latest(d.metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
