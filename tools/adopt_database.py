"""Stamp a validated existing schema-v6 SQLite database at the Alembic baseline."""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alembic import command

from energy_optimizer.config import load_database_url
from energy_optimizer.db.migrations import ALEMBIC_HEAD, alembic_config

REQUIRED_TABLES = {
    "observations",
    "forecast_runs",
    "forecast_points",
    "observation_derivations",
    "ev_session_annotations",
    "ev_session_annotation_rows",
    "schema_version",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = args.database_url or load_database_url()
    if not url.startswith("sqlite:///"):
        parser.error("adoption is only supported for an existing SQLite database")
    path = Path(url.removeprefix("sqlite:///"))
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version = (
            connection.execute("SELECT version FROM schema_version").fetchone()
            if "schema_version" in tables
            else None
        )
    missing = sorted(REQUIRED_TABLES - tables)
    if missing or version != (6,):
        raise SystemExit(
            f"Refusing adoption: version={version!r}, missing_tables={missing}"
        )
    print(f"Validated legacy SQLite schema version 6 at {path}")
    if not args.apply:
        print("Dry run only; pass --apply to stamp the Alembic baseline.")
        return 0
    command.stamp(alembic_config(url), ALEMBIC_HEAD)
    print(f"Stamped revision {ALEMBIC_HEAD}; no application rows were recreated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
