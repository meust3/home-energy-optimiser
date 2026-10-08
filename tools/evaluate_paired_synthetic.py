"""Print one allowlisted synthetic 24-hour experiment; no arbitrary data input."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from energy_optimizer.offline_paired_fixtures import (  # noqa: E402
    PUBLIC_FIXTURES,
    evaluate_fixture,
)
from energy_optimizer.offline_paired_synthetic import AdmissionError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixture", choices=PUBLIC_FIXTURES)
    group.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        print(
            json.dumps(
                {"authored_public_24h_fixtures": PUBLIC_FIXTURES}, sort_keys=True
            )
        )
        return 0
    try:
        report = evaluate_fixture(args.fixture)
    except AdmissionError as exc:
        print(json.dumps({"admitted": False, "reasons": exc.reasons}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0 if report["admitted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
