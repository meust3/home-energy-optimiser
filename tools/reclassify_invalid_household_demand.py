"""Safely inspect or repair derived fields for negative household demand."""

import argparse
import json

from energy_optimizer.config import load_reserve_config
from energy_optimizer.household_demand_reclassification import (
    reclassify_invalid_household_demand,
)
from energy_optimizer.persistence import open_repository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-verified", action="store_true")
    args = parser.parse_args()
    config = load_reserve_config()
    repository = open_repository(config.database_url)
    try:
        report = reclassify_invalid_household_demand(
            repository,
            apply=args.apply,
            backup_verified=args.backup_verified,
            timezone_name=config.timezone,
        )
    finally:
        repository.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
