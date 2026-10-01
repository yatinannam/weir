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


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str


def _rate_limit_wait(error: Exception) -> float | None:
    return 30.0 if getattr(error, "code", None) == 429 else None


class Judge:
    def __init__(self, call: Callable[[str], Awaitable[str]], cache_dir: Path, model: str,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._call = call
        self._cache_dir = cache_dir
        self._model = model
        self._sleep = sleep
        cache_dir.mkdir(parents=True, exist_ok=True)

    async def grade(self, query: str, facts: list[str], source_text: str, answer: str) -> JudgeVerdict:
        key = hashlib.sha256(json.dumps([RUBRIC_VERSION, self._model, query, facts, answer]).encode()).hexdigest()
        cached = self._cache_dir / f"{key}.json"
        if cached.exists():
            return JudgeVerdict.model_validate_json(cached.read_text(encoding="utf-8"))
        prompt = (f"{RUBRIC}\n\n### Source document\n{source_text}\n\n### Question\n{query}\n\n"
                  f"### Required facts\n{json.dumps(facts, ensure_ascii=False)}\n\n### Answer to grade\n{answer}\n")
        last_error: Exception | None = None
        for _ in range(2):  # one retry on malformed output
            raw = await with_retries(lambda: self._call(prompt), _rate_limit_wait, sleep=self._sleep)
            try:
                verdict = JudgeVerdict.model_validate_json(raw)
            except ValidationError as e:
                last_error = e
                continue
            cached.write_text(verdict.model_dump_json(), encoding="utf-8")
            return verdict
        raise ValueError(f"judge returned invalid output twice: {last_error}")


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
