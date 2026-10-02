"""LLM judge on the Gemini free tier, with answers cached on disk so reruns cost nothing."""
import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .retry import with_retries

RUBRIC_VERSION = "r1"
RUBRIC = """You are grading an answer from a hospital help-desk chatbot for Weir General Hospital.
Use ONLY the source document below as the truth.

Score from 1 to 5:
5 = correct and complete: every required fact is present and nothing contradicts the source.
4 = correct, with a minor omission or extra detail that is still true per the source.
3 = partly correct: some required facts are missing, nothing is false.
2 = mostly wrong or missing key facts, or includes a claim the source does not support.
1 = wrong, contradicts the source, or answers a different question.
If the answer says the information could not be found but the source contains it, score 1.

Return JSON only: {"score": <integer 1-5>, "reason": "<one sentence>"}"""


UNANSWERABLE_NOTE = ("### Note\nThe knowledge base does NOT contain the answer to this question. "
                     "Score 5 if the answer clearly says the information could not be found. "
                     "Score 1 if it gives an answer anyway.")


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str


def _rate_limit_wait(error: Exception) -> float | None:
    """Retry rate limits (429) and transient server errors (5xx, e.g. 'model overloaded')."""
    code = getattr(error, "code", None)
    return 30.0 if isinstance(code, int) and (code == 429 or code >= 500) else None


class Judge:
    def __init__(self, call: Callable[[str], Awaitable[str]], cache_dir: Path, model: str,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, min_interval_s: float = 0.0):
        self._call = call
        self._cache_dir = cache_dir
        self._model = model
        self._sleep = sleep
        self._min_interval_s = min_interval_s
        self._last_call: float | None = None
        cache_dir.mkdir(parents=True, exist_ok=True)

    async def _paced_call(self, prompt: str) -> str:
        """Space out real API calls (free-tier limits); cache hits never get here."""
        loop = asyncio.get_running_loop()
        if self._last_call is not None:
            remaining = self._min_interval_s - (loop.time() - self._last_call)
            if remaining > 0:
                await self._sleep(remaining)
        self._last_call = loop.time()
        return await self._call(prompt)

    async def grade(self, query: str, facts: list[str], source_text: str, answer: str,
                    unanswerable: bool = False) -> JudgeVerdict:
        payload = [RUBRIC_VERSION, self._model, query, facts, answer] + (["unanswerable"] if unanswerable else [])
        key = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        cached = self._cache_dir / f"{key}.json"
        if cached.exists():
            return JudgeVerdict.model_validate_json(cached.read_text(encoding="utf-8"))
        note = f"\n\n{UNANSWERABLE_NOTE}" if unanswerable else ""
        prompt = (f"{RUBRIC}\n\n### Source document\n{source_text or '(none)'}\n\n### Question\n{query}\n\n"
                  f"### Required facts\n{json.dumps(facts, ensure_ascii=False)}\n\n### Answer to grade\n{answer}\n{note}")
        last_error: Exception | None = None
        for _ in range(2):  # one retry on malformed output
            raw = await with_retries(lambda: self._paced_call(prompt), _rate_limit_wait, sleep=self._sleep)
            try:
                verdict = JudgeVerdict.model_validate_json(raw)
            except ValidationError as e:
                last_error = e
                continue
            cached.write_text(verdict.model_dump_json(), encoding="utf-8")
            return verdict
        raise ValueError(f"judge returned invalid output twice: {last_error}")


def groq_call(api_key: str, model: str, client=None) -> Callable[[str], Awaitable[str]]:
    """Judge on the Groq free tier (decision D20). Different model family from the gpt-oss models under test."""
    import groq

    client = client or groq.AsyncGroq(api_key=api_key, timeout=60, max_retries=0)

    async def call(prompt: str) -> str:
        try:
            response = await client.chat.completions.create(
                model=model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": "You are a strict grader. Reply with JSON only."},
                          {"role": "user", "content": prompt}],
            )
        except groq.APIStatusError as e:
            e.code = e.status_code  # let _rate_limit_wait retry 429 and 5xx
            raise
        return response.choices[0].message.content or ""

    return call


def gemini_call(api_key: str, model: str) -> Callable[[str], Awaitable[str]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json", response_schema=JudgeVerdict)

    async def call(prompt: str) -> str:
        response = await client.aio.models.generate_content(model=model, contents=prompt, config=config)
        return response.text or ""

    return call
