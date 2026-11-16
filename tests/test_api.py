"""Tests on the HTTP service, using the offline backend.

These pin down the behaviour the deployed service promises: it reports the
version it is serving, it routes correctly, it rejects bad input, and it fails
safe when the model's answer breaks the output contract.
"""
import pytest
from fastapi.testclient import TestClient

from triage.agent import TriageAgent
from triage.api import FALLBACK_REASON, create_app
from triage.backends import LocalPolicyBackend, account_endpoint
from triage.schema import validate_decision


@pytest.fixture()
def client(shipping_manifest):
    agent = TriageAgent(shipping_manifest, backend=LocalPolicyBackend())
    return TestClient(create_app(agent))


def test_health(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_version_reports_the_release_being_served(client, shipping_manifest):
    body = client.get("/version").json()
    assert body["release_id"] == shipping_manifest.release_id
    assert body["prompt_sha256"] == shipping_manifest.prompt_sha256
    assert body["backend"] == "local-policy"


def test_security_ticket_routes_to_security(client, shipping_manifest):
    resp = client.post("/triage", json={"ticket_id": "S-1", "text": "We received a phishing email."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == "security-incident"
    assert body["priority"] == "P1"
    assert validate_decision(body).ok
    assert resp.headers["X-Release-Id"] == shipping_manifest.release_id
    assert "X-Triage-Fallback" not in resp.headers


def test_ticket_id_in_response_is_the_one_sent(client):
    body = client.post("/triage", json={"ticket_id": "ABC-42", "text": "refund please"}).json()
    assert body["ticket_id"] == "ABC-42"


@pytest.mark.parametrize(
    "payload",
    [
        {"ticket_id": "", "text": "hello"},
        {"ticket_id": "T-1", "text": ""},
        {"ticket_id": "T-1"},
        {"ticket_id": "T-1", "text": "x" * 8001},
    ],
)
def test_bad_input_is_rejected(client, payload):
    assert client.post("/triage", json=payload).status_code == 422


class _BrokenModel:
    """A model that answers, but not in the contracted format."""

    name = "broken"

    def decide(self, ticket_id, text, spec):
        return "Sure! I'd route this to billing."


class _UnreachableModel:
    name = "unreachable"

    def decide(self, ticket_id, text, spec):
        raise TimeoutError("model did not answer")


def test_contract_violation_fails_safe_to_human_review(shipping_manifest):
    client = TestClient(create_app(TriageAgent(shipping_manifest, backend=_BrokenModel())))
    resp = client.post("/triage", json={"ticket_id": "T-9", "text": "refund please"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == "triage-review"
    assert body["needs_human_review"] is True
    assert body["rationale"] == FALLBACK_REASON
    assert resp.headers["X-Triage-Fallback"] == "contract-violation"


class RateLimitError(Exception):
    """Stands in for openai.RateLimitError, matched by name."""


class _ThrottledModel:
    name = "throttled"

    def decide(self, ticket_id, text, spec):
        raise RateLimitError("429 Too Many Requests")


def test_rate_limit_is_a_429_with_retry_after(shipping_manifest):
    client = TestClient(
        create_app(TriageAgent(shipping_manifest, backend=_ThrottledModel())),
        raise_server_exceptions=False,
    )
    resp = client.post("/triage", json={"ticket_id": "T-9", "text": "refund please"})
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "10"


def test_model_outage_is_a_503_not_a_fallback(shipping_manifest):
    client = TestClient(
        create_app(TriageAgent(shipping_manifest, backend=_UnreachableModel())),
        raise_server_exceptions=False,
    )
    resp = client.post("/triage", json={"ticket_id": "T-9", "text": "refund please"})
    assert resp.status_code == 503


@pytest.mark.parametrize(
    "given, expected",
    [
        ("https://acct.services.ai.azure.com/api/projects/p1",
         "https://acct.services.ai.azure.com/"),
        ("https://acct.services.ai.azure.com/api/projects/p1/",
         "https://acct.services.ai.azure.com/"),
        ("https://acct.openai.azure.com", "https://acct.openai.azure.com/"),
    ],
)
def test_project_endpoint_is_reduced_to_the_account_endpoint(given, expected):
    assert account_endpoint(given) == expected
