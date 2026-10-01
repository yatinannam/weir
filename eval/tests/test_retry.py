import pytest

from weir_eval.retry import with_retries


class Flaky(Exception):
    pass


async def test_retries_then_succeeds():
    calls, sleeps = [], []

    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise Flaky()
        return "ok"

    async def fake_sleep(s):
        sleeps.append(s)

    result = await with_retries(fn, lambda e: 5.0 if isinstance(e, Flaky) else None, sleep=fake_sleep)
    assert result == "ok" and sleeps == [5.0, 5.0]


async def test_non_retryable_raises_immediately():
    async def fn():
        raise ValueError("no")

    with pytest.raises(ValueError):
        await with_retries(fn, lambda e: None)


async def test_gives_up_after_max_attempts():
    async def fn():
        raise Flaky()

    async def fake_sleep(s):
        pass

    with pytest.raises(Flaky):
        await with_retries(fn, lambda e: 1.0, max_attempts=3, sleep=fake_sleep)
