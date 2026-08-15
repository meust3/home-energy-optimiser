from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from energy_optimizer.collector import build_observation
from energy_optimizer.dashboard_api import DashboardService
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import alembic_config, current_revision
from energy_optimizer.db.models import (
    ForecastPointScore,
    ReserveOpportunityEvaluation,
    ReserveRun,
)
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.forecast_operations import (
    ForecastCoordinator,
    ForecastOperationsConfig,
    next_aligned_boundary,
)
from energy_optimizer.home_assistant_app import AppHealth
from energy_optimizer.models import ForecastPoint as ForecastPointModel
from energy_optimizer.models import ForecastRun as ForecastRunModel
from energy_optimizer.persistence import open_repository
from energy_optimizer.reserve import estimate_battery_reserve


def _url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def _repository_factory(path: Path):
    url = _url(path)
    repository = open_repository(url)
    repository.create_schema_for_tests()
    repository.close()
    return lambda: open_repository(url)


def test_options_are_disabled_and_conservative_by_default():
    options = ForecastOperationsConfig()
    assert options.enabled is False
    assert options.interval_minutes == 30
    assert options.horizon_hours == 24
    assert options.max_runtime_seconds == 120
    assert options.reserve_snapshot_enabled is True


def test_scheduler_repository_uses_bounded_postgresql_waits(monkeypatch):
    import energy_optimizer.persistence as persistence

    captured = {}
    original = create_database_engine

    def fake_engine(_url, **kwargs):
        captured.update(kwargs)
        return original("sqlite+pysqlite:///:memory:")

    monkeypatch.setattr(persistence, "create_database_engine", fake_engine)
    repository = persistence.open_bounded_forecast_repository(
        "postgresql+psycopg://example.invalid/db", max_runtime_seconds=120
    )
    repository.close()
    assert captured == {
        "connect_timeout_seconds": 10,
        "statement_timeout_ms": 30000,
    }


def test_scheduler_alignment_uses_brisbane_wall_clock():
    now = datetime(2026, 8, 11, 2, 14, 59, tzinfo=UTC)
    assert next_aligned_boundary(
        now, timezone_name="Australia/Brisbane", alignment_minutes=30
    ) == datetime(2026, 8, 11, 2, 30, tzinfo=UTC)


def test_single_claim_prevents_restart_duplicate(tmp_path, config):
    path = tmp_path / "operations.db"
    factory = _repository_factory(path)
    health = AppHealth(900)
    created = datetime(2026, 8, 11, 2, 30, tzinfo=UTC)
    coordinator = ForecastCoordinator(
        repository_factory=factory,
        collector_config=config,
        operations_config=ForecastOperationsConfig(
            enabled=True, reserve_snapshot_enabled=False
        ),
        health=health,
        clock=lambda: created,
    )
    assert coordinator.run_boundary(created)
    assert not coordinator.run_boundary(created)
    repository = factory()
    try:
        status = repository.forecast_operations_status_read_only()
        assert status["last_attempt"]["status"] == "success"
        assert status["last_attempt"]["forecast_point_count"] == 288
        assert len(repository.forecast_run_summaries_read_only()) == 1
    finally:
        repository.close()


def test_durable_lock_records_overlapping_boundary_as_skipped(config):
    values = {}

    class LockedRepository:
        def try_forecast_operation_lock(self):
            return False

        def claim_forecast_operation(self, **_kwargs):
            return 7

        def finish_forecast_operation(self, attempt_id, **kwargs):
            values.update(attempt_id=attempt_id, **kwargs)

        def release_forecast_operation_lock(self, _token):
            return None

        def close(self):
            return None

    boundary = datetime(2026, 8, 11, 2, 30, tzinfo=UTC)
    coordinator = ForecastCoordinator(
        repository_factory=LockedRepository,
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=True),
        health=AppHealth(900),
        clock=lambda: boundary,
    )
    assert not coordinator.run_boundary(boundary)
    assert values["attempt_id"] == 7
    assert values["status"] == "skipped"


def test_runtime_deadline_marks_attempt_failed(tmp_path, config):
    path = tmp_path / "timeout.db"
    factory = _repository_factory(path)
    health = AppHealth(900)
    boundary = datetime(2026, 8, 11, 2, 30, tzinfo=UTC)
    times = iter((0.0, 121.0, 122.0))
    coordinator = ForecastCoordinator(
        repository_factory=factory,
        collector_config=config,
        operations_config=ForecastOperationsConfig(
            enabled=True, max_runtime_seconds=120, reserve_snapshot_enabled=False
        ),
        health=health,
        clock=lambda: boundary,
        monotonic=lambda: next(times),
    )
    assert not coordinator.run_boundary(boundary)
    repository = factory()
    try:
        attempt = repository.forecast_operations_status_read_only()["last_attempt"]
        assert attempt["status"] == "failed"
        assert attempt["failure_summary"] == "Configured forecast runtime exceeded"
    finally:
        repository.close()


def test_stop_event_interrupts_wait_and_preserves_collector_grace(config):
    calls = []

    class RecoveryRepository:
        def recover_stale_forecast_operations(self, **_kwargs):
            return 0

        def close(self):
            return None

    class StopEvent:
        def is_set(self):
            return False

        def wait(self, delay):
            calls.append(delay)
            return True

    now = datetime(2026, 8, 11, 2, 14, 59, tzinfo=UTC)
    coordinator = ForecastCoordinator(
        repository_factory=RecoveryRepository,
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=True),
        health=AppHealth(900),
        clock=lambda: now,
    )
    coordinator.run(StopEvent())
    assert calls == [921.0]


def test_failure_isolated_from_collector_health(tmp_path, config):
    class BrokenRepository:
        def try_forecast_operation_lock(self):
            return True

        def release_forecast_operation_lock(self, _token):
            return None

        def claim_forecast_operation(self, **_kwargs):
            return 1

        def reserve_history_rows_read_only(self, **_kwargs):
            raise RuntimeError("secret detail")

        def finish_forecast_operation(self, *_args, **kwargs):
            assert kwargs["failure_summary"] == "RuntimeError during forecast operation"

        def close(self):
            return None

    health = AppHealth(900)
    boundary = datetime(2026, 8, 11, 2, 30, tzinfo=UTC)
    coordinator = ForecastCoordinator(
        repository_factory=BrokenRepository,
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=True),
        health=health,
        clock=lambda: boundary,
    )
    assert not coordinator.run_boundary(boundary)
    status, payload = health.response(now=boundary)
    assert status == 200
    assert payload["collector"] == "healthy"
    assert payload["forecast_scheduler"] == "warning"


def test_forecast_input_is_bounded_at_creation_time(config):
    captured = {}

    class Repository:
        def reserve_history_rows_read_only(self, **kwargs):
            captured.update(kwargs)
            return []

    created = datetime(2026, 8, 11, 2, 30, tzinfo=UTC)
    coordinator = ForecastCoordinator(
        repository_factory=lambda: None,
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=True),
        health=AppHealth(900),
    )
    run = coordinator._build_forecast(Repository(), created)
    assert captured["as_of"] == created
    assert run.created_at_utc == created
    assert run.horizon_end_utc - run.horizon_start_utc == timedelta(hours=24)
    assert run.metadata["run_kind"] == "genuine_out_of_sample"
    assert all(point.actual_value is None for point in run.points)


def test_scoring_delay_missing_health_metrics_and_immutability(
    tmp_path, config, healthy_states, now
):
    database_url = _url(tmp_path / "score.db")
    repository = DatabaseRepository(create_database_engine(database_url))
    repository.create_schema_for_tests()
    observation = build_observation(healthy_states, config, observed_at=now)
    repository.save_observation(observation)
    start = observation.slot_utc
    run_id = repository.save_forecast_run(
        ForecastRunModel(
            created_at_utc=start - timedelta(minutes=30),
            forecast_type="baseline_household_load",
            source="scheduled_forecast_operations",
            horizon_start_utc=start,
            horizon_end_utc=start + timedelta(minutes=15),
            model_version="test-model",
            metadata={"alignment_version": "full_5m_v1"},
            points=[
                ForecastPointModel(
                    period_start_utc=start,
                    period_end_utc=start + timedelta(minutes=5),
                    expected_value=1000,
                    unit="W",
                ),
                ForecastPointModel(
                    period_start_utc=start + timedelta(minutes=5),
                    period_end_utc=start + timedelta(minutes=10),
                    expected_value=2000,
                    unit="W",
                ),
            ],
        )
    )
    before = repository.forecast_run(run_id)
    assert (
        repository.score_completed_forecast_points(
            now=start + timedelta(minutes=14), delay_minutes=10
        )
        == 0
    )
    assert (
        repository.score_completed_forecast_points(
            now=start + timedelta(minutes=25), delay_minutes=10
        )
        == 2
    )
    after = repository.forecast_run(run_id)
    assert before == after
    with Session(repository.engine) as session:
        scores = list(
            session.scalars(
                select(ForecastPointScore).order_by(
                    ForecastPointScore.forecast_point_id
                )
            )
        )
    assert scores[0].actual_value == 1800
    assert scores[0].signed_error == 800
    assert scores[0].absolute_error == 800
    assert scores[0].squared_error == 640000
    assert scores[1].actual_value is None
    assert scores[1].missing_reason == "no_observation"
    rows = repository.forecast_accuracy_rows_read_only(
        after=start - timedelta(minutes=1),
        before=start + timedelta(hours=1),
    )
    assert len(rows) == 2
    response = DashboardService(database_url, AppHealth(900)).forecast_accuracy(
        range_name="24h", forecast_run_id=run_id, now=start + timedelta(minutes=30)
    )
    assert response.available
    assert response.metrics.sample_count == 1
    assert response.metrics.coverage_percent == 50
    assert response.metrics.mae == 800
    assert response.metrics.bias == 800
    assert response.metrics.rmse == 800
    assert "0-6h" in response.by_horizon


def test_full_reserve_result_and_opportunities_are_persisted(
    tmp_path, config, healthy_states, now
):
    database_url = _url(tmp_path / "reserve-audit.db")
    repository = DatabaseRepository(create_database_engine(database_url))
    repository.create_schema_for_tests()
    observation = build_observation(healthy_states, config, observed_at=now)
    repository.save_observation(observation)
    forecast_run_id = repository.save_forecast_run(
        ForecastRunModel(
            created_at_utc=now,
            forecast_type="baseline_household_load",
            source="scheduled_forecast_operations",
            horizon_start_utc=now,
            horizon_end_utc=now + timedelta(hours=24),
            model_version="test-model",
        )
    )
    estimate = estimate_battery_reserve(
        repository, config, now=now, source="history", as_of=now
    )
    reserve_id = repository.save_reserve_run(
        estimate,
        forecast_run_id=forecast_run_id,
        model_version="reserve-estimator-v1",
    )
    with Session(repository.engine) as session:
        stored = session.get(ReserveRun, reserve_id)
        opportunities = list(
            session.scalars(
                select(ReserveOpportunityEvaluation).where(
                    ReserveOpportunityEvaluation.reserve_run_id == reserve_id
                )
            )
        )
    assert stored.command_issued is False
    assert stored.estimate_json == estimate.model_dump(mode="json")
    assert stored.recommended_reserve_kwh == estimate.recommended_reserve_kwh
    assert stored.potentially_tradable_kwh == estimate.potentially_tradable_kwh
    assert len(opportunities) == len(estimate.evaluated_opportunities)
    service = DashboardService(database_url, AppHealth(900))
    latest = service.reserve_latest()
    assert latest.available
    assert latest.command_issued is False
    assert latest.potentially_tradable_energy_kwh == estimate.potentially_tradable_kwh
    history = service.reserve_history(range_name="24h", now=now + timedelta(hours=1))
    assert history.available
    assert history.runs[0]["command_issued"] is False


def test_dashboard_operations_empty_states_are_truthful(tmp_path):
    path = tmp_path / "empty-dashboard.db"
    database_url = _url(path)
    factory = _repository_factory(path)
    repository = factory()
    repository.close()
    health = AppHealth(900)
    service = DashboardService(database_url, health)
    operations = service.forecast_operations_status()
    accuracy = service.forecast_accuracy(
        range_name="7d", now=datetime(2026, 8, 11, tzinfo=UTC)
    )
    reserve = service.reserve_history(
        range_name="30d", now=datetime(2026, 8, 11, tzinfo=UTC)
    )
    assert operations.enabled is False
    assert operations.last_attempt is None
    assert not accuracy.available and accuracy.metrics.total_count == 0
    assert not reserve.available and reserve.runs == []


def test_migration_upgrade_downgrade_reupgrade_preserves_observations(tmp_path):
    path = tmp_path / "migration.db"
    url = _url(path)
    config = alembic_config(url)
    command.upgrade(config, "20260811_01")
    engine = create_database_engine(url)
    legacy_columns = {
        column["name"] for column in inspect(engine).get_columns("observations")
    }
    command.upgrade(config, "head")
    assert current_revision(engine) == "20260813_01"
    assert set(inspect(engine).get_table_names()) >= {
        "forecast_point_scores",
        "forecast_operation_attempts",
        "reserve_runs",
        "reserve_opportunity_evaluations",
        "forecast_accuracy_rollups",
        "forecast_maintenance_runs",
    }
    command.downgrade(config, "20260811_01")
    assert current_revision(engine) == "20260811_01"
    assert {
        column["name"] for column in inspect(engine).get_columns("observations")
    } == legacy_columns
    assert "reserve_runs" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert current_revision(engine) == "20260813_01"


def test_migration_compiles_reversible_postgresql_ddl():
    output = StringIO()
    config = alembic_config(
        "postgresql+psycopg://migration:placeholder@example.invalid/home_energy"
    )
    config.output_buffer = output
    command.upgrade(config, "20260811_01:20260812_01", sql=True)
    command.downgrade(config, "20260812_01:20260811_01", sql=True)
    sql = output.getvalue()
    for table in (
        "forecast_point_scores",
        "forecast_operation_attempts",
        "reserve_runs",
        "reserve_opportunity_evaluations",
    ):
        assert f"CREATE TABLE {table}" in sql
        assert f"DROP TABLE {table}" in sql
    assert "JSONB" in sql
    assert "DROP TABLE observations" not in sql
    assert "ALTER TABLE observations" not in sql


def test_v051_migration_compiles_reversible_postgresql_ddl():
    output = StringIO()
    config = alembic_config(
        "postgresql+psycopg://migration:placeholder@example.invalid/home_energy"
    )
    config.output_buffer = output
    command.upgrade(config, "20260812_01:20260813_01", sql=True)
    command.downgrade(config, "20260813_01:20260812_01", sql=True)
    sql = output.getvalue()
    for table in ("forecast_accuracy_rollups", "forecast_maintenance_runs"):
        assert f"CREATE TABLE {table}" in sql
        assert f"DROP TABLE {table}" in sql
    assert "DROP TABLE observations" not in sql
    assert "ALTER TABLE observations" not in sql


def test_no_hardware_or_home_assistant_write_surface():
    coordinator_methods = set(vars(ForecastCoordinator))
    assert not coordinator_methods & {"post", "put", "patch", "delete", "write_modbus"}
    assert ForecastOperationsConfig().enabled is False
