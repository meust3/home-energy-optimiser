"""Replay one persisted shadow decision without writing to the database."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from energy_optimizer.persistence import open_repository
from energy_optimizer.shadow_replay import replay_persisted_shadow_decision


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay one immutable shadow-decision boundary. Database access is "
            "read-only; output is marked synthetic_replay=true."
        )
    )
    parser.add_argument("decision_run_id", type=int)
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Explicitly opt in to writing the synthetic result to this local file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = open_repository()
    try:
        result = replay_persisted_shadow_decision(repository, args.decision_run_id)
    finally:
        repository.close()
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output_json is not None:
        args.output_json.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
