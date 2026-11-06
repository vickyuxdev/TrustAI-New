"""
services/gateway/app/governance.py
Client for the governance control plane: key authorisation (cached) and per-phase policy enforcement.
All calls carry X-Internal-Secret; the governance service rejects them otherwise.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

# Transport hook for tests.
TRANSPORT: httpx.AsyncBaseTransport | None = None
_KEY_CACHE: dict[str, tuple[float, "KeyInfo | None"]] = {}


class GovernanceUnavailable(Exception):
    """The control plane could not be reached or answered with a server error."""


@dataclass(frozen=True)
class KeyInfo:
    """What a gateway key is allowed to do."""

    agent_id: str
    project_id: str
    agent_name: str
    model: str
    allowed_models: tuple[str, ...]


def _client() -> httpx.AsyncClient:
    """HTTP client bound to the governance URL with the internal secret."""
    s = get_settings()
    return httpx.AsyncClient(base_url=s.governance_url.rstrip("/"), timeout=s.enforce_timeout_seconds,
                             headers={"X-Internal-Secret": s.internal_api_secret.get_secret_value()},
                             transport=TRANSPORT)


def clear_cache() -> None:
    """Forget cached key resolutions (tests, revocation fan-out)."""
    _KEY_CACHE.clear()


async def authorize(raw_key: str) -> KeyInfo | None:
    """Resolve a client key to its agent; None for unknown/revoked keys. Positive and negative answers are cached."""
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    hit = _KEY_CACHE.get(digest)
    if hit and time.monotonic() - hit[0] < get_settings().key_cache_seconds:
        return hit[1]
    try:
        async with _client() as client:
            resp = await client.post("/api/v1/gateway/authorize", json={"api_key": raw_key})
    except httpx.HTTPError as exc:
        raise GovernanceUnavailable(type(exc).__name__) from exc
    if resp.status_code in (401, 403, 404):
        info = None
    elif resp.status_code >= 400:
        raise GovernanceUnavailable(f"HTTP {resp.status_code}")
    else:
        d = resp.json()
        info = KeyInfo(agent_id=d["agent_id"], project_id=d["project_id"], agent_name=d["agent_name"],
                       model=d["model"], allowed_models=tuple(d.get("allowed_models") or [d["model"]]))
    _KEY_CACHE[digest] = (time.monotonic(), info)
    return info


async def enforce(agent_id: str, phase: str, text: str, correlation_id: str, query: str | None = None,
                  tool_name: str | None = None) -> dict[str, Any]:
    """Run the agent's policies for one phase; returns the governance EnforceOut body."""
    payload = {"agent_id": agent_id, "phase": phase, "text": text[:200_000], "query": query,
               "tool_name": tool_name, "correlation_id": correlation_id, "source": "gateway"}
    try:
        async with _client() as client:
            resp = await client.post("/api/v1/enforce", json=payload)
    except httpx.HTTPError as exc:
        raise GovernanceUnavailable(type(exc).__name__) from exc
    if resp.status_code >= 400:
        raise GovernanceUnavailable(f"HTTP {resp.status_code}")
    return resp.json()
