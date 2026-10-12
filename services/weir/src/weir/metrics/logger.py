"""One row per request into weir.request_log, written off the request path.

Rows go into an in-process queue; a background task batches them into Postgres.
A logging failure never fails the user's request: it is counted and logged.
"""
import asyncio
import contextlib
import logging
from dataclasses import astuple, dataclass, fields
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

log = logging.getLogger("weir.metrics")


@dataclass
class RequestLogRow:
    request_id: UUID
    ts: datetime
    namespace: str
    cache_status: str
    route: str
    status: str
    latency_total_ms: int
    query_hash: str
    bypass_reason: str | None = None
    route_reason: str | None = None
    similarity: float | None = None
    cache_entry_id: UUID | None = None
    escalated: bool = False
    model_calls: int = 0
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    embed_tokens: int | None = None
    retrieval_top_score: float | None = None
    grounding_passed: bool | None = None
    grounding_reason: str | None = None
    grounding_overlap: float | None = None
    coverage_passed: bool | None = None
    coverage_reason: str | None = None
    escalated_for: str | None = None     # "grounding" or "coverage": why a small answer went to the large model
    latency_embed_ms: int | None = None
    latency_cache_ms: int | None = None
    latency_retrieval_ms: int | None = None
    latency_llm_ms: int | None = None
    cost_usd: Decimal = Decimal(0)
    counterfactual_cost_usd: Decimal = Decimal(0)
    error_detail: str | None = None
    query_text: str | None = None
    answer_len: int | None = None
    config_label: str | None = None


COLUMNS = [f.name for f in fields(RequestLogRow)]
INSERT_SQL = (  # one row; the writer uses COPY_SQL for batches
    f"insert into weir.request_log ({', '.join(COLUMNS)}) "
    f"values ({', '.join(['%s'] * len(COLUMNS))})"
)
COPY_SQL = f"copy weir.request_log ({', '.join(COLUMNS)}) from stdin"


class LogSink(Protocol):
    def submit(self, row: RequestLogRow) -> None: ...


class LogWriter:
    # COPY in batches of up to 500: at ~250 req/s, 100-row INSERT batches fell behind and dropped rows (D76)
    def __init__(self, pool, max_queue: int = 10_000, batch_size: int = 500, flush_interval_s: float = 0.5):
        self._pool = pool
        self._queue: asyncio.Queue[RequestLogRow] = asyncio.Queue(max_queue)
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._task: asyncio.Task | None = None
        self.dropped = 0
        self.failed = 0
        self.batches = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def submit(self, row: RequestLogRow) -> None:
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped % 1000 == 1:  # one line per 1,000: a log line per row costs CPU exactly when it's short
                log.warning("request log queue full; %d rows dropped so far", self.dropped)

    async def stop(self, timeout_s: float = 5.0) -> None:
        if self._task is None:
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._queue.join(), timeout_s)
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            batch = [await self._queue.get()]
            deadline = loop.time() + self._flush_interval_s
            while len(batch) < self._batch_size:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self._queue.get(), remaining))
                except asyncio.TimeoutError:
                    break
            await self._write(batch)
            for _ in batch:
                self._queue.task_done()

    async def _write(self, batch: list[RequestLogRow]) -> None:
        try:
            async with self._pool.connection() as conn, conn.cursor() as cur:
                async with cur.copy(COPY_SQL) as copy:
                    for r in batch:
                        await copy.write_row(astuple(r))
            self.batches += 1
        except Exception:  # noqa: BLE001 - logging must never break requests
            self.failed += len(batch)
            log.exception("failed to write %d request log rows", len(batch))
