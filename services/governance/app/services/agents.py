"""
services/governance/app/services/agents.py
Agent registry: onboarding (idempotent upsert), lifecycle transitions, connection tests, policies, MCP servers.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentPolicy, AgentStatusChange, GovernedAgent, LifecycleStatus, McpServer, Policy
from app.schemas import AgentOnboard, AgentOut, AgentUpdate, McpOnboard
from app.security import Principal
from app.services import catalog
from app.services.agent_client import AgentReply, call_agent
from app.services.common import emit, get_agent, portal_url, slugify

# Transitions a machine credential (factory, CI) may request. The rest are human or gate-driven.
MACHINE_STATUSES = {LifecycleStatus.ONBOARDED, LifecycleStatus.ASSESSED, LifecycleStatus.EVALUATED}
# Allowed transitions (from -> to). DEPLOYED is set by a gateway deployment, never via the status endpoint.
TRANSITIONS: dict[LifecycleStatus, set[LifecycleStatus]] = {
    LifecycleStatus.REGISTERED: {LifecycleStatus.ONBOARDED, LifecycleStatus.RETIRED},
    LifecycleStatus.ONBOARDED: {LifecycleStatus.ASSESSED, LifecycleStatus.EVALUATED, LifecycleStatus.SUSPENDED,
                                LifecycleStatus.RETIRED},
    LifecycleStatus.ASSESSED: {LifecycleStatus.EVALUATED, LifecycleStatus.ONBOARDED, LifecycleStatus.SUSPENDED,
                               LifecycleStatus.RETIRED},
    LifecycleStatus.EVALUATED: {LifecycleStatus.APPROVED, LifecycleStatus.ASSESSED, LifecycleStatus.ONBOARDED,
                                LifecycleStatus.SUSPENDED, LifecycleStatus.RETIRED},
    LifecycleStatus.APPROVED: {LifecycleStatus.EVALUATED, LifecycleStatus.SUSPENDED, LifecycleStatus.RETIRED},
    LifecycleStatus.DEPLOYED: {LifecycleStatus.EVALUATED, LifecycleStatus.SUSPENDED, LifecycleStatus.RETIRED},
    LifecycleStatus.SUSPENDED: {LifecycleStatus.ONBOARDED, LifecycleStatus.EVALUATED, LifecycleStatus.RETIRED},
    LifecycleStatus.RETIRED: set(),
}
# Ordering used so a re-run of an earlier factory step never moves an agent backwards.
PROGRESS = [LifecycleStatus.REGISTERED, LifecycleStatus.ONBOARDED, LifecycleStatus.ASSESSED,
            LifecycleStatus.EVALUATED, LifecycleStatus.APPROVED, LifecycleStatus.DEPLOYED]


async def policy_ids(session: AsyncSession, agent_id: uuid.UUID) -> list[uuid.UUID]:
    """Ids of the policies attached to an agent."""
    return list((await session.execute(
        select(AgentPolicy.policy_id).where(AgentPolicy.agent_id == agent_id))).scalars())


async def to_out(session: AsyncSession, agent: GovernedAgent) -> AgentOut:
    """ORM -> API model including attached policies and the portal link."""
    out = AgentOut.model_validate(agent)
    out.policy_ids = await policy_ids(session, agent.id)
    out.portal_url = portal_url(f"governance/agents/{agent.id}")
    return out


def _runtime(body: AgentOnboard | AgentUpdate) -> dict[str, Any] | None:
    """Runtime config from either the full `runtime` block or the `endpoint` shortcut."""
    if body.runtime is not None:
        data = body.runtime.model_dump(mode="json")
        return data
    endpoint = getattr(body, "endpoint", None)
    if endpoint is not None:
        return {"base_url": str(endpoint), "request_template": {"message": "{{prompt}}"}, "response_key": "response",
                "timeout_seconds": 60.0}
    return None


async def record_transition(session: AsyncSession, agent: GovernedAgent, to: LifecycleStatus, actor: str,
                            reason: str | None) -> None:
    """Set the status and append history + event."""
    previous = agent.lifecycle_status
    if previous == to:
        return
    agent.lifecycle_status = to
    session.add(AgentStatusChange(agent_id=agent.id, from_status=previous.value if previous else None,
                                  to_status=to.value, reason=reason, actor=actor))
    await emit(session, project_id=agent.project_id, event_type=f"agent.{to.value}", resource_type="agent",
               resource_id=agent.id, agent_id=agent.id, actor=actor,
               payload={"from": previous.value if previous else None, "to": to.value, "reason": reason})


async def advance(session: AsyncSession, agent: GovernedAgent, to: LifecycleStatus, actor: str,
                  reason: str | None) -> None:
    """Move forward only (used by automated steps so re-runs never regress an approved/deployed agent)."""
    if agent.lifecycle_status not in PROGRESS:  # suspended / retired agents stay where a person put them
        return
    if PROGRESS.index(to) > PROGRESS.index(agent.lifecycle_status):
        await record_transition(session, agent, to, actor, reason)


async def onboard(session: AsyncSession, principal: Principal, body: AgentOnboard) -> tuple[GovernedAgent, bool]:
    """Create or update the agent identified by (project, external_id). Returns (agent, created)."""
    project_id = principal.resolve_project(body.project_id)
    agent = (await session.execute(select(GovernedAgent).where(
        GovernedAgent.project_id == project_id, GovernedAgent.external_id == body.external_id))).scalar_one_or_none()
    created = agent is None
    tools = [t.model_dump(mode="json", exclude_none=True) for t in body.tools]
    if agent is None:
        agent = GovernedAgent(project_id=project_id, external_id=body.external_id, name=body.name,
                              slug=slugify(body.external_id), lifecycle_status=LifecycleStatus.REGISTERED)
        session.add(agent)
    agent.name, agent.description, agent.version = body.name, body.description, body.version
    agent.owner, agent.built_by, agent.model, agent.autonomy_level = body.client, body.built_by, body.model, body.autonomy_level
    agent.tools, agent.capabilities, agent.tags = tools, body.capabilities, body.tags
    agent.extra_metadata = {**(agent.extra_metadata or {}), **body.metadata}
    runtime = _runtime(body)
    if runtime is not None:
        agent.runtime_config = runtime
    await session.flush()

    if body.attach_baseline_policy and not await policy_ids(session, agent.id):
        baseline = await catalog.system_policy(session, catalog.BASELINE_POLICY_KEY)
        if baseline is not None:
            session.add(AgentPolicy(agent_id=agent.id, policy_id=baseline.id, attached_by=principal.subject))
    if agent.default_guardrail_id is None:
        guard = await catalog.system_guardrail(session, catalog.DEFAULT_GUARDRAIL_KEY)
        agent.default_guardrail_id = guard.id if guard else None
    await emit(session, project_id=project_id, event_type="agent.registered" if created else "agent.updated",
               resource_type="agent", resource_id=agent.id, agent_id=agent.id, actor=principal.subject,
               payload={"external_id": body.external_id, "version": body.version, "tools": len(tools)})
    if agent.lifecycle_status == LifecycleStatus.REGISTERED:
        await record_transition(session, agent, LifecycleStatus.ONBOARDED, principal.subject, "onboarded via API")
    await session.flush()
    return agent, created


async def update(session: AsyncSession, principal: Principal, agent_id: uuid.UUID, body: AgentUpdate) -> GovernedAgent:
    """Patch editable fields."""
    agent = await get_agent(session, principal, agent_id)
    data = body.model_dump(exclude_unset=True, mode="json")
    runtime = _runtime(body) if "runtime" in data else None
    for field in ("name", "description", "version", "model", "tags"):
        if field in data:
            setattr(agent, field, data[field])
    if "tools" in data and data["tools"] is not None:
        agent.tools = [{k: v for k, v in t.items() if v is not None} for t in data["tools"]]
    if runtime is not None:
        agent.runtime_config = runtime
    await emit(session, project_id=agent.project_id, event_type="agent.updated", resource_type="agent",
               resource_id=agent.id, agent_id=agent.id, actor=principal.subject, payload={"fields": sorted(data)})
    return agent


async def change_status(session: AsyncSession, principal: Principal, agent_id: uuid.UUID, to: LifecycleStatus,
                        reason: str | None) -> GovernedAgent:
    """Validated lifecycle transition (machines are limited to onboarded / assessed / evaluated)."""
    agent = await get_agent(session, principal, agent_id)
    if to == LifecycleStatus.DEPLOYED:
        raise HTTPException(status.HTTP_409_CONFLICT, "agents become 'deployed' through a gateway deployment")
    if principal.kind == "api_key" and to not in MACHINE_STATUSES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"'{to.value}' is a human decision in the TrustAI portal")
    if to == agent.lifecycle_status:
        return agent
    if principal.kind == "api_key" and agent.lifecycle_status in PROGRESS and PROGRESS.index(to) < PROGRESS.index(agent.lifecycle_status):
        return agent  # an automated re-run never moves an agent backwards
    if to not in TRANSITIONS[agent.lifecycle_status]:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"cannot move from '{agent.lifecycle_status.value}' to '{to.value}'")
    await record_transition(session, agent, to, principal.subject, reason)
    return agent


async def set_policies(session: AsyncSession, principal: Principal, agent_id: uuid.UUID,
                       ids: list[uuid.UUID]) -> GovernedAgent:
    """Replace the agent's attached policies (each must be a system policy or in the agent's project)."""
    agent = await get_agent(session, principal, agent_id)
    found = (await session.execute(select(Policy).where(Policy.id.in_(ids)))).scalars().all() if ids else []
    if len(found) != len(set(ids)) or any(p.project_id not in (None, agent.project_id) for p in found):
        raise HTTPException(422, "unknown policy id for this agent's project")
    await session.execute(delete(AgentPolicy).where(AgentPolicy.agent_id == agent.id))
    for pid in dict.fromkeys(ids):
        session.add(AgentPolicy(agent_id=agent.id, policy_id=pid, attached_by=principal.subject))
    await emit(session, project_id=agent.project_id, event_type="agent.policies_changed", resource_type="agent",
               resource_id=agent.id, agent_id=agent.id, actor=principal.subject,
               payload={"policy_ids": [str(i) for i in ids]})
    await session.flush()
    return agent


async def test_connection(session: AsyncSession, principal: Principal, agent_id: uuid.UUID, prompt: str) -> dict[str, Any]:
    """Send one prompt to the agent's runtime endpoint and report reachability."""
    agent = await get_agent(session, principal, agent_id)
    reply: AgentReply = await call_agent(agent.runtime_config or {}, prompt, timeout_seconds=30)
    await emit(session, project_id=agent.project_id, event_type="agent.connection_test", resource_type="agent",
               resource_id=agent.id, agent_id=agent.id, actor=principal.subject,
               severity="info" if reply.ok else "medium",
               payload={"ok": reply.ok, "status_code": reply.status_code, "latency_ms": reply.latency_ms,
                        "error": reply.error})
    return {"ok": reply.ok, "status_code": reply.status_code, "latency_ms": reply.latency_ms, "error": reply.error,
            "response_preview": reply.text[:500]}


async def onboard_mcp(session: AsyncSession, principal: Principal, body: McpOnboard) -> list[McpServer]:
    """Register (upsert by name) an agent's external MCP servers."""
    agent = await get_agent(session, principal, body.agent_id, body.external_id)
    out: list[McpServer] = []
    for name, spec in body.servers.items():
        row = (await session.execute(select(McpServer).where(
            McpServer.project_id == agent.project_id, McpServer.agent_id == agent.id,
            McpServer.name == name))).scalar_one_or_none()
        if row is None:
            row = McpServer(project_id=agent.project_id, agent_id=agent.id, name=name)
            session.add(row)
        row.transport, row.url, row.command = spec.type, spec.url, spec.command
        out.append(row)
    await session.flush()
    await emit(session, project_id=agent.project_id, event_type="agent.mcp_registered", resource_type="agent",
               resource_id=agent.id, agent_id=agent.id, actor=principal.subject,
               payload={"servers": sorted(body.servers)})
    return out
