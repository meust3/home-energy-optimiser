"""Credential-safe database connectivity, revision, and integrity diagnostics."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from energy_optimizer.config import load_database_url
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import current_revision, expected_revision
from energy_optimizer.db.redaction import display_database_url, redact_database_urls
from energy_optimizer.db.repository import DatabaseRepository


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
    }
    try:
        result["connectivity"] = repository.ping()
        result["current_revision"] = current_revision(engine)
        counts = repository.table_counts()
        result["table_counts"] = counts.__dict__
        rows = repository.observation_rows()
        earliest = rows[0]["slot_utc"] if rows else None
        latest = rows[-1]["slot_utc"] if rows else None
        result.update(
            observation_count=counts.observations,
            earliest_observation=_iso(earliest),
            latest_observation=_iso(latest),
            latest_observation_age_seconds=(
                (datetime.now(UTC) - _aware(latest)).total_seconds() if latest else None
            ),
            duplicate_slot_count=repository.duplicate_slot_count(),
            referential_integrity=repository.integrity_counts(),
            forecast_run_count=counts.forecast_runs,
            forecast_point_count=counts.forecast_points,
            audit_record_counts={
                "observation_derivations": counts.observation_derivations,
                "ev_session_annotations": counts.ev_session_annotations,
                "ev_session_annotation_rows": counts.ev_session_annotation_rows,
            },
        )
        integrity_ok = not any(result["referential_integrity"].values())
        if application_readiness:
            result["application_readiness"] = _application_readiness(engine)
        result["summary"] = (
            "PASS"
            if result["current_revision"] == result["expected_revision"]
            and result["duplicate_slot_count"] == 0
            and integrity_ok
            else "FAIL"
        )
    except Exception as exc:  # CLI boundary: report safely and return failure JSON.
        result["error"] = redact_database_urls(exc)
        result["summary"] = "FAIL"
    finally:
        engine.dispose()
    return result


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
