"""
services/governance/app/engine/pii.py
PII detection. Uses Microsoft Presidio when it is installed; the built-in recognisers below always run and need no
network or model download. Card numbers are Luhn-checked and IBANs mod-97-checked to keep false positives low.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.engine.base import CheckResult, EvalContext


@dataclass(frozen=True)
class PiiEntity:
    """One PII finding (the value itself is masked before it leaves the engine)."""

    category: str
    start: int
    end: int
    masked: str


def _luhn_ok(digits: str) -> bool:
    """Luhn checksum for payment-card numbers."""
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _iban_ok(value: str) -> bool:
    """ISO 13616 mod-97 check."""
    s = value.replace(" ", "").upper()
    if len(s) < 15 or len(s) > 34:
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def _mask(value: str) -> str:
    """Keep the last 2 characters, mask the rest."""
    v = value.strip()
    return ("*" * max(0, len(v) - 2)) + v[-2:] if len(v) > 2 else "**"


_RECOGNISERS: list[tuple[str, re.Pattern[str], Any]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("credit_card", re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
     lambda m: _luhn_ok(re.sub(r"\D", "", m)) and 13 <= len(re.sub(r"\D", "", m)) <= 19),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b"), _iban_ok),
    ("us_ssn", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), None),
    ("in_pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), None),
    ("in_aadhaar", re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b"), None),
    ("phone", re.compile(r"(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\(\d{2,4}\)[ -]?)?\d{3,5}[ -]?\d{3,4}[ -]?\d{3,4}(?!\w)"),
     lambda m: 10 <= len(re.sub(r"\D", "", m)) <= 15),
    ("ip_address", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), None),
    ("passport", re.compile(r"\b(?:passport(?: no\.?| number)?[:# ]+)([A-Z][0-9]{7,8})\b", re.I), None),
]

ALL_CATEGORIES = tuple(name for name, _, _ in _RECOGNISERS)


def _presidio_entities(text: str) -> list[PiiEntity]:
    """Presidio findings when the optional package (and its NLP model) is available; otherwise nothing."""
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional dependency
        return []
    try:
        analyzer = _presidio_entities.__dict__.setdefault("_engine", AnalyzerEngine())
        results = analyzer.analyze(text=text, language="en")
    except Exception:  # noqa: BLE001 - model missing etc.
        return []
    return [PiiEntity(r.entity_type.lower(), r.start, r.end, _mask(text[r.start:r.end])) for r in results
            if r.score >= 0.6]


def find_pii(text: str, categories: list[str] | None = None, blocklist: list[str] | None = None) -> list[PiiEntity]:
    """All PII entities in `text`, optionally limited to `categories`, plus exact blocklist terms."""
    wanted = {c.lower() for c in categories} if categories else None
    found: list[PiiEntity] = []
    taken: list[tuple[int, int]] = []
    for name, pattern, validator in _RECOGNISERS:
        if wanted and name not in wanted:
            continue
        for m in pattern.finditer(text):
            value = m.group(0)
            if validator and not validator(value):
                continue
            span = (m.start(), m.end())
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue  # already covered by a more specific recogniser
            taken.append(span)
            found.append(PiiEntity(name, span[0], span[1], _mask(value)))
    for entity in _presidio_entities(text):
        if (not wanted or entity.category in wanted) and not any(
                s < entity.end and entity.start < e for s, e in taken):
            found.append(entity)
    for term in blocklist or []:
        if term and term.strip():
            for m in re.finditer(re.escape(term.strip()), text, re.I):
                found.append(PiiEntity("blocklist", m.start(), m.end(), _mask(m.group(0))))
    return sorted(found, key=lambda e: e.start)


def redact(text: str, entities: list[PiiEntity]) -> str:
    """Replace each entity with `[CATEGORY]`."""
    out, last = [], 0
    for e in sorted(entities, key=lambda x: x.start):
        if e.start < last:
            continue
        out.append(text[last:e.start])
        out.append(f"[{e.category.upper()}]")
        last = e.end
    out.append(text[last:])
    return "".join(out)


class PiiEvaluator:
    """Fails when the text contains PII from the configured categories (default: all)."""

    type = "pii"
    default_threshold = 50.0

    async def evaluate(self, text: str, ctx: EvalContext, params: dict[str, Any]) -> CheckResult:
        """Score 100 when any PII is found, else 0."""
        threshold = float(params.get("threshold", self.default_threshold))
        entities = find_pii(text, params.get("categories"), params.get("blocklist"))
        score = 100.0 if entities else 0.0
        return CheckResult(
            check=self.type, passed=score < threshold, score=score, threshold=threshold,
            label=",".join(sorted({e.category for e in entities})) or None,
            details={"entities": [{"category": e.category, "start": e.start, "end": e.end, "masked": e.masked}
                                  for e in entities]},
            backend="presidio+builtin" if _presidio_entities.__dict__.get("_engine") else "builtin",
        )
