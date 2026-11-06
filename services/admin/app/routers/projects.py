"""
services/admin/app/routers/projects.py
Project CRUD — create and update projects. Projects are created directly (POST /projects); the per-client path
(POST /clients/{client_id}/projects) stays for existing integrations.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.default_client import get_default_client, require_project_creator
from shared.auth.rbac import get_current_user, require_client_access
from shared.db.session import metadata_session_dep
from shared.models.db import AuditLog, Client, Project, User, UserRole
from shared.models.schemas import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter()


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (no client needed)",
)
async def create_project_direct(
    body: ProjectCreate,
    session: AsyncSession = Depends(metadata_session_dep),
    current_user: User = Depends(require_project_creator),
):
    """Create a project under the hidden default client; the slug must be unique among such projects."""
    client = await get_default_client(session)
    existing = await session.execute(
        select(Project).where(Project.client_id == client.id, Project.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"A project with slug '{body.slug}' already exists")

    project = Project(client_id=client.id, **body.model_dump())
    session.add(project)
    session.add(AuditLog(
        user_id=current_user.id,
        action="create_project",
        resource_type="project",
        resource_id=str(project.id),
        new_value={"name": body.name},
    ))
    await session.flush()
    return ProjectResponse.model_validate(project)


@router.post("/clients/{client_id}/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    client_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(require_client_access(min_role=UserRole.CLIENT_ADMIN)),
):
    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Check slug uniqueness within client
    existing = await session.execute(
        select(Project).where(Project.client_id == client_id, Project.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists for this client")

    project = Project(client_id=client_id, **body.model_dump())
    session.add(project)
    session.add(AuditLog(
        user_id=current_user.id,
        action="create_project",
        resource_type="project",
        resource_id=str(project.id),
        new_value={"name": body.name, "client_id": str(client_id)},
    ))
    await session.flush()
    return ProjectResponse.model_validate(project)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    body: ProjectUpdate,
    project_id: uuid.UUID = Path(...),
    session: AsyncSession = Depends(metadata_session_dep),
    current_user=Depends(get_current_user),
):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    return ProjectResponse.model_validate(project)
