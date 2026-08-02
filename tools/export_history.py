"""Export an inclusive local date range of observations to CSV."""

import argparse
from pathlib import Path

from rich.console import Console

from energy_optimizer.config import load_database_path, load_timezone_name
from energy_optimizer.exporting import export_rows_to_csv
from energy_optimizer.historian import Historian
from energy_optimizer.time_ranges import resolve_history_range


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_value", help="Inclusive ISO date/datetime")
    parser.add_argument("--to", dest="to_value", help="Inclusive ISO date/datetime")
    parser.add_argument("--days", type=int, help="Export this many recent days")
    parser.add_argument("--output", required=True, type=Path, help="Destination CSV")
    args = parser.parse_args()
    timezone_name = load_timezone_name()
    try:
        start, end = resolve_history_range(
            from_value=args.from_value,
            to_value=args.to_value,
            days=args.days,
            timezone_name=timezone_name,
        )
    except ValueError as exc:
        parser.error(str(exc))
    historian = Historian(load_database_path())
    rows = historian.observation_rows(start=start, end=end)
    count = export_rows_to_csv(
        rows, args.output, fieldnames=historian.observation_columns()
    )
    Console().print(
        f"Exported {count} observations to {args.output}. "
        "Stored history was not modified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
