"""
trustai/govern/guard.py
Runtime guard for agents: enforce the agent's TrustAI policies on each phase of a turn.

    guard = Guard(GovernClient(), agent_id="...", mode="enforce")
    verdict = guard.check("input", user_message, session_id="s1")
    if verdict.blocked: return refusal

Modes: enforce (block on violation), log (record only), off. A circuit breaker opens after `max_failures`
consecutive errors for `cooldown_seconds`; while open (or on any error) the guard returns an `error` verdict and
`fail_closed` decides whether that blocks. A guard failure never raises into the agent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from trustai.govern.client import GovernClient

MODES = ("enforce", "log", "off")


@dataclass
class GuardVerdict:
    """Outcome of one guard check."""

    phase: str
    allowed: bool
    blocked: bool
    failed_checks: list[str] = field(default_factory=list)
    policies: list[str] = field(default_factory=list)
    guardrail_eval_ids: list[str] = field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None
    mode: str = "enforce"

    def to_dict(self) -> dict[str, Any]:
        """Audit-log friendly form."""
        return {"phase": self.phase, "passed": self.allowed, "blocked": self.blocked, "failed_checks": self.failed_checks,
                "policies": self.policies, "guardrail_eval_ids": self.guardrail_eval_ids, "latency_ms": self.latency_ms,
                "error": self.error, "mode": self.mode}


class Guard:
    """Synchronous policy guard with a circuit breaker."""

    def __init__(self, client: GovernClient, agent_id: str, mode: str = "enforce", fail_closed: bool = False,
                 max_failures: int = 3, cooldown_seconds: float = 60.0):
        self.client, self.agent_id = client, agent_id
        self.mode = mode if mode in MODES else "enforce"
        self.fail_closed, self.max_failures, self.cooldown = fail_closed, max_failures, cooldown_seconds
        self._failures, self._open_until = 0, 0.0

    def check(self, phase: str, text: str, session_id: str | None = None, query: str | None = None,
              tool_name: str | None = None) -> GuardVerdict | None:
        """Evaluate one phase; None when the guard is off or the text is empty."""
        if self.mode == "off" or not (text or "").strip():
            return None
        started = time.monotonic()
        if time.monotonic() < self._open_until:
            return self._error(phase, "circuit open", started)
        try:
            d = self.client.guardrails.enforce(text, phase=phase, agent_id=self.agent_id, query=query, tool_name=tool_name,
                                               correlation_id=f"{session_id}:{phase}" if session_id else None)
        except Exception as exc:  # noqa: BLE001 - never break the agent's turn
            self._failures += 1
            if self._failures >= self.max_failures:
                self._open_until = time.monotonic() + self.cooldown
            return self._error(phase, f"{type(exc).__name__}: {str(exc)[:200]}", started)
        self._failures = 0
        allowed = bool(d.get("allowed"))
        blocked_by = d.get("blocked_by") or []
        return GuardVerdict(phase=phase, allowed=allowed, blocked=not allowed and self.mode == "enforce",
                            failed_checks=sorted({c for b in blocked_by for c in b.get("failed_checks", [])}),
                            policies=sorted({b.get("policy_name", "") for b in blocked_by}),
                            guardrail_eval_ids=[str(i) for i in d.get("guardrail_eval_ids", [])],
                            latency_ms=round((time.monotonic() - started) * 1000), mode=self.mode)

    def _error(self, phase: str, message: str, started: float) -> GuardVerdict:
        """Verdict when TrustAI could not decide."""
        block = self.fail_closed and self.mode == "enforce"
        return GuardVerdict(phase=phase, allowed=not block, blocked=block, error=message,
                            latency_ms=round((time.monotonic() - started) * 1000), mode=self.mode)
