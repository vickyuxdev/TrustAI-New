"""
services/governance/app/security.py
Authentication, authorisation and secure response headers for the governance API.

Three kinds of caller:
  * machine  - `X-API-Key: tai_live_...` project key with scope `govern` (AI Factory, SDK, CI). Bound to one project.
  * user     - `Authorization: Bearer <Azure AD JWT>` (dashboard). Super admins see every project; other users see
               the projects they hold a role on. In development without a token the dev super admin is used,
               exactly like the other TrustAI services.
  * internal - `X-Internal-Secret` (the TrustAI AI Gateway calling authorize/enforce).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.db import session_dep

logger = logging.getLogger("governance.security")

GOVERN_SCOPES = {"govern", "admin", "*"}
DEV_USER_OID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller and the projects it may act on (None = every project)."""

    kind: str  # api_key | user | internal
    subject: str
    project_ids: frozenset[uuid.UUID] | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_global(self) -> bool:
        """True for super admins and the internal gateway."""
        return self.project_ids is None

    @property
    def bound_project(self) -> uuid.UUID | None:
        """The single project an API key is bound to."""
        if self.project_ids is not None and len(self.project_ids) == 1:
            return next(iter(self.project_ids))
        return None

    def resolve_project(self, requested: uuid.UUID | None) -> uuid.UUID:
        """Project for a write: the key's project, or the explicitly requested one if the caller may use it."""
        if requested is None:
            bound = self.bound_project
            if bound is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id is required for this caller")
            return bound
        self.require_project(requested)
        return requested

    def require_project(self, project_id: uuid.UUID) -> None:
        """403 unless the caller may act on `project_id`."""
        if self.project_ids is not None and project_id not in self.project_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed for this project")

    def visible_projects(self) -> frozenset[uuid.UUID] | None:
        """Filter for list queries (None = no filter)."""
        return self.project_ids


@dataclass(frozen=True)
class ResolvedKey:
    """What an API-key lookup returns."""

    project_id: uuid.UUID
    scopes: frozenset[str]
    key_prefix: str


KeyResolver = Callable[[AsyncSession, str], Awaitable[ResolvedKey | None]]
TokenVerifier = Callable[[str], dict[str, Any]]


def hash_key(raw_key: str) -> str:
    """SHA-256 hex digest used for every stored key (TrustAI project keys and gateway keys)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def db_key_resolver(session: AsyncSession, raw_key: str) -> ResolvedKey | None:
    """Look an `X-API-Key` up in TrustAI's `api_keys` table (parameterised SQL, hash comparison only)."""
    row = (await session.execute(
        text(
            "SELECT k.project_id, k.scopes, k.key_prefix, CAST(k.status AS TEXT) AS status, k.expires_at, "
            "p.is_active FROM api_keys k JOIN projects p ON p.id = k.project_id WHERE k.key_hash = :key_hash"
        ),
        {"key_hash": hash_key(raw_key)},
    )).mappings().first()
    if row is None or str(row["status"]).lower() != "active" or not row["is_active"]:
        return None
    expires_at = row["expires_at"]
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None
    scopes = row["scopes"] or []
    project_id = row["project_id"] if isinstance(row["project_id"], uuid.UUID) else uuid.UUID(str(row["project_id"]))
    return ResolvedKey(project_id=project_id, scopes=frozenset(str(s) for s in scopes), key_prefix=row["key_prefix"])


def default_token_verifier(token: str) -> dict[str, Any]:
    """Validate an Azure AD access token with the shared TrustAI verifier."""
    from shared.auth.azure_ad import _validate_azure_token  # local import: optional heavy dependency

    return _validate_azure_token(token)


async def _user_projects(session: AsyncSession, oid: str) -> frozenset[uuid.UUID]:
    """Projects a non-admin user holds a role on (direct project roles plus every project of their clients)."""
    try:
        rows = (await session.execute(
            text(
                "SELECT upr.project_id AS pid FROM user_project_roles upr JOIN users u ON u.id = upr.user_id "
                "WHERE u.azure_oid = :oid "
                "UNION SELECT p.id AS pid FROM projects p JOIN user_client_roles ucr ON ucr.client_id = p.client_id "
                "JOIN users u ON u.id = ucr.user_id WHERE u.azure_oid = :oid"
            ),
            {"oid": oid},
        )).scalars().all()
    except SQLAlchemyError:
        logger.warning("RBAC tables unavailable; user %s sees no projects", oid)
        return frozenset()
    return frozenset(r if isinstance(r, uuid.UUID) else uuid.UUID(str(r)) for r in rows)


def _static_keys() -> dict[str, uuid.UUID]:
    """Development-only keys from TRUSTAI_GOVERNANCE_STATIC_KEYS (never honoured outside development/test)."""
    settings = get_settings()
    raw = settings.static_keys.get_secret_value()
    if not raw or not settings.is_dev:
        return {}
    keys: dict[str, uuid.UUID] = {}
    for pair in raw.split(","):
        key, _, project = pair.strip().partition("=")
        try:
            keys[key.strip()] = uuid.UUID(project.strip())
        except ValueError:
            logger.warning("ignoring malformed TRUSTAI_GOVERNANCE_STATIC_KEYS entry")
    return keys


async def dev_key_resolver(session: AsyncSession, raw_key: str) -> ResolvedKey | None:
    """Static development keys first, then the TrustAI api_keys table (if it exists in this database)."""
    project = _static_keys().get(raw_key)
    if project is not None:
        return ResolvedKey(project_id=project, scopes=frozenset({"govern", "ingest"}), key_prefix=raw_key[:14])
    try:
        return await db_key_resolver(session, raw_key)
    except SQLAlchemyError:
        await session.rollback()
        return None


def get_key_resolver() -> KeyResolver:
    """Dependency hook (tests override it with an in-memory resolver)."""
    return dev_key_resolver if _static_keys() else db_key_resolver


def get_token_verifier() -> TokenVerifier:
    """Dependency hook (tests override it)."""
    return default_token_verifier


async def get_principal(
    session: Annotated[AsyncSession, Depends(session_dep)],
    resolver: Annotated[KeyResolver, Depends(get_key_resolver)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_secret: Annotated[str | None, Header(alias="X-Internal-Secret")] = None,
) -> Principal:
    """Authenticate the request and return its Principal (401/403 otherwise)."""
    settings = get_settings()
    if x_internal_secret is not None:
        expected = settings.internal_api_secret.get_secret_value()
        if not expected or not hmac.compare_digest(x_internal_secret, expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal secret")
        return Principal(kind="internal", subject="trustai-gateway", project_ids=None, scopes=frozenset({"*"}))

    if x_api_key:
        resolved = await resolver(session, x_api_key.strip())
        if resolved is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid, revoked or expired API key")
        if not resolved.scopes & GOVERN_SCOPES:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "API key lacks the 'govern' scope")
        return Principal(kind="api_key", subject=f"api_key:{resolved.key_prefix}",
                         project_ids=frozenset({resolved.project_id}), scopes=resolved.scopes)

    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = verifier(authorization.split(" ", 1)[1].strip())
        except Exception as exc:  # noqa: BLE001 - any validation failure is a 401
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {type(exc).__name__}") from exc
        oid = str(claims.get("oid") or claims.get("sub") or "")
        roles = set(claims.get("roles") or [])
        subject = str(claims.get("preferred_username") or claims.get("upn") or oid)
        if "super_admin" in roles:
            return Principal(kind="user", subject=subject, project_ids=None, scopes=frozenset({"*"}))
        return Principal(kind="user", subject=subject, project_ids=await _user_projects(session, oid),
                         scopes=frozenset({"govern"}))

    if settings.is_dev:
        return Principal(kind="user", subject="dev-admin@trustai.local", project_ids=None, scopes=frozenset({"*"}))
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required",
                        headers={"WWW-Authenticate": "Bearer"})


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_human(principal: Principal) -> None:
    """Human-only actions (risk decisions, approvals) refuse machine credentials."""
    if principal.kind != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this decision must be made by a person in the TrustAI portal")


def require_internal(principal: Principal) -> None:
    """Gateway-only endpoints."""
    if principal.kind not in ("internal",) and not (principal.kind == "user" and principal.is_global):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "internal endpoint")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds secure HTTP headers to every response (OWASP secure-headers baseline for JSON APIs)."""

    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-site",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    }
    DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com")

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Attach the headers; the interactive docs page gets a CSP that lets Swagger UI load."""
        response = await call_next(request)
        for name, value in self.HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path in ("/docs", "/redoc"):
            response.headers["Content-Security-Policy"] = self.DOCS_CSP
        return response
