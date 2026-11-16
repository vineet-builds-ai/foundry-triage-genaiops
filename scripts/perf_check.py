#!/usr/bin/env python3
"""Latency, error-rate and token budget check against a deployed triage API.

Runs in acceptance, after the evaluation gate. The gate answers "are the
answers good enough?"; this answers "is it fast and cheap enough to ship?".
A prompt change can pass the gate and still double the tokens per ticket, or
push p95 latency past what the support tooling tolerates.

Budgets are passed in, not hard-coded, so they live next to the other
promotion settings in the workflow and changing one is a reviewed diff.

Cost is reported as tokens, not money. Prices differ by region and agreement
(see docs/cost.md); tokens per ticket times ticket volume, priced with the
Azure pricing calculator, gives the real figure.

    python scripts/perf_check.py --url https://<fqdn> --requests 40 --concurrency 4

Standard library only, so it runs on a bare CI runner.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def _one(base: str, ticket: dict) -> dict:
    body = json.dumps({"ticket_id": ticket["ticket_id"], "text": ticket["text"]}).encode()
    req = urllib.request.Request(
        f"{base}/triage", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
            status = resp.status
            tokens = int(resp.headers.get("X-Tokens-Total") or 0)
            fallback = bool(resp.headers.get("X-Triage-Fallback"))
    except urllib.error.HTTPError as exc:
        status, tokens, fallback = exc.code, 0, False
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        status, tokens, fallback = 0, 0, False
    return {
        "status": status,
        "latency_ms": (time.perf_counter() - started) * 1000,
        "tokens": tokens,
        "fallback": fallback,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--dataset", default=str(REPO_ROOT / "evals" / "datasets" / "tickets.golden.jsonl"))
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--p95-budget-ms", type=float, default=4000)
    parser.add_argument("--max-error-rate", type=float, default=0.0, help="Percent of requests.")
    parser.add_argument("--max-fallback-rate", type=float, default=0.0, help="Percent of requests.")
    parser.add_argument("--tokens-budget", type=int, default=1500, help="Mean tokens per ticket.")
    parser.add_argument("--warmup", type=int, default=2, help="Requests sent and discarded first.")
    args = parser.parse_args(argv)

    base = args.url.rstrip("/")
    tickets = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    load = [tickets[i % len(tickets)] for i in range(args.requests)]

    for ticket in tickets[: args.warmup]:
        _one(base, ticket)  # cold start is the smoke test's concern, not this one's

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda t: _one(base, t), load))
    wall = time.perf_counter() - started

    ok = [r for r in results if r["status"] == 200]
    latencies = [r["latency_ms"] for r in ok]
    error_rate = 100 * (len(results) - len(ok)) / len(results)
    fallback_rate = 100 * sum(r["fallback"] for r in ok) / max(1, len(ok))
    tokens = [r["tokens"] for r in ok if r["tokens"]]
    mean_tokens = statistics.mean(tokens) if tokens else 0.0
    p50, p95 = _percentile(latencies, 50), _percentile(latencies, 95)

    checks = [
        ("p95 latency", f"{p95:.0f} ms", f"<= {args.p95_budget_ms:.0f} ms", p95 <= args.p95_budget_ms),
        ("error rate", f"{error_rate:.1f}%", f"<= {args.max_error_rate:.1f}%", error_rate <= args.max_error_rate),
        ("fail-safe rate", f"{fallback_rate:.1f}%", f"<= {args.max_fallback_rate:.1f}%", fallback_rate <= args.max_fallback_rate),
        ("tokens / ticket", f"{mean_tokens:.0f}", f"<= {args.tokens_budget}",
         (not tokens) or mean_tokens <= args.tokens_budget),
    ]

    print(f"{len(results)} requests, concurrency {args.concurrency}, {wall:.1f}s wall, "
          f"{len(results) / wall:.1f} req/s")
    print(f"latency p50 {p50:.0f} ms, p95 {p95:.0f} ms, max {max(latencies, default=0):.0f} ms")
    if tokens:
        print(f"tokens per ticket: mean {mean_tokens:.0f}  ->  {mean_tokens * 1000:,.0f} tokens per 1,000 tickets")
    else:
        print("tokens per ticket: not reported by this backend (offline policy backend uses none)")
    print()
    for name, actual, budget, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name:<16} {actual:>10}   budget {budget}")

    passed = all(c[3] for c in checks)
    print("\nPERFORMANCE CHECK " + ("PASSED." if passed else "FAILED."))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
