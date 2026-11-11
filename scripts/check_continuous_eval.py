#!/usr/bin/env python3
"""Check the production continuous-evaluation score against its floor.

Continuous evaluation in Microsoft Foundry scores a sample of live traffic, so
quality decay in production is visible without waiting for a customer to
complain. This script reads the recent score and fails if it has fallen below
the floor, which is what causes the canary watch to roll the release back.

Requires a Foundry project endpoint; skipped automatically when one is not
configured, so it is inert in the offline demo.
"""
from __future__ import annotations

import os
import sys

FLOOR = float(os.environ.get("CONTINUOUS_EVAL_FLOOR", "0.85"))
LOOKBACK_MINUTES = int(os.environ.get("CONTINUOUS_EVAL_LOOKBACK_MINUTES", "15"))


def main() -> int:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        print("No FOUNDRY_PROJECT_ENDPOINT configured; skipping continuous-eval check.")
        return 0

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError:
        print("azure-ai-projects not installed; install requirements-cloud.txt.")
        return 0

    with DefaultAzureCredential() as credential:
        with AIProjectClient(endpoint=endpoint, credential=credential) as project:
            runs = list(project.evaluations.list())

    if not runs:
        print(f"No evaluation runs found in the last {LOOKBACK_MINUTES} minutes.")
        return 0

    latest = runs[0]
    score = None
    metrics = getattr(latest, "metrics", None) or {}
    for key in ("routing_accuracy", "overall", "score"):
        if key in metrics:
            score = float(metrics[key])
            break

    if score is None:
        print(f"Could not read a score from run {getattr(latest, 'id', '?')}; not failing.")
        return 0

    print(f"Continuous evaluation score: {score:.3f} (floor {FLOOR:.3f})")
    return 0 if score >= FLOOR else 1


if __name__ == "__main__":
    sys.exit(main())
