#!/usr/bin/env python3
"""Pre-merge checks on the agent manifest.

These catch the configuration mistakes that are cheap to make and expensive to
discover in production: an unpinned model version, a prompt whose output
contract has drifted from the code's schema, a tool quietly added to a
classifier that is supposed to have none.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from triage.manifest import load_manifest  # noqa: E402
from triage.schema import CANONICAL_FIELDS, QUEUES  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_manifest.py <path-to-agent.yaml>", file=sys.stderr)
        return 2

    manifest = load_manifest(argv[1])
    problems: list[str] = []

    print(f"manifest        : {manifest.path.name}")
    print(f"agent           : {manifest.name} v{manifest.version}")
    print(f"release id      : {manifest.release_id}")
    print(f"prompt          : {manifest.prompt_path.name} (v{manifest.prompt.version})")
    print(f"prompt sha256   : {manifest.prompt_sha256}")
    print(f"model           : {manifest.model_deployment}")
    print(f"routing rules   : {len(manifest.prompt.rules)}")
    print(f"fallback policy : {'declared' if manifest.prompt.fallback else 'ABSENT'}")
    print(f"tools           : {manifest.tools or 'none'}")
    print()

    if manifest.version != manifest.prompt.version:
        problems.append(
            f"manifest version ({manifest.version}) does not match prompt version "
            f"({manifest.prompt.version}); a promotion artefact must be unambiguous"
        )

    if manifest.model_temperature != 0.0:
        problems.append(
            f"temperature is {manifest.model_temperature}; a classifier should be "
            "deterministic, and a non-zero temperature makes the gate flaky"
        )

    if manifest.tools:
        problems.append(
            f"tools declared ({manifest.tools}); triage is a pure classification "
            "step and the empty tool surface is a deliberate security property"
        )

    # The prompt's output contract and the code's schema must agree, or the
    # agent will emit output the downstream router rejects.
    declared = set(manifest.prompt.required_fields)
    if declared and declared != set(CANONICAL_FIELDS):
        missing = sorted(set(CANONICAL_FIELDS) - declared)
        extra = sorted(declared - set(CANONICAL_FIELDS))
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if extra:
            detail.append(f"unexpected {extra}")
        problems.append(
            "the prompt's output contract disagrees with the code schema: "
            + ", ".join(detail)
        )

    unknown_queues = sorted(manifest.prompt.declared_queues - set(QUEUES))
    if unknown_queues:
        problems.append(f"prompt routes to queues outside the taxonomy: {unknown_queues}")

    if manifest.prompt.fallback is None:
        problems.append(
            "no fallback policy declared; without one the agent guesses a "
            "destination for tickets that match no rule instead of deferring "
            "to human triage"
        )

    if problems:
        print(f"FAILED with {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("Manifest OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
