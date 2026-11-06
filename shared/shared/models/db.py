"""
shared/models/db.py
SQLAlchemy ORM models for the TrustAI metadata store (PostgreSQL).
Analytics time-series data lives in analytics_models.py (TimescaleDB).
"""
import enum
import uuid
from datetime import datetime, timezone

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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"      # Full platform access
    CLIENT_ADMIN = "client_admin"    # Manages one client + its projects
    PROJECT_VIEWER = "project_viewer" # Read-only for specific projects
    DEVELOPER = "developer"          # Can generate/use SDK keys


class ClientType(str, enum.Enum):
    EXTERNAL = "external"   # Paying customer
    INTERNAL = "internal"   # Internal team / department


class ContentCaptureMode(str, enum.Enum):
    FULL = "full"           # Capture prompts + responses
    MASKED = "masked"       # Redact PII patterns
    DISABLED = "disabled"   # No content capture


class ConnectorProvider(str, enum.Enum):
    # Azure
    AZURE_OPENAI       = "azure_openai"        # Azure OpenAI Service metrics
    AZURE_APP_INSIGHTS = "azure_app_insights"  # Application Insights / Log Analytics
    AZURE_FOUNDRY      = "azure_foundry"       # Azure AI Foundry (AI Studio)
    # AWS
    AWS_BEDROCK        = "aws_bedrock"         # Amazon Bedrock
    # GCP (placeholder)
    GCP_VERTEX         = "gcp_vertex"          # Google Vertex AI
    # Other
    DATABRICKS_MLFLOW  = "databricks_mlflow"   # Databricks + MLflow
    OPENAI             = "openai"              # Direct OpenAI API
    ANTHROPIC          = "anthropic"           # Anthropic Claude API
    CUSTOM_OTEL        = "custom_otel"         # Custom OpenTelemetry endpoint


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ApiKeyStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


# ─────────────────────────────────────────────
# Core Entities
# ─────────────────────────────────────────────

class Client(Base):
    """
    Top-level organisational unit. Can be an external customer or an
    internal team. All projects, users, and billing roll up to a client.
    """
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    client_type: Mapped[ClientType] = mapped_column(Enum(ClientType), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    users: Mapped[list["UserClientRole"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    alert_rules: Mapped[list["AlertRule"]] = relationship(back_populates="client")

    __table_args__ = (Index("ix_clients_slug", "slug"),)


class Project(Base):
    """
    A distinct AI application or workload within a client.
    E.g., 'invoice-extractor', 'support-bot', 'data-pipeline'.
    """
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    environment_default: Mapped[str] = mapped_column(String(50), default="production")
    # Content capture can be overridden per environment via project settings
    content_capture_mode: Mapped[ContentCaptureMode] = mapped_column(
        Enum(ContentCaptureMode), default=ContentCaptureMode.MASKED
    )
    # Per-environment overrides stored as JSON: {"dev": "full", "prod": "masked"}
    content_capture_overrides: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    client: Mapped["Client"] = relationship(back_populates="projects")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    agents: Mapped[list["Agent"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("client_id", "slug", name="uq_project_client_slug"),
        Index("ix_projects_client_id", "client_id"),
    )

    def get_content_capture_mode(self, environment: str) -> ContentCaptureMode:
        """Resolve effective capture mode for a given environment."""
        override = self.content_capture_overrides.get(environment)
        if override:
            return ContentCaptureMode(override)
        return self.content_capture_mode


class Agent(Base):
    """
    A named AI agent or component within a project.
    E.g., 'document_processor', 'classifier_agent', 'rag_pipeline'.
    Agents can be nested (parent_id for sub-agents).
    """
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    agent_type: Mapped[str | None] = mapped_column(String(100))  # e.g., "llm", "tool", "orchestrator"
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped["Project"] = relationship(back_populates="agents")
    children: Mapped[list["Agent"]] = relationship("Agent", back_populates="parent")
    parent: Mapped["Agent | None"] = relationship("Agent", back_populates="children", remote_side=[id])

    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_agent_project_slug"),
        Index("ix_agents_project_id", "project_id"),
    )


class ApiKey(Base):
    """
    Project-level SDK API keys. The raw key is shown once on creation;
    only the SHA-256 hash is stored.
    """
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g., "tai_live_xxxx"
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[ApiKeyStatus] = mapped_column(Enum(ApiKeyStatus), default=ApiKeyStatus.ACTIVE)
    scopes: Mapped[list] = mapped_column(JSONB, default=list)  # ["ingest", "read"]
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="api_keys")

    __table_args__ = (Index("ix_api_keys_key_hash", "key_hash"),)


# ─────────────────────────────────────────────
# Users & RBAC
# ─────────────────────────────────────────────

class User(Base):
    """
    Platform user. Primary identity comes from Azure AD (oid claim).
    Local record created on first SSO login.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    azure_oid: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # Azure AD object ID
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    client_roles: Mapped[list["UserClientRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    project_roles: Mapped[list["UserProjectRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserClientRole(Base):
    """Maps a user to a client with a role."""
    __tablename__ = "user_client_roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="client_roles")
    client: Mapped["Client"] = relationship(back_populates="users")

    __table_args__ = (
        UniqueConstraint("user_id", "client_id", name="uq_user_client_role"),
    )


class UserProjectRole(Base):
    """Maps a user to a specific project with a role."""
    __tablename__ = "user_project_roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="project_roles")

    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_user_project_role"),
    )


# ─────────────────────────────────────────────
# Model Pricing
# ─────────────────────────────────────────────

class ModelPricing(Base):
    """
    Per-token pricing for LLM models. Provider-neutral schema.
    Prices are in USD per 1M tokens.
    """
    __tablename__ = "model_pricing"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)   # "azure_openai", "openai", "anthropic"
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)  # "gpt-4o", "claude-3-5-sonnet"
    model_version: Mapped[str | None] = mapped_column(String(100))
    input_price_per_1m: Mapped[float] = mapped_column(Float, nullable=False)
    output_price_per_1m: Mapped[float] = mapped_column(Float, nullable=False)
    cached_input_price_per_1m: Mapped[float | None] = mapped_column(Float)
    reasoning_price_per_1m: Mapped[float | None] = mapped_column(Float)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint("provider", "model_name", "model_version", "effective_from", name="uq_model_pricing"),
        Index("ix_model_pricing_lookup", "provider", "model_name", "is_active"),
    )


# ─────────────────────────────────────────────
# Connectors
# ─────────────────────────────────────────────

class Connector(Base):
    """
    Provider-neutral connector config. Stores which cloud/tool a client's
    telemetry is pulled from.
    Secrets are AES-256-GCM encrypted before storage (see shared.crypto).
    """
    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    # Optional project-level scoping (None = client-wide connector)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[ConnectorProvider] = mapped_column(Enum(ConnectorProvider), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Non-secret config (workspace IDs, resource names, regions, subscription IDs, etc.)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # AES-256-GCM encrypted JSON blob containing all secrets
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    # Legacy Key Vault references (kept for migration compatibility)
    secret_refs: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Sync schedule
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=10)
    # Last sync state
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(50))  # "ok" | "error" | "running"
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    last_sync_records: Mapped[int | None] = mapped_column(Integer)  # rows written in last sync
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_connectors_client_id", "client_id"),
        Index("ix_connectors_project_id", "project_id"),
    )


# ─────────────────────────────────────────────
# Alerts
# ─────────────────────────────────────────────

class AlertRule(Base):
    """Threshold-based alert rule (cost spike, error rate, latency, etc.)."""
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)  # "cost_usd", "error_rate", "latency_p99"
    operator: Mapped[str] = mapped_column(String(20), nullable=False)  # "gt", "lt", "gte"
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, default=60)
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity), default=AlertSeverity.WARNING)
    notification_channels: Mapped[list] = mapped_column(JSONB, default=list)  # ["email", "teams"]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    client: Mapped["Client | None"] = relationship(back_populates="alert_rules")
    fired_alerts: Mapped[list["FiredAlert"]] = relationship(back_populates="rule")


class FiredAlert(Base):
    """An instance of an alert rule being triggered."""
    __tablename__ = "fired_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"))
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.ACTIVE)
    triggered_value: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    rule: Mapped["AlertRule"] = relationship(back_populates="fired_alerts")


# ─────────────────────────────────────────────
# Audit Log
# ─────────────────────────────────────────────

class AuditLog(Base):
    """Immutable audit trail of all admin actions."""
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)   # "create_project", "revoke_api_key"
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100))
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (
        Index("ix_audit_logs_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )
