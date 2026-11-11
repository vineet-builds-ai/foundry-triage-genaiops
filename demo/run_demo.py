#!/usr/bin/env python3
"""The demo.

Runs the full before-and-after in one command, with no Azure account and no
network access:

  1. Shows the prompt change as a reviewer would see it.
  2. Runs the static manifest check on both versions.
  3. Runs the evaluation gate on both versions.
  4. Prints the comparison and writes the artefacts to demo/output/.

    make demo
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "demo" / "output"

SHIPPING = "agent/agent.yaml"
REGRESSED = "agent/agent.regressed.yaml"

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
RED, GREEN, YELLOW = "\033[31m", "\033[32m", "\033[33m"


def supports_colour() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text: str, colour: str) -> str:
    return f"{colour}{text}{RESET}" if supports_colour() else text


def banner(step: str, title: str) -> None:
    print()
    print(paint("=" * 74, DIM))
    print(paint(f" {step}  {title}", BOLD))
    print(paint("=" * 74, DIM))
    print()


def run(cmd: list[str], env_extra: dict[str, str] | None = None) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["NO_COLOR"] = "1"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    return proc.returncode, proc.stdout + proc.stderr


def show_prompt_diff() -> str:
    old = (REPO_ROOT / "agent" / "prompts" / "system.v3.md").read_text().splitlines()
    new = (
        REPO_ROOT / "agent" / "prompts" / "system.v4-regressed.md"
    ).read_text().splitlines()

    diff = list(
        difflib.unified_diff(
            old, new, fromfile="system.v3.md", tofile="system.v4-regressed.md", lineterm="", n=1
        )
    )
    rendered = []
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            rendered.append(paint(line, GREEN))
        elif line.startswith("-") and not line.startswith("---"):
            rendered.append(paint(line, RED))
        elif line.startswith("@@"):
            rendered.append(paint(line, DIM))
        else:
            rendered.append(line)
    print("\n".join(rendered))
    return "\n".join(diff)


def extract_metrics(manifest: str, env: str) -> dict:
    """Read the gate record written by the last run of this version."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from triage.manifest import load_manifest

    release = load_manifest(REPO_ROOT / manifest).release_id
    record = REPO_ROOT / "evals" / "_runs" / f"{release}-{env}" / "gate-result.json"
    return json.loads(record.read_text()) if record.is_file() else {}


def main() -> int:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    print()
    print(paint("  Evaluation-gated promotion for an AI product on Azure", BOLD))
    print(paint("  Support ticket triage agent -- offline demo, no Azure account needed", DIM))

    # ---------------------------------------------------------------- step 1
    banner("1/4", "The change a reviewer sees")
    print("Someone tidies the triage prompt. Three edits, all reasonable-sounding:")
    print("  - trim an unused field from the output contract")
    print("  - fold the security rule into the general rules, one less special case")
    print("  - stop sending tickets to triage-review, it was a dumping ground")
    print()
    diff_text = show_prompt_diff()
    (OUTPUT_DIR / "prompt-change.diff").write_text(diff_text + "\n")

    # ---------------------------------------------------------------- step 2
    banner("2/4", "Static check: does the manifest still hold together?")
    static_results = {}
    for label, manifest in (("shipping", SHIPPING), ("regressed", REGRESSED)):
        code, output = run([sys.executable, "scripts/validate_manifest.py", manifest])
        static_results[label] = code
        print(paint(f"--- {label}: {manifest}", BOLD))
        print(output.rstrip())
        print(
            paint("  -> accepted", GREEN)
            if code == 0
            else paint(f"  -> rejected (exit {code})", RED)
        )
        print()
        (OUTPUT_DIR / f"static-check-{label}.txt").write_text(output)

    print("This check costs milliseconds and runs on every pull request. It already")
    print("rejects the change. The gate below shows what it would have cost us.")

    # ---------------------------------------------------------------- step 3
    banner("3/4", "Evaluation gate at the acceptance bar")
    gate_results = {}
    for label, manifest in (("shipping", SHIPPING), ("regressed", REGRESSED)):
        code, output = run(
            [sys.executable, "-m", "evals.run_gate", "--manifest", manifest,
             "--env", "acceptance"]
        )
        gate_results[label] = code
        # Trim the SDK's own progress block; keep the verdict.
        noise = ("execution.bulk", "promptflow", "Aggregated metrics",
                 "Finished ", "Average execution time", "Evaluation results saved")
        lines = [
            line for line in output.splitlines()
            if not any(marker in line for marker in noise)
        ]
        start = next(
            (i for i, line in enumerate(lines) if line.startswith("=" * 10)), 0
        )
        head = [line for line in lines[:12] if line and not line.startswith("{")]
        print(paint(f"--- {label}: {manifest}", BOLD))
        print("\n".join(head))
        print("\n".join(lines[start:]))
        print()
        (OUTPUT_DIR / f"gate-{label}.txt").write_text(output)

    # ---------------------------------------------------------------- step 4
    banner("4/4", "Side by side")
    shipping = extract_metrics(SHIPPING, "acceptance")
    regressed = extract_metrics(REGRESSED, "acceptance")

    for label, record in (("shipping", shipping), ("regressed", regressed)):
        report = (
            REPO_ROOT / "evals" / "_runs"
            / f"{record['release_id']}-acceptance" / "gate-report.md"
        )
        if report.is_file():
            shutil.copy(report, OUTPUT_DIR / f"gate-report-{label}.md")

    metrics = ["schema_validity", "critical_queue_recall", "routing_accuracy",
               "priority_accuracy"]
    bars = {c["metric"]: c["min"] for c in shipping.get("checks", [])}

    print(f"  {'metric':<24} {'bar':>6} {'v3':>8} {'v4':>8}   verdict")
    print(f"  {'-' * 24} {'-' * 6} {'-' * 8} {'-' * 8}   {'-' * 18}")
    for metric in metrics:
        bar = bars.get(metric, 0.0)
        before = shipping.get("metrics", {}).get(metric)
        after = regressed.get("metrics", {}).get(metric)
        if before is None or after is None:
            continue
        verdict = (
            paint("held", GREEN) if after >= bar else paint("BREACHED", RED)
        )
        print(f"  {metric:<24} {bar:>6.2f} {before:>8.3f} {after:>8.3f}   {verdict}")

    misses = [r for r in regressed.get("failing_rows", []) if r["is_critical"]]
    if misses:
        print()
        print(paint(f"  {len(misses)} security tickets were sent somewhere else:", YELLOW))
        for row in misses:
            print(f"    {row['ticket_id']}  security-incident -> {row['predicted_queue']}")

    print()
    print(paint("=" * 74, DIM))
    shipping_ok = gate_results["shipping"] == 0
    regressed_blocked = gate_results["regressed"] != 0
    if shipping_ok and regressed_blocked:
        print(paint("  v3 promoted to acceptance. v4 blocked before it got there.", GREEN))
        print("  No customer saw v4. No incident review. One failed check.")
        outcome = 0
    else:
        print(paint("  DEMO INVARIANT BROKEN -- v3 must pass and v4 must fail.", RED))
        outcome = 1
    print(paint("=" * 74, DIM))
    print()
    print(f"Artefacts written to {OUTPUT_DIR.relative_to(REPO_ROOT)}/")
    for path in sorted(OUTPUT_DIR.iterdir()):
        print(f"  {path.relative_to(REPO_ROOT)}")
    print()
    return outcome


if __name__ == "__main__":
    sys.exit(main())
