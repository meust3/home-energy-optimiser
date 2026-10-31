"""Review uncertainty candidates from a local JSON export, without network access."""

import argparse
import json
from pathlib import Path

from energy_optimizer.forecast_interval_review import review_forecast_intervals
from energy_optimizer.timestamps import aware_datetime, json_safe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--training-end", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.input.stat().st_size > 100 * 1024 * 1024:
        parser.error("JSON input exceeds 100 MiB")
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    report = review_forecast_intervals(
        rows, training_end=aware_datetime(args.training_end)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json_safe(report), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
