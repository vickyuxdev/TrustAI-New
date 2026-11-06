"""
services/governance/app/engine/base.py
Core types of the TrustAI guardrail engine.

Every evaluator scores a text from 0 (safe) to 100 (certain violation). A check fails when score >= threshold.
Evaluators never raise: a backend failure is reported as status "error" and handled by the guardrail's
`fail_closed` setting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class EvalContext:
    """Everything an evaluator may need besides the text itself."""

    phase: str = "input"  # input | output | tool_call:<name> | tool_result:<name>
    query: str | None = None  # the user request (for output-phase relevance/adherence checks)
    policy_text: str | None = None  # natural-language policy for adherence
    agent_tools: list[dict[str, Any]] = field(default_factory=list)  # [{name, side_effect, policy}]
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None


@dataclass
class CheckResult:
    """Outcome of one evaluator."""

    check: str
    passed: bool
    score: float
    threshold: float
    label: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    backend: str = "builtin"
    status: str = "ok"  # ok | unavailable | error

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form used in API responses and stored evaluations."""
        out = asdict(self)
        out["score"] = round(float(self.score), 2)
        return out


class Evaluator(Protocol):
    """Interface every guardrail check implements."""

    type: str
    default_threshold: float

    async def evaluate(self, text: str, ctx: EvalContext, params: dict[str, Any]) -> CheckResult:
        """Score `text`; must not raise."""
        ...


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp a score to the 0-100 range."""
    return max(low, min(high, value))
