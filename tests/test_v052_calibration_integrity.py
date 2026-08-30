import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from energy_optimizer.data_validation import materially_negative_household_demand
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import alembic_config, current_revision
from energy_optimizer.db.models import ForecastPoint as DBForecastPoint
from energy_optimizer.db.models import (
    ForecastPointScore,
    Observation,
    ObservationDerivation,
)
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.ev import calculate_baseline_load
from energy_optimizer.forecast_alignment import FULL_FIVE_MINUTE_ALIGNMENT
from energy_optimizer.forecast_calibration import (
    CURRENT_FORECAST_MODEL_VERSION,
    calculate_forecast_calibration,
    calculate_forecast_calibration_from_rollups,
)
from energy_optimizer.forecast_operations import _represented_calibration_rollup_dates
from energy_optimizer.forecast_retention import run_forecast_retention
from energy_optimizer.forecast_rollups import build_rollup_groups
from energy_optimizer.home_assistant_app import AppHealth
from energy_optimizer.household_demand_reclassification import (
    reclassify_invalid_household_demand,
)
from energy_optimizer.models import ForecastPoint, ForecastRun
from energy_optimizer.solar_diagnostics import calculate_solar_diagnostics


def _row(target, horizon_hours, prediction=1100, actual=1000, run_id=1):
    return {
        "id": run_id,
        "forecast_run_id": run_id,
        "created_at_utc": target - timedelta(hours=horizon_hours),
        "forecast_type": "baseline_household_load",
        "source": "scheduled_forecast_operations",
        "model_version": CURRENT_FORECAST_MODEL_VERSION,
        "run_metadata_json": {
            "alignment_version": FULL_FIVE_MINUTE_ALIGNMENT,
            "training_policy": "verified_preferred",
        },
        "period_start_utc": target,
        "period_end_utc": target + timedelta(minutes=5),
        "expected_value": prediction,
        "actual_value": actual,
        "actual_available": True,
        "health_eligible": True,
        "signed_error": actual - prediction,
        "absolute_error": abs(actual - prediction),
        "squared_error": (actual - prediction) ** 2,
    }


def _complete_dates(count=7, overlaps=2):
    rows = []
    # 14:00 UTC is local midnight in Australia/Brisbane.
    start = datetime(2026, 8, 2, 14, tzinfo=UTC)
    for day in range(count):
        for slot in range(288):
            target = start + timedelta(days=day, minutes=5 * slot)
            for horizon in (1, 4, 8, 18):
                for overlap in range(overlaps):
                    rows.append(
                        _row(
                            target,
                            horizon + overlap / 60,
                            run_id=day * 10_000 + slot * 10 + overlap,
                        )
                    )
    return rows


def test_overlapping_rows_are_separate_from_independent_evidence():
    report = calculate_forecast_calibration(_complete_dates())
    assert report.status == "good"
    assert report.complete_date_count == 7
    assert report.raw_row_metrics.eligible_points == 7 * 288 * 4 * 2
    assert report.metrics.eligible_points == 7 * 288 * 4
    assert report.metrics.mae_w == 100
    assert report.metrics.bias_w == 100
    assert report.metrics.rmse_w == 100
    assert report.metrics.wape_percent == 10
    assert report.independent_evidence_sufficient
    assert report.raw_prediction_row_count == 7 * 288 * 4 * 2
    assert report.unique_actual_target_slot_count == 7 * 288
    assert report.distinct_local_date_count == 7


def test_complete_date_requires_95_percent_coverage_in_every_horizon():
    rows = _complete_dates(overlaps=1)
    start = datetime(2026, 8, 2, 14, tzinfo=UTC)
    for row in rows:
        horizon = (
            row["period_start_utc"] - row["created_at_utc"]
        ).total_seconds() / 3600
        slot = int((row["period_start_utc"] - start).total_seconds() / 300) % 288
        if horizon >= 12 and slot < 20:
            row["health_eligible"] = False
    report = calculate_forecast_calibration(rows)
    assert report.complete_date_count == 0
    assert report.status == "insufficient_data"


def test_daily_underforecast_does_not_count_the_actual_once_per_horizon():
    rows = _complete_dates(overlaps=1)
    for row in rows:
        row["expected_value"] = 900
        row["actual_value"] = 1000
    report = calculate_forecast_calibration(rows)
    assert report.p95_cumulative_underforecast_kwh == pytest.approx(2.4)
    assert report.cumulative_underforecast_kwh == pytest.approx(7 * 2.4)


def test_three_dates_and_explicit_truncation_never_calibrate():
    report = calculate_forecast_calibration(
        _complete_dates(count=3, overlaps=8), truncated=True
    )
    assert report.status == "provisional"
    assert "calibration_query_truncated" in report.quality_blocks
    assert not report.independent_evidence_sufficient


def test_exact_misleading_25000_row_overlap_scenario_remains_insufficient():
    start = datetime(2026, 8, 2, 14, tzinfo=UTC)
    rows = []
    for index in range(25_000):
        target_index = index % 514
        target = start + timedelta(minutes=5 * target_index)
        rows.append(_row(target, (1, 4, 8, 18)[index % 4], run_id=index + 1))
    report = calculate_forecast_calibration(rows)
    assert report.raw_row_metrics.total_points == 25_000
    assert report.complete_date_count < 7
    assert report.status in {"insufficient_data", "provisional"}
    assert not report.independent_evidence_sufficient


@pytest.mark.parametrize(
    ("value", "invalid"),
    [(100.0, False), (0.0, False), (-0.0, False), (-0.5, False), (-607.0, True)],
)
def test_negative_household_demand_tolerance(value, invalid):
    assert materially_negative_household_demand(value) is invalid
    baseline, eligible, reason = calculate_baseline_load(
        value, ev_charging_active=False, ev_power_w=None
    )
    if invalid:
        assert baseline is None
        assert not eligible
        assert reason == "invalid_negative_household_demand"
    else:
        assert baseline == max(value, 0)
        assert eligible


def test_app_health_exposes_current_negative_demand_diagnostic():
    health = AppHealth(900)
    timestamp = datetime.now(UTC)
    health.record_success(
        SimpleNamespace(
            slot_utc=timestamp,
            baseline_exclusion_reason="invalid_negative_household_demand",
        )
    )
    _, payload = health.response(now=timestamp)
    assert payload["invalid_household_demand"] == "current_invalid"


def test_rollup_is_identity_date_horizon_specific_and_slot_weighted():
    target = datetime(2026, 8, 3, tzinfo=UTC)
    groups = build_rollup_groups(
        [_row(target, 1, 900, run_id=1), _row(target, 1.5, 1100, run_id=2)]
    )
    assert len(groups) == 1
    key, value = next(iter(groups.items()))
    assert key[0] == date(2026, 8, 3)
    assert key[5] == "0-3h"
    assert value["total_points"] == 2
    assert value["eligible_target_slots"] == 1
    assert value["date_unique_target_slots"] == 1
    assert value["date_eligible_target_slots"] == 1
    assert value["slot_sum_forecast_w"] == 1000
    assert value["slot_sum_absolute_error_w"] == 0


def test_migrated_default_rollups_are_not_treated_as_v052_backfill():
    day = date(2026, 8, 3)
    rows = [
        {
            "rollup_date": day,
            "forecast_type": "baseline_household_load",
            "model_version": CURRENT_FORECAST_MODEL_VERSION,
            "alignment_version": FULL_FIVE_MINUTE_ALIGNMENT,
            "training_policy": "verified_preferred",
            "horizon_bucket": horizon,
            "complete_day": False,
            "calculated_at_utc": None,
        }
        for horizon in ("0-3h", "3-6h", "6-12h", "12-24h")
    ]
    assert not _represented_calibration_rollup_dates(
        rows, training_policy="verified_preferred"
    )
    report = calculate_forecast_calibration_from_rollups(rows)
    assert report.rollup_row_count == 4
    assert report.calculated_rollup_row_count == 0
    assert report.rollup_completeness_percent == 0
    assert "rollup_backfill_incomplete" in report.quality_blocks


def test_solar_diagnostics_integrate_five_minute_power_and_remain_cautious():
    start = datetime(2026, 8, 3, tzinfo=UTC)
    rows = []
    for index in range(288):
        rows.append(
            {
                "observed_at_local": start + timedelta(minutes=5 * index),
                "pv_power_w": 1000,
                "telemetry_is_healthy": True,
                "battery_soc_percent": 50,
                "grid_export_power_w": 0,
                "solcast_today_kwh_json": {
                    "estimate10": 20,
                    "estimate": 24,
                    "estimate90": 28,
                },
            }
        )
    result = calculate_solar_diagnostics(rows)[0]
    assert result["actual_pv_kwh"] == 24
    assert result["actual_in_solcast_range"] is True
    assert result["classification"] == "likely_unconstrained"
    assert "does not prove curtailment" in result["interpretation"]


def test_solar_overprediction_with_near_full_battery_is_context_not_derating():
    start = datetime(2026, 8, 3, tzinfo=UTC)
    rows = [
        {
            "observed_at_local": start + timedelta(minutes=5 * index),
            "pv_power_w": 500,
            "telemetry_is_healthy": True,
            "battery_soc_percent": 99 if index < 24 else 60,
            "grid_export_power_w": 200,
            "solcast_today_kwh_json": {
                "estimate10": 20,
                "estimate": 30,
                "estimate90": 40,
            },
        }
        for index in range(288)
    ]
    result = calculate_solar_diagnostics(rows)[0]
    assert result["actual_pv_kwh"] == 12
    assert result["classification"] == "possible_battery_saturation"
    assert result["actual_minus_p50_kwh"] == -18
    assert "no automatic Solcast derating" in result["interpretation"]


def test_retention_without_proven_rollup_coverage_fails_closed(tmp_path):
    repository = DatabaseRepository(
        create_database_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'empty.db').as_posix()}"
        )
    )
    repository.create_schema_for_tests()
    old = datetime(2026, 1, 1, tzinfo=UTC)
    repository.save_forecast_run(
        ForecastRun(
            created_at_utc=old,
            forecast_type="baseline_household_load",
            source="scheduled_forecast_operations",
            horizon_start_utc=old,
            horizon_end_utc=old + timedelta(minutes=5),
            model_version=CURRENT_FORECAST_MODEL_VERSION,
            metadata={
                "alignment_version": FULL_FIVE_MINUTE_ALIGNMENT,
                "training_policy": "verified_preferred",
            },
            points=[
                ForecastPoint(
                    period_start_utc=old,
                    period_end_utc=old + timedelta(minutes=5),
                    expected_value=1000,
                    unit="W",
                )
            ],
        )
    )
    result = run_forecast_retention(
        repository,
        now=datetime(2026, 8, 23, tzinfo=UTC),
        point_retention_days=90,
        run_retention_days=365,
    )
    assert result["status"] == "blocked_missing_rollup_coverage"
    assert result["rows_pruned_this_run"]["forecast_points"] == 0
    assert result["rows_remaining_eligible"]["forecast_points"] == 1


def test_current_negative_actual_gets_explicit_ineligible_score(tmp_path):
    repository = DatabaseRepository(
        create_database_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'negative-score.db').as_posix()}"
        )
    )
    repository.create_schema_for_tests()
    timestamp = datetime(2026, 8, 1, tzinfo=UTC)
    with repository.transaction() as session:
        session.add(
            Observation(
                slot_utc=timestamp,
                collected_at_utc=timestamp,
                observed_at_local=timestamp,
                house_consumption_w=-607,
                amber_import_forecast_json=[],
                amber_export_forecast_json=[],
                is_healthy=False,
                health_score=80,
                health_issues_json=[],
                telemetry_is_healthy=False,
                telemetry_health_score=80,
                baseline_house_consumption_w=None,
                baseline_training_eligible=False,
                baseline_exclusion_reason="invalid_negative_household_demand",
            )
        )
    run_id = repository.save_forecast_run(
        ForecastRun(
            created_at_utc=timestamp - timedelta(hours=1),
            forecast_type="baseline_household_load",
            source="scheduled_forecast_operations",
            horizon_start_utc=timestamp,
            horizon_end_utc=timestamp + timedelta(minutes=5),
            model_version=CURRENT_FORECAST_MODEL_VERSION,
            metadata={
                "alignment_version": FULL_FIVE_MINUTE_ALIGNMENT,
                "training_policy": "verified_preferred",
            },
            points=[
                ForecastPoint(
                    period_start_utc=timestamp,
                    period_end_utc=timestamp + timedelta(minutes=5),
                    expected_value=1000,
                    unit="W",
                )
            ],
        )
    )
    assert (
        repository.score_completed_forecast_points(
            now=timestamp + timedelta(hours=1), delay_minutes=10
        )
        == 1
    )
    with Session(repository.engine) as session:
        point_id = session.scalar(
            select(DBForecastPoint.id).where(DBForecastPoint.forecast_run_id == run_id)
        )
        score = session.get(ForecastPointScore, point_id)
        assert score.actual_value == -607
        assert score.actual_available
        assert not score.health_eligible
        assert score.signed_error is None
        assert score.missing_reason == "invalid_actual_negative_household_demand"


def test_historical_negative_reclassification_is_guarded_and_idempotent(tmp_path):
    repository = DatabaseRepository(
        create_database_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'reclassify.db').as_posix()}"
        )
    )
    repository.create_schema_for_tests()
    timestamp = datetime(2026, 8, 1, tzinfo=UTC)
    with repository.transaction() as session:
        session.add(
            Observation(
                slot_utc=timestamp,
                collected_at_utc=timestamp,
                observed_at_local=timestamp,
                house_consumption_w=-607,
                amber_import_forecast_json=[],
                amber_export_forecast_json=[],
                is_healthy=True,
                health_score=100,
                health_issues_json=[],
                telemetry_is_healthy=True,
                telemetry_health_score=100,
                baseline_house_consumption_w=-607,
                baseline_training_eligible=True,
            )
        )
    dry = reclassify_invalid_household_demand(repository)
    assert dry["mode"] == "dry_run" and dry["affected_observations"] == 1
    with Session(repository.engine) as session:
        assert session.get(Observation, timestamp).baseline_training_eligible
    with pytest.raises(ValueError, match="backup-verified"):
        reclassify_invalid_household_demand(repository, apply=True)
    applied = reclassify_invalid_household_demand(
        repository, apply=True, backup_verified=True, now=timestamp
    )
    assert applied["changed_observations"] == 1
    again = reclassify_invalid_household_demand(
        repository, apply=True, backup_verified=True, now=timestamp
    )
    assert again["changed_observations"] == 0
    with Session(repository.engine) as session:
        row = session.get(Observation, timestamp)
        assert row.house_consumption_w == -607
        assert not row.is_healthy
        assert row.baseline_house_consumption_w is None
        assert not row.baseline_training_eligible
        assert row.baseline_exclusion_reason == "invalid_negative_household_demand"
        assert (
            session.scalar(select(func.count()).select_from(ObservationDerivation)) == 1
        )


def test_v052_migration_upgrade_downgrade_reupgrade_preserves_rollup(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, "20260813_01")
    engine = create_database_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO forecast_accuracy_rollups "
                "(rollup_date, forecast_type, model_version, alignment_version, "
                "training_policy, horizon_bucket, day_type, eligible_points, "
                "missing_points, total_points, sum_signed_error, "
                "sum_absolute_error, sum_squared_error, forecast_energy_kwh, "
                "actual_energy_kwh) VALUES "
                "('2026-08-01','baseline_household_load','model','full_5m_v1',"
                "'verified_preferred','0-3h','weekend',1,0,1,-100,100,10000,"
                "0.1,0.09)"
            )
        )
    command.upgrade(config, "20260814_01")
    assert current_revision(engine) == "20260814_01"
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("forecast_accuracy_rollups")
    }
    assert "eligible_target_slots" in columns
    assert "date_unique_target_slots" in columns
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT COUNT(*) FROM forecast_accuracy_rollups"))
            == 1
        )
    command.downgrade(config, "20260813_01")
    assert current_revision(engine) == "20260813_01"
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("forecast_accuracy_rollups")
    }
    assert "eligible_target_slots" not in columns
    assert "date_unique_target_slots" not in columns
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT COUNT(*) FROM forecast_accuracy_rollups"))
            == 1
        )
    command.upgrade(config, "20260814_01")
    assert current_revision(engine) == "20260814_01"
    engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for PostgreSQL migration compatibility",
)
def test_v052_postgresql_populated_migration_round_trip():
    configured = os.environ["TEST_POSTGRES_URL"]
    schema = f"v052_migration_{uuid.uuid4().hex}"
    admin_engine = create_database_engine(configured)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    parsed = make_url(configured)
    query = dict(parsed.query)
    existing_options = query.get("options", "").strip()
    query["options"] = " ".join(
        value for value in (existing_options, f"-csearch_path={schema}") if value
    )
    isolated_url = parsed.set(query=query).render_as_string(hide_password=False)
    engine = None
    try:
        config = alembic_config(isolated_url)
        command.upgrade(config, "20260813_01")
        engine = create_database_engine(isolated_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO forecast_accuracy_rollups "
                    "(rollup_date, forecast_type, model_version, alignment_version, "
                    "training_policy, horizon_bucket, day_type, eligible_points, "
                    "missing_points, total_points, sum_signed_error, "
                    "sum_absolute_error, sum_squared_error, forecast_energy_kwh, "
                    "actual_energy_kwh) VALUES "
                    "('2026-08-01','baseline_household_load','model','full_5m_v1',"
                    "'verified_preferred','0-3h','weekend',1,0,1,-100,100,10000,"
                    "0.1,0.09)"
                )
            )
        command.upgrade(config, "20260814_01")
        assert current_revision(engine) == "20260814_01"
        assert "date_unique_target_slots" in {
            column["name"]
            for column in inspect(engine).get_columns("forecast_accuracy_rollups")
        }
        command.downgrade(config, "20260813_01")
        assert current_revision(engine) == "20260813_01"
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT COUNT(*) FROM forecast_accuracy_rollups")
                )
                == 1
            )
        command.upgrade(config, "20260814_01")
        assert current_revision(engine) == "20260814_01"
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
