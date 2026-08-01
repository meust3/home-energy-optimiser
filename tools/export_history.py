"""Export an inclusive local date range of observations to CSV."""

import argparse
from pathlib import Path

from rich.console import Console

from energy_optimizer.config import load_database_path, load_timezone_name
from energy_optimizer.exporting import export_rows_to_csv
from energy_optimizer.historian import Historian
from energy_optimizer.time_ranges import parse_range_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="Inclusive ISO date/datetime")
    parser.add_argument("--end", required=True, help="Inclusive ISO date/datetime")
    parser.add_argument("--output", required=True, type=Path, help="Destination CSV")
    args = parser.parse_args()
    timezone_name = load_timezone_name()
    try:
        start = parse_range_value(args.start, timezone_name)
        end = parse_range_value(args.end, timezone_name, end=True)
    except ValueError as exc:
        parser.error(str(exc))
    if end < start:
        parser.error("--end must not be before --start")
    rows = Historian(load_database_path()).observation_rows(start=start, end=end)
    count = export_rows_to_csv(rows, args.output)
    Console().print(
        f"Exported {count} observations to {args.output}. "
        "Stored history was not modified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
