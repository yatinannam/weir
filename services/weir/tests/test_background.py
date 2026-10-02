import asyncio

from weir.background import BackgroundQueue, Periodic


async def _append(target, value):
    target.append(value)


async def test_queue_runs_jobs_in_order():
    done = []
    q = BackgroundQueue("t")
    q.start()
    for i in range(3):
        q.submit(lambda i=i: _append(done, i))
    await q.stop()
    assert done == [0, 1, 2]


async def test_queue_counts_failures_and_continues():
    done = []

    async def boom():
        raise RuntimeError("db down")

    q = BackgroundQueue("t")
    q.start()
    q.submit(boom)
    q.submit(lambda: _append(done, "after"))
    await q.stop()
    assert q.failed == 1 and done == ["after"]


async def test_queue_full_drops():
    q = BackgroundQueue("t", max_queue=1)  # not started
    q.submit(lambda: _append([], 1))
    q.submit(lambda: _append([], 2))
    assert q.dropped == 1


async def test_periodic_runs_repeatedly_and_survives_errors():
    calls = []

    async def tick():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("flaky")

    p = Periodic(tick, 0.01, "t")
    p.start()
    await asyncio.sleep(0.08)
    await p.stop()
    assert len(calls) >= 3 and p.failed == 1 and p.runs == len(calls) - 1
