"""Did the ticket get the right priority?

Reports the distance between predicted and expected priority as well as an
exact-match score, because being one level off is a different operational
problem from being three levels off.
"""
from __future__ import annotations

import json
from typing import Any

from triage.schema import priority_distance


class PriorityAccuracyEvaluator:
    def __call__(
        self, *, response: str = "", expected_priority: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        try:
            obj = json.loads(response)
            predicted = obj.get("priority", "") if isinstance(obj, dict) else ""
        except (json.JSONDecodeError, TypeError):
            predicted = ""

        predicted = predicted if isinstance(predicted, str) else ""
        expected = (expected_priority or "").strip()
        distance = priority_distance(predicted, expected)

        return {
            "score": 1.0 if (predicted and predicted == expected) else 0.0,
            "distance": float(distance),
            "predicted_priority": predicted or "<unparseable>",
        }
