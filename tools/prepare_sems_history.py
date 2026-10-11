"""Prepare a private offline session ledger and optional observation-context preview."""

import argparse
import csv
import json
from pathlib import Path

from energy_optimizer.sems_history import prepare_sessions, preview_join


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observations-csv", type=Path)
    parser.add_argument("--confirmed-utc-offset-hours", type=int)
    args = parser.parse_args()
    if args.observations_csv and args.confirmed_utc_offset_hours is None:
        parser.error("A confirmed source UTC offset is required to preview a join")
    ledger = prepare_sessions(json.loads(args.evidence.read_text(encoding="utf-8")))
    if args.observations_csv:
        with args.observations_csv.open(encoding="utf-8-sig", newline="") as source:
            ledger["observation_context_preview"] = preview_join(
                list(csv.DictReader(source)),
                ledger,
                confirmed_utc_offset_hours=args.confirmed_utc_offset_hours,
            )
    # Exclusive create protects both source evidence and earlier review outputs.
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(ledger, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
