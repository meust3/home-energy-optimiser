"""Explicit, optional synthetic Energy review. Default is offline, no model call."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values

from energy_optimizer.ai_integration import AISettings
from energy_optimizer.ai_review import offline_report, run_replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--run", action="store_true", help="Explicit local synthetic replay"
    )
    parser.add_argument(
        "--operation-id", type=UUID, help="Retain this root UUID for uncertain receipts"
    )
    parser.add_argument(
        "--output", type=Path, help="Synthetic metadata report, never request bodies"
    )
    args = parser.parse_args()
    if args.run != (args.operation_id is not None):
        parser.error("--run requires --operation-id; offline mode does not accept one")
    env = dict(os.environ)
    try:
        if args.config:
            if not args.config.is_file():
                raise ValueError("Missing configuration")
            env.update(
                {
                    k: v
                    for k, v in dotenv_values(args.config).items()
                    if k.startswith("ENERGY_AI_") and v is not None
                }
            )
        report = (
            asyncio.run(run_replay(AISettings.from_environment(env), args.operation_id))
            if args.run
            else offline_report()
        )
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(args.output)
        print(text, end="")
    except (ValueError, OSError, ImportError):
        print('{"failure":"configuration_or_optional_sdk_unavailable"}')
        return 2
    return (
        0
        if not args.run
        or (
            report["model_completed"] == report["dataset_cases"]
            and report["model_correct"] == report["dataset_cases"]
        )
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
