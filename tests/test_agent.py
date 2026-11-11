"""Behaviour tests on the agent, including the regression the gate must catch."""
import json

from triage.agent import TriageAgent
from triage.backends import LocalPolicyBackend
from triage.schema import validate_decision


def _agent(manifest):
    return TriageAgent(manifest, backend=LocalPolicyBackend())


def _decide(manifest, text, ticket_id="T-1"):
    return json.loads(_agent(manifest).triage(ticket_id, text))


def test_security_ticket_reaches_the_security_queue(shipping_manifest):
    decision = _decide(shipping_manifest, "I think this is a phishing attempt.")
    assert decision["queue"] == "security-incident"
    assert decision["priority"] == "P1"


def test_security_wins_over_a_competing_keyword(shipping_manifest):
    # Mentions billing, but it is a phishing report. Rule order decides, and
    # the security rule is deliberately first.
    decision = _decide(
        shipping_manifest,
        "An email from your billing team asked for card details. Phishing?",
    )
    assert decision["queue"] == "security-incident"


def test_unmatched_ticket_defers_to_human_triage(shipping_manifest):
    decision = _decide(shipping_manifest, "Following up on our call yesterday.")
    assert decision["queue"] == "triage-review"
    assert decision["needs_human_review"] is True


def test_output_satisfies_the_contract(shipping_manifest, golden_tickets):
    agent = _agent(shipping_manifest)
    for ticket in golden_tickets:
        raw = agent.triage(ticket["ticket_id"], ticket["text"])
        result = validate_decision(raw)
        assert result.ok, f"{ticket['ticket_id']}: {result.violations}"


def test_decisions_are_deterministic(shipping_manifest):
    agent = _agent(shipping_manifest)
    first = agent.triage("T-1", "Invoice is wrong")
    for _ in range(5):
        assert agent.triage("T-1", "Invoice is wrong") == first


def test_ticket_id_is_echoed_back(shipping_manifest):
    assert _decide(shipping_manifest, "Invoice is wrong", "ABC-99")["ticket_id"] == "ABC-99"


# --- The regression. These tests encode what the gate exists to catch. ---

def test_regressed_version_misroutes_security_tickets(regressed_manifest):
    decision = _decide(regressed_manifest, "I think this is a phishing attempt.")
    assert decision["queue"] != "security-incident"


def test_regressed_version_breaks_the_output_contract(regressed_manifest):
    raw = _agent(regressed_manifest).triage("T-1", "Invoice is wrong")
    result = validate_decision(raw)
    assert not result.ok
    assert any("needs_human_review" in v for v in result.violations)


def test_regressed_version_guesses_instead_of_deferring(regressed_manifest):
    decision = _decide(regressed_manifest, "Following up on our call yesterday.")
    assert decision["queue"] != "triage-review"


def test_regression_is_measurable_across_the_golden_set(
    shipping_manifest, regressed_manifest, golden_tickets
):
    """The shipping version routes every security ticket; the regressed one does not."""
    security = [t for t in golden_tickets if t["expected_queue"] == "security-incident"]
    assert security, "the golden set must contain security tickets"

    def hits(manifest):
        agent = _agent(manifest)
        return sum(
            1
            for t in security
            if json.loads(agent.triage(t["ticket_id"], t["text"])).get("queue")
            == "security-incident"
        )

    assert hits(shipping_manifest) == len(security)
    assert hits(regressed_manifest) == 0
