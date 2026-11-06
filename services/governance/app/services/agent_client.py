"""
services/governance/app/services/agent_client.py
Calls a governed agent's HTTP runtime endpoint (connection tests and red-team iterations).
The request body is the agent's `request_template` with every "{{prompt}}" replaced; the answer is read from the
dotted `response_key`. Only http/https endpoints registered on the agent are ever called.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

# Transport hook for tests (an httpx.ASGITransport or MockTransport); None in production.
TRANSPORT: httpx.AsyncBaseTransport | None = None


@dataclass
class AgentReply:
    """Result of one call to an agent."""

    ok: bool
    text: str
    status_code: int | None
    latency_ms: int
    error: str | None = None
    raw: Any = None
    blocked_by_guardrail: bool = False


def _fill(template: Any, prompt: str) -> Any:
    """Recursively substitute {{prompt}} in strings of the request template."""
    if isinstance(template, str):
        return template.replace("{{prompt}}", prompt)
    if isinstance(template, dict):
        return {k: _fill(v, prompt) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, prompt) for v in template]
    return template


def _extract(body: Any, key: str) -> Any:
    """Read a dotted path (a.b.0.c) from a JSON body."""
    cur = body
    for part in key.split(".") if key else []:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _guard_blocked(body: Any) -> bool:
    """True when the agent reports that its own guardrail / TrustAI guard blocked the turn."""
    if not isinstance(body, dict):
        return False
    if body.get("blocked") is True or body.get("refused") is True:
        return True
    guard = body.get("trustai_guard")
    if isinstance(guard, list):
        return any(isinstance(g, dict) and g.get("passed") is False for g in guard)
    return False


async def call_agent(runtime: dict[str, Any], prompt: str, timeout_seconds: float | None = None,
                     session_id: str | None = None) -> AgentReply:
    """POST one prompt to the agent and return its reply text (never raises)."""
    url = str(runtime.get("base_url") or "")
    if not url.startswith(("http://", "https://")):
        return AgentReply(False, "", None, 0, "agent has no http(s) runtime endpoint")
    body = _fill(runtime.get("request_template") or {"message": "{{prompt}}"}, prompt)
    if session_id and isinstance(body, dict):
        body.setdefault("session_id", session_id)
    timeout = float(timeout_seconds or runtime.get("timeout_seconds") or 60.0)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=TRANSPORT, follow_redirects=False) as client:
            resp = await client.post(url, json=body, headers={"User-Agent": "TrustAI-Governance/0.1"})
    except httpx.HTTPError as exc:
        return AgentReply(False, "", None, round((time.monotonic() - started) * 1000), f"{type(exc).__name__}: {exc}"[:300])
    latency = round((time.monotonic() - started) * 1000)
    try:
        data: Any = resp.json()
    except (json.JSONDecodeError, ValueError):
        data = resp.text
    if resp.status_code in (400, 403, 422) and "guardrail" in json.dumps(data, default=str).lower():
        return AgentReply(True, str(data)[:4000], resp.status_code, latency, raw=data, blocked_by_guardrail=True)
    if resp.status_code >= 400:
        return AgentReply(False, "", resp.status_code, latency, f"HTTP {resp.status_code}", raw=data)
    value = _extract(data, str(runtime.get("response_key") or "response")) if isinstance(data, (dict, list)) else data
    text = value if isinstance(value, str) else json.dumps(value, default=str) if value is not None else ""
    return AgentReply(True, text[:20000], resp.status_code, latency, raw=data, blocked_by_guardrail=_guard_blocked(data))
