"""Off-request-path work: a job queue (cache writes, hit counters) and periodic tasks
(version refresh, expired-entry cleanup). Failures are counted and logged, never raised."""
import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("weir.background")
Job = Callable[[], Awaitable[object]]


class BackgroundQueue:
    def __init__(self, name: str, max_queue: int = 10_000):
        self._name = name
        self._queue: asyncio.Queue[Job] = asyncio.Queue(max_queue)
        self._task: asyncio.Task | None = None
        self.dropped = 0
        self.failed = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def submit(self, job: Job) -> None:
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            self.dropped += 1
            log.warning("%s queue full; dropped a job", self._name)

    async def stop(self, timeout_s: float = 5.0) -> None:
        if self._task is None:
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._queue.join(), timeout_s)
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await job()
            except Exception:  # noqa: BLE001 - background work must never break requests
                self.failed += 1
                log.exception("%s job failed", self._name)
            finally:
                self._queue.task_done()


class Periodic:
    def __init__(self, fn: Job, interval_s: float, name: str):
        self._fn = fn
        self._interval_s = interval_s
        self._name = name
        self._task: asyncio.Task | None = None
        self.runs = 0
        self.failed = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self._fn()
                self.runs += 1
            except Exception:  # noqa: BLE001
                self.failed += 1
                log.exception("%s failed", self._name)
            await asyncio.sleep(self._interval_s)
