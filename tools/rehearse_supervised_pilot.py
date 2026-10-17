"""Explicit local fake commissioning operator flow; there is no live mode."""

import argparse
import json
import sqlite3

from energy_optimizer.arbitrage.executor import FakeTransport
from energy_optimizer.arbitrage.supervised_pilot import (
    SupervisedPilot,
    open_rehearsal_journal,
    parse_contract,
    parse_feedback,
    parse_state,
    parse_utc_time,
    read_rehearsal_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, help="Owned *.pilot.sqlite3 path")
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser(
        "propose", help="Display exact synthetic action and binding"
    )
    propose.add_argument("--fixture", required=True)
    for command in ("propose", "approve", "rehearse", "reject"):
        item = propose if command == "propose" else sub.add_parser(command)
        item.add_argument(
            "--at", required=True, help="Explicit aware synthetic ISO time"
        )
        if command != "reject":
            item.add_argument("--monotonic", required=True, type=float)
        if command != "propose":
            item.add_argument("--key", required=True)
        if command in {"approve", "rehearse"}:
            item.add_argument("--binding", required=True)
            item.add_argument("--operator", required=True)
        if command == "rehearse":
            item.add_argument("--state-fixture", required=True)
            item.add_argument("--lost-ack", action="store_true")
    observe = sub.add_parser(
        "record-feedback", help="Record synthetic effect/return evidence"
    )
    observe.add_argument("--key", required=True)
    observe.add_argument("--fixture", required=True)
    status = sub.add_parser("status")
    status.add_argument("--key", required=True)
    args = parser.parse_args()
    journal = None
    try:
        journal = open_rehearsal_journal(args.journal)
        pilot = SupervisedPilot(
            journal,
            FakeTransport(lost_ack=getattr(args, "lost_ack", False)),
            fake_rehearsal=True,
        )
        if args.command == "propose":
            intent, envelope = parse_contract(read_rehearsal_json(args.fixture))
            result = pilot.propose(
                intent,
                envelope,
                at=parse_utc_time(args.at),
                monotonic_seconds=args.monotonic,
            )
            result["proposal"] = pilot.status(result["intent_id"])
        elif args.command in {"approve", "rehearse"}:
            pilot.approve(
                args.key,
                binding=args.binding,
                operator=args.operator,
                at=parse_utc_time(args.at),
                monotonic_seconds=args.monotonic,
            )
            if args.command == "rehearse":
                pilot.dispatch(
                    args.key, parse_state(read_rehearsal_json(args.state_fixture))
                )
            result = pilot.status(args.key)
        elif args.command == "reject":
            pilot.reject(args.key, at=parse_utc_time(args.at))
            result = pilot.status(args.key)
        elif args.command == "record-feedback":
            pilot.observe(args.key, parse_feedback(read_rehearsal_json(args.fixture)))
            result = pilot.status(args.key)
        else:
            result = pilot.status(args.key)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, PermissionError, sqlite3.Error):
        print(json.dumps({"error": "fake_rehearsal_refused", "live_dispatch": False}))
        return 2
    finally:
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
