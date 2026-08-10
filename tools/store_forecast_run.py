"""Store one forecast run in the configured database."""

import argparse
import json
from pathlib import Path

from rich.console import Console

from energy_optimizer.models import ForecastRun
from energy_optimizer.persistence import open_repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Forecast-run JSON file")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    run = ForecastRun.model_validate(payload)
    run_id = open_repository().save_forecast_run(run)
    Console().print(f"Stored forecast run {run_id} with {len(run.points)} points.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
