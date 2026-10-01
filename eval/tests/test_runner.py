import json

import httpx
import pytest

from weir_eval.judge import Judge
from weir_eval.runner import Limiter, ask, run_eval

from .conftest import q


async def no_sleep(s):
    pass


def weir_ok(request):
    return httpx.Response(200, json={"answer": "Open at 4 pm.", "sources": [{"id": "pub-a", "title": "A"}],
                                     "meta": {"request_id": "r", "cache_status": "bypass", "similarity": None,
                                              "route": "large", "escalated": False, "model": "m",
                                              "latency_ms": 10, "cost_usd": 0.0004}})


class ScoreCall:
    async def __call__(self, prompt):
        return json.dumps({"score": 5, "reason": "ok"})


async def test_ask_retries_on_503():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "rate_limited", "request_id": "r"}, headers={"Retry-After": "3"})
        return weir_ok(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://w") as http:
        record = await ask(http, "key", q("d1", "d1"), sleep=no_sleep)
    assert record["status_code"] == 200 and len(calls) == 2


async def test_ask_records_non_retryable_error():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})), base_url="http://w") as http:
        record = await ask(http, "key", q("d1", "d1"), sleep=no_sleep)
    assert record["status_code"] == 403 and record["error"]


async def test_run_eval_writes_scored_jsonl(tmp_path):
    seen_keys = []

    def handler(request):
        seen_keys.append(request.headers["X-API-Key"])
        return weir_ok(request)

    judge = Judge(ScoreCall(), tmp_path / "cache", "m", sleep=no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://w") as http:
        records = await run_eval([q("d1", "d1"), q("d2", "d2")], http, {"weir-general/en/public": "pub-key"},
                                 judge, {"pub-a": "Open at 4 pm."}, tmp_path, min_interval_s=0, sleep=no_sleep)
    assert [r["fact_score"] for r in records] == [1.0, 1.0]
    assert [r["judge_score"] for r in records] == [5, 5]
    assert seen_keys == ["pub-key", "pub-key"]
    lines = (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["id"] == "d1"


async def test_limiter_spaces_calls():
    now = [0.0]
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        now[0] += s

    limiter = Limiter(10.0, clock=lambda: now[0], sleep=fake_sleep)
    await limiter.wait()
    now[0] += 4.0
    await limiter.wait()
    assert slept == [pytest.approx(6.0)]


class FlakyJudgeCall:
    """Fails permanently for prompts mentioning 'question d1'; scores everything else 4."""

    async def __call__(self, prompt):
        if "question d1" in prompt:
            raise ValueError("safety block")
        return json.dumps({"score": 4, "reason": "ok"})


async def test_judge_failure_is_recorded_and_run_continues(tmp_path):
    judge = Judge(FlakyJudgeCall(), tmp_path / "cache", "m", sleep=no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(weir_ok), base_url="http://w") as http:
        records = await run_eval([q("d1", "d1"), q("d2", "d2")], http, {"weir-general/en/public": "k"},
                                 judge, {"pub-a": "Open at 4 pm."}, tmp_path, min_interval_s=0, sleep=no_sleep)
    assert records[0]["judge_score"] is None and "safety block" in records[0]["judge_error"]
    assert records[0]["fact_score"] == 1.0
    assert records[1]["judge_score"] == 4


async def test_ask_retries_transport_errors():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("weir restarting", request=request)
        return weir_ok(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://w") as http:
        record = await ask(http, "key", q("d1", "d1"), sleep=no_sleep)
    assert record["status_code"] == 200 and len(calls) == 2


async def test_rejudge_scores_only_missing_verdicts(tmp_path):
    from weir_eval.runner import rejudge

    results = tmp_path / "results.jsonl"
    rows = [
        {"id": "d1", "status_code": 200, "answer": "Open at 4 pm.", "judge_score": None, "judge_error": "x"},
        {"id": "d2", "status_code": 200, "answer": "Open at 4 pm.", "judge_score": 2, "judge_reason": "kept"},
        {"id": "d3", "status_code": 503, "error": "gave up"},
    ]
    results.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    judge = Judge(ScoreCall(), tmp_path / "cache", "m", sleep=no_sleep)
    queries = {x.id: x for x in [q("d1", "d1"), q("d2", "d2"), q("d3", "d3")]}
    records = await rejudge(results, judge, queries, {"pub-a": "Open at 4 pm."})
    assert [r.get("judge_score") for r in records] == [5, 2, None]
    assert "judge_error" not in records[0]
    assert [json.loads(l)["id"] for l in results.read_text(encoding="utf-8").splitlines()] == ["d1", "d2", "d3"]
