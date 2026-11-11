"""The triage agent."""
from __future__ import annotations

from typing import Iterable

from .backends import ModelBackend, select_backend
from .manifest import AgentManifest


class TriageAgent:
    def __init__(self, manifest: AgentManifest, backend: ModelBackend | None = None) -> None:
        self.manifest = manifest
        self.backend = backend or select_backend(manifest)

    @property
    def backend_name(self) -> str:
        return self.backend.name

    def triage(self, ticket_id: str, text: str) -> str:
        """Return the agent's raw output for one ticket."""
        return self.backend.decide(ticket_id, text, self.manifest.prompt)

    def batch(self, tickets: Iterable[dict]) -> list[dict]:
        """Triage many tickets, preserving each row's expected labels."""
        rows: list[dict] = []
        for ticket in tickets:
            ticket_id = ticket["ticket_id"]
            text = ticket["text"]
            rows.append(
                {
                    "ticket_id": ticket_id,
                    "query": text,
                    "response": self.triage(ticket_id, text),
                    "expected_queue": ticket.get("expected_queue", ""),
                    "expected_priority": ticket.get("expected_priority", ""),
                }
            )
        return rows
