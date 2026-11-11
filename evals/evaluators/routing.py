"""Did the ticket reach the right queue?

Also reports whether the row belongs to a critical queue and whether that
critical queue was reached, so the gate can compute per-queue recall rather
than hiding a security miss inside an overall average.
"""
from __future__ import annotations

import json
from typing import Any

from triage.schema import CRITICAL_QUEUES


def _predicted_queue(response: str) -> str:
    try:
        obj = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(obj, dict):
        return ""
    queue = obj.get("queue")
    return queue if isinstance(queue, str) else ""


class RoutingCorrectnessEvaluator:
    def __call__(
        self, *, response: str = "", expected_queue: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        predicted = _predicted_queue(response)
        expected = (expected_queue or "").strip()
        hit = bool(predicted) and predicted == expected
        is_critical = expected in CRITICAL_QUEUES

        return {
            "score": 1.0 if hit else 0.0,
            "predicted_queue": predicted or "<unparseable>",
            "is_critical": 1.0 if is_critical else 0.0,
            "critical_hit": 1.0 if (is_critical and hit) else 0.0,
        }
