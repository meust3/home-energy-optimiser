"""Prepare or run a synthetic offline lifecycle rehearsal; live mode is absent."""

import argparse
import asyncio
import json
from pathlib import Path

from energy_optimizer.jev_runner import RunnerRefused, manifest_template, rehearse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--experiment-id", required=True)
    prepare.add_argument("--max-cost-usd", default="0.13")
    prepare.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--approval", type=Path, required=True)
    run.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            value = manifest_template(args.experiment_id, args.max_cost_usd)
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, allow_nan=False)
            return 0
        report = asyncio.run(
            rehearse(
                args.manifest.read_bytes(), args.approval.read_bytes(), args.registry
            )
        )
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0 if report["status"] == "completed" else 2
    except (OSError, ValueError, RunnerRefused):
        parser.exit(2, "Offline rehearsal refused or evidence could not be saved.\n")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
