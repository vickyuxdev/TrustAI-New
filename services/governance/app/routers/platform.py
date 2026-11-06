"""
services/governance/app/routers/platform.py
Gateway control-plane endpoints (models, deployments, key authorisation for the gateway), the event feed and
the governance overview.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_dep
from app.models import DeploymentStatus, GatewayDeployment, GovernanceEvent
from app.schemas import EventOut, GatewayAuthorizeIn, GatewayAuthorizeOut
from app.security import CurrentPrincipal, require_internal
from app.services import evidence as evidence_svc
from app.services import gateway as gateway_svc

router = APIRouter()
Session = Annotated[AsyncSession, Depends(session_dep)]


@router.get("/gateway/models", summary="Models served by the AI Gateway")
async def models(principal: CurrentPrincipal) -> dict[str, Any]:
    """Configured gateway models."""
    return {"models": gateway_svc.available_models()}


@router.get("/gateway/deployments", summary="Gateway deployments")
async def deployments(principal: CurrentPrincipal, session: Session, active_only: bool = True,
                      limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    """Deployments visible to the caller (keys are never returned)."""
    stmt = select(GatewayDeployment).order_by(GatewayDeployment.created_at.desc()).limit(limit)
    if principal.visible_projects() is not None:
        stmt = stmt.where(GatewayDeployment.project_id.in_(principal.visible_projects()))
    if active_only:
        stmt = stmt.where(GatewayDeployment.status == DeploymentStatus.ACTIVE)
    return [{"deployment_id": str(d.id), "agent_id": str(d.agent_id), "model": d.model,
             "allowed_models": d.allowed_models, "key_prefix": d.key_prefix, "status": d.status.value,
             "deployed_by": d.deployed_by, "created_at": d.created_at.isoformat(),
             "revoked_at": d.revoked_at.isoformat() if d.revoked_at else None}
            for d in (await session.execute(stmt)).scalars()]


@router.post("/gateway/authorize", response_model=GatewayAuthorizeOut, summary="Resolve a gateway key (internal)")
async def authorize(body: GatewayAuthorizeIn, principal: CurrentPrincipal, session: Session) -> GatewayAuthorizeOut:
    """Called by the TrustAI AI Gateway with X-Internal-Secret to map a client key to its agent."""
    require_internal(principal)
    row, agent = await gateway_svc.authorize(session, body.api_key)
    return GatewayAuthorizeOut(deployment_id=row.id, agent_id=agent.id, project_id=agent.project_id,
                               agent_name=agent.name, model=row.model, allowed_models=row.allowed_models)


@router.get("/events", response_model=list[EventOut], summary="Governance event feed")
async def events(principal: CurrentPrincipal, session: Session, agent_id: uuid.UUID | None = None,
                 event_type: str | None = Query(default=None, max_length=80),
                 severity: str | None = Query(default=None, max_length=20),
                 limit: int = Query(default=100, ge=1, le=500)) -> list[Any]:
    """Audit trail and alerts (lifecycle, decisions, deployments, policy violations), newest first."""
    stmt = select(GovernanceEvent).order_by(GovernanceEvent.created_at.desc()).limit(limit)
    if principal.visible_projects() is not None:
        stmt = stmt.where(GovernanceEvent.project_id.in_(principal.visible_projects()))
    if agent_id:
        stmt = stmt.where(GovernanceEvent.agent_id == agent_id)
    if event_type:
        stmt = stmt.where(GovernanceEvent.event_type.like(event_type.replace("*", "%")))
    if severity:
        stmt = stmt.where(GovernanceEvent.severity == severity)
    return list((await session.execute(stmt)).scalars())


@router.get("/overview", summary="Governance KPIs")
async def overview(principal: CurrentPrincipal, session: Session) -> dict[str, Any]:
    """Agents by status and tier, trust, checks, violations, pending decisions, running evaluations, deployments."""
    return await evidence_svc.overview(session, principal)
