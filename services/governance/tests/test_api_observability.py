"""Integration tests: POST /agents/{id}/observability wires a governed agent up for traces via the admin service."""
from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.services import observability
from tests.conftest import FACTORY, OTHER

API = "/api/v1"
CLIENT_ID, PROJECT_ID = uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def admin_calls() -> list[httpx.Request]:
    """Fake admin service: records each request and issues a new raw key per call."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("X-Internal-Secret") != "test-internal-secret":
            return httpx.Response(401, json={"detail": "invalid internal secret"})
        return httpx.Response(201, json={
            "client_id": str(CLIENT_ID), "project_id": str(PROJECT_ID), "api_key_id": str(uuid.uuid4()),
            "key_prefix": "tai_live_abcdefg", "raw_key": f"tai_live_raw_{len(calls)}", "scopes": ["ingest"],
            "created_client": len(calls) == 1, "created_project": len(calls) == 1, "revoked_keys": len(calls) - 1})

    observability.TRANSPORT = httpx.MockTransport(handler)
    yield calls
    observability.TRANSPORT = None


async def test_provision_returns_one_time_key_and_records_mapping(client: httpx.AsyncClient, agent: dict,
                                                                 admin_calls: list[httpx.Request]) -> None:
    resp = await client.post(f"{API}/agents/{agent['id']}/observability", json={"environment": "development"},
                             headers=FACTORY)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["ingest_key"] == "tai_live_raw_1" and out["project_id"] == str(PROJECT_ID)
    assert out["ingest_url"].startswith("http") and out["traces_url"].endswith("/traces") and out["rotated"] is False

    sent = json.loads(admin_calls[0].content)
    assert admin_calls[0].url.path == "/api/v1/internal/observability/provision"
    assert sent["client_slug"] == "acme-manufacturing" and sent["project_slug"] == agent["slug"]
    assert sent["governance_agent_id"] == agent["id"] and sent["environment"] == "development"

    events = (await client.get(f"{API}/events", headers=FACTORY)).json()
    event = next(e for e in events if e["event_type"] == "agent.observability_provisioned")
    assert event["payload"]["project_id"] == str(PROJECT_ID)
    assert "tai_live_raw_1" not in json.dumps(event)  # the raw key is never stored or logged


async def test_reprovision_rotates_key(client: httpx.AsyncClient, agent: dict,
                                       admin_calls: list[httpx.Request]) -> None:
    first = await client.post(f"{API}/agents/{agent['id']}/observability", json={}, headers=FACTORY)
    second = await client.post(f"{API}/agents/{agent['id']}/observability", json={}, headers=FACTORY)
    assert first.json()["ingest_key"] != second.json()["ingest_key"] and second.json()["rotated"] is True


async def test_other_project_cannot_provision(client: httpx.AsyncClient, agent: dict,
                                              admin_calls: list[httpx.Request]) -> None:
    resp = await client.post(f"{API}/agents/{agent['id']}/observability", json={}, headers=OTHER)
    assert resp.status_code == 404 and not admin_calls


async def test_admin_down_is_503(client: httpx.AsyncClient, agent: dict) -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    observability.TRANSPORT = httpx.MockTransport(boom)
    try:
        resp = await client.post(f"{API}/agents/{agent['id']}/observability", json={}, headers=FACTORY)
    finally:
        observability.TRANSPORT = None
    assert resp.status_code == 503


async def test_invalid_environment_is_422(client: httpx.AsyncClient, agent: dict,
                                          admin_calls: list[httpx.Request]) -> None:
    resp = await client.post(f"{API}/agents/{agent['id']}/observability", json={"environment": "Prod; DROP"},
                             headers=FACTORY)
    assert resp.status_code == 422 and not admin_calls
