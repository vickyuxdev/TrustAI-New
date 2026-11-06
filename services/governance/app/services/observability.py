"""
services/governance/app/services/observability.py
Wires a governed agent up for TrustAI observability (traces).

Governance owns the agent registry; the admin service owns observability clients, projects and API keys. This
service maps one governed agent to one observability project (client = the agent's owner), asks the admin service
for a fresh ingest-only key over the internal service channel, and records the mapping (never the key) on the agent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas import ObservabilityIn, ObservabilityOut
from app.security import Principal
from app.services.common import emit, get_agent, portal_url, slugify

# Transport hook for tests (an httpx.MockTransport); None in production.
TRANSPORT: httpx.AsyncBaseTransport | None = None
DEFAULT_CLIENT = "RandomTrees Internal"


async def _admin_provision(payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the admin service's internal provisioning endpoint; maps failures to 502/503."""
    settings = get_settings()
    url = settings.admin_url.rstrip("/") + "/api/v1/internal/observability/provision"
    headers = {"X-Internal-Secret": settings.internal_api_secret.get_secret_value(),
               "User-Agent": "TrustAI-Governance/0.1"}
    try:
        async with httpx.AsyncClient(timeout=settings.admin_timeout_seconds, transport=TRANSPORT,
                                     follow_redirects=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"TrustAI admin service unreachable: {type(exc).__name__}") from exc
    if resp.status_code != status.HTTP_201_CREATED:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"TrustAI admin service refused provisioning (HTTP {resp.status_code})")
    data = resp.json()
    if not isinstance(data, dict) or not data.get("raw_key") or not data.get("project_id"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "TrustAI admin service returned an invalid response")
    return data


async def provision(session: AsyncSession, principal: Principal, agent_id: uuid.UUID,
                    body: ObservabilityIn) -> ObservabilityOut:
    """Get-or-create the agent's observability project and issue a new ingest key (rotates the previous one)."""
    agent = await get_agent(session, principal, agent_id)
    client_name = (body.client_name or agent.owner or DEFAULT_CLIENT).strip()
    payload = {
        "client_slug": slugify(client_name, 100),
        "client_name": client_name,
        "project_slug": slugify(agent.slug or agent.name, 100),
        "project_name": agent.name[:255],
        "description": f"Traces of governed agent {agent.external_id}",
        "environment": body.environment,
        "key_name": f"AI Factory agent ingest key ({body.environment})",
        "governance_agent_id": str(agent.id),
    }
    data = await _admin_provision(payload)

    previous = (agent.extra_metadata or {}).get("observability") or {}
    mapping = {"client_id": str(data["client_id"]), "project_id": str(data["project_id"]),
               "key_prefix": data["key_prefix"], "environment": body.environment,
               "provisioned_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    agent.extra_metadata = {**(agent.extra_metadata or {}), "observability": mapping}
    await emit(session, project_id=agent.project_id, event_type="agent.observability_provisioned",
               resource_type="agent", resource_id=agent.id, actor=principal.subject, agent_id=agent.id,
               payload={k: v for k, v in mapping.items() if k != "provisioned_at"} | {"rotated": bool(previous)})
    await session.flush()

    return ObservabilityOut(
        agent_id=agent.id, client_id=uuid.UUID(str(data["client_id"])), project_id=uuid.UUID(str(data["project_id"])),
        ingest_url=get_settings().ingestion_public_url.rstrip("/"), ingest_key=data["raw_key"],
        key_prefix=data["key_prefix"], environment=body.environment, traces_url=portal_url("traces"),
        rotated=bool(previous),
    )
