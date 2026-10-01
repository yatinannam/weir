import json

import pytest

from weir_eval.judge import Judge


class FakeCall:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


async def no_sleep(s):
    pass


async def test_grade_parses_and_caches(tmp_path):
    call = FakeCall([json.dumps({"score": 4, "reason": "fine"})])
    judge = Judge(call, tmp_path, "gemini-x", sleep=no_sleep)
    v1 = await judge.grade("q?", ["4 pm"], "SOURCE", "It opens at 4 pm.")
    v2 = await judge.grade("q?", ["4 pm"], "SOURCE", "It opens at 4 pm.")
    assert (v1.score, v2.score) == (4, 4)
    assert len(call.prompts) == 1  # second call served from disk cache
    assert "SOURCE" in call.prompts[0] and "4 pm" in call.prompts[0]


async def test_invalid_json_retried_once_then_raises(tmp_path):
    judge = Judge(FakeCall(["not json", "still not"]), tmp_path, "m", sleep=no_sleep)
    with pytest.raises(ValueError):
        await judge.grade("q", ["f"], "s", "a")


async def test_rate_limit_is_retried(tmp_path):
    class RateErr(Exception):
        code = 429

    call = FakeCall([RateErr(), json.dumps({"score": 5, "reason": "ok"})])
    v = await Judge(call, tmp_path, "m", sleep=no_sleep).grade("q", ["f"], "s", "a")
    assert v.score == 5


async def test_out_of_range_score_rejected(tmp_path):
    judge = Judge(FakeCall([json.dumps({"score": 9, "reason": "x"})] * 2), tmp_path, "m", sleep=no_sleep)
    with pytest.raises(ValueError):
        await judge.grade("q", ["f"], "s", "a")


async def test_server_errors_are_retried(tmp_path):
    class Overloaded(Exception):
        code = 503

    call = FakeCall([Overloaded(), json.dumps({"score": 3, "reason": "ok"})])
    assert (await Judge(call, tmp_path, "m", sleep=no_sleep).grade("q", ["f"], "s", "a")).score == 3


async def test_pacing_applies_only_to_real_calls(tmp_path):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    call = FakeCall([json.dumps({"score": 4, "reason": "x"})] * 2)
    judge = Judge(call, tmp_path, "m", sleep=fake_sleep, min_interval_s=5.0)
    await judge.grade("q1", ["f"], "s", "a")
    await judge.grade("q1", ["f"], "s", "a")  # cached: no call, no wait
    await judge.grade("q2", ["f"], "s", "a")
    assert len(call.prompts) == 2 and len(slept) == 1


async def test_groq_call_requests_json_at_temperature_zero():
    from types import SimpleNamespace

    from weir_eval.judge import groq_call

    seen = {}

    class Completions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            msg = SimpleNamespace(content='{"score": 5, "reason": "ok"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    call = groq_call("key", "qwen/qwen3.8-27b", client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    assert await call("grade this") == '{"score": 5, "reason": "ok"}'
    assert seen["model"] == "qwen/qwen3.8-27b" and seen["temperature"] == 0
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["messages"][-1]["content"] == "grade this"
