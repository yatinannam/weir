import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    """asyncio.run, but on a selector loop on Windows (psycopg async needs it)."""
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)
