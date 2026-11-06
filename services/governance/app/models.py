"""
services/governance/app/models.py
ORM models for the governance plane. Every table is project-scoped (project_id = TrustAI project) except
system-wide catalog rows (guardrails/policies with project_id NULL and is_system TRUE).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GovBase, JSONType


def utcnow() -> datetime:
    """Timezone-aware UTC now (all governance timestamps are UTC)."""
    return datetime.now(timezone.utc)


class LifecycleStatus(str, enum.Enum):
    """Registry lifecycle of a governed agent. `approved`, `deployed`, `retired` need a human or a gate."""
    REGISTERED = "registered"
    ONBOARDED = "onboarded"
    ASSESSED = "assessed"
    EVALUATED = "evaluated"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class AssessmentStatus(str, enum.Enum):
    """Risk-assessment workflow states."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CLASSIFIED = "classified"
    DECIDED = "decided"


class Decision(str, enum.Enum):
    """Human decision on a classified assessment."""
    APPROVED = "approved"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    REJECTED = "rejected"


class EvaluationStatus(str, enum.Enum):
    """Red-team / classification evaluation job states."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentStatus(str, enum.Enum):
    """Gateway deployment key state."""
    ACTIVE = "active"
    REVOKED = "revoked"


class GovernedAgent(GovBase):
    """An AI agent registered for governance (one row per project + external_id, e.g. a factory workload)."""
    __tablename__ = "gov_agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    owner: Mapped[str | None] = mapped_column(String(255))  # client / business owner
    built_by: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(200))
    autonomy_level: Mapped[str | None] = mapped_column(String(50))
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSONType, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    runtime_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    lifecycle_status: Mapped[LifecycleStatus] = mapped_column(
        Enum(LifecycleStatus, native_enum=False, length=20), default=LifecycleStatus.REGISTERED)
    risk_tier: Mapped[int | None] = mapped_column(Integer)
    trust_score: Mapped[float | None] = mapped_column(Float)
    default_guardrail_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    policy_links: Mapped[list[AgentPolicy]] = relationship(back_populates="agent", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("project_id", "external_id", name="uq_gov_agent_project_external"),
        Index("ix_gov_agents_project", "project_id"),
    )


class AgentStatusChange(GovBase):
    """Append-only lifecycle history (who moved the agent, when and why)."""
    __tablename__ = "gov_agent_status_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gov_agents.id", ondelete="CASCADE"))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class McpServer(GovBase):
    """An MCP server an agent uses, registered for inventory and tool governance."""
    __tablename__ = "gov_mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gov_agents.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    transport: Mapped[str] = mapped_column(String(30), default="http")
    url: Mapped[str | None] = mapped_column(String(1000))
    command: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "agent_id", "name", name="uq_gov_mcp_project_agent_name"),)


class Guardrail(GovBase):
    """A set of evaluator checks with thresholds. `evaluators` = [{type, threshold, params}]."""
    __tablename__ = "gov_guardrails"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(120), nullable=False)  # stable slug, e.g. "trustai-baseline-input"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    evaluators: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_gov_guardrail_project_key"),)


class Policy(GovBase):
    """A policy binds guardrails to phases with severities. `rules` = [{guardrail_id, phase, severity}]."""
    __tablename__ = "gov_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    fail_on_severity_level: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    min_risk_tier: Mapped[int | None] = mapped_column(Integer)  # recommend for agents at or above this tier
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_gov_policy_project_key"),)


class AgentPolicy(GovBase):
    """Policies attached to an agent (enforced at runtime guard and gateway)."""
    __tablename__ = "gov_agent_policies"

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gov_agents.id", ondelete="CASCADE"), primary_key=True)
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gov_policies.id", ondelete="CASCADE"), primary_key=True)
    attached_by: Mapped[str] = mapped_column(String(255))
    attached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent: Mapped[GovernedAgent] = relationship(back_populates="policy_links")


class GuardrailEvaluation(GovBase):
    """One guardrail/policy decision (runtime guard, gateway, metrics). Text is never stored, only its hash."""
    __tablename__ = "gov_guardrail_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    guardrail_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(30), default="api")  # runtime | gateway | api | evaluation
    phase: Mapped[str] = mapped_column(String(60), default="input")
    correlation_id: Mapped[str | None] = mapped_column(String(200))
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failed_checks: Mapped[list[str]] = mapped_column(JSONType, default=list)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    text_sha256: Mapped[str] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_gov_gr_eval_agent_created", "agent_id", "created_at"),
        Index("ix_gov_gr_eval_guardrail", "guardrail_id"),
    )


class RiskAssessment(GovBase):
    """Risk assessment of an agent against a TrustAI template, with tiering and a human decision."""
    __tablename__ = "gov_assessments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gov_agents.id", ondelete="CASCADE"))
    template_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[AssessmentStatus] = mapped_column(
        Enum(AssessmentStatus, native_enum=False, length=20), default=AssessmentStatus.DRAFT)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    risk_tier: Mapped[int | None] = mapped_column(Integer)
    risk_score: Mapped[float | None] = mapped_column(Float)
    tier_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    required_controls: Mapped[list[str]] = mapped_column(JSONType, default=list)
    decision: Mapped[Decision | None] = mapped_column(Enum(Decision, native_enum=False, length=30))
    conditions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_gov_assessments_agent", "agent_id"),)


class Evaluation(GovBase):
    """A red-team (or classification) evaluation run against an agent's runtime endpoint."""
    __tablename__ = "gov_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gov_agents.id", ondelete="CASCADE"))
    eval_type: Mapped[str] = mapped_column(String(30), default="red_team")
    status: Mapped[EvaluationStatus] = mapped_column(
        Enum(EvaluationStatus, native_enum=False, length=20), default=EvaluationStatus.QUEUED)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    prompts: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    iterations: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    trust_score: Mapped[float | None] = mapped_column(Float)
    block_rate_pct: Mapped[float | None] = mapped_column(Float)
    prompts_total: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_gov_evaluations_agent_created", "agent_id", "created_at"),)


class GatewayDeployment(GovBase):
    """A per-agent AI-gateway key. Only the SHA-256 of the key is stored; the raw key is shown once."""
    __tablename__ = "gov_gateway_deployments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gov_agents.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(200))
    allowed_models: Mapped[list[str]] = mapped_column(JSONType, default=list)
    key_prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[DeploymentStatus] = mapped_column(
        Enum(DeploymentStatus, native_enum=False, length=20), default=DeploymentStatus.ACTIVE)
    gate: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # what allowed the deployment
    deployed_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_gov_gateway_agent", "agent_id"),)


class GovernanceEvent(GovBase):
    """Audit + alert feed: lifecycle changes, decisions, deployments and policy violations."""
    __tablename__ = "gov_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80))  # e.g. agent.onboarded, policy.violation
    severity: Mapped[str] = mapped_column(String(20), default="info")  # info | low | medium | high | critical
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(80))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_gov_events_project_created", "project_id", "created_at"),)
