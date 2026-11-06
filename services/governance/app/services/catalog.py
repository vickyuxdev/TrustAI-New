"""
services/governance/app/services/catalog.py
The TrustAI system catalog: built-in guardrails and policies seeded (idempotently, by key) at startup.
Policies are mapped to the OWASP Top 10 for LLM Applications (2025) and EU AI Act risk practice.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Guardrail, Policy

logger = logging.getLogger("governance.catalog")

SYSTEM_GUARDRAILS: list[dict[str, Any]] = [
    {"key": "trustai-input-shield", "name": "Input Shield",
     "description": "Blocks prompt injection, jailbreak / role-play, system-prompt extraction, approval bypass and "
                    "toxic input. OWASP LLM01, LLM07.",
     "evaluators": [{"type": "prompt_manipulation", "threshold": 50}, {"type": "toxicity", "threshold": 50}],
     "tags": ["injection", "jailbreak", "toxicity", "owasp-llm01", "owasp-llm07"]},
    {"key": "trustai-strict-input-shield", "name": "Strict Input Shield",
     "description": "Lower thresholds for high-risk agents: blocks borderline manipulation and toxicity.",
     "evaluators": [{"type": "prompt_manipulation", "threshold": 35}, {"type": "toxicity", "threshold": 35}],
     "tags": ["injection", "jailbreak", "toxicity", "high-risk"]},
    {"key": "trustai-pii-guard", "name": "PII Guard",
     "description": "Detects personal data (email, phone, payment cards, IBAN, national ids). OWASP LLM02.",
     "evaluators": [{"type": "pii", "threshold": 50}], "tags": ["pii", "privacy", "owasp-llm02"]},
    {"key": "trustai-output-safety", "name": "Output Safety",
     "description": "Stops toxic answers and leaked credentials in agent output. OWASP LLM02, LLM05.",
     "evaluators": [{"type": "toxicity", "threshold": 50}, {"type": "secrets", "threshold": 50}],
     "tags": ["toxicity", "secrets", "owasp-llm02", "owasp-llm05"]},
    {"key": "trustai-tool-guard", "name": "Tool Guard",
     "description": "Tool calls checked against registered tool policies and tool results screened for indirect "
                    "prompt injection. OWASP LLM06 (excessive agency).",
     "evaluators": [{"type": "tool_permission", "threshold": 50}, {"type": "prompt_manipulation", "threshold": 50}],
     "tags": ["tools", "agency", "indirect-injection", "owasp-llm06"]},
]

# rules reference guardrails by key; resolved to ids when seeding
SYSTEM_POLICIES: list[dict[str, Any]] = [
    {"key": "trustai-baseline", "name": "TrustAI Baseline",
     "description": "Default policy for every onboarded agent: input shield, output safety and tool guard.",
     "fail_on_severity_level": 3, "min_risk_tier": 1, "tags": ["baseline", "default"],
     "rules": [("trustai-input-shield", "input", 4), ("trustai-output-safety", "output", 4),
               ("trustai-tool-guard", "tool", 4)]},
    {"key": "trustai-owasp-llm-top10", "name": "OWASP LLM Top 10 Aligned",
     "description": "Covers LLM01 prompt injection, LLM02 sensitive information disclosure, LLM05 improper output "
                    "handling, LLM06 excessive agency and LLM07 system-prompt leakage.",
     "fail_on_severity_level": 3, "min_risk_tier": 2, "tags": ["owasp", "security", "compliance"],
     "rules": [("trustai-input-shield", "input", 4), ("trustai-pii-guard", "output", 3),
               ("trustai-output-safety", "output", 4), ("trustai-tool-guard", "tool", 4)]},
    {"key": "trustai-pii-strict", "name": "PII Strict",
     "description": "For agents handling personal data: blocks PII in answers and flags it in input. GDPR / DPDP.",
     "fail_on_severity_level": 3, "min_risk_tier": 2, "tags": ["pii", "privacy", "gdpr", "dpdp", "hipaa", "finance"],
     "rules": [("trustai-pii-guard", "output", 4), ("trustai-pii-guard", "input", 2)]},
    {"key": "trustai-high-risk", "name": "High-Risk Agent",
     "description": "Tier 3-4 agents (autonomous write actions, regulated domains): strict thresholds everywhere.",
     "fail_on_severity_level": 2, "min_risk_tier": 3, "tags": ["high-risk", "autonomous", "write-actions", "finance"],
     "rules": [("trustai-strict-input-shield", "input", 4), ("trustai-output-safety", "output", 4),
               ("trustai-pii-guard", "output", 3), ("trustai-tool-guard", "tool", 5)]},
    {"key": "trustai-monitor-only", "name": "Monitor Only",
     "description": "Evaluates every message and records violations without blocking (shadow mode).",
     "fail_on_severity_level": 5, "min_risk_tier": None, "tags": ["monitor", "shadow"],
     "rules": [("trustai-input-shield", "input", 3), ("trustai-output-safety", "output", 3),
               ("trustai-pii-guard", "output", 3)]},
]

BASELINE_POLICY_KEY = "trustai-baseline"
DEFAULT_GUARDRAIL_KEY = "trustai-input-shield"


async def seed_catalog(session: AsyncSession) -> None:
    """Insert (or refresh) the system guardrails and policies. Safe to run on every start."""
    by_key: dict[str, Guardrail] = {
        g.key: g for g in (await session.execute(
            select(Guardrail).where(Guardrail.project_id.is_(None), Guardrail.is_system.is_(True)))).scalars()}
    for spec in SYSTEM_GUARDRAILS:
        row = by_key.get(spec["key"])
        if row is None:
            row = Guardrail(project_id=None, is_system=True, **spec)
            session.add(row)
            by_key[spec["key"]] = row
        elif row.evaluators != spec["evaluators"] or row.description != spec["description"]:
            row.evaluators, row.description, row.tags = spec["evaluators"], spec["description"], spec["tags"]
            row.version += 1
    await session.flush()
    existing = {p.key: p for p in (await session.execute(
        select(Policy).where(Policy.project_id.is_(None), Policy.is_system.is_(True)))).scalars()}
    for spec in SYSTEM_POLICIES:
        rules = [{"guardrail_id": str(by_key[g].id), "phase": phase, "severity": sev} for g, phase, sev in spec["rules"]]
        fields = {k: v for k, v in spec.items() if k != "rules"}
        row = existing.get(spec["key"])
        if row is None:
            session.add(Policy(project_id=None, is_system=True, rules=rules, **fields))
        else:
            row.rules = rules
            for k, v in fields.items():
                setattr(row, k, v)
    await session.flush()
    logger.info("system catalog seeded: %d guardrails, %d policies", len(SYSTEM_GUARDRAILS), len(SYSTEM_POLICIES))


async def system_policy(session: AsyncSession, key: str) -> Policy | None:
    """A system policy by key."""
    return (await session.execute(
        select(Policy).where(Policy.project_id.is_(None), Policy.key == key))).scalar_one_or_none()


async def system_guardrail(session: AsyncSession, key: str) -> Guardrail | None:
    """A system guardrail by key."""
    return (await session.execute(
        select(Guardrail).where(Guardrail.project_id.is_(None), Guardrail.key == key))).scalar_one_or_none()
