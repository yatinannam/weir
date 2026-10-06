import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

from . import service
from .db import open_pool
from .embedding import Embedder
from .llm import LLM, GroqLLM, LatencyProfile, LLMError, LLMTimeout, LognormalTiming, RateLimited, StubLLM
from .prompt import PROMPT_VERSION
from .schemas import ChunkOut, GenerateIn, GenerateOut, RetrieveIn, RetrieveOut
from .settings import Settings
from .store import search, versions


@dataclass
class Deps:
    pool: AsyncConnectionPool | None
    embedder: Embedder
    llm: LLM
    retrieve_k: int
    llm_mode: str = "test"


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def create_app(deps: Deps | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is not None:
            yield
            return
        s = Settings()
        embedder = Embedder(s.embed_model, s.embed_cache_dir)
        if s.llm_mode == "stub":
            timing = (LognormalTiming({s.stub_small_model: LatencyProfile(s.stub_small_median_ms, s.stub_small_p95_ms),
                                       s.stub_large_model: LatencyProfile(s.stub_large_median_ms, s.stub_large_p95_ms)},
                                      s.stub_large_model, s.stub_seed)
                      if s.stub_timing == "realistic" else None)
            llm: LLM = StubLLM(s.stub_latency_ms, embedder.count_tokens, timing)
        else:
            llm = GroqLLM(s.groq_api_key, s.groq_timeout_s, s.max_completion_tokens, s.reasoning_effort)
        pool = await open_pool(s.database_url)
        app.state.deps = Deps(pool, embedder, llm, s.retrieve_k, s.llm_mode)
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(title="hospital-rag", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps

    @app.get("/info")
    async def info(request: Request) -> dict:
        found = await versions(request.app.state.deps.pool)
        return {"namespaces": {ns: {"kb_version": v, "prompt_version": PROMPT_VERSION} for ns, v in found.items()}}

    @app.post("/retrieve", response_model=RetrieveOut)
    async def retrieve(body: RetrieveIn, request: Request) -> RetrieveOut:
        d: Deps = request.app.state.deps
        started = time.perf_counter()
        [vector] = await asyncio.to_thread(d.embedder.embed, [body.query])
        version, chunks = await search(d.pool, body.namespace, vector, body.k or d.retrieve_k)
        scores = [c.score for c in chunks]
        top = scores[0] if scores else 0.0
        gap = scores[0] - scores[1] if len(scores) > 1 else top
        return RetrieveOut(
            chunks=[ChunkOut(**asdict(c)) for c in chunks], top_score=top, score_gap=gap,
            context_tokens=sum(c.token_count for c in chunks), kb_version=version,
            latency_ms=_ms(started),
        )

    @app.post("/generate", response_model=GenerateOut)
    async def generate(body: GenerateIn, request: Request):
        try:
            return await service.generate(body, request.app.state.deps.llm)
        except RateLimited as e:
            return JSONResponse(status_code=503, content={"error": "rate_limited", "retry_after": e.retry_after})
        except LLMTimeout:
            return JSONResponse(status_code=504, content={"error": "timeout"})
        except LLMError as e:
            return JSONResponse(status_code=502, content={"error": "llm_error", "detail": str(e)[:300]})

    @app.get("/healthz")
    async def healthz(request: Request):
        d: Deps = request.app.state.deps
        try:
            async with d.pool.connection() as conn:
                await conn.execute("select 1")
        except Exception as e:  # noqa: BLE001 - report any DB failure as unhealthy
            return JSONResponse(status_code=503, content={"status": "db_error", "detail": str(e)[:200]})
        return {"status": "ok", "llm_mode": d.llm_mode}

    return app


app = create_app()
