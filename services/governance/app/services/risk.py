"""
services/governance/app/services/risk.py
TrustAI risk assessment.

Template `trustai_build_v1` follows EU AI Act risk categories (prohibited practices, Annex III high-risk domains,
transparency) and NIST AI RMF (Map/Measure/Manage): impact, autonomy, actions, data, audience, oversight.

Tiering is deterministic and explainable:
  * every answer adds weighted points (mitigations subtract), each listed in `tier_reasons`;
  * hard floors override the score (prohibited practice -> Tier 4; Annex III domain making decisions -> Tier 3+;
    autonomous financial write actions -> Tier 3+);
  * Tier 1 minimal (<20), Tier 2 limited (<40), Tier 3 high (<75), Tier 4 critical (>=75 or a hard floor).
Facts from the AI Factory pre-fill answers; anything not provided gets the conservative default and is listed under
`evidence.assumptions` so a reviewer can correct it before deciding.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssessmentStatus, Decision, GovernedAgent, LifecycleStatus, RiskAssessment
from app.security import Principal
from app.services import agents as agent_svc
from app.services.common import emit, get_agent

TEMPLATE_ID = "trustai_build_v1"

HIGH_RISK_DOMAINS = {"finance", "healthcare", "hr_employment", "education", "critical_infrastructure",
                     "law_enforcement", "legal", "public_services"}

# Each question: id, section, label, type, options [(value, label, points)] or bool points, required, default
QUESTIONS: list[dict[str, Any]] = [
    {"id": "purpose.domain", "section": "Purpose & impact", "type": "select", "required": True,
     "label": "Business domain the agent operates in",
     "help": "EU AI Act Annex III lists employment, credit, education, essential services, law enforcement and "
             "critical infrastructure as high-risk areas.",
     "options": [("general", "General productivity", 0), ("customer_service", "Customer service", 5),
                 ("operations", "Operations / back office", 5), ("finance", "Finance, credit or payments", 15),
                 ("healthcare", "Healthcare", 18), ("hr_employment", "HR / employment decisions", 18),
                 ("education", "Education / assessment", 15), ("legal", "Legal", 12),
                 ("public_services", "Access to essential public services", 18),
                 ("critical_infrastructure", "Critical infrastructure", 20),
                 ("law_enforcement", "Law enforcement / justice", 22)], "default": "operations"},
    {"id": "purpose.decision_impact", "section": "Purpose & impact", "type": "select", "required": True,
     "label": "What the agent's output does",
     "options": [("informational", "Informs a person only", 0), ("recommends", "Recommends; a person decides", 5),
                 ("decides_with_review", "Decides; a person reviews before it takes effect", 10),
                 ("decides_autonomously", "Decides and acts without review", 20)], "default": "decides_with_review"},
    {"id": "purpose.prohibited_practice", "section": "Purpose & impact", "type": "bool", "required": True,
     "label": "Could it perform a prohibited practice (social scoring, manipulative techniques, emotion recognition "
              "at work, untargeted biometric scraping)?", "points_true": 100, "default": False},
    {"id": "autonomy.level", "section": "Autonomy", "type": "select", "required": True,
     "label": "Autonomy level",
     "options": [("assistive", "Assistive - a person performs every action", 0),
                 ("supervised", "Supervised - actions need approval", 6),
                 ("conditional", "Conditional - acts alone below thresholds", 12),
                 ("autonomous", "Autonomous - acts without approval", 20)], "default": "conditional"},
    {"id": "actions.write_actions", "section": "Actions", "type": "bool", "required": True,
     "label": "Can it change data or systems (write actions)?", "points_true": 8, "default": True},
    {"id": "actions.financial", "section": "Actions", "type": "bool", "required": True,
     "label": "Can it move money, approve payments or commit spend?", "points_true": 12, "default": False},
    {"id": "actions.irreversible", "section": "Actions", "type": "bool", "required": False,
     "label": "Can an action be irreversible (delete, send externally, pay)?", "points_true": 6, "default": True},
    {"id": "actions.approval_gates", "section": "Actions", "type": "bool", "required": True,
     "label": "Do risky actions require human approval (approval queue, thresholds)?", "points_true": -8,
     "default": False},
    {"id": "data.personal_data", "section": "Data", "type": "bool", "required": True,
     "label": "Does it process personal data?", "points_true": 8, "default": True},
    {"id": "data.special_category", "section": "Data", "type": "bool", "required": False,
     "label": "Special-category data (health, biometrics, religion, union membership, children)?",
     "points_true": 12, "default": False},
    {"id": "data.regulatory_scope", "section": "Data", "type": "multi", "required": False,
     "label": "Regulations in scope", "points_each": 3, "max_points": 12,
     "options": [("gdpr", "GDPR", 0), ("dpdp", "India DPDP", 0), ("hipaa", "HIPAA", 0), ("pci_dss", "PCI DSS", 0),
                 ("sox", "SOX", 0), ("eu_ai_act", "EU AI Act", 0), ("iso_42001", "ISO/IEC 42001", 0),
                 ("other", "Other", 0)], "default": []},
    {"id": "users.audience", "section": "People affected", "type": "select", "required": True,
     "label": "Who uses or is affected by it",
     "options": [("internal_employees", "Internal employees", 0), ("business_customers", "Business customers", 5),
                 ("general_public", "General public", 10), ("vulnerable_groups", "Vulnerable groups (minors, patients)", 18)],
     "default": "business_customers"},
    {"id": "users.scale", "section": "People affected", "type": "select", "required": False,
     "label": "People affected per month",
     "options": [("lt_100", "Fewer than 100", 0), ("lt_10k", "100 - 10,000", 4), ("gte_10k", "More than 10,000", 8)],
     "default": "lt_10k"},
    {"id": "integration.external_systems", "section": "Integration", "type": "number", "required": False,
     "label": "Number of connected business systems", "points_per": 2, "max_points": 10, "default": 1},
    {"id": "integration.internet_access", "section": "Integration", "type": "bool", "required": False,
     "label": "Can it read from or post to the open internet?", "points_true": 5, "default": False},
    {"id": "oversight.human_in_loop", "section": "Oversight", "type": "bool", "required": True,
     "label": "Is a named person accountable and able to intervene?", "points_true": -5, "default": False},
    {"id": "oversight.audit_logging", "section": "Oversight", "type": "bool", "required": True,
     "label": "Are prompts, tool calls and decisions audit-logged?", "points_true": -4, "default": False},
    {"id": "oversight.kill_switch", "section": "Oversight", "type": "bool", "required": False,
     "label": "Can it be suspended immediately (kill switch / gateway revoke)?", "points_true": -3, "default": False},
    {"id": "transparency.disclosed", "section": "Oversight", "type": "bool", "required": False,
     "label": "Are users told they are interacting with AI?", "points_true": -2, "default": False},
]
_Q = {q["id"]: q for q in QUESTIONS}

TIER_LABELS = {1: "Tier 1 - Minimal", 2: "Tier 2 - Limited", 3: "Tier 3 - High", 4: "Tier 4 - Critical"}
CONTROLS = {
    1: ["TrustAI Baseline policy attached", "Runtime guard enabled"],
    2: ["TrustAI Baseline policy attached", "Runtime guard enabled", "PII Strict policy when personal data is processed",
        "Red-team trust score >= 90 before release", "Annual review"],
    3: ["High-Risk Agent policy attached", "Human approval on every write action",
        "Red-team trust score >= 95 before release", "Human risk decision before gateway deployment",
        "Audit logging retained >= 1 year", "Quarterly review"],
    4: ["High-Risk Agent policy attached", "Human approval on every write action",
        "Red-team trust score >= 98 before release", "Executive sign-off and DPIA before deployment",
        "Continuous monitoring with violation alerts", "Monthly review"],
}


def template() -> dict[str, Any]:
    """Public template definition (pages -> questions -> options)."""
    sections: dict[str, list[dict[str, Any]]] = {}
    for q in QUESTIONS:
        item = {k: v for k, v in q.items() if k not in ("options",)}
        if "options" in q:
            item["options"] = [{"value": v, "label": label, "points": p} for v, label, p in q["options"]]
        sections.setdefault(q["section"], []).append(item)
    return {"id": TEMPLATE_ID, "name": "TrustAI Build Risk Assessment", "version": 1,
            "frameworks": ["EU AI Act", "NIST AI RMF 1.0", "ISO/IEC 42001"],
            "sections": [{"title": t, "questions": qs} for t, qs in sections.items()],
            "tiers": [{"tier": t, "label": TIER_LABELS[t], "required_controls": CONTROLS[t]} for t in (1, 2, 3, 4)]}


_FIN_RE = re.compile(r"pay|payment|transfer|refund|disburse|invoice_approve|approve_invoice|wire|remit|credit|charge", re.I)
_IRREVERSIBLE_RE = re.compile(r"delete|remove|send|email|post|publish|pay|transfer|wire|terminate|cancel", re.I)
_DOMAIN_MAP = [
    (re.compile(r"bank|financ|insur|credit|lend|payment|account|treasury|invoice|procure", re.I), "finance"),
    (re.compile(r"health|medic|pharma|clinic|hospital|patient", re.I), "healthcare"),
    (re.compile(r"\bhr\b|human resource|recruit|hiring|employ|payroll", re.I), "hr_employment"),
    (re.compile(r"educat|school|universit|exam", re.I), "education"),
    (re.compile(r"legal|law firm|contract|compliance", re.I), "legal"),
    (re.compile(r"energy|utilit|power|grid|water|telecom|transport", re.I), "critical_infrastructure"),
    (re.compile(r"government|public sector|citizen", re.I), "public_services"),
    (re.compile(r"support|customer service|contact cent|helpdesk", re.I), "customer_service"),
    (re.compile(r"manufactur|supply|logistic|operation|warehouse|retail", re.I), "operations"),
]
_REG_MAP = {"gdpr": "gdpr", "dpdp": "dpdp", "hipaa": "hipaa", "pci": "pci_dss", "sox": "sox", "ai act": "eu_ai_act",
            "42001": "iso_42001"}


def answers_from_facts(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Map build facts (AI Factory risk request) to answers. Returns (answers, provenance per answer)."""
    answers: dict[str, Any] = {}
    prov: dict[str, str] = {}

    def put(qid: str, value: Any, why: str) -> None:
        answers[qid] = value
        prov[qid] = why

    domain_src = " ".join(str(facts.get(k) or "") for k in ("industry", "system_type"))
    for pattern, domain in _DOMAIN_MAP:
        if domain_src.strip() and pattern.search(domain_src):
            put("purpose.domain", domain, f"industry/system_type = {domain_src.strip()!r}")
            break
    autonomy = str(facts.get("autonomy_level") or "").lower()
    if autonomy:
        level = ("autonomous" if re.search(r"auto|full|l4|l5|high", autonomy) else
                 "conditional" if re.search(r"cond|semi|l3|medium|partial", autonomy) else
                 "supervised" if re.search(r"super|approv|l2|human", autonomy) else
                 "assistive" if re.search(r"assist|advis|l1|low|copilot", autonomy) else None)
        if level:
            put("autonomy.level", level, f"autonomy_level = {autonomy!r}")
            impact = {"autonomous": "decides_autonomously", "conditional": "decides_with_review",
                      "supervised": "decides_with_review", "assistive": "recommends"}[level]
            put("purpose.decision_impact", impact, f"derived from autonomy_level = {autonomy!r}")
    writes = [str(a) for a in facts.get("write_actions") or []]
    if "write_actions" in facts:
        put("actions.write_actions", bool(writes), f"write_actions = {writes}")
        put("actions.financial", any(_FIN_RE.search(a) for a in writes), "write action names")
        put("actions.irreversible", any(_IRREVERSIBLE_RE.search(a) for a in writes), "write action names")
    if "approval_required_actions" in facts:
        # gated = always needs approval, or needs it above a threshold; denied tools can never run at all
        gated = [str(a) for a in (facts.get("approval_required_actions") or []) + (facts.get("threshold_gated_actions") or [])]
        denied = {str(a) for a in facts.get("denied_actions") or []}
        ungated = [a for a in writes if a not in gated and a not in denied]
        put("actions.approval_gates", bool(gated) and not ungated,
            f"approval / threshold-gated actions = {gated}; denied = {sorted(denied)}; ungated writes = {ungated}")
    if "handles_pii" in facts:
        put("data.personal_data", bool(facts.get("handles_pii")), "handles_pii")
    regs = facts.get("regulatory_scope")
    if regs:
        mapped = sorted({v for r in regs for k, v in _REG_MAP.items() if k in str(r).lower()} or {"other"})
        put("data.regulatory_scope", mapped, f"regulatory_scope = {regs}")
    if "integrations" in facts:
        put("integration.external_systems", len(facts.get("integrations") or []), "integrations")
    if facts.get("audit_logging") is not None:
        put("oversight.audit_logging", bool(facts["audit_logging"]), "audit_logging")
    if "ai factory" in str(facts.get("built_by") or "").lower() or facts.get("governed_runtime"):
        put("oversight.audit_logging", True, "AI Factory governed runtime writes an audit log")
        put("oversight.kill_switch", True, "TrustAI gateway revoke / registry suspend")
    return answers, prov


def validate(answers: dict[str, Any]) -> dict[str, Any]:
    """Check types/options; list missing required answers."""
    errors: list[dict[str, str]] = []
    missing = [q["id"] for q in QUESTIONS if q.get("required") and q["id"] not in answers]
    for qid, value in answers.items():
        q = _Q.get(qid)
        if q is None:
            errors.append({"question": qid, "error": "unknown question"})
            continue
        if q["type"] == "select" and value not in {o[0] for o in q["options"]}:
            errors.append({"question": qid, "error": f"invalid option {value!r}"})
        elif q["type"] == "bool" and not isinstance(value, bool):
            errors.append({"question": qid, "error": "must be true or false"})
        elif q["type"] == "multi" and (not isinstance(value, list) or
                                       any(v not in {o[0] for o in q["options"]} for v in value)):
            errors.append({"question": qid, "error": "invalid options"})
        elif q["type"] == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
            errors.append({"question": qid, "error": "must be a non-negative number"})
    return {"valid": not errors and not missing, "errors": errors, "missing": missing}


def classify(answers: dict[str, Any]) -> dict[str, Any]:
    """Score answers -> {tier, score, reasons, required_controls}. Missing answers use the question default."""
    reasons: list[dict[str, Any]] = []
    score = 0.0
    eff = {q["id"]: answers.get(q["id"], q.get("default")) for q in QUESTIONS}
    for q in QUESTIONS:
        v = eff[q["id"]]
        pts = 0.0
        if q["type"] == "select":
            pts = next((p for o, _, p in q["options"] if o == v), 0)
        elif q["type"] == "bool" and v:
            pts = q.get("points_true", 0)
        elif q["type"] == "multi":
            pts = min(q.get("max_points", 99), q.get("points_each", 0) * len(v or []))
        elif q["type"] == "number":
            pts = min(q.get("max_points", 99), q.get("points_per", 0) * float(v or 0))
        if pts:
            score += pts
            reasons.append({"question": q["id"], "answer": v, "points": pts, "label": q["label"]})
    tier = 1 if score < 20 else 2 if score < 40 else 3 if score < 75 else 4
    floors: list[str] = []
    if eff["purpose.prohibited_practice"]:
        tier, floors = 4, floors + ["prohibited AI practice (EU AI Act Art. 5) -> Tier 4"]
    if eff["purpose.domain"] in HIGH_RISK_DOMAINS and eff["purpose.decision_impact"] in ("decides_with_review", "decides_autonomously"):
        if tier < 3:
            floors.append(f"Annex III domain '{eff['purpose.domain']}' with decision-making -> at least Tier 3")
        tier = max(tier, 3)
    if eff["actions.financial"] and eff["autonomy.level"] in ("conditional", "autonomous") and not eff["actions.approval_gates"]:
        if tier < 3:
            floors.append("autonomous financial actions without approval gates -> at least Tier 3")
        tier = max(tier, 3)
    if eff["users.audience"] == "vulnerable_groups" and eff["data.special_category"]:
        if tier < 3:
            floors.append("special-category data about vulnerable groups -> at least Tier 3")
        tier = max(tier, 3)
    controls = list(CONTROLS[tier])
    if tier == 2 and not eff["data.personal_data"]:
        controls = [c for c in controls if not c.startswith("PII Strict")]
    return {"tier": tier, "label": TIER_LABELS[tier], "score": round(score, 1), "reasons": reasons,
            "floors": floors, "required_controls": controls}


# --------------------------------------------------------------------------------------------- persistence


async def get_assessment(session: AsyncSession, principal: Principal, assessment_id: uuid.UUID) -> RiskAssessment:
    """Load an assessment the caller may see."""
    row = await session.get(RiskAssessment, assessment_id)
    if row is None or (principal.visible_projects() is not None and row.project_id not in principal.visible_projects()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "assessment not found")
    return row


async def create(session: AsyncSession, principal: Principal, agent_id: uuid.UUID | None, external_id: str | None,
                 answers: dict[str, Any], facts: dict[str, Any] | None, template_id: str = TEMPLATE_ID) -> RiskAssessment:
    """New draft assessment, pre-filled from facts; explicit answers win over facts."""
    if template_id != TEMPLATE_ID:
        raise HTTPException(422, f"unknown template {template_id!r}")
    agent = await get_agent(session, principal, agent_id, external_id)
    prefilled, prov = answers_from_facts(facts or {})
    merged = {**prefilled, **answers}
    evidence = {"facts": facts or {}, "provenance": {**prov, **{k: "answered by user" for k in answers}}}
    row = RiskAssessment(project_id=agent.project_id, agent_id=agent.id, template_id=template_id, answers=merged,
                         evidence=evidence, created_by=principal.subject, status=AssessmentStatus.DRAFT)
    session.add(row)
    await session.flush()
    await emit(session, project_id=agent.project_id, event_type="assessment.created", resource_type="assessment",
               resource_id=row.id, agent_id=agent.id, actor=principal.subject)
    return row


async def save_answers(session: AsyncSession, principal: Principal, row: RiskAssessment, answers: dict[str, Any],
                       evidence: dict[str, Any]) -> RiskAssessment:
    """Merge answers; a decided assessment is frozen (start a new one instead)."""
    if row.status == AssessmentStatus.DECIDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "assessment already decided; create a new assessment")
    row.answers = {**(row.answers or {}), **answers}
    prov = dict((row.evidence or {}).get("provenance") or {})
    prov.update({k: f"answered by {principal.subject}" for k in answers})
    row.evidence = {**(row.evidence or {}), **evidence, "provenance": prov}
    row.validation = validate(row.answers)
    if row.status != AssessmentStatus.DRAFT:
        row.status = AssessmentStatus.DRAFT  # answers changed -> must be re-submitted
    return row


async def submit(session: AsyncSession, principal: Principal, row: RiskAssessment, *, fill_defaults: bool) -> RiskAssessment:
    """Validate and classify. With fill_defaults, unanswered questions take conservative defaults (recorded)."""
    if row.status == AssessmentStatus.DECIDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "assessment already decided")
    answers = dict(row.answers or {})
    assumptions = []
    if fill_defaults:
        for q in QUESTIONS:
            if q["id"] not in answers:
                answers[q["id"]] = q.get("default")
                assumptions.append({"question": q["id"], "assumed": q.get("default"), "label": q["label"]})
    check = validate(answers)
    row.validation = check
    if not check["valid"]:
        raise HTTPException(422, {"message": "assessment incomplete", **check})
    row.answers = answers
    row.evidence = {**(row.evidence or {}), "assumptions": assumptions}
    row.submitted_at = datetime.now(timezone.utc)
    row.status = AssessmentStatus.SUBMITTED
    return await run_classification(session, principal, row)


async def run_classification(session: AsyncSession, principal: Principal, row: RiskAssessment) -> RiskAssessment:
    """Classify a submitted assessment and propagate the tier to the agent."""
    if row.status not in (AssessmentStatus.SUBMITTED, AssessmentStatus.CLASSIFIED):
        raise HTTPException(status.HTTP_409_CONFLICT, "submit the assessment before classifying")
    result = classify(row.answers or {})
    row.risk_tier, row.risk_score = result["tier"], result["score"]
    row.tier_reasons = result["reasons"] + [{"floor": f} for f in result["floors"]]
    row.required_controls = result["required_controls"]
    row.status = AssessmentStatus.CLASSIFIED
    agent = await session.get(GovernedAgent, row.agent_id)
    assert agent is not None
    agent.risk_tier = result["tier"]
    await agent_svc.advance(session, agent, LifecycleStatus.ASSESSED, principal.subject,
                            f"risk assessment {row.id}: {result['label']}")
    await emit(session, project_id=row.project_id, event_type="assessment.classified", resource_type="assessment",
               resource_id=row.id, agent_id=row.agent_id, actor=principal.subject,
               severity="high" if result["tier"] >= 3 else "info",
               payload={"risk_tier": result["tier"], "score": result["score"], "floors": result["floors"]})
    return row


async def decide(session: AsyncSession, principal: Principal, row: RiskAssessment, decision: Decision,
                 conditions: list[str], note: str | None) -> RiskAssessment:
    """Record the human decision (only people, only on classified assessments)."""
    if row.status != AssessmentStatus.CLASSIFIED:
        raise HTTPException(status.HTTP_409_CONFLICT, "only a classified assessment can be decided")
    if decision == Decision.APPROVED_WITH_CONDITIONS and not conditions:
        raise HTTPException(422, "conditions are required for approved_with_conditions")
    row.decision, row.conditions, row.decision_note = decision, conditions, note
    row.decided_by, row.decided_at = principal.subject, datetime.now(timezone.utc)
    row.status = AssessmentStatus.DECIDED
    await emit(session, project_id=row.project_id, event_type=f"assessment.{decision.value}", resource_type="assessment",
               resource_id=row.id, agent_id=row.agent_id, actor=principal.subject,
               severity="medium" if decision == Decision.REJECTED else "info",
               payload={"decision": decision.value, "conditions": conditions, "risk_tier": row.risk_tier})
    return row


async def latest_for_agent(session: AsyncSession, agent_id: uuid.UUID) -> RiskAssessment | None:
    """Most recent assessment of an agent."""
    return (await session.execute(select(RiskAssessment).where(RiskAssessment.agent_id == agent_id)
                                  .order_by(RiskAssessment.created_at.desc()).limit(1))).scalar_one_or_none()
