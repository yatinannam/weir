import asyncio
import math
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import groq


@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    finish_reason: str
    model: str
    latency_ms: int


class LLMError(Exception):
    pass


class RateLimited(LLMError):
    def __init__(self, retry_after: float | None):
        super().__init__(f"rate limited (retry after {retry_after}s)")
        self.retry_after = retry_after


class LLMTimeout(LLMError):
    pass


class LLM(Protocol):
    async def complete(self, messages: list[dict], model: str) -> LLMResult: ...


class GroqLLM:
    def __init__(self, api_key: str, timeout_s: float, max_completion_tokens: int,
                 reasoning_effort: str | None, client=None):
        if client is None and not api_key:
            raise ValueError("GROQ_API_KEY is empty; set it in .env or use LLM_MODE=stub")
        self._client = client or groq.AsyncGroq(api_key=api_key, timeout=timeout_s, max_retries=0)
        self._max_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort

    async def complete(self, messages: list[dict], model: str) -> LLMResult:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_completion_tokens": self._max_tokens,
        }
        if self._reasoning_effort:
            kwargs["extra_body"] = {"reasoning_effort": self._reasoning_effort}
        started = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except groq.RateLimitError as e:
            raise RateLimited(_retry_after(e)) from e
        except groq.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except groq.APIError as e:
            raise LLMError(str(e)) from e
        choice = resp.choices[0]
        return LLMResult(
            text=choice.message.content or "",
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            finish_reason=choice.finish_reason or "stop",
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _retry_after(error: groq.RateLimitError) -> float | None:
    value = error.response.headers.get("retry-after") if error.response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class LatencyProfile:
    median_ms: float
    p95_ms: float


class FixedTiming:
    def __init__(self, ms: float):
        self._ms = ms

    def delay_ms(self, model: str) -> float:
        return self._ms


class LognormalTiming:
    """Per-model delays from a lognormal fitted to a measured median and p95 (Phase 5 addendum §3.1, D49)."""

    Z95 = 1.6448536269514722

    def __init__(self, profiles: dict[str, LatencyProfile], default_model: str, seed: int):
        self._profiles = profiles
        self._default = profiles[default_model]
        self._rng = random.Random(seed)

    def delay_ms(self, model: str) -> float:
        p = self._profiles.get(model, self._default)
        sigma = math.log(p.p95_ms / p.median_ms) / self.Z95
        return self._rng.lognormvariate(math.log(p.median_ms), sigma)


class StubLLM:
    """Fake model used for load tests: answers from passage [c1], no network; fixed or realistic timing."""

    FIRST_PASSAGE = re.compile(r"\[c1\] (.+?)(?:\n\n\[c2\] |\n\nQuestion:)", re.DOTALL)

    def __init__(self, latency_ms: int, count_tokens: Callable[[str], int], timing=None):
        self._latency_ms = latency_ms
        self._count = count_tokens
        self._timing = timing or FixedTiming(latency_ms)

    async def complete(self, messages: list[dict], model: str) -> LLMResult:
        delay = self._timing.delay_ms(model)
        await asyncio.sleep(delay / 1000)
        match = self.FIRST_PASSAGE.search(messages[-1]["content"])
        if match:
            body = match.group(1).split("\n", 1)[-1]  # drop the "Title: heading" line
            text = " ".join(body.split()[:25]) + " [c1]"
        else:
            text = "NOT_FOUND"
        tokens_in = sum(self._count(m["content"]) for m in messages)
        return LLMResult(text, tokens_in, self._count(text), "stop", model, int(delay))
