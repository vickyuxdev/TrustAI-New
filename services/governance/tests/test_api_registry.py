"""Integration tests: health, security, authentication and the agent registry."""
from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from tests.conftest import AGENT_BODY, FACTORY, OTHER

API = "/api/v1"


async def test_health_ready_and_secure_headers(client: httpx.AsyncClient) -> None:
    health = await client.get("/health")
    ready = await client.get("/ready")
    assert health.json()["status"] == "ok" and ready.json()["status"] == "ready"
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy", "Strict-Transport-Security",
                   "Referrer-Policy", "X-Request-ID"):
        assert header in health.headers


async def test_auth_rejects_bad_keys_and_missing_scope(client: httpx.AsyncClient) -> None:
    bad = await client.get(f"{API}/agents", headers={"X-API-Key": "tai_live_nope"})
    no_scope = await client.get(f"{API}/agents", headers={"X-API-Key": "tai_live_ingest_only_ccccccccccccccccc"})
    bad_secret = await client.get(f"{API}/agents", headers={"X-Internal-Secret": "wrong"})
    assert (bad.status_code, no_scope.status_code, bad_secret.status_code) == (401, 403, 401)


async def test_unauthenticated_outside_dev_is_401(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTAI_ENVIRONMENT", "production")
    get_settings.cache_clear()
    resp = await client.get(f"{API}/agents")
    assert resp.status_code == 401 and resp.headers["WWW-Authenticate"] == "Bearer"


async def test_onboard_is_idempotent_and_attaches_baseline(client: httpx.AsyncClient, agent: dict) -> None:
    assert agent["lifecycle_status"] == "onboarded" and agent["slug"] == "wl-20261027-acme-001"
    assert len(agent["policy_ids"]) == 1 and agent["default_guardrail_id"]
    assert agent["runtime_config"]["base_url"] == "http://agent.test/chat"
    again = await client.post(f"{API}/agents", json={**AGENT_BODY, "version": "1.1.0"}, headers=FACTORY)
    assert again.status_code == 200 and again.json()["id"] == agent["id"] and again.json()["version"] == "1.1.0"
    assert again.json()["policy_ids"] == agent["policy_ids"]


async def test_onboard_validates_input(client: httpx.AsyncClient) -> None:
    bad_id = await client.post(f"{API}/agents", json={**AGENT_BODY, "external_id": "bad id with spaces"}, headers=FACTORY)
    bad_policy = await client.post(f"{API}/agents", json={**AGENT_BODY, "tools": [{"name": "x", "policy": "maybe"}]},
                                   headers=FACTORY)
    bad_url = await client.post(f"{API}/agents", json={**AGENT_BODY, "endpoint": "ftp://x"}, headers=FACTORY)
    assert {bad_id.status_code, bad_policy.status_code, bad_url.status_code} == {422}


async def test_list_filter_get_patch_and_history(client: httpx.AsyncClient, agent: dict) -> None:
    listed = (await client.get(f"{API}/agents", params={"search": "invoice"}, headers=FACTORY)).json()
    assert listed["total"] == 1
    by_ext = (await client.get(f"{API}/agents", params={"external_id": AGENT_BODY["external_id"]})).json()
    assert by_ext["items"][0]["id"] == agent["id"]
    assert (await client.get(f"{API}/agents", params={"status": "deployed"})).json()["total"] == 0
    patched = await client.patch(f"{API}/agents/{agent['id']}", json={"tags": ["finance"], "model": "gpt-4o-mini"},
                                 headers=FACTORY)
    assert patched.json()["tags"] == ["finance"] and patched.json()["model"] == "gpt-4o-mini"
    history = (await client.get(f"{API}/agents/{agent['id']}/history", headers=FACTORY)).json()
    assert [h["to_status"] for h in history] == ["onboarded"]


async def test_projects_are_isolated(client: httpx.AsyncClient, agent: dict) -> None:
    assert (await client.get(f"{API}/agents/{agent['id']}", headers=OTHER)).status_code == 404
    assert (await client.get(f"{API}/agents", headers=OTHER)).json()["total"] == 0


async def test_status_rules_for_machines_and_people(client: httpx.AsyncClient, agent: dict) -> None:
    url = f"{API}/agents/{agent['id']}/status"
    assert (await client.post(url, json={"status": "evaluated"}, headers=FACTORY)).json()["lifecycle_status"] == "evaluated"
    assert (await client.post(url, json={"status": "approved"}, headers=FACTORY)).status_code == 403
    assert (await client.post(url, json={"status": "onboarded"}, headers=FACTORY)).json()["lifecycle_status"] == "evaluated"
    assert (await client.post(url, json={"status": "deployed"})).status_code == 409
    approved = await client.post(url, json={"status": "approved", "reason": "reviewed"})  # dev user = person
    assert approved.json()["lifecycle_status"] == "approved"
    assert (await client.post(url, json={"status": "registered"})).status_code == 409


async def test_connection_test_and_mcp(client: httpx.AsyncClient, agent: dict) -> None:
    conn = (await client.post(f"{API}/agents/{agent['id']}/test-connection", json={}, headers=FACTORY)).json()
    assert conn["ok"] is True and conn["status_code"] == 200 and "Happy to help" in conn["response_preview"]
    servers = {"servers": {"erp": {"type": "http", "url": "https://erp.internal/mcp"}, "files": {"type": "stdio", "command": "mcp-files"}}}
    reg = await client.post(f"{API}/mcp-servers", json={"external_id": AGENT_BODY["external_id"], **servers}, headers=FACTORY)
    assert reg.status_code == 200 and {s["name"] for s in reg.json()} == {"erp", "files"}
    again = await client.post(f"{API}/mcp-servers", json={"agent_id": agent["id"], **servers}, headers=FACTORY)
    assert {s["id"] for s in again.json()} == {s["id"] for s in reg.json()}
    assert len((await client.get(f"{API}/mcp-servers", params={"agent_id": agent["id"]}, headers=FACTORY)).json()) == 2


async def test_unreachable_agent_reports_error(client: httpx.AsyncClient, agent: dict) -> None:
    from app.services import agent_client

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    agent_client.TRANSPORT = httpx.MockTransport(boom)
    conn = (await client.post(f"{API}/agents/{agent['id']}/test-connection", json={}, headers=FACTORY)).json()
    assert conn["ok"] is False and "ConnectError" in conn["error"]
