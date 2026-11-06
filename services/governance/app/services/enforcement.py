"""
services/governance/app/services/enforcement.py
Guardrail evaluation, policy enforcement and policy recommendation. Every decision is stored (hash of the text,
never the text) so evidence and dashboards can show it; blocked decisions also raise `policy.violation` events.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.base import EvalContext
from app.engine.registry import enforce as engine_enforce
from app.engine.registry import run_guardrail
from app.models import AgentPolicy, GovernedAgent, Guardrail, GuardrailEvaluation, Policy
from app.schemas import EnforceIn, EnforceOut, GuardrailEvaluateIn, GuardrailEvaluateOut
from app.security import Principal
from app.services.common import emit, get_agent

SEVERITY_NAMES = {1: "low", 2: "low", 3: "medium", 4: "high", 5: "critical"}


def sha256(text: str) -> str:
    """Hash stored instead of the evaluated text."""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def normalise_phase(phase: str) -> str:
    """Map factory runtime phase names onto engine phases (user_input -> input, final/answer -> output)."""
    p = (phase or "input").strip().lower()
    if p in ("user_input", "prompt", "request"):
        return "input"
    if p in ("final", "answer", "response", "assistant"):
        return "output"
    return p


async def get_guardrail(session: AsyncSession, principal: Principal, guardrail_id: uuid.UUID) -> Guardrail:
    """A guardrail the caller may use (system or in a visible project)."""
    row = await session.get(Guardrail, guardrail_id)
    if row is None or (row.project_id is not None and principal.visible_projects() is not None
                       and row.project_id not in principal.visible_projects()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "guardrail not found")
    return row


async def _resolve_target(session: AsyncSession, principal: Principal, target: str | None) -> GovernedAgent | None:
    """target_id may be an agent UUID or an external id; unknown targets are simply not linked."""
    if not target:
        return None
    try:
        return await get_agent(session, principal, agent_id=uuid.UUID(target))
    except (ValueError, HTTPException):
        try:
            return await get_agent(session, principal, external_id=target)
        except HTTPException:
            return None


async def evaluate_guardrail(session: AsyncSession, principal: Principal, guardrail_id: uuid.UUID,
                             body: GuardrailEvaluateIn, source: str = "api") -> GuardrailEvaluateOut:
    """Run one guardrail on a text and store the decision."""
    guardrail = await get_guardrail(session, principal, guardrail_id)
    agent = await _resolve_target(session, principal, body.target_id)
    text = body.resolved_text()
    phase = normalise_phase(body.phase)
    ctx = EvalContext(phase=phase, query=(body.input or {}).get("query"), policy_text=body.policy_text,
                      agent_tools=(agent.tools if agent else []), tool_name=body.tool_name)
    outcome = await run_guardrail(guardrail.evaluators, text, ctx)
    project_id = agent.project_id if agent else (guardrail.project_id or principal.bound_project)
    row = GuardrailEvaluation(project_id=project_id or uuid.UUID(int=0), guardrail_id=guardrail.id,
                              agent_id=agent.id if agent else None, source=source, phase=phase,
                              correlation_id=body.correlation_id, passed=outcome.passed,
                              failed_checks=outcome.failed_checks, scores=outcome.scores, text_sha256=sha256(text),
                              latency_ms=outcome.latency_ms)
    session.add(row)
    await session.flush()
    return GuardrailEvaluateOut(passed=outcome.passed, guardrail_eval_id=row.id, failed_checks=outcome.failed_checks,
                                scores=outcome.scores, results=outcome.results(), latency_ms=outcome.latency_ms)


async def agent_policy_bundle(session: AsyncSession, agent: GovernedAgent,
                              only: list[uuid.UUID] | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Attached (or explicitly listed) policies of an agent plus every guardrail they reference, as plain dicts."""
    if only:
        policies = (await session.execute(select(Policy).where(Policy.id.in_(only)))).scalars().all()
    else:
        policies = (await session.execute(select(Policy).join(AgentPolicy, AgentPolicy.policy_id == Policy.id)
                                          .where(AgentPolicy.agent_id == agent.id))).scalars().all()
    gids = {uuid.UUID(str(r["guardrail_id"])) for p in policies for r in p.rules or []}
    guardrails = (await session.execute(select(Guardrail).where(Guardrail.id.in_(gids)))).scalars().all() if gids else []
    return ([{"id": str(p.id), "name": p.name, "rules": p.rules, "fail_on_severity_level": p.fail_on_severity_level}
             for p in policies],
            {str(g.id): {"name": g.name, "evaluators": g.evaluators} for g in guardrails})


async def enforce(session: AsyncSession, principal: Principal, body: EnforceIn) -> EnforceOut:
    """Enforce an agent's attached policies on one message; store every guardrail decision; raise violations."""
    agent = await get_agent(session, principal, body.agent_id, body.external_id)
    phase = normalise_phase(body.phase)
    tool_name = body.tool_name or (phase.split(":", 1)[1] if ":" in phase else None)
    policies, guardrails = await agent_policy_bundle(session, agent)
    ctx = EvalContext(phase=phase, query=body.query, agent_tools=agent.tools or [], tool_name=tool_name)
    decision = await engine_enforce(policies, guardrails, phase, body.text, ctx)
    text_hash = sha256(body.text)
    ids: list[uuid.UUID] = []
    for ev in decision.evaluations:
        row = GuardrailEvaluation(project_id=agent.project_id, guardrail_id=uuid.UUID(ev["guardrail_id"]),
                                  agent_id=agent.id, source=body.source, phase=phase,
                                  correlation_id=body.correlation_id, passed=ev["passed"],
                                  failed_checks=ev["failed_checks"], scores=ev["scores"], text_sha256=text_hash,
                                  latency_ms=ev["latency_ms"])
        session.add(row)
        await session.flush()
        ids.append(row.id)
    for block in decision.blocked_by:
        await emit(session, project_id=agent.project_id, event_type="policy.violation",
                   severity=SEVERITY_NAMES.get(int(block["severity"]), "medium"), resource_type="policy",
                   resource_id=block["policy_id"], agent_id=agent.id, actor=principal.subject,
                   payload={"target_id": str(agent.id), "phase": phase, "source": body.source,
                            "policy_name": block["policy_name"], "guardrail_name": block["guardrail_name"],
                            "failed_guardrails": [block["guardrail_id"]], "failed_checks": block["failed_checks"],
                            "fail_severity_level": block["severity"], "correlation_id": body.correlation_id})
    return EnforceOut(allowed=decision.allowed, phase=phase, blocked_by=decision.blocked_by,
                      evaluations=decision.evaluations, guardrail_eval_ids=ids, latency_ms=decision.latency_ms)


def _agent_signals(agent: GovernedAgent) -> set[str]:
    """Tags describing an agent's risk surface (used to match policy tags)."""
    signals = {t.lower() for t in agent.tags or []} | {c.lower() for c in agent.capabilities or []}
    tools = agent.tools or []
    if any(t.get("side_effect") == "write" for t in tools):
        signals |= {"write-actions", "tools"}
    if any(t.get("policy") == "require_approval" for t in tools):
        signals.add("approval")
    if any(any(w in str(t.get("name", "")).lower() for w in ("pay", "invoice", "refund", "transfer", "payment"))
           for t in tools):
        signals.add("finance")
    if (agent.autonomy_level or "").lower().startswith(("auto", "high", "l3", "l4")):
        signals.add("autonomous")
    if (agent.extra_metadata or {}).get("handles_pii"):
        signals.add("pii")
    return signals


async def recommend(session: AsyncSession, principal: Principal, agent_id: uuid.UUID | None, tags: list[str],
                    risk_tier: int | None) -> list[dict[str, Any]]:
    """Rank system + project policies for an agent by tag overlap and risk tier."""
    agent = await get_agent(session, principal, agent_id) if agent_id else None
    signals = {t.lower() for t in tags} | (_agent_signals(agent) if agent else set())
    tier = risk_tier or (agent.risk_tier if agent else None)
    stmt = select(Policy)
    if agent is not None:
        stmt = stmt.where(or_(Policy.project_id.is_(None), Policy.project_id == agent.project_id))
    elif principal.visible_projects() is not None:
        stmt = stmt.where(or_(Policy.project_id.is_(None), Policy.project_id.in_(principal.visible_projects())))
    attached = set(await _attached(session, agent.id)) if agent else set()
    ranked: list[dict[str, Any]] = []
    for p in (await session.execute(stmt)).scalars():
        if "monitor" in (p.tags or []):
            continue
        reasons: list[str] = []
        overlap = signals & {t.lower() for t in p.tags or []}
        score = 10.0 * len(overlap)
        if overlap:
            reasons.append("matches " + ", ".join(sorted(overlap)))
        if tier is not None and p.min_risk_tier is not None:
            if tier >= p.min_risk_tier:
                score += 15 + 5 * p.min_risk_tier
                reasons.append(f"required from risk tier {p.min_risk_tier} (agent is tier {tier})")
            else:
                score -= 20
        if "baseline" in (p.tags or []):
            score += 5
            reasons.append("TrustAI baseline")
        if score > 0:
            ranked.append({"policy": p, "score": score, "reasons": reasons, "attached": p.id in attached})
    return sorted(ranked, key=lambda r: (-r["score"], r["policy"].name))


async def _attached(session: AsyncSession, agent_id: uuid.UUID) -> list[uuid.UUID]:
    """Attached policy ids."""
    return list((await session.execute(select(AgentPolicy.policy_id).where(AgentPolicy.agent_id == agent_id))).scalars())
