"""Tests for the production-feedback harvester."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "harvest_feedback.py"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_corrections_become_reviewable_candidates(tmp_path):
    corrections = tmp_path / "corrections.jsonl"
    _write(corrections, [
        {"ticket_id": "1", "text": "Someone logged in from Brazil and changed our admin email.",
         "predicted_queue": "account-access", "predicted_priority": "P2",
         "corrected_queue": "security-incident", "corrected_priority": "P1", "corrected_by": "lead"},
        {"ticket_id": "2", "text": "Please add dark mode.",
         "predicted_queue": "feature-request", "predicted_priority": "P4",
         "corrected_queue": "feature-request", "corrected_priority": "P4"},  # not a correction
        {"ticket_id": "3", "text": "Odd one", "corrected_queue": "nonsense", "corrected_priority": "P1"},
    ])
    out = tmp_path / "out" / "candidates.jsonl"
    result = _run(str(corrections), "--out", str(out))
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["expected_queue"] == "security-incident"
    assert rows[0]["review_status"] == "pending"


def test_refuses_to_write_real_tickets_into_the_repository(tmp_path):
    corrections = tmp_path / "corrections.jsonl"
    _write(corrections, [{"ticket_id": "1", "text": "x", "corrected_queue": "billing", "corrected_priority": "P2"}])
    inside_repo = SCRIPT.parent.parent / "evals" / "datasets" / "should-not-exist.jsonl"
    result = _run(str(corrections), "--out", str(inside_repo))
    assert result.returncode == 2
    assert not inside_repo.exists()
