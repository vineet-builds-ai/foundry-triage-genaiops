#!/usr/bin/env python3
"""Smoke test a deployed triage API.

Runs immediately after every deployment. It answers three questions, cheapest
first, and fails the deployment if any answer is wrong:

  1. Is it up?                 GET /healthz returns 200.
  2. Is it the right version?  GET /version reports the release id of the
                               manifest being promoted. This is the check that
                               catches "deployed, but the old image is still
                               serving" -- a stale revision, a cached tag, a
                               traffic split pointing the wrong way.
  3. Does it work end to end?  A few unambiguous tickets go through the real
                               model and come back valid and correctly routed.

This is not the evaluation gate. It is three tickets, not forty-nine, and it
proves the deployment is wired correctly, not that the agent is good enough.

    python scripts/smoke_test.py --url https://<fqdn> --manifest agent/agent.yaml

Standard library only, so it runs on a bare CI runner.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Clear-cut tickets only. A smoke test that can fail on a judgement call is a
# flaky smoke test, and flaky smoke tests get ignored.
CASES = [
    {
        "ticket_id": "SMOKE-SEC",
        "text": "We received a phishing email impersonating your login page and two staff entered their passwords.",
        "queue": "security-incident",
        "priority": "P1",
    },
    {
        "ticket_id": "SMOKE-BIL",
        "text": "We were charged twice on this month's invoice. Please refund the duplicate payment.",
        "queue": "billing",
        "priority": None,
    },
    {
        "ticket_id": "SMOKE-OUT",
        "text": "Total outage: the service is down for all users, nothing loads since 09:00.",
        "queue": "technical-support",
        "priority": "P1",
    },
]


def _request(url: str, payload: dict | None = None, timeout: float = 60.0):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # Header names are case-insensitive; normalise so lookups cannot miss.
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status, headers, json.loads(resp.read() or b"{}")


def wait_until_healthy(base: str, wait_seconds: int) -> None:
    """Scale-to-zero environments and new revisions take a while to answer."""
    deadline = time.monotonic() + wait_seconds
    last = "no response"
    while time.monotonic() < deadline:
        try:
            status, _, _ = _request(f"{base}/healthz", timeout=30)
            if status == 200:
                return
            last = f"HTTP {status}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = str(exc)
        time.sleep(10)
    raise SystemExit(f"FAIL health: not healthy after {wait_seconds}s ({last})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="Base URL, e.g. https://app.region.azurecontainerapps.io")
    parser.add_argument("--manifest", default="agent/agent.yaml")
    parser.add_argument("--expect-release", default=None,
                        help="Release id that must be serving. Defaults to the manifest's.")
    parser.add_argument("--wait", type=int, default=300, help="Seconds to wait for health.")
    args = parser.parse_args(argv)

    base = args.url.rstrip("/")
    expected = args.expect_release
    if not expected:
        from triage.manifest import load_manifest
        expected = load_manifest(args.manifest).release_id

    from triage.schema import validate_decision

    failures: list[str] = []

    wait_until_healthy(base, args.wait)
    print(f"PASS health        {base}/healthz")

    _, _, version = _request(f"{base}/version")
    serving = version.get("release_id")
    if serving == expected:
        print(f"PASS version       serving {serving} ({version.get('backend')}, {version.get('environment')})")
    else:
        failures.append(f"version: expected {expected}, serving {serving}")
        print(f"FAIL version       expected {expected}, serving {serving}")

    for case in CASES:
        try:
            status, headers, body = _request(
                f"{base}/triage", {"ticket_id": case["ticket_id"], "text": case["text"]}
            )
        except urllib.error.HTTPError as exc:
            failures.append(f"{case['ticket_id']}: HTTP {exc.code}")
            print(f"FAIL {case['ticket_id']:<13} HTTP {exc.code}")
            continue

        problems = []
        if not validate_decision(body).ok:
            problems.append("invalid decision")
        if headers.get("x-triage-fallback"):
            problems.append("model output broke the contract (fail-safe used)")
        if body.get("queue") != case["queue"]:
            problems.append(f"queue {body.get('queue')} != {case['queue']}")
        if case["priority"] and body.get("priority") != case["priority"]:
            problems.append(f"priority {body.get('priority')} != {case['priority']}")

        detail = f"{body.get('queue')}/{body.get('priority')} in {headers.get('x-latency-ms', '?')} ms"
        if problems:
            failures.append(f"{case['ticket_id']}: {'; '.join(problems)}")
            print(f"FAIL {case['ticket_id']:<13} {detail}: {'; '.join(problems)}")
        else:
            print(f"PASS {case['ticket_id']:<13} {detail}")

    if failures:
        print(f"\nSMOKE TEST FAILED ({len(failures)} problem(s)).")
        return 1
    print("\nSMOKE TEST PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
