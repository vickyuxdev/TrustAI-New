"""
services/governance/app/services/evidence.py
Evidence packs (everything an auditor needs about one agent), the platform overview and policy optimisation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentStatusChange,
    DeploymentStatus,
    Evaluation,
    EvaluationStatus,
    GatewayDeployment,
    GovernanceEvent,
    GovernedAgent,
    Guardrail,
    GuardrailEvaluation,
    Policy,
    RiskAssessment,
)
from app.security import Principal
from app.services import agents as agent_svc
from app.services import enforcement
from app.services import evaluations as eval_svc
from app.services import gateway as gateway_svc
from app.services import risk as risk_svc
from app.services.catalog import system_guardrail
from app.services.common import emit, get_agent, portal_url

# red-team category -> system policies that close it
CATEGORY_POLICY_HINTS: dict[str, list[str]] = {
    "prompt_injection": ["trustai-high-risk", "trustai-owasp-llm-top10"],
    "jailbreak": ["trustai-high-risk"],
    "system_prompt_extraction": ["trustai-owasp-llm-top10", "trustai-high-risk"],
    "indirect_injection": ["trustai-owasp-llm-top10", "trustai-high-risk"],
    "approval_bypass": ["trustai-high-risk"],
    "prohibited_action": ["trustai-high-risk"],
    "tool_abuse": ["trustai-high-risk"],
    "pii_extraction": ["trustai-pii-strict"],
    "data_exfiltration": ["trustai-pii-strict", "trustai-high-risk"],
    "harmful_content": ["trustai-baseline", "trustai-owasp-llm-top10"],
    "off_scope": ["trustai-owasp-llm-top10"],
}
CATEGORY_GUARDRAIL_HINTS: dict[str, list[tuple[str, str, int]]] = {
    "prompt_injection": [("trustai-strict-input-shield", "input", 4)],
    "jailbreak": [("trustai-strict-input-shield", "input", 4)],
    "system_prompt_extraction": [("trustai-strict-input-shield", "input", 4), ("trustai-output-safety", "output", 4)],
    "indirect_injection": [("trustai-tool-guard", "tool", 4)],
    "approval_bypass": [("trustai-strict-input-shield", "input", 4), ("trustai-tool-guard", "tool", 5)],
    "prohibited_action": [("trustai-tool-guard", "tool", 5)],
    "tool_abuse": [("trustai-tool-guard", "tool", 5)],
    "pii_extraction": [("trustai-pii-guard", "output", 4)],
    "data_exfiltration": [("trustai-pii-guard", "output", 4), ("trustai-output-safety", "output", 4)],
    "harmful_content": [("trustai-output-safety", "output", 4), ("trustai-input-shield", "input", 4)],
}


async def evidence_pack(session: AsyncSession, principal: Principal, agent_id: uuid.UUID) -> dict[str, Any]:
    """Complete governance evidence for one agent."""
    agent = await get_agent(session, principal, agent_id)
    pids = await agent_svc.policy_ids(session, agent.id)
    policies = (await session.execute(select(Policy).where(Policy.id.in_(pids)))).scalars().all() if pids else []
    history = (await session.execute(select(AgentStatusChange).where(AgentStatusChange.agent_id == agent.id)
                                     .order_by(AgentStatusChange.created_at))).scalars().all()
    assessment = await risk_svc.latest_for_agent(session, agent.id)
    evals = (await session.execute(select(Evaluation).where(Evaluation.agent_id == agent.id)
                                   .order_by(Evaluation.created_at.desc()).limit(20))).scalars().all()
    gr_total, gr_failed = (await session.execute(
        select(func.count(), func.sum(case((GuardrailEvaluation.passed.is_(False), 1), else_=0)))
        .where(GuardrailEvaluation.agent_id == agent.id))).one()
    by_source = dict((await session.execute(
        select(GuardrailEvaluation.source, func.count()).where(GuardrailEvaluation.agent_id == agent.id)
        .group_by(GuardrailEvaluation.source))).all())
    latest = (await session.execute(select(GuardrailEvaluation).where(GuardrailEvaluation.agent_id == agent.id)
                                    .order_by(GuardrailEvaluation.created_at.desc()).limit(20))).scalars().all()
    violations = (await session.execute(select(func.count()).select_from(GovernanceEvent).where(
        GovernanceEvent.agent_id == agent.id, GovernanceEvent.event_type == "policy.violation"))).scalar_one()
    deployment = await gateway_svc.active_deployment(session, agent.id)
    latest_completed = next((e for e in evals if e.status == EvaluationStatus.COMPLETED), None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent": {"id": str(agent.id), "external_id": agent.external_id, "name": agent.name, "version": agent.version,
                  "owner": agent.owner, "built_by": agent.built_by, "model": agent.model, "tools": agent.tools},
        "agent_status": agent.lifecycle_status.value,
        "risk_tier": agent.risk_tier,
        "trust_score": agent.trust_score,
        "trust_score_evaluation_id": str(latest_completed.id) if latest_completed else None,
        "policies": [{"id": str(p.id), "key": p.key, "name": p.name} for p in policies],
        "lifecycle_history": [{"from": h.from_status, "to": h.to_status, "reason": h.reason, "actor": h.actor,
                               "at": h.created_at.isoformat()} for h in history],
        "risk_assessment": None if assessment is None else {
            "assessment_id": str(assessment.id), "status": assessment.status.value, "tier": assessment.risk_tier,
            "score": assessment.risk_score, "decision": assessment.decision.value if assessment.decision else None,
            "conditions": assessment.conditions, "decided_by": assessment.decided_by,
            "required_controls": assessment.required_controls,
            "assumptions": (assessment.evidence or {}).get("assumptions", [])},
        "evaluations": [{"evaluation_id": str(e.id), "evaluation_type": e.eval_type, "status": e.status.value,
                         "trust_score": e.trust_score, "block_rate_pct": e.block_rate_pct, "prompts": e.prompts_total,
                         "created_at": e.created_at.isoformat()} for e in evals],
        "guardrail_evaluations": {"count": int(gr_total or 0), "failed": int(gr_failed or 0), "by_source": by_source,
                                  "latest": [{"id": str(g.id), "phase": g.phase, "source": g.source,
                                              "passed": g.passed, "failed_checks": g.failed_checks,
                                              "at": g.created_at.isoformat()} for g in latest]},
        "policy_violations": int(violations),
        "gateway": None if deployment is None else {"deployment_id": str(deployment.id), "model": deployment.model,
                                                     "status": deployment.status.value,
                                                     "deployed_at": deployment.created_at.isoformat(),
                                                     "deployed_by": deployment.deployed_by},
        "portal_url": portal_url(f"governance/agents/{agent.id}"),
    }


async def overview(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    """Platform-level governance KPIs for the dashboard."""
    visible = principal.visible_projects()

    def scoped(stmt: Any, model: Any) -> Any:
        return stmt.where(model.project_id.in_(visible)) if visible is not None else stmt

    by_status = dict((await session.execute(scoped(
        select(GovernedAgent.lifecycle_status, func.count()).group_by(GovernedAgent.lifecycle_status), GovernedAgent))).all())
    by_tier = dict((await session.execute(scoped(
        select(GovernedAgent.risk_tier, func.count()).group_by(GovernedAgent.risk_tier), GovernedAgent))).all())
    avg_trust = (await session.execute(scoped(select(func.avg(GovernedAgent.trust_score)), GovernedAgent))).scalar_one()
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    checks_24h = (await session.execute(scoped(select(func.count()).select_from(GuardrailEvaluation)
                                               .where(GuardrailEvaluation.created_at >= since), GuardrailEvaluation))).scalar_one()
    violations_24h = (await session.execute(scoped(select(func.count()).select_from(GovernanceEvent).where(
        GovernanceEvent.event_type == "policy.violation", GovernanceEvent.created_at >= since), GovernanceEvent))).scalar_one()
    pending = (await session.execute(scoped(select(func.count()).select_from(RiskAssessment).where(
        RiskAssessment.status == "classified", RiskAssessment.risk_tier >= 3), RiskAssessment))).scalar_one()
    running = (await session.execute(scoped(select(func.count()).select_from(Evaluation).where(
        Evaluation.status.in_(["queued", "running"])), Evaluation))).scalar_one()
    deployed = (await session.execute(scoped(select(func.count()).select_from(GatewayDeployment).where(
        GatewayDeployment.status == DeploymentStatus.ACTIVE), GatewayDeployment))).scalar_one()
    return {"agents_total": sum(by_status.values()),
            "agents_by_status": {(k.value if hasattr(k, "value") else str(k)): v for k, v in by_status.items()},
            "agents_by_tier": {str(k) if k is not None else "unassessed": v for k, v in by_tier.items()},
            "average_trust_score": round(float(avg_trust), 1) if avg_trust is not None else None,
            "guardrail_checks_24h": int(checks_24h), "policy_violations_24h": int(violations_24h),
            "decisions_pending": int(pending), "evaluations_running": int(running),
            "gateway_deployments_active": int(deployed)}


async def optimize(session: AsyncSession, principal: Principal, agent_id: uuid.UUID, name: str | None,
                   evaluation_id: uuid.UUID | None, create_policy: bool) -> dict[str, Any]:
    """Turn the latest red-team gaps into ranked policy recommendations (+ an optional composed project policy)."""
    agent = await get_agent(session, principal, agent_id)
    evaluation = (await eval_svc.get_evaluation(session, principal, evaluation_id) if evaluation_id
                  else await eval_svc.latest_completed(session, agent.id))
    summary = evaluation.summary if evaluation else {}
    gaps = [c for c, s in (summary.get("by_category") or {}).items() if s.get("block_rate_pct", 100) < 100]
    ranked = await enforcement.recommend(session, principal, agent.id, [], agent.risk_tier)
    hinted = {k for g in gaps for k in CATEGORY_POLICY_HINTS.get(g, [])}
    recs: list[dict[str, Any]] = []
    for r in ranked:
        p = r["policy"]
        reasons = list(r["reasons"])
        score = r["score"]
        if p.key in hinted:
            closes = sorted(g for g in gaps if p.key in CATEGORY_POLICY_HINTS.get(g, []))
            reasons.insert(0, "closes red-team gaps: " + ", ".join(closes))
            score += 40
        recs.append({"id": str(p.id), "key": p.key, "name": p.name, "score": score, "reasons": reasons,
                     "attached": r["attached"]})
    recs.sort(key=lambda x: -x["score"])
    composed = None
    if create_policy and gaps:
        rules: dict[tuple[str, str], int] = {}
        for gap in gaps:
            for gkey, phase, sev in CATEGORY_GUARDRAIL_HINTS.get(gap, []):
                g = await system_guardrail(session, gkey)
                if g is not None:
                    rules[(str(g.id), phase)] = max(sev, rules.get((str(g.id), phase), 0))
        if rules:
            key = "optimized-" + agent.slug[:80] + "-" + uuid.uuid4().hex[:6]
            policy = Policy(project_id=agent.project_id, key=key, name=name or f"{agent.name} - optimized",
                            description=f"Composed by TrustAI optimisation from evaluation "
                                        f"{evaluation.id if evaluation else '-'} gaps: {', '.join(sorted(gaps))}",
                            rules=[{"guardrail_id": gid, "phase": ph, "severity": sev} for (gid, ph), sev in rules.items()],
                            fail_on_severity_level=3, tags=["optimized", *sorted(gaps)])
            session.add(policy)
            await session.flush()
            composed = {"id": str(policy.id), "key": policy.key, "name": policy.name, "rules": policy.rules,
                        "attached": False, "note": "review and attach it in the TrustAI portal"}
            await emit(session, project_id=agent.project_id, event_type="policy.composed", resource_type="policy",
                       resource_id=policy.id, agent_id=agent.id, actor=principal.subject, payload={"gaps": gaps})
    return {"agent_id": str(agent.id), "evaluation_id": str(evaluation.id) if evaluation else None,
            "trust_score": summary.get("trust_score"), "block_rate_pct": summary.get("block_rate_pct"),
            "gaps": [{"category": g, **(summary.get("by_category") or {}).get(g, {})} for g in gaps],
            "per_guardrail": summary.get("per_guardrail", []), "recommended_policies": recs[:5],
            "composed_policy": composed,
            "report": {"summary": (f"{len(gaps)} red-team categories leaked; {len([r for r in recs[:5] if not r['attached']])} "
                                   "recommended policies are not attached yet") if evaluation else
                       "no completed red-team evaluation yet - run one first"}}


async def list_guardrails_for(session: AsyncSession, principal: Principal) -> list[Guardrail]:
    """System guardrails plus those of visible projects."""
    stmt = select(Guardrail)
    visible = principal.visible_projects()
    if visible is not None:
        stmt = stmt.where((Guardrail.project_id.is_(None)) | (Guardrail.project_id.in_(visible)))
    return list((await session.execute(stmt.order_by(Guardrail.is_system.desc(), Guardrail.name))).scalars())
