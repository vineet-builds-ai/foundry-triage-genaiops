"""The output contract for a triage decision.

This is deliberately strict. A triage decision feeds an automated routing
system downstream, so a malformed decision is an incident, not a nuisance.
Schema validity is therefore a gated metric with a zero-tolerance threshold.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

QUEUES: tuple[str, ...] = (
    "security-incident",
    "account-access",
    "billing",
    "technical-support",
    "feature-request",
    "triage-review",
)

PRIORITIES: tuple[str, ...] = ("P1", "P2", "P3", "P4")

CANONICAL_FIELDS: tuple[str, ...] = (
    "ticket_id",
    "queue",
    "priority",
    "category",
    "needs_human_review",
    "rationale",
)

# Queues that must never be reached by guesswork. Mis-routing one of these is
# the failure mode the acceptance gate exists to catch.
CRITICAL_QUEUES: frozenset[str] = frozenset({"security-incident"})


@dataclass
class ValidationResult:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.ok


def priority_distance(a: str, b: str) -> int:
    """How many priority levels apart two labels are. 99 if either is unknown."""
    try:
        return abs(PRIORITIES.index(a) - PRIORITIES.index(b))
    except ValueError:
        return 99


def validate_decision(raw: str | dict[str, Any]) -> ValidationResult:
    """Validate a raw model output against the triage output contract."""
    violations: list[str] = []

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return ValidationResult(False, ["empty output"])
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            return ValidationResult(False, [f"not valid JSON: {exc.msg}"])
    else:
        obj = raw

    if not isinstance(obj, dict):
        return ValidationResult(False, [f"expected a JSON object, got {type(obj).__name__}"])

    for name in CANONICAL_FIELDS:
        if name not in obj:
            violations.append(f"missing required field '{name}'")

    extra = set(obj) - set(CANONICAL_FIELDS)
    for name in sorted(extra):
        violations.append(f"unexpected field '{name}'")

    queue = obj.get("queue")
    if queue is not None and queue not in QUEUES:
        violations.append(f"queue '{queue}' is not in the taxonomy")

    priority = obj.get("priority")
    if priority is not None and priority not in PRIORITIES:
        violations.append(f"priority '{priority}' is not one of {'/'.join(PRIORITIES)}")

    review = obj.get("needs_human_review")
    if "needs_human_review" in obj and not isinstance(review, bool):
        violations.append("needs_human_review must be a boolean")

    rationale = obj.get("rationale")
    if "rationale" in obj and (not isinstance(rationale, str) or not rationale.strip()):
        violations.append("rationale must be a non-empty string")

    return ValidationResult(not violations, violations)
