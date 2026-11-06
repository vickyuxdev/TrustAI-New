"""
services/governance/app/schemas.py
Pydantic v2 request/response models for the governance API. Inputs are validated strictly (lengths, enums,
URL schemes); outputs mirror the ORM rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import AssessmentStatus, Decision, DeploymentStatus, EvaluationStatus, LifecycleStatus

T = TypeVar("T")
Phase = str  # input | output | tool_call:<name> | tool_result:<name> | any


class Page(BaseModel, Generic[T]):
    """Paginated list envelope."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ORMModel(BaseModel):
    """Base for models built from ORM rows."""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------------------------- agents


class ToolSpecIn(BaseModel):
    """A tool the agent can call, with the factory's policy for it."""

    name: str = Field(min_length=1, max_length=200)
    side_effect: str | None = Field(default=None, max_length=30)  # read | write | none
    policy: Literal["allow", "deny", "require_approval"] = "allow"
    approval_threshold: dict[str, Any] | None = None
    description: str | None = Field(default=None, max_length=2000)


class RuntimeConfig(BaseModel):
    """How TrustAI reaches the agent for connection tests and red-team runs (HTTP JSON endpoint)."""

    base_url: HttpUrl
    request_template: dict[str, Any] = Field(default_factory=lambda: {"message": "{{prompt}}"})
    response_key: str = Field(default="response", max_length=200)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)


class AgentOnboard(BaseModel):
    """Onboarding request (idempotent upsert by project + external_id)."""

    external_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:\-]+$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    version: str = Field(default="1.0.0", max_length=50)
    client: str | None = Field(default=None, max_length=255)
    built_by: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=200)
    autonomy_level: str | None = Field(default=None, max_length=50)
    tools: list[ToolSpecIn] = Field(default_factory=list, max_length=500)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)
    endpoint: HttpUrl | None = None  # shortcut: chat endpoint taking {"message"} and returning {"response"}
    runtime: RuntimeConfig | None = None
    project_id: uuid.UUID | None = None
    attach_baseline_policy: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    """Editable agent fields."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    version: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = None
    runtime: RuntimeConfig | None = None
    tools: list[ToolSpecIn] | None = None


class AgentOut(ORMModel):
    """Agent registry entry."""

    id: uuid.UUID
    project_id: uuid.UUID
    external_id: str
    name: str
    slug: str
    description: str | None
    version: str
    owner: str | None
    built_by: str | None
    model: str | None
    autonomy_level: str | None
    tools: list[dict[str, Any]]
    capabilities: list[str]
    tags: list[str]
    runtime_config: dict[str, Any]
    lifecycle_status: LifecycleStatus
    risk_tier: int | None
    trust_score: float | None
    default_guardrail_id: uuid.UUID | None
    policy_ids: list[uuid.UUID] = Field(default_factory=list)
    portal_url: str | None = None
    created_at: datetime
    updated_at: datetime


class StatusChange(BaseModel):
    """Lifecycle transition request."""

    status: LifecycleStatus
    reason: str | None = Field(default=None, max_length=2000)


class StatusHistoryOut(ORMModel):
    """One lifecycle change."""

    from_status: str | None
    to_status: str
    reason: str | None
    actor: str
    created_at: datetime


class ConnectionTest(BaseModel):
    """Prompt sent to the agent's runtime endpoint."""

    prompt: str = Field(default="Hello - this is a TrustAI connection test. Reply briefly.", max_length=4000)


class AttachPolicies(BaseModel):
    """Replace the agent's attached policies."""

    policy_ids: list[uuid.UUID] = Field(max_length=50)


class McpServerIn(BaseModel):
    """One MCP server definition (factory .mcp.json shape)."""

    type: str = Field(default="http", max_length=30)
    url: str | None = Field(default=None, max_length=1000)
    command: str | None = Field(default=None, max_length=1000)


class McpOnboard(BaseModel):
    """Register an agent's external MCP servers."""

    agent_id: uuid.UUID | None = None
    external_id: str | None = Field(default=None, max_length=200)
    servers: dict[str, McpServerIn] = Field(min_length=1, max_length=100)

    @field_validator("servers")
    @classmethod
    def _names(cls, v: dict[str, McpServerIn]) -> dict[str, McpServerIn]:
        """Server names are identifiers."""
        for name in v:
            if not 1 <= len(name) <= 200:
                raise ValueError("server name length must be 1-200")
        return v


class McpServerOut(ORMModel):
    """Registered MCP server."""

    id: uuid.UUID
    agent_id: uuid.UUID | None
    name: str
    transport: str
    url: str | None
    created_at: datetime


# --------------------------------------------------------------------------------------------- guardrails & policies


class EvaluatorSpec(BaseModel):
    """One check inside a guardrail (extra keys are evaluator parameters, e.g. categories, terms)."""

    model_config = ConfigDict(extra="allow")
    type: str = Field(min_length=1, max_length=60)
    threshold: float = Field(default=50, ge=0, le=100)


class GuardrailIn(BaseModel):
    """Create a guardrail."""

    key: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    evaluators: list[EvaluatorSpec] = Field(min_length=1, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=30)
    project_id: uuid.UUID | None = None


class GuardrailUpdate(BaseModel):
    """Edit a guardrail (bumps its version)."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    evaluators: list[EvaluatorSpec] | None = Field(default=None, min_length=1, max_length=20)
    tags: list[str] | None = None


class GuardrailOut(ORMModel):
    """Guardrail definition."""

    id: uuid.UUID
    project_id: uuid.UUID | None
    key: str
    name: str
    description: str | None
    evaluators: list[dict[str, Any]]
    tags: list[str]
    is_system: bool
    version: int
    created_at: datetime
    updated_at: datetime


class GuardrailEvaluateIn(BaseModel):
    """Evaluate text against one guardrail. Either `text` or `input` (query/response) is required."""

    text: str | None = Field(default=None, max_length=100_000)
    input: dict[str, str] | None = None  # {"query": ..., "response": ...} (factory runtime shape)
    phase: Phase = Field(default="input", max_length=120)
    target_id: str | None = Field(default=None, max_length=200)  # agent id or external id
    correlation_id: str | None = Field(default=None, max_length=200)
    tool_name: str | None = Field(default=None, max_length=200)
    policy_text: str | None = Field(default=None, max_length=8000)

    def resolved_text(self) -> str:
        """The text to score: explicit text, else the response, else the query."""
        if self.text is not None:
            return self.text
        data = self.input or {}
        return data.get("response") or data.get("query") or ""


class GuardrailEvaluateOut(BaseModel):
    """Guardrail decision."""

    passed: bool
    guardrail_eval_id: uuid.UUID
    failed_checks: list[str]
    scores: dict[str, float]
    results: dict[str, Any]
    latency_ms: int


class GuardrailEvaluationOut(ORMModel):
    """Stored guardrail decision (no text, only its hash)."""

    id: uuid.UUID
    guardrail_id: uuid.UUID | None
    policy_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    source: str
    phase: str
    correlation_id: str | None
    passed: bool
    failed_checks: list[str]
    scores: dict[str, Any]
    latency_ms: int
    created_at: datetime


class PolicyRule(BaseModel):
    """Guardrail applied at a phase with a severity (1 low ... 5 critical)."""

    guardrail_id: uuid.UUID
    phase: str = Field(default="input", pattern=r"^(input|output|tool|tool_call|tool_result|any)$")
    severity: int = Field(default=3, ge=1, le=5)


class PolicyIn(BaseModel):
    """Create a policy."""

    key: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    rules: list[PolicyRule] = Field(min_length=1, max_length=30)
    fail_on_severity_level: int = Field(default=1, ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=30)
    min_risk_tier: int | None = Field(default=None, ge=1, le=4)
    project_id: uuid.UUID | None = None


class PolicyUpdate(BaseModel):
    """Edit a policy."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    rules: list[PolicyRule] | None = Field(default=None, min_length=1, max_length=30)
    fail_on_severity_level: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None


class PolicyOut(ORMModel):
    """Policy definition."""

    id: uuid.UUID
    project_id: uuid.UUID | None
    key: str
    name: str
    description: str | None
    rules: list[dict[str, Any]]
    fail_on_severity_level: int
    tags: list[str]
    min_risk_tier: int | None
    is_system: bool
    created_at: datetime
    updated_at: datetime


class RecommendIn(BaseModel):
    """Recommend policies for an agent (or for free-form tags / tier)."""

    agent_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    risk_tier: int | None = Field(default=None, ge=1, le=4)


class Recommendation(BaseModel):
    """One recommended policy with why."""

    policy: PolicyOut
    score: float
    reasons: list[str]
    attached: bool


class EnforceIn(BaseModel):
    """Enforce an agent's attached policies on one message (runtime guard, gateway)."""

    agent_id: uuid.UUID | None = None
    external_id: str | None = Field(default=None, max_length=200)
    phase: Phase = Field(default="input", max_length=120)
    text: str = Field(max_length=200_000)
    query: str | None = Field(default=None, max_length=100_000)
    tool_name: str | None = Field(default=None, max_length=200)
    correlation_id: str | None = Field(default=None, max_length=200)
    source: Literal["runtime", "gateway", "api", "evaluation"] = "api"


class EnforceOut(BaseModel):
    """Policy decision for one phase."""

    allowed: bool
    phase: str
    blocked_by: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    guardrail_eval_ids: list[uuid.UUID]
    latency_ms: int


class MetricIn(BaseModel):
    """Stand-alone metric scoring."""

    text: str = Field(max_length=100_000)
    params: dict[str, Any] = Field(default_factory=dict)
    query: str | None = Field(default=None, max_length=100_000)
    policy: str | None = Field(default=None, max_length=8000)
    categories: list[str] | None = None
    blocklist: list[str] | None = None


# --------------------------------------------------------------------------------------------- risk


class AssessmentCreate(BaseModel):
    """Start an assessment; `facts` pre-fills answers from the agent's build facts."""

    agent_id: uuid.UUID
    template_id: str = Field(default="trustai_build_v1", max_length=80)
    answers: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] | None = None


class AnswersIn(BaseModel):
    """Save answers (merged into existing ones)."""

    answers: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)


class DecisionIn(BaseModel):
    """Human decision on a classified assessment."""

    decision: Decision
    conditions: list[str] = Field(default_factory=list, max_length=30)
    note: str | None = Field(default=None, max_length=4000)


class RiskAssessIn(BaseModel):
    """One-shot assessment for automation: create, pre-fill from facts, submit, classify."""

    agent_id: uuid.UUID | None = None
    external_id: str | None = Field(default=None, max_length=200)
    facts: dict[str, Any] = Field(default_factory=dict)
    answers: dict[str, Any] = Field(default_factory=dict)
    template_id: str = Field(default="trustai_build_v1", max_length=80)


class AssessmentOut(ORMModel):
    """Risk assessment."""

    id: uuid.UUID
    project_id: uuid.UUID
    agent_id: uuid.UUID
    template_id: str
    status: AssessmentStatus
    answers: dict[str, Any]
    evidence: dict[str, Any]
    validation: dict[str, Any]
    risk_tier: int | None
    risk_score: float | None
    tier_reasons: list[dict[str, Any]]
    required_controls: list[str]
    decision: Decision | None
    conditions: list[str]
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_by: str
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    portal_url: str | None = None


# --------------------------------------------------------------------------------------------- evaluations


class CustomPrompt(BaseModel):
    """A labelled prompt (factory dataset-generation shape)."""

    model_config = ConfigDict(extra="allow")
    prompt: str = Field(min_length=1, max_length=20_000)
    harmful: bool = True
    id: str | None = Field(default=None, max_length=120)
    vector: str | None = Field(default=None, max_length=120)
    persona: str | None = Field(default=None, max_length=200)
    strategy: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)


class PromptSource(BaseModel):
    """Where the evaluation prompts come from."""

    source: Literal["custom", "generate", "reuse", "mixed"] = "generate"
    custom_prompts: list[CustomPrompt] = Field(default_factory=list, max_length=2000)
    num_generate: int = Field(default=40, ge=0, le=500)
    benign_ratio: float = Field(default=0.3, ge=0, le=0.9)
    categories: list[str] = Field(default_factory=list, max_length=20)
    from_evaluation_id: uuid.UUID | None = None
    seed: int | None = None


class EvaluationCreate(BaseModel):
    """Start a red-team / classification evaluation."""

    agent_id: uuid.UUID | None = None
    external_id: str | None = Field(default=None, max_length=200)
    eval_type: Literal["red_team", "classification"] = "red_team"
    prompts: PromptSource = Field(default_factory=PromptSource)
    policy_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)  # grade per guardrail; default attached
    endpoint: HttpUrl | None = None  # override the agent's runtime endpoint
    trust_threshold: float = Field(default=95.0, ge=0, le=100)


class EvaluationOut(ORMModel):
    """Evaluation summary (iterations only when requested)."""

    id: uuid.UUID
    project_id: uuid.UUID
    agent_id: uuid.UUID
    eval_type: str
    status: EvaluationStatus
    config: dict[str, Any]
    summary: dict[str, Any]
    trust_score: float | None
    block_rate_pct: float | None
    prompts_total: int
    progress: int
    error: str | None
    created_by: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    iterations: list[dict[str, Any]] | None = None
    portal_url: str | None = None


# --------------------------------------------------------------------------------------------- gateway


class GatewayDeployIn(BaseModel):
    """Deploy an agent behind the TrustAI AI Gateway."""

    model: str | None = Field(default=None, max_length=200)
    allowed_models: list[str] = Field(default_factory=list, max_length=20)
    allow_conditional: bool = False


class GatewayDeployOut(BaseModel):
    """Deployment result; `api_key` is returned exactly once."""

    deployment_id: uuid.UUID
    agent_id: uuid.UUID
    gateway_url: str
    model: str
    allowed_models: list[str]
    api_key: str | None = None
    key_prefix: str
    status: DeploymentStatus
    gate: dict[str, Any]
    created_at: datetime


class ObservabilityIn(BaseModel):
    """Wire a governed agent up for tracing (client defaults to the agent's owner)."""

    client_name: str | None = Field(default=None, min_length=2, max_length=255)
    environment: str = Field(default="production", min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")


class ObservabilityOut(BaseModel):
    """Where the agent sends traces; `ingest_key` is returned exactly once."""

    agent_id: uuid.UUID
    client_id: uuid.UUID
    project_id: uuid.UUID
    ingest_url: str
    ingest_key: str
    key_prefix: str
    environment: str
    traces_url: str
    rotated: bool


class GatewayAuthorizeIn(BaseModel):
    """Gateway asks: which agent owns this key?"""

    api_key: str = Field(min_length=10, max_length=300)


class GatewayAuthorizeOut(BaseModel):
    """Key resolution for the gateway."""

    deployment_id: uuid.UUID
    agent_id: uuid.UUID
    project_id: uuid.UUID
    agent_name: str
    model: str
    allowed_models: list[str]


# --------------------------------------------------------------------------------------------- events / evidence


class EventOut(ORMModel):
    """Governance event."""

    id: uuid.UUID
    project_id: uuid.UUID
    event_type: str
    severity: str
    resource_type: str
    resource_id: str
    agent_id: uuid.UUID | None
    actor: str
    payload: dict[str, Any]
    created_at: datetime


class OptimizeIn(BaseModel):
    """Policy optimisation from the latest red-team results."""

    name: str | None = Field(default=None, max_length=255)
    evaluation_id: uuid.UUID | None = None
    create_policy: bool = True
