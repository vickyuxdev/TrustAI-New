"""
services/governance/app/routers/agents.py
Agent registry endpoints: onboarding, lookup, lifecycle, policies, connection test, MCP servers, gateway
deployment, evidence and policy optimisation.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_dep
from app.models import AgentStatusChange, GovernedAgent, LifecycleStatus, McpServer
from app.schemas import (
    AgentOnboard,
    AgentOut,
    AgentUpdate,
    AttachPolicies,
    ConnectionTest,
    GatewayDeployIn,
    GatewayDeployOut,
    McpOnboard,
    McpServerOut,
    ObservabilityIn,
    ObservabilityOut,
    OptimizeIn,
    Page,
    StatusChange,
    StatusHistoryOut,
)
from app.security import CurrentPrincipal
from app.services import agents as svc
from app.services import evidence as evidence_svc
from app.services import gateway as gateway_svc
from app.services import observability as observability_svc
from app.services.common import get_agent, paginate

router = APIRouter()
Session = Annotated[AsyncSession, Depends(session_dep)]


@router.post("/agents", response_model=AgentOut, summary="Onboard (create or update) an agent")
async def onboard_agent(body: AgentOnboard, principal: CurrentPrincipal, session: Session, response: Response) -> AgentOut:
    """Idempotent upsert by (project, external_id); new agents get the TrustAI Baseline policy and move to onboarded."""
    agent, created = await svc.onboard(session, principal, body)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return await svc.to_out(session, agent)


@router.get("/agents", response_model=Page[AgentOut], summary="List agents")
async def list_agents(
    principal: CurrentPrincipal, session: Session,
    project_id: uuid.UUID | None = None, lifecycle_status: LifecycleStatus | None = Query(default=None, alias="status"),
    risk_tier: int | None = Query(default=None, ge=1, le=4), search: str | None = Query(default=None, max_length=200),
    external_id: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
) -> Page[AgentOut]:
    """Filterable, paginated registry listing."""
    stmt = select(GovernedAgent).order_by(GovernedAgent.updated_at.desc())
    visible = principal.visible_projects()
    if visible is not None:
        stmt = stmt.where(GovernedAgent.project_id.in_(visible))
    if project_id:
        stmt = stmt.where(GovernedAgent.project_id == project_id)
    if lifecycle_status:
        stmt = stmt.where(GovernedAgent.lifecycle_status == lifecycle_status)
    if risk_tier:
        stmt = stmt.where(GovernedAgent.risk_tier == risk_tier)
    if external_id:
        stmt = stmt.where(GovernedAgent.external_id == external_id)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(GovernedAgent.name.ilike(like), GovernedAgent.external_id.ilike(like)))
    rows, total = await paginate(session, stmt, limit, offset)
    return Page(items=[await svc.to_out(session, a) for a in rows], total=total, limit=limit, offset=offset)


@router.get("/agents/{agent_id}", response_model=AgentOut, summary="Get an agent")
async def get_one(agent_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> AgentOut:
    """Registry entry with attached policies."""
    return await svc.to_out(session, await get_agent(session, principal, agent_id))


@router.patch("/agents/{agent_id}", response_model=AgentOut, summary="Update an agent")
async def patch_agent(agent_id: uuid.UUID, body: AgentUpdate, principal: CurrentPrincipal, session: Session) -> AgentOut:
    """Edit metadata, runtime endpoint or tools."""
    return await svc.to_out(session, await svc.update(session, principal, agent_id, body))


@router.post("/agents/{agent_id}/status", response_model=AgentOut, summary="Change lifecycle status")
async def set_status(agent_id: uuid.UUID, body: StatusChange, principal: CurrentPrincipal, session: Session) -> AgentOut:
    """Machines may set onboarded/assessed/evaluated; approved/suspended/retired are human decisions."""
    return await svc.to_out(session, await svc.change_status(session, principal, agent_id, body.status, body.reason))


@router.get("/agents/{agent_id}/history", response_model=list[StatusHistoryOut], summary="Lifecycle history")
async def history(agent_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> list[Any]:
    """Every lifecycle change, oldest first."""
    agent = await get_agent(session, principal, agent_id)
    return list((await session.execute(select(AgentStatusChange).where(AgentStatusChange.agent_id == agent.id)
                                       .order_by(AgentStatusChange.created_at))).scalars())


@router.put("/agents/{agent_id}/policies", response_model=AgentOut, summary="Attach policies")
async def put_policies(agent_id: uuid.UUID, body: AttachPolicies, principal: CurrentPrincipal, session: Session) -> AgentOut:
    """Replace the set of policies enforced for this agent."""
    return await svc.to_out(session, await svc.set_policies(session, principal, agent_id, body.policy_ids))


@router.post("/agents/{agent_id}/test-connection", summary="Test the agent's runtime endpoint")
async def connection(agent_id: uuid.UUID, body: ConnectionTest, principal: CurrentPrincipal, session: Session) -> dict[str, Any]:
    """Send one prompt to the agent and report reachability and latency."""
    return await svc.test_connection(session, principal, agent_id, body.prompt)


@router.post("/mcp-servers", response_model=list[McpServerOut], summary="Register MCP servers")
async def onboard_mcp(body: McpOnboard, principal: CurrentPrincipal, session: Session) -> list[Any]:
    """Upsert an agent's external MCP servers by name."""
    return await svc.onboard_mcp(session, principal, body)


@router.get("/mcp-servers", response_model=list[McpServerOut], summary="List MCP servers")
async def list_mcp(principal: CurrentPrincipal, session: Session, agent_id: uuid.UUID | None = None) -> list[Any]:
    """MCP servers visible to the caller, optionally for one agent."""
    stmt = select(McpServer).order_by(McpServer.name)
    if principal.visible_projects() is not None:
        stmt = stmt.where(McpServer.project_id.in_(principal.visible_projects()))
    if agent_id:
        stmt = stmt.where(McpServer.agent_id == agent_id)
    return list((await session.execute(stmt)).scalars())


@router.get("/agents/{agent_id}/gateway/gate", summary="Check the deployment gate")
async def gate(agent_id: uuid.UUID, principal: CurrentPrincipal, session: Session,
               allow_conditional: bool = False) -> dict[str, Any]:
    """Dry-run of every deployment condition (nothing changes)."""
    return await gateway_svc.evaluate_gate(session, await get_agent(session, principal, agent_id), allow_conditional)


@router.post("/agents/{agent_id}/gateway", response_model=GatewayDeployOut, status_code=status.HTTP_201_CREATED,
             summary="Deploy the agent behind the AI Gateway")
async def deploy(agent_id: uuid.UUID, body: GatewayDeployIn, principal: CurrentPrincipal, session: Session) -> GatewayDeployOut:
    """Passes the gate, rotates the agent's gateway key (returned once) and marks the agent deployed."""
    row, raw_key = await gateway_svc.deploy(session, principal, agent_id, body)
    return GatewayDeployOut(deployment_id=row.id, agent_id=row.agent_id, gateway_url=_gateway_url(), model=row.model,
                            allowed_models=row.allowed_models, api_key=raw_key, key_prefix=row.key_prefix,
                            status=row.status, gate=row.gate, created_at=row.created_at)


@router.get("/agents/{agent_id}/gateway", response_model=GatewayDeployOut | None, summary="Active gateway deployment")
async def active(agent_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> GatewayDeployOut | None:
    """The agent's active deployment (never includes the key)."""
    agent = await get_agent(session, principal, agent_id)
    row = await gateway_svc.active_deployment(session, agent.id)
    if row is None:
        return None
    return GatewayDeployOut(deployment_id=row.id, agent_id=row.agent_id, gateway_url=_gateway_url(), model=row.model,
                            allowed_models=row.allowed_models, key_prefix=row.key_prefix, status=row.status,
                            gate=row.gate, created_at=row.created_at)


@router.delete("/agents/{agent_id}/gateway", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke gateway access")
async def revoke(agent_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> Response:
    """Revoke the active key immediately (kill switch)."""
    await gateway_svc.revoke(session, principal, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/agents/{agent_id}/observability", response_model=ObservabilityOut, status_code=status.HTTP_201_CREATED,
             summary="Wire the agent up for traces (issues a one-time ingest key)")
async def observability(agent_id: uuid.UUID, body: ObservabilityIn, principal: CurrentPrincipal,
                        session: Session) -> ObservabilityOut:
    """Get-or-create the agent's observability project; re-calling rotates the ingest key."""
    return await observability_svc.provision(session, principal, agent_id, body)


@router.get("/agents/{agent_id}/evidence", summary="Evidence pack")
async def evidence(agent_id: uuid.UUID, principal: CurrentPrincipal, session: Session) -> dict[str, Any]:
    """Lifecycle, risk, evaluations, guardrail decisions, violations and gateway state for one agent."""
    return await evidence_svc.evidence_pack(session, principal, agent_id)


@router.post("/agents/{agent_id}/optimize", summary="Recommend policies from red-team gaps")
async def optimize(agent_id: uuid.UUID, body: OptimizeIn, principal: CurrentPrincipal, session: Session) -> dict[str, Any]:
    """Ranks policies that close the latest evaluation's gaps and optionally composes one (not attached)."""
    return await evidence_svc.optimize(session, principal, agent_id, body.name, body.evaluation_id, body.create_policy)


def _gateway_url() -> str:
    """Public OpenAI-compatible base URL of the TrustAI AI Gateway."""
    from app.config import get_settings

    return get_settings().gateway_public_url.rstrip("/") + "/v1"
