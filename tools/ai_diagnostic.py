"""Explicit Energy diagnostics; default local status performs no network I/O."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values

from energy_optimizer.ai_integration import AISettings, local_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Explicit Energy-only env file")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--discover", action="store_true")
    actions.add_argument(
        "--decide", action="store_true", help="One fixed synthetic probe"
    )
    parser.add_argument(
        "--operation-id", type=UUID, help="Stable UUID; never auto-retried"
    )
    args = parser.parse_args()
    if args.decide != (args.operation_id is not None):
        parser.error("--decide requires --operation-id; other modes do not accept it")
    env = dict(os.environ)
    if args.config:
        if not args.config.is_file():
            print('{"configuration": "unavailable"}')
            return 2
        env.update(
            {
                k: v
                for k, v in dotenv_values(args.config).items()
                if k.startswith("ENERGY_AI_") and v is not None
            }
        )
    if not (args.discover or args.decide):
        print(json.dumps(local_status(env), indent=2))
        return 2  # Local inspection is not proof of connectivity.
    try:
        settings = AISettings.from_environment(env)
    except ValueError:
        print('{"configuration": "invalid"}')
        return 2
    from energy_optimizer.ai_panel import manual_check

    try:
        report = asyncio.run(manual_check(settings, args.operation_id))
    except OSError:
        print('{"diagnostic_evidence": "write_failed"}')
        return 2
    print(report.model_dump_json(indent=2, exclude={"configuration_hash"}))
    return 0 if report.failure is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
