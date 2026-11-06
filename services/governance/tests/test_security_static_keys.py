"""Development static keys: honoured in development/test only, never in production."""
from __future__ import annotations

import uuid

import httpx
import pytest

from app.config import get_settings

PROJECT = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
async def raw_client() -> httpx.AsyncClient:
    """App WITHOUT the test resolver override (exercises the real resolver selection)."""
    from app.main import create_app, init_storage

    await init_storage()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://gov.test") as c:
        yield c


async def test_static_key_in_development(raw_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTAI_GOVERNANCE_STATIC_KEYS", f"tai_live_dev_local_key_123=  {PROJECT}, broken")
    get_settings.cache_clear()
    ok = await raw_client.post("/api/v1/agents", headers={"X-API-Key": "tai_live_dev_local_key_123"},
                               json={"external_id": "WL-STATIC", "name": "Static"})
    assert ok.status_code == 201 and ok.json()["project_id"] == str(uuid.UUID(PROJECT))
    # unknown key falls through to the api_keys table, which does not exist here -> 401 (not 500)
    assert (await raw_client.get("/api/v1/agents", headers={"X-API-Key": "tai_live_other"})).status_code == 401


async def test_static_keys_ignored_in_production(raw_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTAI_GOVERNANCE_STATIC_KEYS", f"tai_live_dev_local_key_123={PROJECT}")
    monkeypatch.setenv("TRUSTAI_ENVIRONMENT", "production")
    get_settings.cache_clear()
    from app.security import get_key_resolver

    assert get_key_resolver().__name__ == "db_key_resolver"
