"""Compare saved synthetic results offline; never submits an inference request."""

import argparse
import json
from pathlib import Path

from energy_optimizer.jev_evaluation import compare


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapika", type=Path, required=True)
    parser.add_argument("--jev", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        retained = json.loads(args.mapika.read_text(encoding="utf-8"))
        challenger = (
            json.loads(args.jev.read_text(encoding="utf-8"))
            if args.jev
            else {"results": []}
        )
        report = compare(retained, challenger)
        rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            # Preserve existing evidence, including the input files.
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        parser.exit(
            2, "Offline comparison failed: invalid input or unavailable output.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
