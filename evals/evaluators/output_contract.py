"""Does the output satisfy the triage output contract?

A malformed decision breaks the downstream router, so this is gated at 1.0 in
every environment. It is also the cheapest signal there is: no model call and
no judge, just a schema check.
"""
from __future__ import annotations

from typing import Any

from triage.schema import validate_decision


class OutputContractEvaluator:
    def __call__(self, *, response: str = "", **kwargs: Any) -> dict[str, Any]:
        result = validate_decision(response)
        return {
            "score": 1.0 if result.ok else 0.0,
            "violation_count": float(len(result.violations)),
            "violations": "; ".join(result.violations) or "none",
        }
