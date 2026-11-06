"""
services/governance/app/db.py
Async SQLAlchemy engine/session for the governance tables.

The engine is created lazily from settings so the same code runs on Postgres (every deployment) and on SQLite
(unit tests). All governance columns use portable types; Postgres gets JSONB through a type variant.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger("governance.db")

# JSON everywhere, JSONB on Postgres (indexable, compact).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class GovBase(DeclarativeBase):
    """Declarative base for governance tables (separate metadata from the observability tables)."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Create (once) and return the async engine configured from TRUSTAI_POSTGRES_URL."""
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"pool_pre_ping": True}
        if not settings.database_url.startswith("sqlite"):
            kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow)
        _engine = create_async_engine(settings.database_url, **kwargs)
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the governance engine."""
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def reset_engine() -> None:
    """Dispose the engine (tests and graceful shutdown)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


async def create_tables(retries: int = 15, delay_seconds: float = 2.0) -> None:
    """Create governance tables if missing; retries while the database container is still starting."""
    from app import models  # noqa: F401 - register tables on GovBase.metadata

    for attempt in range(1, retries + 1):
        try:
            async with get_engine().begin() as conn:
                await conn.run_sync(GovBase.metadata.create_all)
            logger.info("governance tables ready")
            return
        except Exception as exc:  # noqa: BLE001 - startup must survive a slow database
            if attempt == retries:
                raise
            logger.warning("governance table init attempt %d failed: %s", attempt, exc)
            await asyncio.sleep(delay_seconds)


async def session_dep() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one transaction per request, committed on success and rolled back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
