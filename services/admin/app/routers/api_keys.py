"""
services/admin/app/routers/api_keys.py
API key lifecycle management — generate, list, revoke.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user, require_project_access
from shared.db.session import metadata_session_dep
from shared.models.db import ApiKey, ApiKeyStatus, AuditLog, Project, UserRole
from shared.models.schemas import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse

router = APIRouter()

_KEY_PREFIX = "tai_live_"


def _generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_prefix, key_hash)."""
    random_part = secrets.token_urlsafe(32)
    raw_key = f"{_KEY_PREFIX}{random_part}"
    key_prefix = raw_key[:16]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_prefix, key_hash


@router.get(
    "/projects/{project_id}/api-keys",
    response_model=list[ApiKeyResponse],
    summary="List API keys for a project",
)
async def list_api_keys(
    project_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_project_access(min_role=UserRole.DEVELOPER)),
):
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.project_id == project_id)
        .order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/projects/{project_id}/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new API key",
)
async def create_api_key(
    body: ApiKeyCreate,
    project_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_project_access(min_role=UserRole.DEVELOPER)),
):
    # Verify project exists
    proj = await session.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    raw_key, prefix, key_hash = _generate_api_key()

    api_key = ApiKey(
        project_id=project_id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        expires_at=body.expires_at,
        created_by=current_user.id,
    )
    session.add(api_key)

    # Audit log
    session.add(AuditLog(
        user_id=current_user.id,
        action="create_api_key",
        resource_type="api_key",
        resource_id=str(api_key.id),
        new_value={"name": body.name, "project_id": str(project_id)},
    ))

    await session.flush()

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=prefix,
        raw_key=raw_key,  # Only shown once
        scopes=api_key.scopes,
        created_at=api_key.created_at,
    )


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    api_key = await session.get(ApiKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.status = ApiKeyStatus.REVOKED

    session.add(AuditLog(
        user_id=current_user.id,
        action="revoke_api_key",
        resource_type="api_key",
        resource_id=str(key_id),
    ))
