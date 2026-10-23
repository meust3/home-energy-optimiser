"""Read one explicit offline review record; never load application settings."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from energy_optimizer.arbitrage.readiness import review_readiness


def read_review(path: str) -> dict:
    def unique_object(pairs: list[tuple]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_review_field")
            result[key] = value
        return result

    with Path(path).open("rb") as source:
        body = source.read(16385)
    if len(body) > 16384:
        raise ValueError("review_record_too_large")
    return json.loads(body, object_pairs_hook=unique_object)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--at", required=True, help="Explicit aware review time")
    args = parser.parse_args(argv)
    try:
        result = review_readiness(
            read_review(args.review), at=datetime.fromisoformat(args.at)
        )
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        print(
            json.dumps(
                {"error": "offline_review_refused", "hardware_authorized": False}
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
