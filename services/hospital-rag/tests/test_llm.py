from types import SimpleNamespace

import groq
import httpx
import pytest

from hospital_rag.llm import GroqLLM, LLMError, LLMTimeout, RateLimited, StubLLM
from hospital_rag.prompt import build_messages

from .conftest import word_count

REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


class FakeCompletions:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.kwargs = result, error, None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def fake_client(completions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def ok_response(text="Answer [c1]", finish="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
    )


def llm_with(completions):
    return GroqLLM("key", 20.0, 700, "low", client=fake_client(completions))


async def test_groq_success_maps_usage_and_sends_settings():
    comp = FakeCompletions(result=ok_response())
    result = await llm_with(comp).complete([{"role": "user", "content": "q"}], "openai/gpt-oss-120b")
    assert (result.text, result.tokens_in, result.tokens_out) == ("Answer [c1]", 120, 30)
    assert result.finish_reason == "stop" and result.model == "openai/gpt-oss-120b"
    assert comp.kwargs["temperature"] == 0
    assert comp.kwargs["max_completion_tokens"] == 700
    assert comp.kwargs["extra_body"] == {"reasoning_effort": "low"}


async def test_groq_rate_limit_raises_with_retry_after():
    err = groq.RateLimitError("slow down", response=httpx.Response(429, headers={"retry-after": "7"}, request=REQ), body=None)
    with pytest.raises(RateLimited) as exc:
        await llm_with(FakeCompletions(error=err)).complete([], "m")
    assert exc.value.retry_after == 7.0


async def test_groq_timeout_raises_llm_timeout():
    with pytest.raises(LLMTimeout):
        await llm_with(FakeCompletions(error=groq.APITimeoutError(request=REQ))).complete([], "m")


async def test_groq_other_error_raises_llm_error():
    err = groq.InternalServerError("boom", response=httpx.Response(500, request=REQ), body=None)
    with pytest.raises(LLMError):
        await llm_with(FakeCompletions(error=err)).complete([], "m")


async def test_stub_answers_from_first_passage_without_network():
    messages, _ = build_messages("When?", [("a#0", "Title: S\nVisiting is from 4 pm to 8 pm daily."), ("b#0", "Other")])
    result = await StubLLM(latency_ms=1, count_tokens=word_count).complete(messages, "m")
    assert result.text.endswith("[c1]")
    assert "4 pm to 8 pm" in result.text
    assert result.tokens_in > 0 and result.tokens_out > 0 and result.finish_reason == "stop"
