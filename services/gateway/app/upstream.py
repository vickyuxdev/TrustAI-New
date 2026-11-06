"""
services/gateway/app/upstream.py
Calls the upstream model provider for a chat completion (non-streaming; the gateway re-streams after output
enforcement). Providers: Azure OpenAI deployments and any OpenAI-compatible API. `mock` is a deterministic echo
model for local development and tests only (refused in staging/production by config).
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from app.config import Upstream

TRANSPORT: httpx.AsyncBaseTransport | None = None

# Request fields forwarded to the provider (everything else is dropped).
FORWARDED = {"messages", "temperature", "top_p", "max_tokens", "max_completion_tokens", "stop", "tools",
             "tool_choice", "response_format", "seed", "presence_penalty", "frequency_penalty", "user", "n"}


class UpstreamError(Exception):
    """Provider failure, carrying the HTTP status to return."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _mock_completion(alias: str, body: dict[str, Any]) -> dict[str, Any]:
    """Echo the last user message (development only)."""
    last = next((m.get("content") for m in reversed(body.get("messages") or []) if m.get("role") == "user"), "")
    text = f"[mock:{alias}] {last if isinstance(last, str) else 'ok'}"
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion", "created": int(time.time()),
            "model": alias, "choices": [{"index": 0, "finish_reason": "stop",
                                         "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": len(str(last)) // 4 + 1, "completion_tokens": len(text) // 4 + 1,
                      "total_tokens": (len(str(last)) + len(text)) // 4 + 2}}


async def complete(alias: str, route: Upstream, body: dict[str, Any]) -> dict[str, Any]:
    """Return an OpenAI-shaped chat.completion from the routed provider."""
    payload = {k: v for k, v in body.items() if k in FORWARDED}
    if route.provider == "mock":
        return _mock_completion(alias, payload)
    key = route.api_key()
    if not key:
        raise UpstreamError(503, f"upstream credentials for model {alias!r} are not configured")
    if route.provider == "azure_openai":
        url = (f"{route.base_url.rstrip('/')}/openai/deployments/{route.deployment or alias}/chat/completions"
               f"?api-version={route.api_version}")
        headers = {"api-key": key}
    else:
        url = route.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}"}
        payload["model"] = route.model or alias
    try:
        async with httpx.AsyncClient(timeout=route.timeout_seconds, transport=TRANSPORT) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise UpstreamError(502, f"upstream unreachable: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        # pass provider content-filter / validation errors through with their status, never the provider key
        detail = resp.text[:500]
        raise UpstreamError(resp.status_code if resp.status_code < 500 else 502, f"upstream error: {detail}")
    data = resp.json()
    data["model"] = alias
    return data
