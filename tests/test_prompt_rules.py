from triage.prompt_rules import parse_prompt

PROMPT = """---
version: 7
---
FIELDS: ticket_id, queue

RULE: breach|phishing -> security-incident | P1
RULE: invoice -> billing | P2

FALLBACK: triage-review | P3 | needs_human_review=true
"""


def test_parses_version_fields_rules_and_fallback():
    spec = parse_prompt(PROMPT)
    assert spec.version == 7
    assert spec.required_fields == ("ticket_id", "queue")
    assert len(spec.rules) == 2
    assert spec.fallback is not None
    assert spec.fallback.queue == "triage-review"
    assert spec.fallback.needs_human_review is True


def test_rule_order_is_preserved():
    spec = parse_prompt(PROMPT)
    assert spec.rules[0].queue == "security-incident"


def test_rules_match_case_insensitively():
    spec = parse_prompt(PROMPT)
    assert spec.rules[0].matches("Possible PHISHING attempt") == "phishing"
    assert spec.rules[0].matches("nothing relevant here") is None


def test_absent_fallback_is_reported_as_none():
    spec = parse_prompt(PROMPT.replace("FALLBACK: triage-review | P3 | needs_human_review=true", ""))
    assert spec.fallback is None


def test_declared_queues_includes_the_fallback():
    spec = parse_prompt(PROMPT)
    assert spec.declared_queues == {"security-incident", "billing", "triage-review"}
