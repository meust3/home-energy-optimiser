"""Export stored projected-vs-actual forecast points to CSV or JSON."""

import argparse
import json
from pathlib import Path

from energy_optimizer.config import load_timezone_name
from energy_optimizer.exporting import export_rows_to_csv
from energy_optimizer.persistence import open_repository
from energy_optimizer.time_ranges import parse_range_value
from energy_optimizer.timestamps import json_safe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-type")
    parser.add_argument("--from", dest="from_value")
    parser.add_argument("--to", dest="to_value")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    timezone_name = load_timezone_name()
    try:
        start = (
            parse_range_value(args.from_value, timezone_name)
            if args.from_value
            else None
        )
        end = (
            parse_range_value(args.to_value, timezone_name, end=True)
            if args.to_value
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))
    rows = open_repository().forecast_comparison_rows(
        forecast_type=args.forecast_type, start=start, end=end
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        args.output.write_text(json.dumps(json_safe(rows), indent=2), encoding="utf-8")
    else:
        export_rows_to_csv(rows, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
