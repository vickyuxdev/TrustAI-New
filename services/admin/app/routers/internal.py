"""
services/admin/app/routers/internal.py
Service-to-service endpoints (never exposed to browsers or users).

POST /internal/observability/provision is called by the governance service when the AI Factory wires a governed
agent up for tracing: it gets-or-creates the observability client and project and issues a fresh ingest-only API key
(the previous key with the same name is revoked, so re-provisioning rotates the key). Authenticated with the shared
X-Internal-Secret header (TRUSTAI_INTERNAL_API_SECRET), compared in constant time.
"""
import hashlib
import hmac
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.db.session import metadata_session_dep
from shared.models.db import ApiKey, ApiKeyStatus, AuditLog, Client, ClientType, ContentCaptureMode, Project

router = APIRouter()

_KEY_PREFIX = "tai_live_"
_SLUG = r"^[a-z0-9][a-z0-9-]*$"


def require_internal_secret(
    x_internal_secret: Annotated[str | None, Header(alias="X-Internal-Secret")] = None,
) -> None:
    """401 unless the caller presents the shared internal secret."""
    expected = get_settings().internal_api_secret.get_secret_value()
    if not x_internal_secret or not expected or not hmac.compare_digest(x_internal_secret, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal secret")


class ObservabilityProvisionIn(BaseModel):
    """Which client/project the agent's traces belong to."""

    client_slug: str = Field(min_length=2, max_length=100, pattern=_SLUG)
    client_name: str = Field(min_length=2, max_length=255)
    client_type: ClientType = ClientType.INTERNAL
    project_slug: str = Field(min_length=2, max_length=100, pattern=_SLUG)
    project_name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    environment: str = Field(default="production", min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")
    content_capture_mode: ContentCaptureMode = ContentCaptureMode.MASKED
    key_name: str = Field(default="AI Factory agent ingest key", min_length=2, max_length=255)
    governance_agent_id: uuid.UUID | None = None


class ObservabilityProvisionOut(BaseModel):
    """Ids plus the one-time raw ingest key (never stored in clear text)."""

    client_id: uuid.UUID
    project_id: uuid.UUID
    api_key_id: uuid.UUID
    key_prefix: str
    raw_key: str
    scopes: list[str]
    created_client: bool
    created_project: bool
    revoked_keys: int


@router.post(
    "/internal/observability/provision",
    response_model=ObservabilityProvisionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Get-or-create an observability project and issue an ingest key (service-to-service)",
    dependencies=[Depends(require_internal_secret)],
)
async def provision_observability(
    body: ObservabilityProvisionIn,
    session: AsyncSession = Depends(metadata_session_dep),
) -> ObservabilityProvisionOut:
    """Idempotent for client and project; always issues a new key and revokes the previous one of the same name."""
    client = (await session.execute(select(Client).where(Client.slug == body.client_slug))).scalar_one_or_none()
    created_client = client is None
    if client is None:
        client = Client(name=body.client_name, slug=body.client_slug, client_type=body.client_type,
                        description="Provisioned by TrustAI governance for AI Factory agents")
        session.add(client)
        await session.flush()

    project = (await session.execute(
        select(Project).where(Project.client_id == client.id, Project.slug == body.project_slug)
    )).scalar_one_or_none()
    created_project = project is None
    if project is None:
        project = Project(client_id=client.id, name=body.project_name, slug=body.project_slug,
                          description=body.description, environment_default=body.environment,
                          content_capture_mode=body.content_capture_mode,
                          extra_metadata={"governance_agent_id": str(body.governance_agent_id)}
                          if body.governance_agent_id else {})
        session.add(project)
        await session.flush()

    previous = (await session.execute(
        select(ApiKey).where(ApiKey.project_id == project.id, ApiKey.name == body.key_name,
                             ApiKey.status == ApiKeyStatus.ACTIVE)
    )).scalars().all()
    for old in previous:
        old.status = ApiKeyStatus.REVOKED

    raw_key = f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    api_key = ApiKey(id=uuid.uuid4(), project_id=project.id, name=body.key_name, key_prefix=raw_key[:16],
                     key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), status=ApiKeyStatus.ACTIVE,
                     scopes=["ingest"])
    session.add(api_key)
    session.add(AuditLog(
        user_id=None,
        action="provision_observability",
        resource_type="api_key",
        resource_id=str(api_key.id),
        new_value={"client_id": str(client.id), "project_id": str(project.id), "key_prefix": api_key.key_prefix,
                   "revoked_keys": len(previous), "source": "governance"},
    ))
    await session.flush()

    return ObservabilityProvisionOut(
        client_id=client.id, project_id=project.id, api_key_id=api_key.id, key_prefix=api_key.key_prefix,
        raw_key=raw_key, scopes=["ingest"], created_client=created_client, created_project=created_project,
        revoked_keys=len(previous),
    )
