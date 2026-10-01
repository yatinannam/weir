import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    is_retryable: Callable[[Exception], float | None],
    max_attempts: int = 4,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as e:  # noqa: BLE001 - classified by is_retryable
            wait = is_retryable(e)
            if wait is None or attempt == max_attempts:
                raise
            await sleep(wait)
    raise AssertionError("unreachable")
