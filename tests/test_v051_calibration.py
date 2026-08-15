import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import func, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from energy_optimizer.collector import build_observation
from energy_optimizer.dashboard_api import _retention_health
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import alembic_config, current_revision
from energy_optimizer.db.models import (
    ForecastAccuracyRollup,
    ForecastMaintenanceRun,
    ForecastPointScore,
    ReserveRun,
)
from energy_optimizer.db.models import (
    ForecastPoint as DBForecastPoint,
)
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.demand_forecast import forecast_household_demand
from energy_optimizer.estimator_comparison import EstimatorCase, compare_estimators
from energy_optimizer.forecast_alignment import (
    FULL_FIVE_MINUTE_ALIGNMENT,
    LEGACY_ALIGNMENT,
    operational_forecast_window,
)
from energy_optimizer.forecast_calibration import (
    CURRENT_FORECAST_MODEL_VERSION,
    CalibrationIdentity,
    calculate_forecast_calibration,
)
from energy_optimizer.forecast_operations import (
    ForecastCoordinator,
    ForecastOperationsConfig,
    build_reserve_forecast_reconciliation,
)
from energy_optimizer.forecast_retention import (
    inspect_forecast_retention,
    run_forecast_retention,
)
from energy_optimizer.historical_ev import (
    HistoricalEVCandidateConfig,
    detect_historical_ev_candidates,
)
from energy_optimizer.home_assistant_app import AppHealth
from energy_optimizer.models import ForecastPoint, ForecastRun
from energy_optimizer.persistence import open_repository
from energy_optimizer.reserve import estimate_battery_reserve
from energy_optimizer.training_provenance import (
    classify_training_cohort,
    summarize_training_provenance,
)


def test_operational_alignment_at_execution_offset_and_exact_boundary(config):
    created = datetime(2026, 8, 15, 0, 0, 20, tzinfo=UTC)
    window = operational_forecast_window(created, horizon_hours=24)
    assert window.start_utc == datetime(2026, 8, 15, 0, 5, tzinfo=UTC)
    assert window.end_utc - window.start_utc == timedelta(hours=24)

    class History:
        def reserve_history_rows_read_only(self, **_kwargs):
            return []

    coordinator = ForecastCoordinator(
        repository_factory=History,
        collector_config=config,
        operations_config=ForecastOperationsConfig(),
        health=AppHealth(900),
    )
    run = coordinator._build_forecast(History(), created)
    assert len(run.points) == 288
    assert run.created_at_utc == created
    assert run.horizon_start_utc == window.start_utc
    assert run.metadata["alignment_version"] == FULL_FIVE_MINUTE_ALIGNMENT
    assert all(point.period_start_utc >= created for point in run.points)
    assert all(point.period_start_utc.minute % 5 == 0 for point in run.points)
    assert all(
        point.period_end_utc - point.period_start_utc == timedelta(minutes=5)
        for point in run.points
    )
    exact = operational_forecast_window(created.replace(second=0), horizon_hours=24)
    assert exact.start_utc == created.replace(second=0)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {
                "ev_source": "byd_vehicle_cloud",
                "ev_telemetry_fresh": True,
                "ev_charging_active": False,
                "ev_detection_confidence": "direct_fresh",
            },
            "verified_non_ev",
        ),
        (
            {
                "ev_source": "byd_vehicle_cloud",
                "ev_telemetry_fresh": True,
                "ev_charging_active": True,
                "ev_detection_confidence": "direct_fresh",
            },
            "verified_ev_excluded",
        ),
        ({"ev_source": "charger", "ev_power_w": 7000}, "direct_ev_separated"),
        (
            {
                "ev_source": "manual_annotation",
                "baseline_exclusion_reason": "known_ev_session_without_ev_power",
            },
            "manual_historical_ev",
        ),
        (
            {"ev_source": "byd_vehicle_cloud", "ev_telemetry_fresh": False},
            "pre_ev_telemetry_unknown",
        ),
        ({"historical_ev_candidate": True}, "suspected_historical_ev"),
    ],
)
def test_training_cohort_classification(row, expected):
    assert classify_training_cohort(row) == expected


def test_mixed_selected_history_keeps_contamination_warning():
    now = datetime(2026, 8, 15, tzinfo=UTC)
    summary = summarize_training_provenance(
        all_rows=[],
        selected_rows=[
            (now, "verified_non_ev"),
            (now - timedelta(days=1), "pre_ev_telemetry_unknown"),
        ],
        policy="verified_preferred",
    )
    assert summary.verified_share == 0.5
    assert summary.unverified_share == 0.5
    assert summary.unidentified_ev_contamination_risk


def test_verified_preferred_uses_clean_exact_samples_and_falls_back_deterministically():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 31, 10, tzinfo=zone)
    rows = []
    for days, power, verified in (
        (7, 1000, True),
        (14, 1000, True),
        (21, 1000, True),
        (28, 9000, False),
    ):
        rows.append(
            {
                "observed_at_local": (start - timedelta(days=days)).isoformat(),
                "baseline_house_consumption_w": power,
                "telemetry_is_healthy": True,
                "baseline_training_eligible": True,
                "ev_source": "byd_vehicle_cloud" if verified else "none",
                "ev_telemetry_fresh": verified,
                "ev_charging_active": False if verified else None,
                "ev_detection_confidence": (
                    "direct_fresh" if verified else "unconfirmed"
                ),
            }
        )
    preferred = forecast_household_demand(
        rows,
        start_local=start,
        end_local=start + timedelta(minutes=5),
        minimum_samples=3,
        fallback_kw=2,
        training_policy="verified_preferred",
    )
    assert preferred.slot_decisions[0].estimated_power_kw == 1
    assert preferred.diagnostics.verified_share == 1
    assert not preferred.diagnostics.unidentified_ev_contamination_risk
    fallback = forecast_household_demand(
        rows[1:],
        start_local=start,
        end_local=start + timedelta(minutes=5),
        minimum_samples=3,
        fallback_kw=2,
        training_policy="verified_preferred",
    )
    assert fallback.slot_decisions[0].estimated_power_kw > 1
    assert fallback.diagnostics.unidentified_ev_contamination_risk
    assert "unverified_ev_history_caps_medium" in fallback.confidence_ceilings


def test_historical_ev_detector_is_conservative_and_unreviewed():
    start = datetime(2026, 7, 1, tzinfo=UTC)
    plateau = [
        {
            "slot_utc": start + timedelta(minutes=5 * index),
            "baseline_house_consumption_w": 9000 + (index % 2) * 100,
            "telemetry_is_healthy": True,
            "baseline_training_eligible": True,
        }
        for index in range(24)
    ]
    candidates = detect_historical_ev_candidates(
        plateau, config=HistoricalEVCandidateConfig()
    )
    assert len(candidates) == 1
    assert candidates[0].status == "unreviewed"
    assert candidates[0].estimated_energy_kwh > 15
    assert "oven or cooktop" in candidates[0].false_positive_risks
    short = detect_historical_ev_candidates(
        plateau[:3], config=HistoricalEVCandidateConfig()
    )
    assert short == []


def _calibration_rows(
    run_id: int,
    created: datetime,
    *,
    error: float = 100,
    count: int = 288,
    model_version: str = CURRENT_FORECAST_MODEL_VERSION,
    alignment: str = FULL_FIVE_MINUTE_ALIGNMENT,
    training_policy: str = "verified_preferred",
):
    return [
        {
            "forecast_run_id": run_id,
            "created_at_utc": created,
            "forecast_type": "baseline_household_load",
            "source": "scheduled_forecast_operations",
            "model_version": model_version,
            "run_metadata_json": {
                "alignment_version": alignment,
                "training_policy": training_policy,
            },
            "period_start_utc": created + timedelta(minutes=5 * (index + 1)),
            "period_end_utc": created + timedelta(minutes=5 * (index + 2)),
            "expected_value": 1000 + error,
            "actual_value": 1000,
            "actual_available": True,
            "health_eligible": True,
        }
        for index in range(count)
    ]


def test_calibration_metrics_status_horizons_energy_and_legacy_exclusion():
    created = datetime(2026, 8, 1, tzinfo=UTC)
    rows = _calibration_rows(1, created) + _calibration_rows(
        2, created + timedelta(minutes=30), count=1
    )
    rows.append(
        {
            **rows[0],
            "forecast_run_id": 99,
            "run_metadata_json": {"alignment_version": LEGACY_ALIGNMENT},
        }
    )
    report = calculate_forecast_calibration(rows)
    assert report.status == "good"
    assert report.metrics.bias_w == 100
    assert report.metrics.mae_w == 100
    assert report.metrics.rmse_w == 100
    assert report.complete_run_count == 1
    assert report.complete_run_energy[0].energy_bias_kwh == pytest.approx(2.4)
    assert set(report.metrics_by_horizon) == {"0-3h", "3-6h", "6-12h", "12-24h"}
    assert report.legacy_baseline_run_count == 1
    assert report.legacy_baseline_metrics.mae_w == 100


def test_current_calibration_identity_isolates_model_policy_and_alignment():
    created = datetime(2026, 8, 1, tzinfo=UTC)
    current = _calibration_rows(1, created, count=287)
    rows = (
        current
        + _calibration_rows(
            2,
            created + timedelta(days=1),
            error=9000,
            alignment=LEGACY_ALIGNMENT,
        )
        + _calibration_rows(
            3,
            created + timedelta(days=2),
            error=8000,
            model_version="future-model",
        )
        + _calibration_rows(
            4,
            created + timedelta(days=3),
            error=7000,
            training_policy="legacy_all_eligible",
        )
    )
    report = calculate_forecast_calibration(rows)
    assert report.status == "insufficient_data"
    assert report.eligible_run_count == 1
    assert report.metrics.total_points == 287
    assert report.metrics.mae_w == 100
    assert report.model_versions == [CURRENT_FORECAST_MODEL_VERSION]
    assert report.training_policies == ["verified_preferred"]
    assert report.legacy_baseline_metrics.mae_w == 9000

    future = calculate_forecast_calibration(
        rows,
        current_identity=CalibrationIdentity(
            forecast_type="baseline_household_load",
            model_version="future-model",
            alignment_version=FULL_FIVE_MINUTE_ALIGNMENT,
            training_policy="verified_preferred",
        ),
    )
    assert future.metrics.mae_w == 8000
    assert future.eligible_run_count == 1


def test_overlapping_points_alone_do_not_inflate_calibration_status():
    report = calculate_forecast_calibration(
        _calibration_rows(1, datetime(2026, 8, 1, tzinfo=UTC), count=287)
    )
    assert report.status == "insufficient_data"


def test_offline_estimators_use_identical_cases_and_do_not_change_production():
    cases = [
        EstimatorCase(
            training_values_w=[1000, 1100, 1200, 9000],
            actual_w=1100,
            horizon_hours=1,
            local_hour=8,
            day_type="weekday",
        ),
        EstimatorCase(
            training_values_w=[900, 1000, 1100, 8000],
            actual_w=1000,
            horizon_hours=4,
            local_hour=9,
            day_type="weekday",
        ),
    ]
    report = compare_estimators(cases)
    assert set(report.metrics) == {
        "arithmetic_mean",
        "median",
        "trimmed_mean_10",
        "winsorized_mean_10",
    }
    assert report.same_training_samples
    assert not report.production_estimator_changed
    assert report.metrics["median"].mae_w < report.metrics["arithmetic_mean"].mae_w


def test_retention_rolls_up_before_detail_deletion_and_is_daily_idempotent(
    tmp_path, healthy_states, config, now
):
    url = f"sqlite+pysqlite:///{(tmp_path / 'retention.db').as_posix()}"
    repository = DatabaseRepository(create_database_engine(url))
    repository.create_schema_for_tests()
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=now)
    )
    retention_now = datetime(2026, 8, 15, tzinfo=UTC)
    run = ForecastRun(
        created_at_utc=retention_now - timedelta(days=100),
        forecast_type="baseline_household_load",
        source="scheduled_forecast_operations",
        horizon_start_utc=retention_now - timedelta(days=100),
        horizon_end_utc=retention_now - timedelta(days=99),
        model_version="v051",
        metadata={
            "alignment_version": FULL_FIVE_MINUTE_ALIGNMENT,
            "training_policy": "verified_preferred",
        },
        points=[
            ForecastPoint(
                period_start_utc=retention_now - timedelta(days=100),
                period_end_utc=retention_now
                - timedelta(days=100)
                + timedelta(minutes=5),
                expected_value=1200,
                unit="W",
            )
        ],
    )
    run_id = repository.save_forecast_run(run)
    with repository.transaction() as session:
        point_id = session.scalar(
            select(DBForecastPoint.id).where(DBForecastPoint.forecast_run_id == run_id)
        )
        session.add(
            ForecastPointScore(
                forecast_point_id=point_id,
                scored_at_utc=retention_now - timedelta(days=99),
                actual_value=1000,
                absolute_error=200,
                signed_error=-200,
                squared_error=40000,
                actual_available=True,
                health_eligible=True,
                metadata_json={},
            )
        )
    result = run_forecast_retention(
        repository,
        now=retention_now,
        point_retention_days=90,
        run_retention_days=365,
    )
    assert result["points_deleted"] == 1
    assert repository.table_counts().forecast_runs == 1
    assert repository.table_counts().observations == 1
    with Session(repository.engine) as session:
        rollup = session.scalar(select(ForecastAccuracyRollup))
        assert rollup.eligible_points == 1
        assert session.scalar(select(DBForecastPoint.id)) is None
    assert (
        run_forecast_retention(
            repository,
            now=retention_now,
            point_retention_days=90,
            run_retention_days=365,
        )["status"]
        == "already_completed"
    )


def _seed_retention_detail(
    repository, *, retention_now: datetime, point_count: int
) -> None:
    remaining = point_count
    run_index = 0
    while remaining:
        count = min(remaining, 288)
        created = retention_now - timedelta(days=100, minutes=run_index)
        run_id = repository.save_forecast_run(
            ForecastRun(
                created_at_utc=created,
                forecast_type="baseline_household_load",
                source="scheduled_forecast_operations",
                horizon_start_utc=created,
                horizon_end_utc=created + timedelta(minutes=5 * count),
                model_version=CURRENT_FORECAST_MODEL_VERSION,
                metadata={
                    "alignment_version": FULL_FIVE_MINUTE_ALIGNMENT,
                    "training_policy": "verified_preferred",
                },
                points=[
                    ForecastPoint(
                        period_start_utc=created + timedelta(minutes=5 * index),
                        period_end_utc=created + timedelta(minutes=5 * (index + 1)),
                        expected_value=1100,
                        unit="W",
                    )
                    for index in range(count)
                ],
            )
        )
        with repository.transaction() as session:
            point_ids = list(
                session.scalars(
                    select(DBForecastPoint.id).where(
                        DBForecastPoint.forecast_run_id == run_id
                    )
                )
            )
            session.execute(
                insert(ForecastPointScore),
                [
                    {
                        "forecast_point_id": point_id,
                        "scored_at_utc": created + timedelta(days=1),
                        "actual_value": 1000,
                        "absolute_error": 100,
                        "signed_error": -100,
                        "squared_error": 10000,
                        "actual_available": True,
                        "health_eligible": True,
                        "missing_reason": None,
                        "metadata_json": {},
                    }
                    for point_id in point_ids
                ],
            )
        remaining -= count
        run_index += 1


def test_retention_daily_capacity_exceeds_steady_state_and_prunes_both_detail_tables(
    tmp_path,
):
    repository = DatabaseRepository(
        create_database_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'capacity.db').as_posix()}"
        )
    )
    repository.create_schema_for_tests()
    retention_now = datetime(2026, 8, 15, tzinfo=UTC)
    _seed_retention_detail(
        repository, retention_now=retention_now, point_count=13_824 + 288
    )
    result = run_forecast_retention(
        repository,
        now=retention_now,
        point_retention_days=90,
        run_retention_days=365,
    )
    assert result["detail_rows_eligible"] == {
        "forecast_points": 14_112,
        "forecast_point_scores": 14_112,
    }
    assert result["rows_pruned_this_run"] == {
        "forecast_points": 14_112,
        "forecast_point_scores": 14_112,
    }
    assert result["rows_remaining_eligible"] == {
        "forecast_points": 0,
        "forecast_point_scores": 0,
    }
    assert result["batches_executed"] == 3
    assert result["batch_size"] == 5000
    assert result["maximum_rows_per_run"] == 30_000
    assert result["estimated_daily_creation_rate"] == 13_824
    assert result["steady_state_capacity_ok"] is True


def test_retention_reports_backlog_and_commits_interrupted_batches(tmp_path):
    repository = DatabaseRepository(
        create_database_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'backlog.db').as_posix()}"
        )
    )
    repository.create_schema_for_tests()
    retention_now = datetime(2026, 8, 15, tzinfo=UTC)
    _seed_retention_detail(repository, retention_now=retention_now, point_count=25)
    calls = 0

    def should_stop() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    result = run_forecast_retention(
        repository,
        now=retention_now,
        point_retention_days=90,
        run_retention_days=365,
        batch_size=10,
        max_batches_per_table=3,
        estimated_daily_creation_rate=5,
        should_stop=should_stop,
    )
    assert result["status"] == "interrupted"
    assert result["rows_pruned_this_run"]["forecast_points"] == 10
    assert result["rows_remaining_eligible"]["forecast_points"] == 15
    assert result["batches_executed"] == 1
    with Session(repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(DBForecastPoint)) == 15
        assert (
            session.scalar(select(func.count()).select_from(ForecastPointScore)) == 15
        )
        audit = session.scalar(select(ForecastMaintenanceRun))
        assert audit.status == "failed"
        assert audit.rows_rolled_up == 10
        assert (
            session.scalar(select(func.sum(ForecastAccuracyRollup.total_points))) == 10
        )
    duplicate = run_forecast_retention(
        repository,
        now=retention_now,
        point_retention_days=90,
        run_retention_days=365,
        batch_size=10,
        max_batches_per_table=3,
        estimated_daily_creation_rate=5,
    )
    assert duplicate["status"] == "already_completed"
    assert duplicate["maintenance_status"] == "failed"


def test_retention_bounded_backlog_and_unhealthy_under_capacity_are_reported(
    tmp_path,
):
    repository = DatabaseRepository(
        create_database_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'bounded.db').as_posix()}"
        )
    )
    repository.create_schema_for_tests()
    retention_now = datetime(2026, 8, 15, tzinfo=UTC)
    _seed_retention_detail(repository, retention_now=retention_now, point_count=25)
    result = run_forecast_retention(
        repository,
        now=retention_now,
        point_retention_days=90,
        run_retention_days=365,
        batch_size=10,
        max_batches_per_table=2,
        estimated_daily_creation_rate=5,
    )
    assert result["rows_pruned_this_run"]["forecast_points"] == 20
    assert result["rows_remaining_eligible"]["forecast_points"] == 5
    assert result["maximum_rows_per_run"] == 20
    assert result["estimated_days_to_clear_backlog"] == 1

    inspection = inspect_forecast_retention(
        repository,
        now=retention_now + timedelta(days=1),
        point_retention_days=90,
        batch_size=10,
        max_batches_per_table=1,
        estimated_daily_creation_rate=11,
    )
    assert inspection["retention_diagnostics"]["steady_state_capacity_ok"] is False
    assert (
        inspection["retention_diagnostics"]["estimated_days_to_clear_backlog"] is None
    )
    assert (
        _retention_health(
            True, {"status": "success"}, inspection["retention_diagnostics"]
        )
        == "unhealthy_capacity"
    )


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for PostgreSQL retention compatibility",
)
def test_retention_multi_batch_is_postgresql_compatible():
    configured = os.environ["TEST_POSTGRES_URL"]
    schema = f"retention_{uuid.uuid4().hex}"
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
    repository = None
    try:
        command.upgrade(alembic_config(isolated_url), "head")
        repository = DatabaseRepository(create_database_engine(isolated_url))
        retention_now = datetime(2026, 8, 15, tzinfo=UTC)
        _seed_retention_detail(repository, retention_now=retention_now, point_count=25)
        result = run_forecast_retention(
            repository,
            now=retention_now,
            point_retention_days=90,
            run_retention_days=365,
            batch_size=10,
            max_batches_per_table=3,
            estimated_daily_creation_rate=5,
        )
        assert result["rows_pruned_this_run"] == {
            "forecast_points": 25,
            "forecast_point_scores": 25,
        }
        assert result["batches_executed"] == 3
        assert result["rows_remaining_eligible"]["forecast_points"] == 0
    finally:
        if repository is not None:
            repository.engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_scheduled_reserve_reconciles_alignment_gap_without_changing_288_points(
    tmp_path, healthy_states, config
):
    repository = DatabaseRepository(
        create_database_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'reserve-reconcile.db').as_posix()}"
        )
    )
    repository.create_schema_for_tests()
    created = datetime(2026, 8, 15, 0, 0, 20, tzinfo=UTC)
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=created)
    )
    coordinator = ForecastCoordinator(
        repository_factory=lambda: repository,
        collector_config=config,
        operations_config=ForecastOperationsConfig(),
        health=AppHealth(900),
    )
    run = coordinator._build_forecast(repository, created)
    estimate = estimate_battery_reserve(
        repository, config, now=created, source="history", as_of=created
    )
    reconciliation = build_reserve_forecast_reconciliation(estimate, run)
    assert reconciliation["alignment_gap_minutes"] == pytest.approx(4 + 40 / 60)
    assert reconciliation["alignment_gap_demand_kwh"] > 0
    assert reconciliation["linked_operational_point_count"] == 288
    assert reconciliation["linked_operational_points_are_full_five_minutes"] is True
    assert reconciliation["history_as_of_utc"] == created.isoformat()
    assert reconciliation["reconciliation_error_kwh"] == pytest.approx(0)
    assert reconciliation["shared_full_interval_reserve_demand_kwh"] == pytest.approx(
        reconciliation["shared_full_interval_linked_demand_kwh"], abs=0.001
    )
    components = (
        reconciliation["alignment_gap_demand_kwh"]
        + reconciliation["shared_full_interval_reserve_demand_kwh"]
        + reconciliation["reserve_only_boundary_demand_kwh"]
    )
    assert components == pytest.approx(
        reconciliation["reserve_expected_household_demand_kwh"], abs=0.001
    )

    exact_created = created.replace(second=0)
    exact_run = coordinator._build_forecast(repository, exact_created)
    exact_estimate = estimate_battery_reserve(
        repository,
        config,
        now=exact_created,
        source="history",
        as_of=exact_created,
    )
    exact = build_reserve_forecast_reconciliation(exact_estimate, exact_run)
    assert exact["alignment_gap_minutes"] == 0
    assert exact["alignment_gap_demand_kwh"] == 0
    assert exact["linked_operational_point_count"] == 288


def test_scheduled_coordinator_persists_reserve_alignment_reconciliation(
    tmp_path, healthy_states, config
):
    url = f"sqlite+pysqlite:///{(tmp_path / 'persisted-reconcile.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    created = datetime(2026, 8, 15, 0, 0, 20, tzinfo=UTC)
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=created)
    )
    repository.close()
    coordinator = ForecastCoordinator(
        repository_factory=lambda: open_repository(url),
        collector_config=config,
        operations_config=ForecastOperationsConfig(
            enabled=True, reserve_snapshot_enabled=True
        ),
        health=AppHealth(900),
        clock=lambda: created,
    )
    assert coordinator.run_boundary(created.replace(second=0))
    repository = open_repository(url)
    try:
        with Session(repository.engine) as session:
            stored = session.scalar(select(ReserveRun))
            reconciliation = stored.operational_context_json[
                "linked_forecast_reconciliation"
            ]
            assert reconciliation["alignment_gap_minutes"] == pytest.approx(4 + 40 / 60)
            assert reconciliation["reconciliation_error_kwh"] == pytest.approx(0)
            assert reconciliation["linked_operational_point_count"] == 288
            assert reconciliation[
                "linked_forecast_demand_is_not_added_to_reserve_total"
            ]
    finally:
        repository.close()


def test_v051_sqlite_migration_physical_round_trip(
    tmp_path, healthy_states, config, now
):
    url = f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    migration_config = alembic_config(url)
    command.upgrade(migration_config, "20260812_01")
    engine = create_database_engine(url)
    repository = DatabaseRepository(engine)
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=now)
    )
    with engine.connect() as connection:
        before = dict(
            connection.execute(text("SELECT * FROM observations")).mappings().one()
        )
    command.upgrade(migration_config, "20260813_01")
    assert current_revision(engine) == "20260813_01"
    assert {"forecast_accuracy_rollups", "forecast_maintenance_runs"} <= set(
        inspect(engine).get_table_names()
    )
    command.downgrade(migration_config, "20260812_01")
    assert current_revision(engine) == "20260812_01"
    assert "forecast_accuracy_rollups" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        after = dict(
            connection.execute(text("SELECT * FROM observations")).mappings().one()
        )
    assert after == before
    command.upgrade(migration_config, "20260813_01")
    assert current_revision(engine) == "20260813_01"
