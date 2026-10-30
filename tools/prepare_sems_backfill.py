"""Prepare a review plan from an explicit local snapshot; never opens a database."""

import argparse
import json
from collections import Counter
from pathlib import Path

from energy_optimizer.sems_backfill import prepare_backfill


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = prepare_backfill(
        json.loads(args.snapshot.read_text(encoding="utf-8")),
        json.loads(args.ledger.read_text(encoding="utf-8")),
    )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(plan, output, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "plan_id": plan["plan_id"],
                "counts": dict(Counter(e["disposition"] for e in plan["entries"])),
            }
        )
    )


if __name__ == "__main__":
    main()
