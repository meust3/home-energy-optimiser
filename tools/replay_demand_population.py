"""Offline demand replay from a checksum-bound original population only."""

import argparse
import json
from pathlib import Path

from energy_optimizer.frozen_training import (
    MAX_POPULATION_BYTES,
    replay_demand_population,
)
from energy_optimizer.timestamps import aware_datetime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("population", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--decision-at", type=aware_datetime, required=True)
    parser.add_argument("--start", type=aware_datetime, required=True)
    parser.add_argument("--end", type=aware_datetime, required=True)
    parser.add_argument("--minimum-samples", type=int, required=True)
    parser.add_argument("--fallback-kw", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.population.open("rb") as stream:
            data = stream.read(MAX_POPULATION_BYTES + 1)
        result = replay_demand_population(
            data,
            expected_sha256=args.expected_sha256,
            decision_at=args.decision_at,
            start_local=args.start,
            end_local=args.end,
            minimum_samples=args.minimum_samples,
            fallback_kw=args.fallback_kw,
        )
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError):
        # Paths and exception text can contain private household information.
        parser.exit(2, "Offline replay refused: invalid/unavailable input or output.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
