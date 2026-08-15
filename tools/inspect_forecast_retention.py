"""Inspect forecast retention and optionally run one bounded audited prune."""

import argparse
import json
from datetime import UTC, datetime

from energy_optimizer.config import load_config
from energy_optimizer.forecast_retention import (
    inspect_forecast_retention,
    run_forecast_retention,
)
from energy_optimizer.persistence import open_repository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = load_config()
    repository = open_repository(config.database_url)
    try:
        now = datetime.now(UTC)
        before = inspect_forecast_retention(
            repository,
            now=now,
            point_retention_days=config.forecast_point_retention_days,
        )
        payload = {"mode": "apply" if args.apply else "dry_run", "before": before}
        if args.apply:
            payload["result"] = run_forecast_retention(
                repository,
                now=now,
                point_retention_days=config.forecast_point_retention_days,
                run_retention_days=config.forecast_run_retention_days,
            )
        print(json.dumps(payload, default=str, indent=2))
        return 0
    finally:
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
