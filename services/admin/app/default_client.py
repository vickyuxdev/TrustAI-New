"""
services/admin/app/default_client.py
The hidden default client.

TrustAI's dashboard and APIs are project-based: a project holds agents, and users no longer see or pick a client.
The database still hangs every project (and connector) off a `clients` row, so anything created without naming a
client attaches to this one. Existing clients and their projects are untouched.
"""
import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.rbac import get_current_user
from shared.db.session import metadata_session_dep
from shared.models.db import Client, ClientType, User, UserClientRole, UserRole

DEFAULT_CLIENT_SLUG = "default"
DEFAULT_CLIENT_NAME = "Default"


async def get_default_client(session: AsyncSession) -> Client:
    """The default client row, created on first use (safe if two requests race to create it)."""
    found = (await session.execute(select(Client).where(Client.slug == DEFAULT_CLIENT_SLUG))).scalar_one_or_none()
    if found:
        return found
    client = Client(
        name=DEFAULT_CLIENT_NAME,
        slug=DEFAULT_CLIENT_SLUG,
        client_type=ClientType.INTERNAL,
        description="Created automatically: projects are not grouped by client.",
    )
    try:
        async with session.begin_nested():
            session.add(client)
            await session.flush()
        return client
    except IntegrityError:  # another request created it first
        return (await session.execute(select(Client).where(Client.slug == DEFAULT_CLIENT_SLUG))).scalar_one()


async def can_create_projects(user: User, session: AsyncSession, default_client_id: uuid.UUID) -> bool:
    """Platform super admins, and client admins of the default client, may create projects."""
    if user.is_super_admin:
        return True
    role = (await session.execute(
        select(UserClientRole).where(UserClientRole.user_id == user.id, UserClientRole.client_id == default_client_id)
    )).scalar_one_or_none()
    return bool(role and role.role in (UserRole.CLIENT_ADMIN, UserRole.SUPER_ADMIN))


async def require_project_creator(
    session: AsyncSession = Depends(metadata_session_dep),
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency for creating a project without naming a client."""
    client = await get_default_client(session)
    if not await can_create_projects(current_user, session, client.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project admin access required")
    return current_user
