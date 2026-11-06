"""
Admin service test fixtures: the real FastAPI app over an in-memory SQLite database (no Postgres needed),
with Azure AD authentication replaced by a claims object the test chooses.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.main import app
from shared.auth.azure_ad import AzureADClaims, get_azure_claims
from shared.db.session import metadata_session_dep
from shared.models.db import Base


@compiles(JSONB, "sqlite")
def _jsonb_as_json(_type, _compiler, **_kw) -> str:
    """The shared models use Postgres JSONB; SQLite stores the same documents as JSON."""
    return "JSON"


ADMIN_OID = "00000000-0000-0000-0000-0000000000aa"


class Caller:
    """Who the next request is made by (Azure AD claims)."""

    def __init__(self) -> None:
        self.claims = AzureADClaims({"oid": ADMIN_OID, "preferred_username": "admin@test", "name": "Admin",
                                     "roles": ["super_admin"]})

    def as_user(self, oid: str | None = None, roles: list[str] | None = None) -> str:
        oid = oid or str(uuid.uuid4())
        self.claims = AzureADClaims({"oid": oid, "preferred_username": f"{oid[:6]}@test", "name": "User",
                                     "roles": roles or []})
        return oid


@pytest_asyncio.fixture
async def sessionmaker_() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest_asyncio.fixture
async def api(sessionmaker_, caller: Caller) -> AsyncIterator[httpx.AsyncClient]:
    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[metadata_session_dep] = session_dep
    app.dependency_overrides[get_azure_claims] = lambda: caller.claims
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://admin.test") as client:
        yield client
    app.dependency_overrides.clear()
