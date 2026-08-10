"""Dry-run-first SQLite-to-PostgreSQL migration and integrity validation."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.redaction import (
    display_database_url,
    redact_database_urls,
    safe_url,
)
from energy_optimizer.db.transfer import source_fingerprint, transfer, validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sqlite", type=Path, required=True)
    parser.add_argument("--target-database-url", default=None)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--validation-mode",
        choices=("exact", "source-preserved"),
        default="exact",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    target_url = args.target_database_url or os.getenv("DATABASE_URL", "").strip()
    if not target_url:
        parser.error("provide --target-database-url or explicitly set DATABASE_URL")
    target = safe_url(target_url)
    if target.get_backend_name() != "postgresql":
        parser.error("target must use postgresql+psycopg")
    if target.database == "home_energy" and args.apply and not args.confirm_production:
        parser.error("production target home_energy requires --confirm-production")
    if not args.source_sqlite.is_file():
        parser.error("source SQLite file does not exist")
    source_url = (
        f"sqlite:///file:{args.source_sqlite.resolve().as_posix()}?mode=ro&uri=true"
    )
    source_engine = create_database_engine(source_url)
    target_engine = create_database_engine(target_url)
    try:
        if args.validate_only:
            report = validate(
                source_engine, target_engine, validation_mode=args.validation_mode
            )
        else:
            report = transfer(
                source_engine,
                target_engine,
                source_id=source_fingerprint(args.source_sqlite),
                batch_size=args.batch_size,
                apply=args.apply,
                resume=args.resume,
            )
            report["validation"] = (
                validate(
                    source_engine,
                    target_engine,
                    validation_mode=args.validation_mode,
                )
                if args.apply
                else None
            )
        report["source"] = str(args.source_sqlite)
        report["target"] = display_database_url(target_url)
    except Exception as exc:
        report = {
            "summary": "FAIL",
            "error": redact_database_urls(exc),
            "target": display_database_url(target_url),
        }
    finally:
        source_engine.dispose()
        target_engine.dispose()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report.get("summary") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
