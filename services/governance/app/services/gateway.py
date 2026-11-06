"""
services/governance/app/services/gateway.py
AI-gateway control plane: the deployment gate, per-agent gateway keys (hash stored, raw shown once), key
authorisation for the gateway data plane, revocation and the model list.

Deployment gate (server-side; the AI Factory's own Gate 06 runs before this):
  * agent not suspended / retired, and its latest risk decision is not `rejected`
  * a classified (or decided) risk assessment exists
  * the latest completed red-team trust score meets the tier threshold (Tier 1-2: 90, Tier 3: 95, Tier 4: 98)
  * Tier 3+: a human decision exists; `approved_with_conditions` needs allow_conditional=true
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AssessmentStatus,
    Decision,
    DeploymentStatus,
    GatewayDeployment,
    GovernedAgent,
    LifecycleStatus,
)
from app.schemas import GatewayDeployIn
from app.security import Principal, hash_key
from app.services import agents as agent_svc
from app.services import evaluations as eval_svc
from app.services import risk as risk_svc
from app.services.common import emit, get_agent

KEY_PREFIX = "tai_gw_"
TIER_TRUST_THRESHOLD = {None: 90.0, 1: 90.0, 2: 90.0, 3: 95.0, 4: 98.0}


def available_models(agent: GovernedAgent | None = None) -> list[str]:
    """Models the gateway serves (TRUSTAI_GATEWAY_MODELS) plus the agent's own model when no list is configured."""
    s = get_settings()
    configured = [m.strip() for m in s.gateway_models.split(",") if m.strip()]
    if configured:
        return configured
    models = [s.default_gateway_model]
    if agent is not None and agent.model and agent.model not in models:
        models.append(agent.model)
    return models


async def evaluate_gate(session: AsyncSession, agent: GovernedAgent, allow_conditional: bool) -> dict[str, Any]:
    """Check every deployment condition; returns {allowed, checks[], tier, trust_score, decision}."""
    checks: list[dict[str, Any]] = []
    checks.append({"check": "agent_active", "passed": agent.lifecycle_status not in
                   (LifecycleStatus.SUSPENDED, LifecycleStatus.RETIRED), "detail": agent.lifecycle_status.value})
    assessment = await risk_svc.latest_for_agent(session, agent.id)
    classified = assessment is not None and assessment.status in (AssessmentStatus.CLASSIFIED, AssessmentStatus.DECIDED)
    tier = assessment.risk_tier if classified and assessment else None
    checks.append({"check": "risk_assessed", "passed": classified,
                   "detail": f"tier {tier}" if classified else "no classified risk assessment"})
    decision = assessment.decision if assessment else None
    checks.append({"check": "not_rejected", "passed": decision != Decision.REJECTED,
                   "detail": decision.value if decision else "no decision"})
    if tier is not None and tier >= 3:
        has_decision = decision in (Decision.APPROVED, Decision.APPROVED_WITH_CONDITIONS)
        checks.append({"check": "human_decision_for_high_risk", "passed": has_decision,
                       "detail": decision.value if decision else "Tier 3+ needs a human risk decision in TrustAI"})
        if decision == Decision.APPROVED_WITH_CONDITIONS:
            checks.append({"check": "conditions_acknowledged", "passed": allow_conditional,
                           "detail": "pass allow_conditional=true to deploy with conditions",
                           "conditions": assessment.conditions if assessment else []})
    evaluation = await eval_svc.latest_completed(session, agent.id)
    threshold = TIER_TRUST_THRESHOLD.get(tier, 95.0)
    trust = evaluation.trust_score if evaluation else None
    checks.append({"check": "red_team_trust_score", "passed": trust is not None and trust >= threshold,
                   "detail": f"trust score {trust} (needs {threshold})" if trust is not None else "no completed red-team",
                   "evaluation_id": str(evaluation.id) if evaluation else None})
    return {"allowed": all(c["passed"] for c in checks), "checks": checks, "risk_tier": tier, "trust_score": trust,
            "trust_threshold": threshold, "decision": decision.value if decision else None,
            "assessment_id": str(assessment.id) if assessment else None}


async def deploy(session: AsyncSession, principal: Principal, agent_id: uuid.UUID, body: GatewayDeployIn) -> tuple[GatewayDeployment, str]:
    """Pass the gate, rotate the agent's gateway key and mark the agent deployed. Returns (deployment, raw_key)."""
    agent = await get_agent(session, principal, agent_id)
    gate = await evaluate_gate(session, agent, body.allow_conditional)
    if not gate["allowed"]:
        await emit(session, project_id=agent.project_id, event_type="gateway.deploy_blocked", resource_type="agent",
                   resource_id=agent.id, agent_id=agent.id, actor=principal.subject, severity="medium", payload=gate)
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "deployment gate not passed", "gate": gate})
    models = available_models(agent)
    model = body.model or agent.model or get_settings().default_gateway_model
    if model not in models:
        raise HTTPException(422, f"model {model!r} not served; available: {models}")
    allowed = [m for m in (body.allowed_models or [model]) if m in models] or [model]
    for old in (await session.execute(select(GatewayDeployment).where(
            GatewayDeployment.agent_id == agent.id, GatewayDeployment.status == DeploymentStatus.ACTIVE))).scalars():
        old.status, old.revoked_at = DeploymentStatus.REVOKED, datetime.now(timezone.utc)
    raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
    row = GatewayDeployment(project_id=agent.project_id, agent_id=agent.id, model=model, allowed_models=allowed,
                            key_prefix=raw_key[:14], key_hash=hash_key(raw_key), gate=gate,
                            deployed_by=principal.subject)
    session.add(row)
    await agent_svc.record_transition(session, agent, LifecycleStatus.DEPLOYED, principal.subject,
                                      f"deployed behind the TrustAI AI Gateway (model {model})")
    await emit(session, project_id=agent.project_id, event_type="gateway.deployed", resource_type="agent",
               resource_id=agent.id, agent_id=agent.id, actor=principal.subject,
               payload={"model": model, "allowed_models": allowed, "key_prefix": row.key_prefix})
    await session.flush()
    return row, raw_key


async def active_deployment(session: AsyncSession, agent_id: uuid.UUID) -> GatewayDeployment | None:
    """The agent's active gateway deployment, if any."""
    return (await session.execute(select(GatewayDeployment).where(
        GatewayDeployment.agent_id == agent_id, GatewayDeployment.status == DeploymentStatus.ACTIVE)
        .order_by(GatewayDeployment.created_at.desc()).limit(1))).scalar_one_or_none()


async def revoke(session: AsyncSession, principal: Principal, agent_id: uuid.UUID) -> GatewayDeployment:
    """Revoke the active key; the agent drops back to `evaluated`."""
    agent = await get_agent(session, principal, agent_id)
    row = await active_deployment(session, agent.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active gateway deployment")
    row.status, row.revoked_at = DeploymentStatus.REVOKED, datetime.now(timezone.utc)
    if agent.lifecycle_status == LifecycleStatus.DEPLOYED:
        await agent_svc.record_transition(session, agent, LifecycleStatus.EVALUATED, principal.subject,
                                          "gateway access revoked")
    await emit(session, project_id=agent.project_id, event_type="gateway.revoked", resource_type="agent",
               resource_id=agent.id, agent_id=agent.id, actor=principal.subject, severity="medium",
               payload={"key_prefix": row.key_prefix})
    return row


async def authorize(session: AsyncSession, raw_key: str) -> tuple[GatewayDeployment, GovernedAgent]:
    """Resolve a gateway key to its active deployment and agent (401 when unknown, revoked or agent suspended)."""
    row = (await session.execute(select(GatewayDeployment).where(GatewayDeployment.key_hash == hash_key(raw_key))))\
        .scalar_one_or_none()
    if row is None or row.status != DeploymentStatus.ACTIVE:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or revoked gateway key")
    agent = await session.get(GovernedAgent, row.agent_id)
    if agent is None or agent.lifecycle_status in (LifecycleStatus.SUSPENDED, LifecycleStatus.RETIRED):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "agent is suspended or retired")
    return row, agent
