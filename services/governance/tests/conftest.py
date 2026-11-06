"""Shared fixtures: isolated SQLite DB per test, in-memory API keys, an in-process fake agent."""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

os.environ.setdefault("TRUSTAI_ENVIRONMENT", "test")

from app.config import get_settings  # noqa: E402
from app.db import reset_engine  # noqa: E402
from app.engine import backends  # noqa: E402
from app.engine.detectors import score_prompt_manipulation, score_toxicity  # noqa: E402
from app.security import ResolvedKey, get_key_resolver  # noqa: E402
from app.services import agent_client  # noqa: E402

PROJECT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
PROJECT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
KEYS = {
    "tai_live_factory_key_aaaaaaaaaaaaaaaa": ResolvedKey(PROJECT_A, frozenset({"ingest", "govern"}), "tai_live_facto"),
    "tai_live_other_project_bbbbbbbbbbbbbb": ResolvedKey(PROJECT_B, frozenset({"govern"}), "tai_live_other"),
    "tai_live_ingest_only_ccccccccccccccccc": ResolvedKey(PROJECT_A, frozenset({"ingest"}), "tai_live_inges"),
}
FACTORY = {"X-API-Key": "tai_live_factory_key_aaaaaaaaaaaaaaaa"}
OTHER = {"X-API-Key": "tai_live_other_project_bbbbbbbbbbbbbb"}
INTERNAL = {"X-Internal-Secret": "test-internal-secret"}


def build_fake_agent() -> FastAPI:
    """A governed-looking agent: refuses attacks and abuse, answers benign prompts, leaks on PII extraction."""
    agent = FastAPI()

    @agent.post("/chat")
    async def chat(body: dict) -> dict:
        msg = str(body.get("message", ""))
        lowered = msg.lower()
        if "full names, emails" in lowered:  # deliberate weakness: PII extraction leaks
            return {"response": "Sure: Jane Roe, jane.roe@example.com, +44 20 7946 0958"}
        if score_prompt_manipulation(msg)[0] >= 50 or score_toxicity(msg)[0] >= 50 or any(
                w in lowered for w in ("delete all", "export the entire", "bank account details", "500 times",
                                       "essay", "stock tips", "diagnose", "other clients", "empty filter",
                                       "every customer", "credential", "home address", "card numbers")):
            return {"response": "I'm sorry, but I can't help with that request.", "trustai_guard": []}
        return {"response": f"Happy to help. Here is what I found for: {msg[:60]}"}

    return agent


@pytest.fixture(autouse=True)
async def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Fresh database file, settings and caches for every test."""
    monkeypatch.setenv("TRUSTAI_ENVIRONMENT", "test")
    monkeypatch.setenv("TRUSTAI_POSTGRES_URL", f"sqlite+aiosqlite:///{(tmp_path / 'gov.db').as_posix()}")
    monkeypatch.setenv("TRUSTAI_INTERNAL_API_SECRET", "test-internal-secret")
    monkeypatch.setenv("TRUSTAI_EVAL_EXECUTOR", "inline")
    monkeypatch.setenv("TRUSTAI_GATEWAY_PUBLIC_URL", "http://gateway.test")
    for var in ("AZURE_CONTENT_SAFETY_ENDPOINT", "TRUSTAI_JUDGE_PROVIDER", "TRUSTAI_GATEWAY_MODELS"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    backends.clear_cache()
    await reset_engine()
    agent_client.TRANSPORT = httpx.ASGITransport(app=build_fake_agent())
    yield
    agent_client.TRANSPORT = None
    await reset_engine()
    get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """API client against a freshly initialised app (tables + catalog)."""
    from app.main import create_app, init_storage

    app = create_app()

    async def resolver(_session, raw_key: str) -> ResolvedKey | None:
        return KEYS.get(raw_key)

    app.dependency_overrides[get_key_resolver] = lambda: resolver
    await init_storage()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gov.test") as c:
        yield c


AGENT_BODY = {
    "external_id": "WL-20261027-ACME-001",
    "name": "Invoice Payments Agent",
    "description": "Validates supplier invoices and schedules approved payments.",
    "client": "Acme Manufacturing",
    "built_by": "RandomTrees AI Factory",
    "model": "gpt-4o",
    "autonomy_level": "conditional",
    "tools": [
        {"name": "read_invoice", "side_effect": "read", "policy": "allow"},
        {"name": "schedule_payment", "side_effect": "write", "policy": "require_approval",
         "approval_threshold": {"amount_gt": 10000}},
        {"name": "delete_vendor", "side_effect": "write", "policy": "deny"},
    ],
    "endpoint": "http://agent.test/chat",
}


@pytest.fixture
async def agent(client: httpx.AsyncClient) -> dict:
    """An onboarded agent in project A."""
    resp = await client.post("/api/v1/agents", json=AGENT_BODY, headers=FACTORY)
    assert resp.status_code == 201, resp.text
    return resp.json()
