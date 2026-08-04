"""Annotate or reverse local historical EV sessions; dry-run by default."""

import argparse
import json

from energy_optimizer.config import load_config
from energy_optimizer.ev_annotation import (
    annotate_ev_session,
    parse_aware_timestamp,
    remove_ev_session,
)
from energy_optimizer.historian import Historian


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--session-id")
    parser.add_argument("--note")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remove-session")
    args = parser.parse_args()
    historian = Historian(load_config().database_path)
    if args.remove_session:
        if args.start or args.end or args.session_id:
            parser.error(
                "--remove-session cannot be combined with range/session options"
            )
        report = remove_ev_session(
            historian, session_id=args.remove_session, note=args.note, apply=args.apply
        )
    else:
        if not args.start or not args.end:
            parser.error("--start and --end are required for annotation")
        report = annotate_ev_session(
            historian,
            start=parse_aware_timestamp(args.start),
            end=parse_aware_timestamp(args.end),
            session_id=args.session_id,
            note=args.note,
            apply=args.apply,
        )
    print(json.dumps(report.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
