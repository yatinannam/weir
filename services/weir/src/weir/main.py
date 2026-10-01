import logging
import math
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .auth import TenantRegistry
from .config import WeirConfig, load_config
from .db import open_pool
from .llm.pricing import PriceTable, sync_prices
from .metrics.logger import LogWriter
from .pipeline import Pipeline, PipelineError, QueryRequest, QueryResponse
from .rag.adapter import RagClient
from .settings import Settings

logging.basicConfig(level=logging.INFO)


@dataclass
class AppDeps:
    pipeline: Pipeline
    tenants: TenantRegistry
    config: WeirConfig
    health: Callable[[], Awaitable[dict[str, bool]]]


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
        for model in (cfg.router.small_model, cfg.router.large_model):
            prices.price_for(model, today)  # fail fast: every configured model must be priced
        pool = await open_pool(s.database_url)
        await sync_prices(pool, prices)
        writer = LogWriter(pool)
        writer.start()
        rag = RagClient(cfg.rag.base_url, cfg.rag.timeout_seconds)

        async def health() -> dict[str, bool]:
            try:
                async with pool.connection() as conn:
                    await conn.execute("select 1")
                db_ok = True
            except Exception:  # noqa: BLE001
                db_ok = False
            return {"db": db_ok, "rag": await rag.health()}

        app.state.deps = AppDeps(Pipeline(cfg, rag, prices, writer), tenants, cfg, health)
        try:
            yield
        finally:
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

    @app.get("/healthz")
    async def healthz(request: Request):
        d: AppDeps = request.app.state.deps
        checks = await d.health()
        ok = all(checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={
            "status": "ok" if ok else "degraded", "checks": checks, "config_label": d.config.config_label})

    return app


app = create_app()
