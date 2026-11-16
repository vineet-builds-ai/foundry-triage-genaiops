#!/usr/bin/env python3
"""Turn production corrections into golden-set candidates.

The golden set goes stale. Customers change how they write, new products bring
new ticket types, and 49 hand-written examples stop representing production.
The cheapest fix is the signal production already produces: every time a
support agent moves a ticket the triage agent mis-routed, that correction is a
labelled example of exactly the kind the golden set is missing.

Input is a JSONL export of corrections, one per line:

    {"ticket_id": "...", "text": "...",
     "predicted_queue": "billing", "predicted_priority": "P2",
     "corrected_queue": "security-incident", "corrected_priority": "P1",
     "corrected_by": "support-lead@team"}

Output is candidate rows in golden-set format, for a human to review before
any are adopted. Nothing is added to the gate automatically: a reviewer decides
which candidates are representative, and that review is the control.

Real tickets are customer data. They must not be committed to source control
(docs/governance.md, "Data handling"), so this script refuses to write inside
the repository unless --synthetic says the input is invented. Real candidates
belong in the Foundry project's dataset storage, with access controlled like
any other customer data.

    python scripts/harvest_feedback.py corrections.jsonl --out /secure/path/candidates.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from triage.schema import CRITICAL_QUEUES, PRIORITIES, QUEUES  # noqa: E402

GOLDEN = REPO_ROOT / "evals" / "datasets" / "tickets.golden.jsonl"


def _is_inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("corrections", help="JSONL export of production corrections")
    parser.add_argument("--out", required=True, help="Where to write candidate rows (JSONL)")
    parser.add_argument("--synthetic", action="store_true",
                        help="Input is invented data, so writing inside the repository is allowed.")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if _is_inside_repo(out) and not args.synthetic:
        print(f"Refusing to write {out}: it is inside the repository, and production "
              "tickets are customer data that must not be committed. Write to the "
              "project's dataset storage instead, or pass --synthetic for invented data.",
              file=sys.stderr)
        return 2

    known_text = set()
    if GOLDEN.exists():
        for line in GOLDEN.read_text(encoding="utf-8").splitlines():
            if line.strip():
                known_text.add(json.loads(line)["text"].strip().lower())

    candidates, skipped = [], Counter()
    seen = set()
    for n, line in enumerate(Path(args.corrections).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        text = (row.get("text") or "").strip()
        queue, priority = row.get("corrected_queue"), row.get("corrected_priority")
        if not text:
            skipped["no text"] += 1
            continue
        if queue not in QUEUES or priority not in PRIORITIES:
            skipped["invalid correction label"] += 1
            continue
        if queue == row.get("predicted_queue") and priority == row.get("predicted_priority"):
            skipped["not actually a correction"] += 1
            continue
        key = text.lower()
        if key in known_text or key in seen:
            skipped["already in golden set or duplicate"] += 1
            continue
        seen.add(key)
        candidates.append({
            "ticket_id": f"FB-{row.get('ticket_id', n)}",
            "text": text,
            "expected_queue": queue,
            "expected_priority": priority,
            "note": (f"production correction: agent said {row.get('predicted_queue')}/"
                     f"{row.get('predicted_priority')}; corrected by {row.get('corrected_by', 'unknown')}"),
            "source": "production-feedback",
            "review_status": "pending",
        })

    # Critical-queue misses first: they are the ones the gate most needs.
    candidates.sort(key=lambda c: c["expected_queue"] not in CRITICAL_QUEUES)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for c in candidates:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    critical = sum(c["expected_queue"] in CRITICAL_QUEUES for c in candidates)
    print(f"{len(candidates)} candidate(s) written to {out} ({critical} for critical queues).")
    for reason, count in skipped.items():
        print(f"  skipped {count}: {reason}")
    print("Next: a reviewer accepts or rejects each candidate before it joins the golden set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
