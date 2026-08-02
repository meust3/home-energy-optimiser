"""Store one forecast run from a typed JSON document in local SQLite."""

import argparse
import json
from pathlib import Path

from rich.console import Console

from energy_optimizer.config import load_database_path
from energy_optimizer.historian import Historian
from energy_optimizer.models import ForecastRun


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Forecast-run JSON file")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    run = ForecastRun.model_validate(payload)
    run_id = Historian(load_database_path()).save_forecast_run(run)
    Console().print(f"Stored forecast run {run_id} with {len(run.points)} points.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
