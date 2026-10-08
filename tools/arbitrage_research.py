"""Private local admission/selection/evaluation; no database or hardware transport."""

import argparse
import json
from pathlib import Path

from energy_optimizer.arbitrage.archive import (
    context_from_capture,
    evaluate_files,
    freeze_context,
)
from energy_optimizer.arbitrage.decision_types import canonical, decision_from_dict
from energy_optimizer.arbitrage.offline_guard import install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    select = modes.add_parser("select")
    select.add_argument("--decision", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    admit = modes.add_parser("admit-capture")
    admit.add_argument("--inputs", type=Path, required=True)
    admit.add_argument("--source", type=Path, required=True)
    admit.add_argument("--declared-context", type=Path, required=True)
    admit.add_argument("--output", type=Path, required=True)
    evaluate = modes.add_parser("evaluate")
    for field in ("decision", "receipt", "outcome", "output"):
        evaluate.add_argument("--" + field, type=Path, required=True)
    args = parser.parse_args()
    install()

    def read(p):
        return json.loads(p.read_text(encoding="utf-8"))

    if args.mode == "evaluate":
        result = evaluate_files(args.decision, args.receipt, args.outcome)
        with args.output.open("x", encoding="utf-8") as f:
            f.write(canonical(result) + "\n")
    else:
        context = (
            context_from_capture(
                read(args.inputs), read(args.source), read(args.declared_context)
            )
            if args.mode == "admit-capture"
            else decision_from_dict(read(args.decision))
        )
        receipt = freeze_context(context, args.output)
        print(
            canonical(
                {
                    "receipt_sha256": receipt.sha256,
                    "selected": receipt.selected,
                    "reasons": receipt.reasons,
                }
            )
        )


if __name__ == "__main__":
    main()
