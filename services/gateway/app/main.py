"""
services/gateway/app/main.py
TrustAI AI Gateway - OpenAI-compatible endpoint that enforces each agent's TrustAI policies.

  POST /v1/chat/completions   Authorization: Bearer tai_gw_...   (or `api-key:` header, Azure style)
    1. key -> agent (governance /gateway/authorize, cached)       401 unknown/revoked, 403 suspended
    2. per-key rate limit                                         429
    3. model must be in the deployment's allowed models          403
    4. input policies on the latest user message                 400 content_filter (never forwarded)
    5. upstream completion (Azure OpenAI / OpenAI-compatible)
    6. tool-call and output policies on the response             400 content_filter (content withheld)
    7. response (JSON, or re-streamed as SSE when stream=true) + telemetry span to TrustAI ingestion
If governance is unreachable the gateway fails closed (503) unless TRUSTAI_GATEWAY_FAIL_CLOSED=false.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from app import governance
from app.config import get_settings
from app.upstream import UpstreamError, complete

logger = logging.getLogger("gateway")
_RATE: dict[str, deque[float]] = {}
_BACKGROUND: set[asyncio.Task[None]] = set()

SECURE_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


def error(status: int, message: str, etype: str, code: str | None = None, **extra: Any) -> JSONResponse:
    """OpenAI-style error body."""
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": etype, "code": code, **extra}})


def _client_key(request: Request) -> str | None:
    """Bearer token or Azure-style api-key header."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    return request.headers.get("api-key") or None


def _rate_limited(key_digest: str) -> bool:
    """Sliding one-minute window per key (per gateway replica)."""
    now = time.monotonic()
    window = _RATE.setdefault(key_digest, deque())
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= get_settings().rate_limit_rpm:
        return True
    window.append(now)
    return False


def _tool_name_for_call(messages: list[dict[str, Any]], call_id: str | None) -> str | None:
    """The real function name for a tool_call_id, from the assistant message that made the call.

    A `{"role": "tool", ...}` result message only ever carries `tool_call_id`, never the function name itself -
    it has to be looked up from whichever earlier assistant message's `tool_calls` made that call."""
    if not call_id:
        return None
    for m in messages:
        for call in m.get("tool_calls") or []:
            if call.get("id") == call_id:
                return (call.get("function") or {}).get("name")
    return None


def _text(content: Any) -> str:
    """Flatten OpenAI message content (string or parts) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _blocked(decision: dict[str, Any], phase: str, rid: str) -> JSONResponse:
    """Uniform guardrail refusal (the factory runtime and SDKs treat 400 content_filter as a refusal)."""
    names = sorted({b.get("policy_name") or "policy" for b in decision.get("blocked_by", [])})
    checks = sorted({c for b in decision.get("blocked_by", []) for c in b.get("failed_checks", [])})
    return error(400, f"Request blocked by TrustAI guardrail ({phase}): {', '.join(checks) or 'policy violation'}",
                 "trustai_guardrail", "content_filter", phase=phase, policies=names, failed_checks=checks,
                 guardrail_eval_ids=[str(i) for i in decision.get("guardrail_eval_ids", [])], request_id=rid)


async def _emit_span(info: governance.KeyInfo, model: str, started: datetime, latency_ms: int,
                     usage: dict[str, Any], outcome: str, rid: str) -> None:
    """Best-effort span into TrustAI ingestion (Traces / Cost pages)."""
    s = get_settings()
    if not (s.ingest_url and s.ingest_api_key.get_secret_value() and s.ingest_project_id):
        return
    span = {"trace_id": uuid.uuid4().hex, "span_id": uuid.uuid4().hex[:16], "span_name": f"gateway.{model}",
            "span_kind": "client", "started_at": started.isoformat(), "duration_ms": latency_ms,
            "provider": "trustai_gateway", "model_name": model, "operation": "chat",
            "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"), "status": "error" if outcome != "ok" else "ok",
            "attributes": {"trustai.agent_id": info.agent_id, "trustai.gateway.outcome": outcome, "request_id": rid}}
    try:
        async with httpx.AsyncClient(timeout=5, transport=governance.TRANSPORT) as client:
            await client.post(s.ingest_url.rstrip("/") + "/v1/traces",
                              headers={"X-API-Key": s.ingest_api_key.get_secret_value()},
                              json={"project_id": s.ingest_project_id, "environment": s.environment,
                                    "agent_name": info.agent_name, "sdk_version": "trustai-gateway/0.1", "spans": [span]})
    except httpx.HTTPError as exc:
        logger.warning("telemetry span not delivered: %s", type(exc).__name__)


def _spawn(coro: Awaitable[None]) -> None:
    """Fire-and-forget with a held reference."""
    task = asyncio.ensure_future(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def _sse(completion: dict[str, Any]) -> AsyncIterator[bytes]:
    """Re-stream an already-checked completion as OpenAI chat.completion.chunk events."""
    base = {"id": completion.get("id"), "object": "chat.completion.chunk", "created": completion.get("created"),
            "model": completion.get("model")}
    for choice in completion.get("choices", []):
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        first = {"role": "assistant"}
        if msg.get("tool_calls"):
            first["tool_calls"] = msg["tool_calls"]
        yield f"data: {json.dumps({**base, 'choices': [{'index': choice.get('index', 0), 'delta': first}]})}\n\n".encode()
        for i in range(0, len(content), 64):
            delta = {"index": choice.get("index", 0), "delta": {"content": content[i:i + 64]}}
            yield f"data: {json.dumps({**base, 'choices': [delta]})}\n\n".encode()
        done = {"index": choice.get("index", 0), "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}
        yield f"data: {json.dumps({**base, 'choices': [done], 'usage': completion.get('usage')})}\n\n".encode()
    yield b"data: [DONE]\n\n"


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    app = FastAPI(title="TrustAI AI Gateway", version="0.1.0", docs_url="/docs", redoc_url=None,
                  root_path=os.getenv("TRUSTAI_ROOT_PATH", ""),
                  description="OpenAI-compatible gateway that enforces TrustAI policies per agent.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "api-key"])

    @app.middleware("http")
    async def headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Body-size guard, request id and secure headers."""
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > get_settings().max_body_bytes:
            return error(413, "request body too large", "invalid_request_error")
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.rid = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        for k, v in SECURE_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path == "/docs":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com")
        return response

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness."""
        return {"status": "ok", "service": "gateway"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """Readiness: governance reachable and at least one model routed."""
        try:
            async with httpx.AsyncClient(timeout=5, transport=governance.TRANSPORT) as client:
                ok = (await client.get(get_settings().governance_url.rstrip("/") + "/health")).status_code == 200
        except httpx.HTTPError:
            ok = False
        models = sorted(get_settings().upstreams())
        status = 200 if ok and models else 503
        return JSONResponse(status_code=status, content={"status": "ready" if status == 200 else "unavailable",
                                                         "governance": ok, "models": models})

    async def _auth(request: Request) -> governance.KeyInfo | JSONResponse:
        """Resolve the caller's key or return the error response."""
        raw = _client_key(request)
        if not raw:
            return error(401, "missing API key (Authorization: Bearer tai_gw_...)", "authentication_error", "missing_key")
        try:
            info = await governance.authorize(raw)
        except governance.GovernanceUnavailable as exc:
            return error(503, f"TrustAI governance unavailable ({exc})", "service_unavailable")
        if info is None:
            return error(401, "invalid or revoked gateway key", "authentication_error", "invalid_api_key")
        if _rate_limited(raw[-24:]):
            return error(429, "rate limit exceeded", "rate_limit_error", "rate_limit_exceeded")
        return info

    @app.get("/v1/models")
    async def models(request: Request) -> Any:
        """Models this key may use."""
        info = await _auth(request)
        if isinstance(info, JSONResponse):
            return info
        routes = get_settings().upstreams()
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "trustai"}
                                           for m in info.allowed_models if m in routes]}

    async def _check(info: governance.KeyInfo, phase: str, text: str, rid: str, query: str | None = None,
                     tool: str | None = None) -> JSONResponse | None:
        """Enforce one phase; returns a refusal/503 response or None when allowed."""
        if not text.strip():
            return None
        try:
            decision = await governance.enforce(info.agent_id, phase, text, rid, query=query, tool_name=tool)
        except governance.GovernanceUnavailable as exc:
            if get_settings().fail_closed:
                return error(503, f"TrustAI policy check unavailable ({exc}); failing closed", "service_unavailable")
            logger.warning("policy check skipped (fail-open): %s", exc)
            return None
        return None if decision.get("allowed", False) else _blocked(decision, phase, rid)

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        """OpenAI-compatible chat completion with TrustAI enforcement."""
        rid = request.state.rid
        info = await _auth(request)
        if isinstance(info, JSONResponse):
            return info
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return error(400, "body must be JSON", "invalid_request_error")
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list) or not body["messages"]:
            return error(400, "`messages` must be a non-empty list", "invalid_request_error")
        model = str(body.get("model") or info.model)
        if model not in info.allowed_models:
            return error(403, f"model {model!r} is not allowed for this agent", "permission_error", "model_not_allowed")
        routes = get_settings().upstreams()
        route = routes.get(model)
        if route is None:
            return error(404, f"model {model!r} is not routed by this gateway", "invalid_request_error", "model_not_found")

        user_text = next((_text(m.get("content")) for m in reversed(body["messages"]) if m.get("role") == "user"), "")
        tool_msg = next((m for m in reversed(body["messages"]) if m.get("role") == "tool"), None)
        tool_text = _text(tool_msg.get("content")) if tool_msg else ""
        if (refusal := await _check(info, "input", user_text, rid)) is not None:
            return refusal
        if tool_text:
            # Resolve the real tool name rather than faking one: an unresolved name must mean "no tool call in
            # context" to the permission evaluator (plain "tool_result" phase), never an invented name that
            # would look like an unregistered tool and get denied regardless of what the result actually says.
            tool_name = _tool_name_for_call(body["messages"], tool_msg.get("tool_call_id") if tool_msg else None)
            phase = f"tool_result:{tool_name}" if tool_name else "tool_result"
            if (refusal := await _check(info, phase, tool_text, rid, tool=tool_name)) is not None:
                return refusal

        started = datetime.now(timezone.utc)
        t0 = time.monotonic()
        try:
            completion = await complete(model, route, body)
        except UpstreamError as exc:
            _spawn(_emit_span(info, model, started, round((time.monotonic() - t0) * 1000), {}, "upstream_error", rid))
            return error(exc.status_code, str(exc), "upstream_error")
        latency = round((time.monotonic() - t0) * 1000)

        for choice in completion.get("choices", []):
            msg = choice.get("message") or {}
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                if (refusal := await _check(info, f"tool_call:{fn.get('name')}", str(fn.get("arguments") or ""),
                                            rid, tool=fn.get("name"))) is not None:
                    _spawn(_emit_span(info, model, started, latency, completion.get("usage") or {}, "blocked_tool", rid))
                    return refusal
            if (refusal := await _check(info, "output", _text(msg.get("content")), rid, query=user_text)) is not None:
                _spawn(_emit_span(info, model, started, latency, completion.get("usage") or {}, "blocked_output", rid))
                return refusal

        _spawn(_emit_span(info, model, started, latency, completion.get("usage") or {}, "ok", rid))
        if body.get("stream"):
            return StreamingResponse(_sse(completion), media_type="text/event-stream")
        return completion

    return app


app = create_app()
