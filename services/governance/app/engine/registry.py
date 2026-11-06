"""
services/governance/app/engine/registry.py
Evaluator registry and the two engine entry points:
  run_guardrail(spec, text, ctx)            -> all checks of one guardrail
  enforce(policies, guardrails, phase, ...) -> policy decision (allowed / blocked_by) for one phase
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.engine.base import CheckResult, EvalContext, Evaluator
from app.engine.detectors import (
    AdherenceEvaluator,
    DenylistEvaluator,
    PromptManipulationEvaluator,
    SecretsEvaluator,
    ToolPermissionEvaluator,
    ToxicityEvaluator,
)
from app.engine.pii import PiiEvaluator

EVALUATORS: dict[str, Evaluator] = {e.type: e for e in (
    PiiEvaluator(), PromptManipulationEvaluator(), ToxicityEvaluator(), SecretsEvaluator(),
    DenylistEvaluator(), ToolPermissionEvaluator(), AdherenceEvaluator(),
)}

EVALUATOR_CATALOG: list[dict[str, Any]] = [
    {"type": "prompt_manipulation", "name": "Prompt manipulation",
     "description": "Prompt injection, jailbreak / role-play, system-prompt extraction, approval bypass, obfuscated payloads.",
     "default_threshold": 50, "backends": ["builtin", "azure_prompt_shields", "judge"]},
    {"type": "pii", "name": "PII detection",
     "description": "Email, phone, card (Luhn), IBAN (mod-97), SSN, PAN, Aadhaar, IP, passport; Presidio when installed.",
     "default_threshold": 50, "params": ["categories", "blocklist"], "backends": ["builtin", "presidio"]},
    {"type": "toxicity", "name": "Toxicity",
     "description": "Hate, harassment, violence, self-harm and sexual content.",
     "default_threshold": 50, "backends": ["builtin", "azure_content_safety", "judge"]},
    {"type": "secrets", "name": "Secret leakage",
     "description": "Cloud keys, API tokens, JWTs, private keys and connection strings.", "default_threshold": 50,
     "backends": ["builtin"]},
    {"type": "denylist", "name": "Deny list", "description": "Forbidden terms and regular expressions.",
     "default_threshold": 50, "params": ["terms", "patterns"], "backends": ["builtin"]},
    {"type": "tool_permission", "name": "Tool permission",
     "description": "Tool calls checked against the agent's registered tool policies (deny / approval / allow-only).",
     "default_threshold": 50, "params": ["deny", "require_approval", "allow_only", "block_approval_required"],
     "backends": ["builtin"]},
    {"type": "adherence", "name": "Policy adherence",
     "description": "LLM-judge check that a response follows a natural-language policy.", "default_threshold": 50,
     "params": ["policy", "fail_closed"], "backends": ["judge"]},
]


@dataclass
class GuardrailOutcome:
    """Result of running one guardrail."""

    passed: bool
    checks: list[CheckResult]
    latency_ms: int

    @property
    def failed_checks(self) -> list[str]:
        """Names of the checks that failed."""
        return [c.check for c in self.checks if not c.passed]

    @property
    def scores(self) -> dict[str, float]:
        """check -> score."""
        return {c.check: round(c.score, 2) for c in self.checks}

    def results(self) -> dict[str, Any]:
        """check -> full result (the shape the runtime guard and SDK read)."""
        return {c.check: c.to_dict() for c in self.checks}


async def _run_check(spec: dict[str, Any], text: str, ctx: EvalContext) -> CheckResult:
    """Run one evaluator spec; unknown types and evaluator crashes are reported, never raised."""
    etype = str(spec.get("type"))
    evaluator = EVALUATORS.get(etype)
    params = {k: v for k, v in spec.items() if k != "type"}
    if evaluator is None:
        return CheckResult(etype, True, 0.0, float(params.get("threshold", 50)), None,
                           {"error": "unknown evaluator"}, status="error")
    try:
        result = await evaluator.evaluate(text, ctx, params)
    except Exception as exc:  # noqa: BLE001 - defensive: evaluators should not raise
        result = CheckResult(etype, not params.get("fail_closed", False), 0.0,
                             float(params.get("threshold", evaluator.default_threshold)), None,
                             {"error": type(exc).__name__}, status="error")
    if result.status == "error" and params.get("fail_closed"):
        result.passed = False
    return result


async def run_guardrail(evaluators: list[dict[str, Any]], text: str, ctx: EvalContext | None = None) -> GuardrailOutcome:
    """Run every evaluator of a guardrail concurrently."""
    ctx = ctx or EvalContext()
    started = time.monotonic()
    checks = await asyncio.gather(*(_run_check(spec, text, ctx) for spec in evaluators))
    return GuardrailOutcome(passed=all(c.passed for c in checks), checks=list(checks),
                            latency_ms=round((time.monotonic() - started) * 1000))


def phase_matches(rule_phase: str, phase: str) -> bool:
    """`input` matches input; `tool` matches tool_call:* and tool_result:*; `any` matches every phase."""
    rule_phase = (rule_phase or "input").lower()
    phase = (phase or "input").lower()
    if rule_phase in ("any", "*"):
        return True
    if rule_phase == "tool":
        return phase.startswith("tool")
    return phase == rule_phase or phase.split(":", 1)[0] == rule_phase


@dataclass
class PolicyDecision:
    """Decision for one phase across all attached policies."""

    allowed: bool
    blocked_by: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)  # per guardrail run
    latency_ms: int = 0


async def enforce(policies: list[dict[str, Any]], guardrails: dict[str, dict[str, Any]], phase: str, text: str,
                  ctx: EvalContext) -> PolicyDecision:
    """
    Evaluate every policy rule that applies to `phase`. A failing rule blocks when its severity is at or above the
    policy's fail_on_severity_level. Each guardrail runs at most once per call even if several policies use it.
    """
    started = time.monotonic()
    wanted: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for policy in policies:
        for rule in policy.get("rules") or []:
            gid = str(rule.get("guardrail_id"))
            if gid in guardrails and phase_matches(str(rule.get("phase")), phase):
                wanted.setdefault(gid, []).append((policy, rule))
    outcomes = dict(zip(wanted, await asyncio.gather(
        *(run_guardrail(guardrails[gid]["evaluators"], text, ctx) for gid in wanted)), strict=True))
    decision = PolicyDecision(allowed=True)
    for gid, outcome in outcomes.items():
        decision.evaluations.append({"guardrail_id": gid, "guardrail_name": guardrails[gid].get("name"),
                                     "passed": outcome.passed, "failed_checks": outcome.failed_checks,
                                     "scores": outcome.scores, "results": outcome.results(),
                                     "latency_ms": outcome.latency_ms})
        if outcome.passed:
            continue
        for policy, rule in wanted[gid]:
            severity = int(rule.get("severity", 3))
            if severity >= int(policy.get("fail_on_severity_level", 1)):
                decision.allowed = False
                decision.blocked_by.append({"policy_id": str(policy.get("id")), "policy_name": policy.get("name"),
                                            "guardrail_id": gid, "guardrail_name": guardrails[gid].get("name"),
                                            "severity": severity, "failed_checks": outcome.failed_checks})
    decision.latency_ms = round((time.monotonic() - started) * 1000)
    return decision
