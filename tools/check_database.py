"""Credential-safe database connectivity, revision, and integrity diagnostics."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from energy_optimizer.config import load_database_url
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import (
    SchemaRevisionStatus,
    current_revision,
    expected_revision,
    schema_revision_status,
)
from energy_optimizer.db.redaction import display_database_url, redact_database_urls
from energy_optimizer.db.repository import DatabaseRepository

COUNTED_TABLES = (
    "observations",
    "forecast_runs",
    "forecast_points",
    "observation_derivations",
    "ev_session_annotations",
    "ev_session_annotation_rows",
    "forecast_point_scores",
    "forecast_operation_attempts",
    "reserve_runs",
    "reserve_opportunity_evaluations",
)


def check_database(
    database_url: str, *, application_readiness: bool = False
) -> dict[str, object]:
    engine = create_database_engine(database_url)
    repository = DatabaseRepository(engine)
    result: dict[str, object] = {
        "backend": engine.dialect.name,
        "target": display_database_url(database_url),
        "connectivity": False,
        "current_revision": None,
        "expected_revision": expected_revision(),
        "schema_status": None,
        "migration_required": False,
    }
    try:
        result["connectivity"] = repository.ping()
        result["current_revision"] = current_revision(engine)
        tables = set(inspect(engine).get_table_names())
        counts = _safe_table_counts(engine, tables)
        result["table_counts"] = counts
        result.update(_safe_observation_summary(engine, tables, counts))
        _add_legacy_count_aliases(result, counts)

        status = schema_revision_status(
            result["current_revision"], str(result["expected_revision"])
        )
        result["schema_status"] = status.value
        if status is not SchemaRevisionStatus.CURRENT:
            result["migration_required"] = status in {
                SchemaRevisionStatus.OUTDATED,
                SchemaRevisionStatus.UNVERSIONED,
            }
            result["reason"] = _schema_mismatch_reason(
                status,
                result["current_revision"],
                str(result["expected_revision"]),
            )
            result["summary"] = "FAIL"
            return result

        missing_tables = sorted(set(COUNTED_TABLES) - tables)
        if missing_tables:
            result["schema_status"] = "table_missing_unexpectedly"
            result["missing_tables"] = missing_tables
            result["reason"] = (
                "Database revision matches the application, but required tables "
                f"are missing: {', '.join(missing_tables)}. The migrated schema "
                "must be repaired or restored before the application can start."
            )
            result["summary"] = "FAIL"
            return result

        result.update(
            referential_integrity=repository.integrity_counts(),
        )
        integrity_ok = not any(result["referential_integrity"].values())
        if application_readiness:
            result["application_readiness"] = _application_readiness(engine)
        result["summary"] = (
            "PASS" if result["duplicate_slot_count"] == 0 and integrity_ok else "FAIL"
        )
    except Exception as exc:  # CLI boundary: report safely and return failure JSON.
        result["error"] = redact_database_urls(exc)
        result["summary"] = "FAIL"
    finally:
        engine.dispose()
    return result


def _safe_table_counts(engine: Engine, tables: set[str]) -> dict[str, int]:
    """Count known tables only when inspection proves they physically exist."""
    available = [name for name in COUNTED_TABLES if name in tables]
    with engine.connect() as connection:
        return {
            name: int(connection.scalar(text(f'SELECT COUNT(*) FROM "{name}"')) or 0)
            for name in available
        }


def _safe_observation_summary(
    engine: Engine, tables: set[str], counts: dict[str, int]
) -> dict[str, object]:
    """Read revision-stable observation metadata without selecting model columns."""
    result: dict[str, object] = {
        "observation_count": counts.get("observations", 0),
    }
    if "observations" not in tables:
        return result
    columns = {column["name"] for column in inspect(engine).get_columns("observations")}
    if "slot_utc" not in columns:
        return result
    with engine.connect() as connection:
        earliest, latest = connection.execute(
            text("SELECT MIN(slot_utc), MAX(slot_utc) FROM observations")
        ).one()
        duplicates = connection.scalar(
            text(
                "SELECT COUNT(*) FROM ("
                "SELECT slot_utc FROM observations GROUP BY slot_utc "
                "HAVING COUNT(*) > 1) AS duplicate_slots"
            )
        )
    result.update(
        earliest_observation=_iso(earliest),
        latest_observation=_iso(latest),
        latest_observation_age_seconds=(
            (datetime.now(UTC) - _aware(latest)).total_seconds() if latest else None
        ),
        duplicate_slot_count=int(duplicates or 0),
    )
    return result


def _add_legacy_count_aliases(
    result: dict[str, object], counts: dict[str, int]
) -> None:
    """Retain the established summary fields whenever their tables are available."""
    if "forecast_runs" in counts:
        result["forecast_run_count"] = counts["forecast_runs"]
    if "forecast_points" in counts:
        result["forecast_point_count"] = counts["forecast_points"]
    audit_names = (
        "observation_derivations",
        "ev_session_annotations",
        "ev_session_annotation_rows",
    )
    available_audits = {name: counts[name] for name in audit_names if name in counts}
    if available_audits:
        result["audit_record_counts"] = available_audits


def _schema_mismatch_reason(
    status: SchemaRevisionStatus, current: object, expected: str
) -> str:
    if status is SchemaRevisionStatus.OUTDATED:
        return (
            f"Database schema revision {current} is older than required revision "
            f"{expected}; an Alembic upgrade is required before this application "
            "version can start."
        )
    if status is SchemaRevisionStatus.UNVERSIONED:
        return (
            f"Database schema has no Alembic revision; migration or reviewed legacy "
            f"adoption to revision {expected} is required before startup."
        )
    return (
        f"Database schema revision {current} is ahead of or unknown to required "
        f"revision {expected}; use application code compatible with that schema."
    )


def _aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value):
    return _aware(value).isoformat() if value is not None else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--application-readiness", action="store_true")
    args = parser.parse_args()
    report = check_database(
        load_database_url(), application_readiness=args.application_readiness
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report["summary"] == "PASS" else 1


def _application_readiness(engine) -> dict[str, dict[str, object]]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    observation_columns = (
        {column["name"] for column in inspector.get_columns("observations")}
        if "observations" in tables
        else set()
    )
    requirements = {
        "collection": ({"observations"}, {"slot_utc", "observed_at_utc"}),
        "history_inspection": ({"observations"}, {"health_domains_json"}),
        "load_forecasting": (
            {"observations"},
            {"baseline_house_consumption_w", "baseline_training_eligible"},
        ),
        "reserve_estimation": (
            {"observations", "forecast_runs", "forecast_points"},
            {"battery_soc_percent", "baseline_house_consumption_w"},
        ),
        "forecast_storage": ({"forecast_runs", "forecast_points"}, set()),
        "ev_annotation": (
            {"observations", "ev_session_annotations", "ev_session_annotation_rows"},
            {"ev_session_id", "ev_power_w"},
        ),
        "vehicle_telemetry": (
            {"observations"},
            {
                "ev_vehicle_soc_percent",
                "ev_vehicle_battery_power_w_raw",
                "ev_plugged_in",
                "ev_vehicle_online",
                "ev_at_home",
                "ev_telemetry_updated_at_utc",
                "ev_telemetry_age_seconds",
                "ev_telemetry_fresh",
                "ev_vehicle_status",
            },
        ),
        "reprocessing": (
            {"observations", "observation_derivations"},
            {"derivation_model_version", "reprocessed_at_utc"},
        ),
    }
    result = {}
    for capability, (required_tables, required_columns) in requirements.items():
        missing_tables = sorted(required_tables - tables)
        missing_columns = sorted(required_columns - observation_columns)
        result[capability] = {
            "status": "PASS" if not missing_tables and not missing_columns else "FAIL",
            "missing_tables": missing_tables,
            "missing_observation_columns": missing_columns,
        }
    return result


if __name__ == "__main__":
    raise SystemExit(main())
