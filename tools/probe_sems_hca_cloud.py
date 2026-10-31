"""Manually approved one-shot SEMS diagnostic; never run by the collector."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from energy_optimizer.sems_probe import (
    AU_LOGIN_URL,
    LOGIN_URL,
    ProbeError,
    SemsCloudProbe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--region", choices=("global", "au"), default="global")
    args = parser.parse_args(argv)
    if not args.allow_live:
        parser.error("Live SEMS requests require owner approval and --allow-live")
    environment = dotenv_values(args.env_file) if args.env_file else {}
    username = os.getenv("SEMS_USERNAME") or environment.get("SEMS_USERNAME") or ""
    password = os.getenv("SEMS_PASSWORD") or environment.get("SEMS_PASSWORD") or ""
    try:
        summary = SemsCloudProbe(
            username,
            password,
            allow_live_requests=True,
            login_url=AU_LOGIN_URL if args.region == "au" else LOGIN_URL,
        ).run_once()
    except ProbeError as exc:
        print(f"SEMS probe failed safely: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
