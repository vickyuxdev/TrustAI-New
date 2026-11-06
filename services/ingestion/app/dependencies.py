"""
services/ingestion/app/dependencies.py
FastAPI dependencies for the Ingestion Service:
  - API key authentication (validates project keys against Postgres)
  - Rate limiting (Redis sliding window per API key)
  - Event Hub publisher
"""
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

import redis.asyncio as aioredis
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import EventHubSettings, RedisSettings
from shared.db.session import metadata_session_dep
from shared.models.db import ApiKey, ApiKeyStatus, Project

logger = logging.getLogger("ingestion.dependencies")

_eh_settings = EventHubSettings()
_redis_settings = RedisSettings()

# ── Event Hub Producer (singleton) ───────────────────────────────

_producer: EventHubProducerClient | None = None


async def get_event_hub_producer() -> EventHubProducerClient:
    global _producer
    conn_str = _eh_settings.connection_string.get_secret_value()
    if not conn_str:
        logger.warning("Event Hub not configured — spans will be logged locally only")
        return None  # type: ignore[return-value]
    if _producer is None:
        _producer = EventHubProducerClient.from_connection_string(
            conn_str=conn_str,
            eventhub_name=_eh_settings.eventhub_name,
        )
    return _producer


# ── Redis Rate Limiter ────────────────────────────────────────────

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            _redis_settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_pool


# 1000 requests per minute per API key
_RATE_LIMIT = 1000
_RATE_WINDOW_SECONDS = 60


async def _check_rate_limit(key_prefix: str, redis: aioredis.Redis) -> None:
    redis_key = f"trustai:rate:{key_prefix}"
    now = int(datetime.now(timezone.utc).timestamp())
    window_start = now - _RATE_WINDOW_SECONDS

    pipe = redis.pipeline()
    pipe.zremrangebyscore(redis_key, "-inf", window_start)
    pipe.zadd(redis_key, {str(now): now})
    pipe.zcard(redis_key)
    pipe.expire(redis_key, _RATE_WINDOW_SECONDS + 5)
    results = await pipe.execute()
    count = results[2]

    if count > _RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Max {_RATE_LIMIT} requests per minute.",
            headers={"Retry-After": str(_RATE_WINDOW_SECONDS)},
        )


# ── API Key Auth ──────────────────────────────────────────────────

class AuthenticatedProject:
    """Result of successful API key authentication."""
    def __init__(self, project: Project, api_key: ApiKey):
        self.project = project
        self.api_key = api_key
        self.project_id = project.id
        self.client_id = project.client_id
        self.content_capture_mode = project.content_capture_mode


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_authenticated_project(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    session: AsyncSession = Depends(metadata_session_dep),
    redis: aioredis.Redis = Depends(get_redis),
) -> AuthenticatedProject:
    """
    Validate X-API-Key header against stored hash.
    Returns the associated project context.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required",
        )

    key_hash = _hash_key(x_api_key)

    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.key_hash == key_hash, ApiKey.status == ApiKeyStatus.ACTIVE)
        .options()  # eager load project if needed
    )
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )

    # Check expiry
    if api_key_record.expires_at and api_key_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has expired",
        )

    # Rate limit check
    await _check_rate_limit(api_key_record.key_prefix, redis)

    # Load project
    proj_result = await session.execute(
        select(Project).where(Project.id == api_key_record.project_id, Project.is_active == True)
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project not found or inactive")

    # Update last_used_at (fire-and-forget style)
    api_key_record.last_used_at = datetime.now(timezone.utc)

    return AuthenticatedProject(project=project, api_key=api_key_record)


# ── Event Hub Publisher ────────────────────────────────────────────

async def publish_to_eventhub(
    producer: EventHubProducerClient | None,
    payload: dict,
    partition_key: str,
) -> None:
    """Send a payload to Event Hub. Falls back to logging if not configured."""
    if producer is None:
        logger.debug("Event Hub not configured; payload: %s", json.dumps(payload)[:200])
        return
    try:
        batch = await producer.create_batch(partition_key=partition_key)
        batch.add(EventData(json.dumps(payload)))
        await producer.send_batch(batch)
    except Exception as exc:
        logger.error("Failed to publish to Event Hub: %s", exc)
        raise
