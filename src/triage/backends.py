"""Model backends.

Two implementations share one interface:

  LocalPolicyBackend   Executes the routing policy declared in the prompt file,
                       deterministically and with no network calls. This is what
                       CI and the offline demo use. It is not a model and does
                       not pretend to be one -- it is an interpreter for the
                       policy the prompt declares, which makes the evaluation
                       suite reproducible and free to run.

  FoundryBackend       Sends the same prompt file verbatim to a model deployed
                       in a Microsoft Foundry project. Selected automatically
                       when FOUNDRY_PROJECT_ENDPOINT is set.

Because both return the model's raw text, every evaluator, the output-contract
check and the gate all behave identically whichever backend produced the row.
"""
from __future__ import annotations

import json
import os
from typing import Any, Protocol

from .prompt_rules import PromptSpec
from .schema import CANONICAL_FIELDS

_CATEGORY_BY_QUEUE = {
    "security-incident": "security",
    "account-access": "identity",
    "billing": "commercial",
    "technical-support": "product",
    "feature-request": "product-feedback",
    "triage-review": "unclassified",
}


class ModelBackend(Protocol):
    name: str

    def decide(self, ticket_id: str, text: str, spec: PromptSpec) -> str:
        """Return the model's raw output for one ticket."""
        ...


class LocalPolicyBackend:
    """Deterministic interpreter of the prompt's declared routing policy."""

    name = "local-policy"

    def decide(self, ticket_id: str, text: str, spec: PromptSpec) -> str:
        queue: str
        priority: str
        needs_review: bool
        matched: str | None = None

        for rule in spec.rules:
            matched = rule.matches(text)
            if matched:
                queue, priority, needs_review = rule.queue, rule.priority, False
                break
        else:
            if spec.fallback is not None:
                queue = spec.fallback.queue
                priority = spec.fallback.priority
                needs_review = spec.fallback.needs_human_review
            else:
                # No fallback policy declared. A model given no instruction for
                # the unmatched case does not abstain -- it picks something
                # plausible and states it confidently. That is the behaviour
                # being reproduced here, and the reason a fallback policy is
                # a reviewable part of the prompt.
                queue = spec.rules[-1].queue if spec.rules else "technical-support"
                priority = "P3"
                needs_review = False

        decision: dict[str, Any] = {
            "ticket_id": ticket_id,
            "queue": queue,
            "priority": priority,
            "category": _CATEGORY_BY_QUEUE.get(queue, "unclassified"),
            "needs_human_review": needs_review,
            "rationale": (
                f"matched policy keyword '{matched}'"
                if matched
                else "no routing rule matched"
            ),
        }

        # Emit exactly the fields the prompt's output contract asks for. A
        # prompt that forgets to require a field gets output that omits it.
        fields = spec.required_fields or CANONICAL_FIELDS
        return json.dumps({k: decision[k] for k in fields if k in decision})


class FoundryBackend:
    """Calls a model deployment in a Microsoft Foundry project.

    Authenticates with the workload's managed identity (or the developer's
    Azure CLI login locally) via DefaultAzureCredential -- no API keys are
    read from configuration or stored in the repository.
    """

    name = "foundry"

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_version: str,
        temperature: float = 0.0,
        max_output_tokens: int = 500,
    ) -> None:
        self.endpoint = endpoint
        self.deployment = deployment
        self.api_version = api_version
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import AzureOpenAI

            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                "https://cognitiveservices.azure.com/.default",
            )
            self._client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
                azure_ad_token_provider=token_provider,
            )
        return self._client

    def decide(self, ticket_id: str, text: str, spec: PromptSpec) -> str:
        client = self._ensure_client()
        completion = client.chat.completions.create(
            model=self.deployment,
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": spec.raw},
                {
                    "role": "user",
                    "content": json.dumps({"ticket_id": ticket_id, "text": text}),
                },
            ],
        )
        return completion.choices[0].message.content or ""


def select_backend(manifest: Any) -> ModelBackend:
    """Pick a backend from the environment.

    Set FOUNDRY_PROJECT_ENDPOINT to run against a real deployment; leave it
    unset and everything runs offline.
    """
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        return LocalPolicyBackend()
    return FoundryBackend(
        endpoint=endpoint,
        deployment=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", manifest.model_deployment),
        api_version=manifest.model_api_version,
        temperature=manifest.model_temperature,
        max_output_tokens=manifest.model_max_output_tokens,
    )
