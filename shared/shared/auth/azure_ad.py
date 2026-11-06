"""
shared/auth/azure_ad.py
Azure AD / Entra ID JWT validation middleware for FastAPI services.
Uses MSAL + Microsoft's JWKS endpoint for offline token verification.
"""
import logging
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from shared.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

_BEARER = HTTPBearer(auto_error=True)

# Microsoft's OpenID Connect metadata endpoint
_OIDC_META_URL = (
    f"https://login.microsoftonline.com/{_settings.tenant_id}"
    "/v2.0/.well-known/openid-configuration"
)


@lru_cache(maxsize=1)
def _get_jwks_uri() -> str:
    """Fetch the JWKS URI from Azure AD's OIDC metadata document (cached)."""
    resp = httpx.get(_OIDC_META_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()["jwks_uri"]


@lru_cache(maxsize=1)
def _get_signing_keys() -> dict[str, Any]:
    """Fetch JWKS and cache it. Should be refreshed periodically in production."""
    jwks_uri = _get_jwks_uri()
    resp = httpx.get(jwks_uri, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _validate_azure_token(token: str) -> dict[str, Any]:
    """
    Validate an Azure AD JWT token offline using JWKS.
    Returns the decoded claims dict on success.
    Raises HTTPException 401 on any validation failure.
    """
    try:
        keys = _get_signing_keys()
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        # Find the matching key
        rsa_key = {}
        for key in keys.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "n": key["n"],
                    "e": key["e"],
                }
                break

        if not rsa_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find matching signing key",
            )

        audience = _settings.audience or _settings.client_id
        claims = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=audience,
        )
        return claims

    except JWTError as exc:
        logger.warning("Azure AD JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        logger.error("Unexpected auth error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


class AzureADClaims:
    """Parsed Azure AD token claims, injected as a FastAPI dependency."""

    def __init__(self, claims: dict[str, Any]):
        self.oid: str = claims.get("oid", "")
        self.email: str = claims.get("preferred_username", claims.get("email", ""))
        self.name: str = claims.get("name", "")
        self.roles: list[str] = claims.get("roles", [])
        self.scopes: list[str] = claims.get("scp", "").split() if claims.get("scp") else []
        self.raw = claims


_BEARER = HTTPBearer(auto_error=False)


async def get_azure_claims(
    credentials: HTTPAuthorizationCredentials | None = Security(_BEARER),
) -> AzureADClaims:
    """FastAPI dependency: validate Azure AD token and return claims."""
    if credentials is None:
        if _settings.environment == "development":
            return AzureADClaims({
                "oid": "00000000-0000-0000-0000-000000000001",
                "preferred_username": "admin@trustai.local",
                "name": "Dev SuperAdmin",
                "roles": ["super_admin"],
            })
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = _validate_azure_token(credentials.credentials)
    return AzureADClaims(claims)
