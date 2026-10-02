"""Explicit offline morning-export replay; never connects to production."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from energy_optimizer.solar_export_replay import replay_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_json", type=Path, help="Local time-bounded snapshot bundle"
    )
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    result = replay_report(payload["snapshots"])
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output_json:
        args.output_json.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
