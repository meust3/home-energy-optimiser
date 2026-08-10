"""Populate actuals for one stored forecast run and report MAE and bias."""

import argparse

from rich.console import Console

from energy_optimizer.persistence import open_repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=int)
    args = parser.parse_args()
    metrics = open_repository().compare_forecast_run(args.run_id)
    Console().print_json(data=metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
