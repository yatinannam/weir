"""Tell CPU saturation apart from a slow cache, so the cache's safety valve can't feed an overload (M31).

A cache lookup that runs out of time normally falls through to retrieval and a model: a cache outage must
never become a user outage. But when the lookup ran out of time while still *embedding* the question, the
CPU is the bottleneck, and the fall-through path embeds the question again (in hospital-rag) and calls a
model, so every timeout adds load and causes more timeouts. The load tests saw exactly that collapse.

The guard counts those embedding timeouts. A single one is noise and still falls through; several within
a short window mean the machine is saturated, and the pipeline sheds the request with a quick 503 instead.
"""
import time
from collections import deque
from collections.abc import Callable


class OverloadGuard:
    def __init__(self, timeouts: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self._timeouts = timeouts      # embedding timeouts within the window that mean "saturated"; 0 = never
        self._window_s = window_s
        self._clock = clock
        self._seen: deque[float] = deque()

    def saturated_after_timeout(self) -> bool:
        """Record one embedding timeout; True when it makes `timeouts` of them within the window."""
        if self._timeouts <= 0:
            return False
        now = self._clock()
        self._seen.append(now)
        while self._seen and self._seen[0] <= now - self._window_s:
            self._seen.popleft()
        return len(self._seen) >= self._timeouts
