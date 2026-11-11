import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for path in (REPO_ROOT, REPO_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest

from triage.manifest import load_manifest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def shipping_manifest():
    return load_manifest(REPO_ROOT / "agent" / "agent.yaml")


@pytest.fixture(scope="session")
def regressed_manifest():
    return load_manifest(REPO_ROOT / "agent" / "agent.regressed.yaml")


@pytest.fixture(scope="session")
def golden_tickets(repo_root):
    import json

    path = repo_root / "evals" / "datasets" / "tickets.golden.jsonl"
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
