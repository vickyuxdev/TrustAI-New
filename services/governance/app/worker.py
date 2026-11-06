"""
services/governance/app/worker.py
Evaluation worker: consumes evaluation ids from Redis (TRUSTAI_EVAL_EXECUTOR=redis) and runs them.
Run: `python -m app.worker` (one process handles TRUSTAI_EVAL_CONCURRENCY prompts at a time per evaluation).
"""
from __future__ import annotations

import asyncio
import logging
import signal
import uuid

import redis.asyncio as aioredis

from app.config import get_settings
from app.db import create_tables, reset_engine
from app.services.evaluations import run_evaluation

logger = logging.getLogger("governance.worker")

# Seconds BLPOP waits for a queue item. The client's socket read timeout must be longer, or an
# idle queue raises TimeoutError (redis-py >= 8 defaults socket_timeout to 5s).
BLPOP_TIMEOUT_S = 5
SOCKET_TIMEOUT_S = BLPOP_TIMEOUT_S + 10
# Back-off between reconnect attempts when Redis is unavailable.
RETRY_DELAY_S = 2.0


async def consume(stop: asyncio.Event) -> None:
    """Block on the queue and run evaluations one after another until stopped."""
    settings = get_settings()
    if settings.create_tables_on_startup:
        await create_tables()
    client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=SOCKET_TIMEOUT_S,
        health_check_interval=30,
    )
    logger.info("evaluation worker listening on %s", settings.eval_queue_name)
    try:
        while not stop.is_set():
            try:
                item = await client.blpop([settings.eval_queue_name], timeout=BLPOP_TIMEOUT_S)
            except (aioredis.TimeoutError, aioredis.ConnectionError) as exc:
                # Redis restarting or briefly unreachable: wait and retry instead of crashing.
                logger.warning("redis unavailable (%s); retrying in %.0fs", exc, RETRY_DELAY_S)
                await asyncio.sleep(RETRY_DELAY_S)
                continue
            if item is None:
                continue
            _, raw_id = item
            try:
                evaluation_id = uuid.UUID(raw_id)
            except ValueError:
                logger.warning("ignoring malformed queue item %r", raw_id)
                continue
            logger.info("running evaluation %s", evaluation_id)
            await run_evaluation(evaluation_id)
    finally:
        await client.aclose()
        await reset_engine()


def main() -> None:
    """Entry point with graceful SIGTERM/SIGINT handling."""
    logging.basicConfig(level=get_settings().log_level)
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows dev machines
            signal.signal(sig, lambda *_: stop.set())
    loop.run_until_complete(consume(stop))


if __name__ == "__main__":
    main()
