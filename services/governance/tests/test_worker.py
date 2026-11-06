"""Evaluation worker resilience: Redis timeouts/disconnects must not crash the consume loop."""
import asyncio

import redis.asyncio as aioredis

from app import worker


class FakeRedis:
    """Stand-in Redis client: first BLPOP times out, then the queue is idle until the test stops it."""

    def __init__(self, stop: asyncio.Event):
        self.stop = stop
        self.calls = 0
        self.closed = False
        self.kwargs: dict = {}

    async def blpop(self, keys, timeout):
        self.calls += 1
        if self.calls == 1:
            raise aioredis.TimeoutError("Timeout reading from redis:6379")
        if self.calls >= 3:
            self.stop.set()
        return None

    async def aclose(self):
        self.closed = True


async def test_worker_survives_redis_timeout(monkeypatch):
    """A TimeoutError from BLPOP is logged and retried; the loop keeps consuming and closes cleanly."""
    stop = asyncio.Event()
    fake = FakeRedis(stop)

    def fake_from_url(url, **kwargs):
        fake.kwargs = kwargs
        return fake

    async def noop():
        return None

    monkeypatch.setattr(worker.aioredis, "from_url", fake_from_url)
    monkeypatch.setattr(worker, "RETRY_DELAY_S", 0)
    monkeypatch.setattr(worker, "create_tables", noop)
    monkeypatch.setattr(worker, "reset_engine", noop)

    await asyncio.wait_for(worker.consume(stop), timeout=5)

    assert fake.calls >= 3
    assert fake.closed
    # The socket read timeout must outlast the BLPOP wait, or idle queues time out.
    assert fake.kwargs["socket_timeout"] > worker.BLPOP_TIMEOUT_S
