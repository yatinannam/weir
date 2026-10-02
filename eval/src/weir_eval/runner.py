import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from .dataset import EvalQuery
from .judge import Judge
from .keyfacts import check_facts
from .retry import with_retries

RETRYABLE = {429, 502, 503, 504}


class Limiter:
    """Keeps at least min_interval_s between calls (free-tier TPM budget)."""

    def __init__(self, min_interval_s: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._interval = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    async def wait(self) -> None:
        if self._last is not None:
            remaining = self._interval - (self._clock() - self._last)
            if remaining > 0:
                await self._sleep(remaining)
        self._last = self._clock()

    def release(self) -> None:
        """The last call was free (a cache hit), so the next one needn't wait."""
        self._last = None


class HttpRetry(Exception):
    def __init__(self, wait_s: float):
        super().__init__(f"retry in {wait_s}s")
        self.wait_s = wait_s


async def ask(http: httpx.AsyncClient, key: str, q: EvalQuery,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> dict:
    record = {"id": q.id, "group": q.group, "cluster_id": q.cluster_id, "difficulty": q.difficulty,
              "namespace": q.namespace, "query": q.query}

    async def once() -> tuple[httpx.Response, int]:
        started = time.perf_counter()
        try:
            response = await http.post("/v1/query", headers={"X-API-Key": key},
                                       json={"query": q.query, "namespace": q.namespace})
        except httpx.TransportError as e:  # Weir or Docker restarting: wait and retry
            raise HttpRetry(15.0) from e
        elapsed = int((time.perf_counter() - started) * 1000)
        if response.status_code in RETRYABLE:
            raise HttpRetry(float(response.headers.get("Retry-After", "30")) + 1)
        return response, elapsed

    try:
        response, elapsed = await with_retries(
            once, lambda e: e.wait_s if isinstance(e, HttpRetry) else None, sleep=sleep)
    except HttpRetry as e:
        return {**record, "status_code": 503, "error": f"gave up after retries: {e}"}
    record.update(status_code=response.status_code, client_latency_ms=elapsed)
    if response.status_code != 200:
        return {**record, "error": response.text[:300]}
    body = response.json()
    record.update(answer=body["answer"], sources=body["sources"], meta=body["meta"], error=None)
    return record


async def run_eval(queries: list[EvalQuery], http: httpx.AsyncClient, keys: dict[str, str], judge: Judge | None,
                   kb: dict[str, str], out_dir: Path, min_interval_s: float,
                   sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    limiter = Limiter(min_interval_s, sleep=sleep)
    records: list[dict] = []
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as out:
        for i, q in enumerate(queries, start=1):
            await limiter.wait()
            record = await ask(http, keys[q.namespace], q, sleep=sleep)
            if record.get("meta", {}).get("cache_status") == "hit":
                limiter.release()
            if record["status_code"] == 200:
                facts = check_facts(record["answer"], q.required_facts)
                record.update(fact_hits=facts.hits, fact_total=facts.total, fact_score=facts.score)
                if judge is None:
                    record.update(judge_score=None, judge_error="not judged yet (--no-judge); run rejudge")
                else:
                    await _grade(record, q, judge, kb)
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()  # keep progress if the run is interrupted
            records.append(record)
            print(f"[{i}/{len(queries)}] {q.id} {record['status_code']} "
                  f"judge={record.get('judge_score')} facts={record.get('fact_score')}")
    return records


async def _grade(record: dict, q: EvalQuery, judge: Judge, kb: dict[str, str]) -> None:
    """Judge one answer; a judge failure is recorded on the row instead of ending the run."""
    source = "\n\n".join(kb.get(d, "") for d in q.source_docs)
    try:
        verdict = await judge.grade(q.query, q.required_facts, source, record["answer"],
                                    unanswerable=q.group == "unanswerable")
    except Exception as e:  # noqa: BLE001 - re-score later with `weir_eval rejudge`
        record.update(judge_score=None, judge_error=f"{type(e).__name__}: {e}"[:300])
        return
    record.pop("judge_error", None)
    record.update(judge_score=verdict.score, judge_reason=verdict.reason)


async def rejudge(results_path: Path, judge: Judge, queries: dict[str, EvalQuery], kb: dict[str, str]) -> list[dict]:
    """Re-score answered rows that have no judge verdict, without calling Weir again.

    The file is rewritten after every graded row, so an interrupted rejudge keeps its progress.
    """
    records = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    pending = [r for r in records if r.get("status_code") == 200 and r.get("judge_score") is None]
    for i, record in enumerate(pending, start=1):
        await _grade(record, queries[record["id"]], judge, kb)
        results_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        print(f"[{i}/{len(pending)}] {record['id']} judge={record.get('judge_score')}", flush=True)
    return records
