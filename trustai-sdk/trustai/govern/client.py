"""
trustai/govern/client.py
Typed client for the TrustAI Governance API (agent registry, risk, guardrails, policies, evaluations, gateway,
evidence). One set of resource methods serves both clients: `GovernClient` returns values, `AsyncGovernClient`
returns awaitables.

    from trustai.govern import GovernClient
    gov = GovernClient(base_url="http://localhost:8004", api_key="tai_live_...")
    agent = gov.agents.onboard(external_id="WL-001", name="Invoice Agent", endpoint="http://agent:8080/chat")
    tier = gov.risk.assess(agent_id=agent["id"], facts={...})["risk_tier"]
    ev = gov.evaluations.run(agent_id=agent["id"], num_generate=40)           # creates and waits
    dep = gov.gateway.deploy(agent["id"])                                      # api_key shown once

Configuration falls back to TRUSTAI_GOVERNANCE_URL / TRUSTAI_BASE_URL and TRUSTAI_API_KEY.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8004"
RETRY_STATUSES = {429, 502, 503, 504}
TERMINAL = {"completed", "failed", "cancelled"}


class TrustAIAPIError(Exception):
    """A non-2xx response from TrustAI (status_code, detail)."""

    def __init__(self, status_code: int, detail: Any, method: str = "", path: str = ""):
        self.status_code, self.detail, self.method, self.path = status_code, detail, method, path
        super().__init__(f"TrustAI {method} {path} -> {status_code}: {str(detail)[:500]}")


class TrustAIConnectionError(TrustAIAPIError):
    """TrustAI could not be reached."""

    def __init__(self, message: str, method: str = "", path: str = ""):
        super().__init__(0, message, method, path)


def _settings(base_url: str | None, api_key: str | None) -> tuple[str, str | None]:
    """Explicit values win over environment variables."""
    url = base_url or os.getenv("TRUSTAI_GOVERNANCE_URL") or os.getenv("TRUSTAI_BASE_URL") or DEFAULT_URL
    return url.rstrip("/"), api_key or os.getenv("TRUSTAI_API_KEY")


def _headers(api_key: str | None) -> dict[str, str]:
    """Auth + identification headers."""
    headers = {"User-Agent": "trustai-sdk-govern/0.2", "Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _parse(resp: httpx.Response, method: str, path: str) -> Any:
    """Body on success, TrustAIAPIError otherwise."""
    if resp.status_code == 204:
        return None
    try:
        body: Any = resp.json()
    except ValueError:
        body = resp.text
    if resp.status_code >= 400:
        detail = body.get("detail", body) if isinstance(body, dict) else body
        raise TrustAIAPIError(resp.status_code, detail, method, path)
    return body


def _retryable(method: str, path: str) -> bool:
    """Every call is retried on transient errors except starting an evaluation (not idempotent)."""
    return not (method == "POST" and path.rstrip("/").endswith("/evaluations"))


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None values from a payload."""
    return {k: v for k, v in d.items() if v is not None}


Call = Callable[..., Any]


class _Agents:
    """Agent registry."""

    def __init__(self, call: Call):
        self._c = call

    def onboard(self, external_id: str, name: str, **fields: Any) -> Any:
        """Create or update an agent (idempotent by external_id). Fields: description, version, client, built_by,
        model, autonomy_level, tools, capabilities, tags, endpoint, runtime, project_id, metadata."""
        return self._c("POST", "/agents", json=_clean({"external_id": external_id, "name": name, **fields}))

    def get(self, agent_id: str) -> Any:
        """One agent."""
        return self._c("GET", f"/agents/{agent_id}")

    def list(self, **filters: Any) -> Any:
        """Paginated agents (status, risk_tier, search, external_id, limit, offset)."""
        return self._c("GET", "/agents", params=_clean(filters))

    def update(self, agent_id: str, **fields: Any) -> Any:
        """Patch an agent."""
        return self._c("PATCH", f"/agents/{agent_id}", json=_clean(fields))

    def set_status(self, agent_id: str, status: str, reason: str | None = None) -> Any:
        """Lifecycle transition (machine keys: onboarded / assessed / evaluated)."""
        return self._c("POST", f"/agents/{agent_id}/status", json=_clean({"status": status, "reason": reason}))

    def history(self, agent_id: str) -> Any:
        """Lifecycle history."""
        return self._c("GET", f"/agents/{agent_id}/history")

    def attach_policies(self, agent_id: str, policy_ids: list[str]) -> Any:
        """Replace attached policies."""
        return self._c("PUT", f"/agents/{agent_id}/policies", json={"policy_ids": policy_ids})

    def test_connection(self, agent_id: str, prompt: str | None = None) -> Any:
        """Reachability of the agent's runtime endpoint."""
        return self._c("POST", f"/agents/{agent_id}/test-connection", json=_clean({"prompt": prompt}))

    def register_mcp(self, servers: dict[str, dict[str, Any]], agent_id: str | None = None,
                     external_id: str | None = None) -> Any:
        """Register MCP servers ({name: {type, url, command}})."""
        return self._c("POST", "/mcp-servers", json=_clean({"agent_id": agent_id, "external_id": external_id,
                                                           "servers": servers}))

    def evidence(self, agent_id: str) -> Any:
        """Evidence pack."""
        return self._c("GET", f"/agents/{agent_id}/evidence")

    def optimize(self, agent_id: str, name: str | None = None, evaluation_id: str | None = None,
                 create_policy: bool = True) -> Any:
        """Policy recommendations from the latest red-team gaps."""
        return self._c("POST", f"/agents/{agent_id}/optimize",
                       json=_clean({"name": name, "evaluation_id": evaluation_id, "create_policy": create_policy}))


class _Risk:
    """Risk assessment."""

    def __init__(self, call: Call):
        self._c = call

    def template(self, template_id: str = "trustai_build_v1") -> Any:
        """Template definition."""
        return self._c("GET", f"/risk/templates/{template_id}")

    def assess(self, facts: dict[str, Any], agent_id: str | None = None, external_id: str | None = None,
               answers: dict[str, Any] | None = None) -> Any:
        """One-shot: create, pre-fill from facts, submit and classify."""
        return self._c("POST", "/risk/assess", json=_clean({"agent_id": agent_id, "external_id": external_id,
                                                           "facts": facts, "answers": answers or {}}))

    def create(self, agent_id: str, answers: dict[str, Any] | None = None, facts: dict[str, Any] | None = None) -> Any:
        """Draft assessment."""
        return self._c("POST", "/assessments", json=_clean({"agent_id": agent_id, "answers": answers or {}, "facts": facts}))

    def get(self, assessment_id: str) -> Any:
        """One assessment."""
        return self._c("GET", f"/assessments/{assessment_id}")

    def save_answers(self, assessment_id: str, answers: dict[str, Any], evidence: dict[str, Any] | None = None) -> Any:
        """Merge answers."""
        return self._c("PUT", f"/assessments/{assessment_id}/answers", json={"answers": answers, "evidence": evidence or {}})

    def submit(self, assessment_id: str, fill_defaults: bool = False) -> Any:
        """Submit and classify."""
        return self._c("POST", f"/assessments/{assessment_id}/submit", params={"fill_defaults": fill_defaults})

    def decide(self, assessment_id: str, decision: str, conditions: list[str] | None = None, note: str | None = None) -> Any:
        """Human decision (requires a user token, not a machine key)."""
        return self._c("POST", f"/assessments/{assessment_id}/decision",
                       json=_clean({"decision": decision, "conditions": conditions or [], "note": note}))


class _Guardrails:
    """Guardrails, policies, enforcement and metrics."""

    def __init__(self, call: Call):
        self._c = call

    def list(self) -> Any:
        """Guardrails."""
        return self._c("GET", "/guardrails")

    def evaluate(self, guardrail_id: str, text: str | None = None, *, query: str | None = None,
                 response: str | None = None, phase: str = "input", target_id: str | None = None,
                 correlation_id: str | None = None) -> Any:
        """Evaluate text (or a query/response pair) against one guardrail."""
        body = _clean({"text": text, "phase": phase, "target_id": target_id, "correlation_id": correlation_id,
                       "input": _clean({"query": query, "response": response}) if text is None else None})
        return self._c("POST", f"/guardrails/{guardrail_id}/evaluate", json=body)

    def policies(self, search: str | None = None, tags: list[str] | None = None) -> Any:
        """Policies."""
        return self._c("GET", "/policies", params=_clean({"search": search, "tags": tags}))

    def recommend(self, agent_id: str | None = None, tags: list[str] | None = None, risk_tier: int | None = None) -> Any:
        """Ranked policy recommendations."""
        return self._c("POST", "/policies/recommend", json=_clean({"agent_id": agent_id, "tags": tags or [], "risk_tier": risk_tier}))

    def enforce(self, text: str, phase: str = "input", agent_id: str | None = None, external_id: str | None = None,
                query: str | None = None, tool_name: str | None = None, correlation_id: str | None = None,
                source: str = "runtime") -> Any:
        """Enforce an agent's attached policies on one message."""
        return self._c("POST", "/enforce", json=_clean({"agent_id": agent_id, "external_id": external_id, "phase": phase,
                                                       "text": text, "query": query, "tool_name": tool_name,
                                                       "correlation_id": correlation_id, "source": source}))

    def metric(self, name: str, text: str, **params: Any) -> Any:
        """Stand-alone metric (pii, prompt_manipulation, toxicity, secrets, denylist, adherence)."""
        top = {k: params.pop(k) for k in ("query", "policy", "categories", "blocklist") if k in params}
        return self._c("POST", f"/metrics/{name}", json=_clean({"text": text, "params": params, **top}))


class _Evaluations:
    """Red-team evaluations."""

    def __init__(self, call: Call):
        self._c = call

    def create(self, agent_id: str | None = None, external_id: str | None = None, *, source: str = "generate",
               custom_prompts: list[dict[str, Any]] | None = None, num_generate: int = 40, benign_ratio: float = 0.3,
               categories: list[str] | None = None, from_evaluation_id: str | None = None,
               endpoint: str | None = None, policy_ids: list[str] | None = None, trust_threshold: float = 95.0) -> Any:
        """Queue an evaluation."""
        prompts = _clean({"source": source, "custom_prompts": custom_prompts or [], "num_generate": num_generate,
                          "benign_ratio": benign_ratio, "categories": categories or [],
                          "from_evaluation_id": from_evaluation_id})
        return self._c("POST", "/evaluations", json=_clean({
            "agent_id": agent_id, "external_id": external_id, "prompts": prompts, "endpoint": endpoint,
            "policy_ids": policy_ids or [], "trust_threshold": trust_threshold}))

    def get(self, evaluation_id: str, include_iterations: bool = False) -> Any:
        """Status and results."""
        return self._c("GET", f"/evaluations/{evaluation_id}", params={"include_iterations": include_iterations})

    def list(self, agent_id: str | None = None, limit: int = 50) -> Any:
        """Evaluations."""
        return self._c("GET", "/evaluations", params=_clean({"agent_id": agent_id, "limit": limit}))

    def cancel(self, evaluation_id: str) -> Any:
        """Cancel."""
        return self._c("POST", f"/evaluations/{evaluation_id}/cancel")


class _Gateway:
    """AI-gateway control."""

    def __init__(self, call: Call):
        self._c = call

    def models(self) -> Any:
        """Served models."""
        return self._c("GET", "/gateway/models")

    def gate(self, agent_id: str, allow_conditional: bool = False) -> Any:
        """Dry-run the deployment gate."""
        return self._c("GET", f"/agents/{agent_id}/gateway/gate", params={"allow_conditional": allow_conditional})

    def deploy(self, agent_id: str, model: str | None = None, allowed_models: list[str] | None = None,
               allow_conditional: bool = False) -> Any:
        """Deploy behind the gateway; the returned api_key is shown only once."""
        return self._c("POST", f"/agents/{agent_id}/gateway", json=_clean({
            "model": model, "allowed_models": allowed_models or [], "allow_conditional": allow_conditional}))

    def revoke(self, agent_id: str) -> Any:
        """Revoke the agent's gateway key."""
        return self._c("DELETE", f"/agents/{agent_id}/gateway")


class _Base:
    """Resources shared by both clients."""

    def _bind(self, call: Call) -> None:
        self.agents = _Agents(call)
        self.risk = _Risk(call)
        self.guardrails = _Guardrails(call)
        self.evaluations = _Evaluations(call)
        self.gateway = _Gateway(call)

    def _events_args(self, agent_id: str | None, event_type: str | None, limit: int) -> dict[str, Any]:
        return _clean({"agent_id": agent_id, "event_type": event_type, "limit": limit})


class GovernClient(_Base):
    """Synchronous governance client."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 30.0,
                 retries: int = 3, transport: httpx.BaseTransport | None = None):
        url, key = _settings(base_url, api_key)
        self._http = httpx.Client(base_url=url + "/api/v1", headers=_headers(key), timeout=timeout, transport=transport)
        self._retries = retries
        self._bind(self._call)

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        """HTTP call with exponential back-off on transient failures."""
        for attempt in range(self._retries + 1):
            try:
                resp = self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                if attempt >= self._retries or not _retryable(method, path):
                    raise TrustAIConnectionError(f"{type(exc).__name__}: {exc}", method, path) from exc
            else:
                if resp.status_code not in RETRY_STATUSES or attempt >= self._retries or not _retryable(method, path):
                    return _parse(resp, method, path)
            time.sleep(min(8.0, 0.5 * 2 ** attempt))
        raise AssertionError("unreachable")

    def wait(self, evaluation_id: str, timeout: float = 900.0, interval: float = 5.0) -> Any:
        """Poll an evaluation until it finishes (TimeoutError after `timeout` seconds)."""
        deadline = time.monotonic() + timeout
        while True:
            ev = self.evaluations.get(evaluation_id)
            if ev["status"] in TERMINAL:
                return ev
            if time.monotonic() > deadline:
                raise TimeoutError(f"evaluation {evaluation_id} still {ev['status']} after {timeout}s")
            time.sleep(interval)

    def run_evaluation(self, timeout: float = 900.0, **create_args: Any) -> Any:
        """Create an evaluation and wait for it."""
        return self.wait(self.evaluations.create(**create_args)["id"], timeout=timeout)

    def events(self, agent_id: str | None = None, event_type: str | None = None, limit: int = 100) -> Any:
        """Governance event feed."""
        return self._call("GET", "/events", params=self._events_args(agent_id, event_type, limit))

    def overview(self) -> Any:
        """Governance KPIs."""
        return self._call("GET", "/overview")

    def close(self) -> None:
        """Close the connection pool."""
        self._http.close()

    def __enter__(self) -> GovernClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncGovernClient(_Base):
    """Asynchronous governance client (every resource method returns an awaitable)."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 30.0,
                 retries: int = 3, transport: httpx.AsyncBaseTransport | None = None):
        url, key = _settings(base_url, api_key)
        self._http = httpx.AsyncClient(base_url=url + "/api/v1", headers=_headers(key), timeout=timeout,
                                       transport=transport)
        self._retries = retries
        self._bind(self._call)

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        """HTTP call with exponential back-off on transient failures."""
        for attempt in range(self._retries + 1):
            try:
                resp = await self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                if attempt >= self._retries or not _retryable(method, path):
                    raise TrustAIConnectionError(f"{type(exc).__name__}: {exc}", method, path) from exc
            else:
                if resp.status_code not in RETRY_STATUSES or attempt >= self._retries or not _retryable(method, path):
                    return _parse(resp, method, path)
            await asyncio.sleep(min(8.0, 0.5 * 2 ** attempt))
        raise AssertionError("unreachable")

    async def wait(self, evaluation_id: str, timeout: float = 900.0, interval: float = 5.0) -> Any:
        """Poll an evaluation until it finishes."""
        deadline = time.monotonic() + timeout
        while True:
            ev = await self.evaluations.get(evaluation_id)
            if ev["status"] in TERMINAL:
                return ev
            if time.monotonic() > deadline:
                raise TimeoutError(f"evaluation {evaluation_id} still {ev['status']} after {timeout}s")
            await asyncio.sleep(interval)

    async def run_evaluation(self, timeout: float = 900.0, **create_args: Any) -> Any:
        """Create an evaluation and wait for it."""
        created = await self.evaluations.create(**create_args)
        return await self.wait(created["id"], timeout=timeout)

    async def events(self, agent_id: str | None = None, event_type: str | None = None, limit: int = 100) -> Any:
        """Governance event feed."""
        return await self._call("GET", "/events", params=self._events_args(agent_id, event_type, limit))

    async def overview(self) -> Any:
        """Governance KPIs."""
        return await self._call("GET", "/overview")

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self._http.aclose()

    async def __aenter__(self) -> AsyncGovernClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
