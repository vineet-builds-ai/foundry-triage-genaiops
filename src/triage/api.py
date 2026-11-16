"""HTTP service for the triage agent.

This is what runs in Container Apps. The container image bakes in one agent
manifest and its prompt, so the image *is* the release: the same bytes that
passed the gate in acceptance are the bytes that serve production.

Endpoints:

  GET  /healthz   Liveness and readiness. No model call, so a slow model does
                  not get healthy replicas killed.
  GET  /version   The release id and prompt SHA-256 actually being served.
                  Smoke tests compare this with the commit being promoted, so
                  "which version is running?" is answered by evidence.
  POST /triage    Classify one ticket.

Two failure behaviours, deliberately different:

  * The model answered, but the answer breaks the output contract. The ticket
    is routed to human triage (fail safe) and the response is marked, so a
    malformed decision never reaches the downstream router.
  * The model could not be reached. The API returns 503, so the failure shows
    up in error-rate monitoring and the canary watch instead of being hidden
    behind a plausible-looking fallback.

Ticket text is never logged. Only the decision and its metadata are.
"""
from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from .agent import TriageAgent
from .backends import decide_with_usage
from .manifest import load_manifest
from .schema import validate_decision

log = logging.getLogger("triage.api")

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "agent" / "agent.yaml"

FALLBACK_REASON = "model output failed the output contract; routed to human triage"


class TicketIn(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=8000)


class Decision(BaseModel):
    ticket_id: str
    queue: str
    priority: str
    category: str
    needs_human_review: bool
    rationale: str


def _configure_telemetry() -> None:
    """Send traces to Application Insights when a connection string is set."""
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:  # pragma: no cover - optional in local runs
        log.warning("azure-monitor-opentelemetry not installed; telemetry disabled")
        return
    configure_azure_monitor(logger_name="triage")


@lru_cache(maxsize=1)
def _agent() -> TriageAgent:
    manifest_path = os.environ.get("TRIAGE_MANIFEST", str(DEFAULT_MANIFEST))
    return TriageAgent(load_manifest(manifest_path))


def fail_safe_decision(ticket_id: str) -> dict[str, Any]:
    return {
        "ticket_id": ticket_id,
        "queue": "triage-review",
        "priority": "P3",
        "category": "unclassified",
        "needs_human_review": True,
        "rationale": FALLBACK_REASON,
    }


def create_app(agent: TriageAgent | None = None) -> FastAPI:
    app = FastAPI(title="Ticket triage agent", version="1")

    def current_agent() -> TriageAgent:
        return agent or _agent()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        current_agent()  # proves the manifest and prompt loaded
        return {"status": "ok"}

    @app.get("/version")
    def version() -> dict[str, Any]:
        a = current_agent()
        m = a.manifest
        return {
            "release_id": m.release_id,
            "agent": m.name,
            "agent_version": m.version,
            "prompt_sha256": m.prompt_sha256,
            "model_deployment": os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", m.model_deployment),
            "backend": a.backend_name,
            "environment": os.environ.get("TRIAGE_ENVIRONMENT", "local"),
            "git_sha": os.environ.get("TRIAGE_GIT_SHA", "unknown"),
        }

    @app.post("/triage", response_model=Decision)
    def triage(ticket: TicketIn, response: Response) -> dict[str, Any]:
        a = current_agent()
        started = time.perf_counter()
        try:
            raw, usage = decide_with_usage(a.backend, ticket.ticket_id, ticket.text, a.manifest.prompt)
        except Exception as exc:  # noqa: BLE001 - any model failure is a 503
            log.error("model call failed", extra={"release_id": a.manifest.release_id,
                                                  "error_type": type(exc).__name__})
            raise HTTPException(status_code=503, detail="model unavailable") from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        result = validate_decision(raw)
        fallback = not result.ok
        if fallback:
            decision = fail_safe_decision(ticket.ticket_id)
        else:
            decision = json.loads(raw)
            decision["ticket_id"] = ticket.ticket_id

        response.headers["X-Release-Id"] = a.manifest.release_id
        response.headers["X-Latency-Ms"] = str(latency_ms)
        if usage.get("total_tokens"):
            response.headers["X-Tokens-Total"] = str(usage["total_tokens"])
        if fallback:
            response.headers["X-Triage-Fallback"] = "contract-violation"

        log.info(
            "triage decision",
            extra={
                "release_id": a.manifest.release_id,
                "queue": decision["queue"],
                "priority": decision["priority"],
                "needs_human_review": decision["needs_human_review"],
                "fallback": fallback,
                "contract_violations": "; ".join(result.violations) if fallback else "",
                "latency_ms": latency_ms,
                "total_tokens": usage.get("total_tokens", 0),
            },
        )
        return decision

    return app


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
_configure_telemetry()
app = create_app()
