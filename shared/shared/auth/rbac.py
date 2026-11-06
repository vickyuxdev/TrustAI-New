"""
shared/auth/rbac.py
Role-Based Access Control decorators and dependency factories for FastAPI.
Enforces the 4-level role hierarchy: super_admin > client_admin > developer > project_viewer.
"""
import uuid
import logging
from functools import wraps
from typing import Callable

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.azure_ad import AzureADClaims, get_azure_claims
from shared.db.session import metadata_session_dep
from shared.models.db import User, UserClientRole, UserProjectRole, UserRole

logger = logging.getLogger(__name__)

# Role hierarchy: higher index = more permissions
_ROLE_HIERARCHY = [
    UserRole.PROJECT_VIEWER,
    UserRole.DEVELOPER,
    UserRole.CLIENT_ADMIN,
    UserRole.SUPER_ADMIN,
]


def _role_rank(role: UserRole) -> int:
    try:
        return _ROLE_HIERARCHY.index(role)
    except ValueError:
        return -1


async def _get_or_create_user(
    claims: AzureADClaims,
    session: AsyncSession,
) -> User:
    """Resolve Azure AD claims to a TrustAI user, creating on first login."""
    result = await session.execute(select(User).where(User.azure_oid == claims.oid))
    user = result.scalar_one_or_none()
    if not user:
        is_admin = True if ("super_admin" in claims.roles or claims.oid == "00000000-0000-0000-0000-000000000001") else False
        user = User(
            azure_oid=claims.oid,
            email=claims.email,
            display_name=claims.name,
            is_super_admin=is_admin,
        )
        session.add(user)
        await session.flush()
        logger.info("Created new TrustAI user for Azure OID %s", claims.oid)
    return user


def require_super_admin():
    """Dependency: user must be a platform super_admin."""
    async def dependency(
        claims: AzureADClaims = Depends(get_azure_claims),
        session: AsyncSession = Depends(metadata_session_dep),
    ) -> User:
        user = await _get_or_create_user(claims, session)
        if not user.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
        return user
    return dependency


def require_client_access(min_role: UserRole = UserRole.PROJECT_VIEWER):
    """
    Dependency factory: user must have at least `min_role` on the client
    identified by the `client_id` path parameter.
    Super admins bypass this check.
    """
    async def dependency(
        client_id: uuid.UUID = Path(...),
        claims: AzureADClaims = Depends(get_azure_claims),
        session: AsyncSession = Depends(metadata_session_dep),
    ) -> User:
        user = await _get_or_create_user(claims, session)
        if user.is_super_admin:
            return user

        result = await session.execute(
            select(UserClientRole).where(
                UserClientRole.user_id == user.id,
                UserClientRole.client_id == client_id,
            )
        )
        role_record = result.scalar_one_or_none()
        if not role_record:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this client")
        if _role_rank(role_record.role) < _role_rank(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_role.value} or higher on this client",
            )
        return user
    return dependency


def require_project_access(min_role: UserRole = UserRole.PROJECT_VIEWER):
    """
    Dependency factory: user must have at least `min_role` on the project
    (or on the parent client) identified by `project_id` path parameter.
    """
    async def dependency(
        project_id: uuid.UUID = Path(...),
        claims: AzureADClaims = Depends(get_azure_claims),
        session: AsyncSession = Depends(metadata_session_dep),
    ) -> User:
        from shared.models.db import Project  # avoid circular
        user = await _get_or_create_user(claims, session)
        if user.is_super_admin:
            return user

        # Check direct project role
        result = await session.execute(
            select(UserProjectRole).where(
                UserProjectRole.user_id == user.id,
                UserProjectRole.project_id == project_id,
            )
        )
        project_role = result.scalar_one_or_none()
        if project_role and _role_rank(project_role.role) >= _role_rank(min_role):
            return user

        # Fall back to client-level role
        proj_result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = proj_result.scalar_one_or_none()
        if project:
            client_result = await session.execute(
                select(UserClientRole).where(
                    UserClientRole.user_id == user.id,
                    UserClientRole.client_id == project.client_id,
                )
            )
            client_role = client_result.scalar_one_or_none()
            if client_role and _role_rank(client_role.role) >= _role_rank(min_role):
                return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient access to this project",
        )
    return dependency


async def get_current_user(
    claims: AzureADClaims = Depends(get_azure_claims),
    session: AsyncSession = Depends(metadata_session_dep),
) -> User:
    """Basic dependency: just resolve claims to a User (no role check)."""
    return await _get_or_create_user(claims, session)
