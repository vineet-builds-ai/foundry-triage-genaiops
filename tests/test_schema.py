import json

import pytest

from triage.schema import CANONICAL_FIELDS, priority_distance, validate_decision


def _valid_payload(**overrides):
    payload = {
        "ticket_id": "T-1",
        "queue": "billing",
        "priority": "P2",
        "category": "commercial",
        "needs_human_review": False,
        "rationale": "mentions an invoice",
    }
    payload.update(overrides)
    return payload


def test_accepts_a_well_formed_decision():
    assert validate_decision(json.dumps(_valid_payload())).ok


def test_rejects_non_json():
    result = validate_decision("I think this is a billing issue.")
    assert not result.ok
    assert "not valid JSON" in result.violations[0]


def test_rejects_empty_output():
    assert not validate_decision("").ok


@pytest.mark.parametrize("field", CANONICAL_FIELDS)
def test_rejects_a_missing_required_field(field):
    payload = _valid_payload()
    del payload[field]
    result = validate_decision(json.dumps(payload))
    assert not result.ok
    assert any(field in v for v in result.violations)


def test_rejects_a_queue_outside_the_taxonomy():
    result = validate_decision(json.dumps(_valid_payload(queue="escalations")))
    assert not result.ok
    assert any("taxonomy" in v for v in result.violations)


def test_rejects_an_unknown_priority():
    assert not validate_decision(json.dumps(_valid_payload(priority="P0"))).ok


def test_rejects_a_non_boolean_review_flag():
    result = validate_decision(json.dumps(_valid_payload(needs_human_review="yes")))
    assert not result.ok
    assert any("boolean" in v for v in result.violations)


def test_rejects_an_empty_rationale():
    assert not validate_decision(json.dumps(_valid_payload(rationale="   "))).ok


def test_rejects_unexpected_fields():
    result = validate_decision(json.dumps(_valid_payload(confidence=0.9)))
    assert not result.ok
    assert any("confidence" in v for v in result.violations)


def test_priority_distance():
    assert priority_distance("P1", "P1") == 0
    assert priority_distance("P1", "P3") == 2
    assert priority_distance("P1", "nonsense") == 99
