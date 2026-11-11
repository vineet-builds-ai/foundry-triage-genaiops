import json

from evals.evaluators import (
    OutputContractEvaluator,
    PriorityAccuracyEvaluator,
    RoutingCorrectnessEvaluator,
)


def _response(**overrides):
    payload = {
        "ticket_id": "T-1",
        "queue": "billing",
        "priority": "P2",
        "category": "commercial",
        "needs_human_review": False,
        "rationale": "invoice mentioned",
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestRouting:
    evaluator = RoutingCorrectnessEvaluator()

    def test_scores_a_correct_route(self):
        result = self.evaluator(response=_response(), expected_queue="billing")
        assert result["score"] == 1.0
        assert result["predicted_queue"] == "billing"
        assert result["is_critical"] == 0.0

    def test_scores_a_wrong_route(self):
        result = self.evaluator(response=_response(), expected_queue="technical-support")
        assert result["score"] == 0.0

    def test_flags_a_critical_queue_hit(self):
        result = self.evaluator(
            response=_response(queue="security-incident"),
            expected_queue="security-incident",
        )
        assert result["is_critical"] == 1.0
        assert result["critical_hit"] == 1.0

    def test_flags_a_critical_queue_miss(self):
        result = self.evaluator(response=_response(), expected_queue="security-incident")
        assert result["is_critical"] == 1.0
        assert result["critical_hit"] == 0.0

    def test_unparseable_output_scores_zero_without_raising(self):
        result = self.evaluator(response="not json at all", expected_queue="billing")
        assert result["score"] == 0.0
        assert result["predicted_queue"] == "<unparseable>"


class TestPriority:
    evaluator = PriorityAccuracyEvaluator()

    def test_exact_match(self):
        result = self.evaluator(response=_response(), expected_priority="P2")
        assert result["score"] == 1.0
        assert result["distance"] == 0.0

    def test_reports_distance_when_wrong(self):
        result = self.evaluator(response=_response(priority="P4"), expected_priority="P2")
        assert result["score"] == 0.0
        assert result["distance"] == 2.0

    def test_unparseable_output(self):
        result = self.evaluator(response="{{{", expected_priority="P2")
        assert result["score"] == 0.0
        assert result["distance"] == 99.0


class TestOutputContract:
    evaluator = OutputContractEvaluator()

    def test_valid_output(self):
        result = self.evaluator(response=_response())
        assert result["score"] == 1.0
        assert result["violation_count"] == 0.0
        assert result["violations"] == "none"

    def test_missing_field_is_reported(self):
        payload = json.loads(_response())
        del payload["needs_human_review"]
        result = self.evaluator(response=json.dumps(payload))
        assert result["score"] == 0.0
        assert "needs_human_review" in result["violations"]
