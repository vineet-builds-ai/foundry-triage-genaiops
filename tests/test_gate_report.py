"""Tests for how the gate classifies failing rows."""
from evals.run_gate import failing_rows


def _row(ticket, expected, predicted, routing, contract=1.0, priority=1.0, critical=1.0):
    return {
        "inputs.ticket_id": ticket,
        "inputs.expected_queue": expected,
        "outputs.routing.predicted_queue": predicted,
        "outputs.routing.score": routing,
        "outputs.routing.is_critical": critical,
        "outputs.priority.score": priority,
        "outputs.contract.score": contract,
    }


def test_critical_row_routed_correctly_but_malformed_is_not_a_critical_miss():
    # Found against the real model: the regressed prompt drops a field, so every
    # row fails the contract, yet most security tickets still reach the right
    # queue. Those must not be reported as mis-routed.
    rows = failing_rows([_row("SEC-1", "security-incident", "security-incident", 1.0, contract=0.0)])
    assert len(rows) == 1
    assert rows[0]["is_critical"] is True
    assert rows[0]["critical_miss"] is False


def test_critical_row_sent_to_the_wrong_queue_is_a_critical_miss():
    rows = failing_rows([_row("SEC-2", "security-incident", "account-access", 0.0)])
    assert rows[0]["critical_miss"] is True


def test_non_critical_wrong_queue_is_not_a_critical_miss():
    rows = failing_rows([_row("BIL-1", "billing", "technical-support", 0.0, critical=0.0)])
    assert rows[0]["critical_miss"] is False
