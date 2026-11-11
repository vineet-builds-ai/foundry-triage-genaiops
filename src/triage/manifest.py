"""The agent manifest: the unit that gets promoted.

A release is a manifest version, not a container tag and not a branch. The
manifest pins the prompt file, the model deployment, decoding parameters and
the tool surface, so "promote version 3 to acceptance" names something exact
and "roll back to version 2" is a pointer change rather than a rebuild.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .prompt_rules import PromptSpec, parse_prompt


@dataclass
class AgentManifest:
    path: Path
    name: str
    version: int
    description: str
    prompt_path: Path
    prompt: PromptSpec
    model_deployment: str
    model_api_version: str
    model_temperature: float
    model_max_output_tokens: int
    tools: list[str]
    dataset: str
    raw: dict[str, Any]

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.raw.encode("utf-8")).hexdigest()

    @property
    def release_id(self) -> str:
        """Stable identifier for this exact agent version."""
        return f"{self.name}-v{self.version}-{self.prompt_sha256[:12]}"


def load_manifest(path: str | Path) -> AgentManifest:
    manifest_path = Path(path).resolve()
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

    prompt_rel = (data.get("prompt") or {}).get("file")
    if not prompt_rel:
        raise ValueError(f"{manifest_path}: prompt.file is required")
    prompt_path = (manifest_path.parent / prompt_rel).resolve()
    if not prompt_path.is_file():
        raise FileNotFoundError(f"{manifest_path}: prompt file not found at {prompt_path}")

    model = data.get("model") or {}
    evaluation = data.get("evaluation") or {}

    return AgentManifest(
        path=manifest_path,
        name=data.get("name", "unnamed-agent"),
        version=int(data.get("version", 0)),
        description=data.get("description", ""),
        prompt_path=prompt_path,
        prompt=parse_prompt(prompt_path.read_text(encoding="utf-8")),
        model_deployment=model.get("deployment", "gpt-4o-mini"),
        model_api_version=model.get("api_version", "2025-04-01-preview"),
        model_temperature=float(model.get("temperature", 0.0)),
        model_max_output_tokens=int(model.get("max_output_tokens", 500)),
        tools=list(data.get("tools") or []),
        dataset=evaluation.get("dataset", "evals/datasets/tickets.golden.jsonl"),
        raw=data,
    )
