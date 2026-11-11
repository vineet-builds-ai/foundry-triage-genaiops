"""Evaluation gate.

Runs the agent version named by a manifest over the golden set, scores it with
the Microsoft Foundry evaluation SDK, compares every metric against the
threshold file for the target environment, and exits non-zero if any bar is
missed.

This is the only thing standing between a commit and the next environment, so
it is built to be boring: deterministic evaluators, thresholds in version
control, a written report, and an audit record naming exactly which prompt
bytes were scored.

    python -m evals.run_gate --manifest agent/agent.yaml --env acceptance
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging as _logging
import multiprocessing
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# The evaluation SDK runs on promptflow, which logs per-line progress at INFO.
# Useful when a cloud evaluation is grinding through thousands of rows, noise
# for a 49-row gate. Set PF_LOGGING_LEVEL=INFO to get it back.
os.environ.setdefault("PF_LOGGING_LEVEL", "WARNING")
_logging.getLogger("promptflow").setLevel(_logging.WARNING)
_logging.getLogger("execution").setLevel(_logging.WARNING)
_logging.getLogger("execution.bulk").setLevel(_logging.WARNING)
_logging.getLogger("azure.ai.evaluation").setLevel(_logging.WARNING)

from triage.manifest import load_manifest  # noqa: E402
from triage.agent import TriageAgent  # noqa: E402
from evals.evaluators import (  # noqa: E402
    OutputContractEvaluator,
    PriorityAccuracyEvaluator,
    RoutingCorrectnessEvaluator,
)

EVALUATORS = {
    "routing": RoutingCorrectnessEvaluator(),
    "priority": PriorityAccuracyEvaluator(),
    "contract": OutputContractEvaluator(),
}

EVALUATOR_CONFIG = {
    "routing": {
        "column_mapping": {
            "response": "${data.response}",
            "expected_queue": "${data.expected_queue}",
        }
    },
    "priority": {
        "column_mapping": {
            "response": "${data.response}",
            "expected_priority": "${data.expected_priority}",
        }
    },
    "contract": {"column_mapping": {"response": "${data.response}"}},
}


def load_dataset(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"{path}: dataset is empty")
    return rows


def _col(row: dict[str, Any], suffix: str) -> Any:
    """Fetch a value from an SDK result row by its unprefixed name."""
    for key in (f"outputs.{suffix}", suffix):
        if key in row:
            return row[key]
    for key, value in row.items():
        if key.endswith(suffix):
            return value
    return None


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Compute gate metrics from per-row evaluator output.

    Conditional metrics are computed here rather than taken from the SDK's
    overall averages, so that a miss on eight security rows cannot be diluted
    by forty-one rows that are not security tickets.
    """
    routing = [float(_col(r, "routing.score") or 0.0) for r in rows]
    priority = [float(_col(r, "priority.score") or 0.0) for r in rows]
    contract = [float(_col(r, "contract.score") or 0.0) for r in rows]
    is_critical = [float(_col(r, "routing.is_critical") or 0.0) for r in rows]
    critical_hit = [float(_col(r, "routing.critical_hit") or 0.0) for r in rows]

    critical_total = sum(is_critical)
    return {
        "routing_accuracy": _mean(routing),
        "priority_accuracy": _mean(priority),
        "schema_validity": _mean(contract),
        "critical_queue_recall": (
            round(sum(critical_hit) / critical_total, 4) if critical_total else 1.0
        ),
        "_rows_evaluated": float(len(rows)),
        "_critical_rows": critical_total,
    }


def failing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        routing_ok = float(_col(row, "routing.score") or 0.0) == 1.0
        priority_ok = float(_col(row, "priority.score") or 0.0) == 1.0
        contract_ok = float(_col(row, "contract.score") or 0.0) == 1.0
        if routing_ok and priority_ok and contract_ok:
            continue
        out.append(
            {
                "ticket_id": _col(row, "inputs.ticket_id") or _col(row, "ticket_id") or "?",
                "expected_queue": _col(row, "expected_queue") or "",
                "predicted_queue": _col(row, "routing.predicted_queue") or "",
                "expected_priority": _col(row, "expected_priority") or "",
                "predicted_priority": _col(row, "priority.predicted_priority") or "",
                "is_critical": float(_col(row, "routing.is_critical") or 0.0) == 1.0,
                "contract_violations": _col(row, "contract.violations") or "none",
            }
        )
    return out


def check(metrics: dict[str, float], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for name, spec in (thresholds.get("metrics") or {}).items():
        minimum = float(spec["min"])
        actual = metrics.get(name)
        if actual is None:
            results.append(
                {"metric": name, "min": minimum, "actual": None, "passed": False,
                 "rationale": spec.get("rationale", ""), "note": "metric not produced"}
            )
            continue
        results.append(
            {"metric": name, "min": minimum, "actual": actual,
             "passed": actual >= minimum, "rationale": spec.get("rationale", "")}
        )
    return results


def render_report(record: dict[str, Any]) -> str:
    verdict = "PASSED" if record["passed"] else "BLOCKED"
    lines = [
        f"# Evaluation gate: {verdict}",
        "",
        f"- Agent version: `{record['release_id']}`",
        f"- Manifest: `{record['manifest']}`",
        f"- Prompt: `{record['prompt']}` (sha256 `{record['prompt_sha256'][:16]}`)",
        f"- Target environment: **{record['environment']}**",
        f"- Dataset: `{record['dataset']}` ({int(record['metrics']['_rows_evaluated'])} rows)",
        f"- Backend: `{record['backend']}`",
        f"- Evaluated at: {record['timestamp']}",
        "",
        "## Gated metrics",
        "",
        "| Metric | Threshold | Measured | Result |",
        "| --- | --- | --- | --- |",
    ]
    for check_result in record["checks"]:
        actual = "n/a" if check_result["actual"] is None else f"{check_result['actual']:.3f}"
        mark = "pass" if check_result["passed"] else "**FAIL**"
        lines.append(
            f"| {check_result['metric']} | >= {check_result['min']:.2f} | {actual} | {mark} |"
        )

    failures = [c for c in record["checks"] if not c["passed"]]
    if failures:
        lines += ["", "## Why this version was blocked", ""]
        for failure in failures:
            actual = "n/a" if failure["actual"] is None else f"{failure['actual']:.3f}"
            lines.append(
                f"**{failure['metric']}** measured {actual} against a bar of "
                f"{failure['min']:.2f}."
            )
            if failure.get("rationale"):
                lines.append("")
                lines.append(f"> {' '.join(failure['rationale'].split())}")
            lines.append("")

    rows = record["failing_rows"]
    if rows:
        critical = [r for r in rows if r["is_critical"]]
        if critical:
            lines += [
                "## Critical-queue misses",
                "",
                "These tickets should have reached a critical queue and did not.",
                "",
                "| Ticket | Expected | Routed to |",
                "| --- | --- | --- |",
            ]
            for row in critical:
                lines.append(
                    f"| {row['ticket_id']} | {row['expected_queue']} | "
                    f"{row['predicted_queue']} |"
                )
            lines.append("")

        lines += [
            "## All rows scoring below full marks",
            "",
            "| Ticket | Expected queue | Routed to | Expected | Priority | Contract |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            violations = row["contract_violations"]
            if len(violations) > 48:
                violations = violations[:45] + "..."
            lines.append(
                f"| {row['ticket_id']} | {row['expected_queue']} | {row['predicted_queue']} "
                f"| {row['expected_priority']} | {row['predicted_priority']} | {violations} |"
            )
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the triage evaluation gate.")
    parser.add_argument("--manifest", default="agent/agent.yaml")
    parser.add_argument("--env", default="acceptance", choices=["dev", "acceptance", "prod"])
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    agent = TriageAgent(manifest)

    dataset_path = (
        Path(args.dataset).resolve()
        if args.dataset
        else (manifest.path.parent / manifest.dataset).resolve()
    )
    thresholds_path = REPO_ROOT / "evals" / "thresholds" / f"{args.env}.yaml"
    thresholds = yaml.safe_load(thresholds_path.read_text(encoding="utf-8")) or {}

    out_dir = Path(args.out_dir).resolve() if args.out_dir else (
        REPO_ROOT / "evals" / "_runs" / f"{manifest.release_id}-{args.env}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Agent version    : {manifest.release_id}")
    print(f"Prompt           : {manifest.prompt_path.name} (v{manifest.prompt.version})")
    print(f"Routing rules    : {len(manifest.prompt.rules)}")
    print(f"Fallback policy  : {'declared' if manifest.prompt.fallback else 'ABSENT'}")
    print(f"Backend          : {agent.backend_name}")
    print(f"Target env       : {args.env}")
    print()

    tickets = load_dataset(dataset_path)
    predictions = agent.batch(tickets)
    predictions_path = out_dir / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as fh:
        for row in predictions:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    from azure.ai.evaluation import evaluate

    sdk_result = evaluate(
        data=str(predictions_path),
        evaluators=EVALUATORS,
        evaluator_config=EVALUATOR_CONFIG,
        evaluation_name=f"{manifest.release_id}-{args.env}",
        output_path=str(out_dir / "sdk_results.json"),
    )

    rows = sdk_result.get("rows") or []
    metrics = aggregate(rows)
    checks = check(metrics, thresholds)
    passed = all(c["passed"] for c in checks)

    record = {
        "passed": passed,
        "environment": args.env,
        "release_id": manifest.release_id,
        "agent_name": manifest.name,
        "agent_version": manifest.version,
        "manifest": str(Path(args.manifest)),
        "prompt": str(manifest.prompt_path.relative_to(REPO_ROOT)),
        "prompt_sha256": manifest.prompt_sha256,
        "prompt_version": manifest.prompt.version,
        "routing_rules_declared": len(manifest.prompt.rules),
        "fallback_policy_declared": manifest.prompt.fallback is not None,
        "backend": agent.backend_name,
        "dataset": str(dataset_path.relative_to(REPO_ROOT)),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metrics": metrics,
        "checks": checks,
        "failing_rows": failing_rows(rows),
        "sdk_metrics": sdk_result.get("metrics", {}),
    }

    (out_dir / "gate-result.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    report = render_report(record)
    (out_dir / "gate-report.md").write_text(report + "\n", encoding="utf-8")

    width = 62
    print("=" * width)
    for check_result in checks:
        actual = "n/a" if check_result["actual"] is None else f"{check_result['actual']:.3f}"
        mark = "PASS" if check_result["passed"] else "FAIL"
        print(f"  {check_result['metric']:<24} >= {check_result['min']:.2f}   "
              f"{actual:>6}   {mark}")
    print("=" * width)

    critical_misses = [r for r in record["failing_rows"] if r["is_critical"]]
    if critical_misses:
        print()
        print(f"  {len(critical_misses)} critical-queue ticket(s) mis-routed:")
        for row in critical_misses:
            print(f"    {row['ticket_id']}: {row['expected_queue']} -> "
                  f"{row['predicted_queue']}")

    print()
    if passed:
        print(f"GATE PASSED. {manifest.release_id} may be promoted to {args.env}.")
    else:
        failed = ", ".join(c["metric"] for c in checks if not c["passed"])
        print(f"GATE BLOCKED. {manifest.release_id} will not be promoted to "
              f"{args.env}.")
        print(f"Failed: {failed}")
    print(f"Report: {(out_dir / 'gate-report.md').relative_to(REPO_ROOT)}")

    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"passed={'true' if passed else 'false'}\n")
            fh.write(f"release_id={manifest.release_id}\n")

    return 0 if passed else 1


if __name__ == "__main__":
    with contextlib.suppress(RuntimeError):
        multiprocessing.set_start_method("spawn", force=True)
    sys.exit(main())
