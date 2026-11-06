"""
shared/db/session.py
Async SQLAlchemy engine + session factories for both databases.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config import get_settings

_settings = get_settings()

# ── Metadata store engine (PostgreSQL) ──────────────────────────
metadata_engine = create_async_engine(
    _settings.postgres_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    echo=_settings.environment == "development",
    pool_pre_ping=True,
)

MetadataSession = async_sessionmaker(
    metadata_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Analytics store engine (TimescaleDB / separate PostgreSQL) ───
analytics_engine = create_async_engine(
    _settings.analytics_db_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    echo=_settings.environment == "development",
    pool_pre_ping=True,
)

AnalyticsSession = async_sessionmaker(
    analytics_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_metadata_session() -> AsyncGenerator[AsyncSession, None]:
    async with MetadataSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_analytics_session() -> AsyncGenerator[AsyncSession, None]:
    async with AnalyticsSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# FastAPI dependency helpers
async def metadata_session_dep() -> AsyncGenerator[AsyncSession, None]:
    async with MetadataSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def analytics_session_dep() -> AsyncGenerator[AsyncSession, None]:
    async with AnalyticsSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
