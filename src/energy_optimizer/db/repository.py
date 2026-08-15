"""Transactional repository shared by SQLite and PostgreSQL."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import Engine, String, cast, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from energy_optimizer.db.engine import translate_database_error
from energy_optimizer.db.models import (
    Base,
    EVSessionAnnotation,
    EVSessionAnnotationRow,
    ForecastAccuracyRollup,
    ForecastMaintenanceRun,
    ForecastOperationAttempt,
    ForecastPoint,
    ForecastPointScore,
    ForecastRun,
    Observation,
    ObservationDerivation,
    ReserveOpportunityEvaluation,
    ReserveRun,
)
from energy_optimizer.forecast_alignment import (
    FULL_FIVE_MINUTE_ALIGNMENT,
)
from energy_optimizer.forecast_alignment import (
    alignment_version as forecast_alignment_version,
)
from energy_optimizer.history_analysis import (
    calculate_gap_report,
    summarize_health_issues,
)
from energy_optimizer.models import EnergyObservation
from energy_optimizer.models import ForecastRun as ForecastRunModel


class DuplicateResult(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class DatabaseCounts:
    observations: int
    forecast_runs: int
    forecast_points: int
    observation_derivations: int
    ev_session_annotations: int
    ev_session_annotation_rows: int
    forecast_point_scores: int = 0
    forecast_operation_attempts: int = 0
    reserve_runs: int = 0
    reserve_opportunity_evaluations: int = 0
    forecast_accuracy_rollups: int = 0
    forecast_maintenance_runs: int = 0


class DatabaseRepository:
    """Keep SQLAlchemy sessions and dialect choices out of application services."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @property
    def backend(self) -> str:
        return self.engine.dialect.name

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        session = Session(self.engine, expire_on_commit=False)
        try:
            with session.begin():
                yield session
        except DBAPIError as exc:
            raise translate_database_error(exc) from None
        finally:
            session.close()

    def create_schema_for_tests(self) -> None:
        """Create tables only for isolated tests; deployments must use Alembic."""
        Base.metadata.create_all(self.engine)

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    def try_forecast_operation_lock(self) -> Any:
        """Hold a PostgreSQL session advisory lock for one whole operation."""
        if self.backend != "postgresql":
            return True
        connection = self.engine.connect()
        acquired = bool(
            connection.scalar(text("SELECT pg_try_advisory_lock(726205005001)"))
        )
        if not acquired:
            connection.close()
            return False
        return connection

    def release_forecast_operation_lock(self, token: Any) -> None:
        if self.backend == "postgresql" and token is not None and token is not False:
            try:
                token.execute(text("SELECT pg_advisory_unlock(726205005001)"))
            finally:
                token.close()

    def save_observation(self, observation: EnergyObservation) -> DuplicateResult:
        values = observation_values(observation)
        with self.transaction() as session:
            existed = session.execute(
                select(Observation.slot_utc).where(
                    Observation.slot_utc == observation.slot_utc
                )
            ).first()
            statement = self._observation_upsert(values)
            session.execute(statement)
        return DuplicateResult.UPDATED if existed else DuplicateResult.INSERTED

    save = save_observation

    def _observation_upsert(self, values: Mapping[str, Any]):
        table = Observation.__table__
        if self.backend == "postgresql":
            statement = postgresql_insert(table).values(**values)
        elif self.backend == "sqlite":
            statement = sqlite_insert(table).values(**values)
        else:
            raise ValueError(f"Unsupported database backend: {self.backend}")
        updates = {key: statement.excluded[key] for key in values if key != "slot_utc"}
        return statement.on_conflict_do_update(
            index_elements=[table.c.slot_utc], set_=updates
        )

    def _slot_value(self, value: datetime | str):
        """Preserve legacy SQLite ISO keys while using typed PostgreSQL timestamps."""
        if self.backend == "sqlite":
            return (
                select(cast(Observation.slot_utc, String))
                .where(
                    func.datetime(Observation.slot_utc) == func.datetime(_iso(value))
                )
                .scalar_subquery()
            )
        return _as_datetime(value)

    def observation_rows(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        columns: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        table = Observation.__table__
        allowed = set(table.c.keys())
        selected = columns or tuple(table.c.keys())
        if not selected or any(name not in allowed for name in selected):
            raise ValueError("Unknown or empty observation column selection")
        statement = select(*(table.c[name] for name in selected))
        if start is not None:
            statement = statement.where(Observation.slot_utc >= start.astimezone(UTC))
        if end is not None:
            statement = statement.where(Observation.slot_utc <= end.astimezone(UTC))
        statement = statement.order_by(Observation.slot_utc)
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    def dashboard_observation_rows_read_only(
        self,
        *,
        start: datetime,
        end: datetime,
        columns: tuple[str, ...],
        limit: int = 9000,
    ) -> list[dict[str, Any]]:
        """Return one explicitly bounded dashboard observation range."""
        _require_aware(start)
        _require_aware(end)
        if start >= end:
            raise ValueError("dashboard observation start must precede end")
        if limit < 1 or limit > 9000:
            raise ValueError("dashboard observation limit must be 1-9000")
        table = Observation.__table__
        allowed = set(table.c.keys())
        if not columns or any(name not in allowed for name in columns):
            raise ValueError("Unknown or empty dashboard observation columns")
        statement = (
            select(*(table.c[name] for name in columns))
            .where(
                Observation.slot_utc >= start.astimezone(UTC),
                Observation.slot_utc <= end.astimezone(UTC),
            )
            .order_by(Observation.slot_utc)
            .limit(limit)
        )
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    list_observations = observation_rows
    observation_range = observation_rows

    def observation_columns(self) -> tuple[str, ...]:
        return tuple(Observation.__table__.c.keys())

    def latest_observation(self) -> dict[str, Any] | None:
        statement = (
            select(Observation.__table__).order_by(Observation.slot_utc.desc()).limit(1)
        )
        with Session(self.engine) as session:
            row = session.execute(statement).mappings().first()
            return dict(row) if row else None

    latest_observation_read_only = latest_observation

    def observation_as_of_read_only(
        self, as_of: datetime | None = None
    ) -> dict[str, Any] | None:
        statement = select(Observation.__table__)
        if as_of is not None:
            _require_aware(as_of)
            statement = statement.where(Observation.slot_utc <= as_of.astimezone(UTC))
        statement = statement.order_by(Observation.slot_utc.desc()).limit(1)
        with Session(self.engine) as session:
            row = session.execute(statement).mappings().first()
            return dict(row) if row else None

    def healthy_load_samples(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict[str, Any]]:
        statement = select(Observation.__table__).where(
            Observation.telemetry_is_healthy.is_(True),
            Observation.baseline_training_eligible.is_(True),
            Observation.baseline_house_consumption_w.is_not(None),
        )
        if start is not None:
            statement = statement.where(Observation.slot_utc >= start.astimezone(UTC))
        if end is not None:
            statement = statement.where(Observation.slot_utc <= end.astimezone(UTC))
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    eligible_baseline_observations = healthy_load_samples

    def healthy_load_samples_read_only(
        self, *, days: int, now: datetime, as_of: datetime | None = None
    ) -> list[dict[str, Any]]:
        end = (as_of or now).astimezone(UTC)
        return [
            {
                "observed_at_local": row["observed_at_local"],
                "house_consumption_w": row["baseline_house_consumption_w"],
            }
            for row in self.healthy_load_samples(
                start=end - timedelta(days=days), end=end
            )
        ]

    def reserve_history_rows_read_only(
        self, *, days: int, now: datetime, as_of: datetime | None = None
    ) -> list[dict[str, Any]]:
        end = (as_of or now).astimezone(UTC)
        columns = (
            "slot_utc",
            "observed_at_local",
            "telemetry_is_healthy",
            "baseline_training_eligible",
            "baseline_exclusion_reason",
            "baseline_house_consumption_w",
            "ev_power_w",
            "ev_source",
            "ev_charging_active",
            "ev_session_id",
            "ev_telemetry_fresh",
            "ev_detection_confidence",
            "ev_vehicle_status",
        )
        return self.observation_rows(
            start=end - timedelta(days=days), end=end, columns=columns
        )

    def power_sign_samples(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict[str, Any]]:
        return self.observation_rows(
            start=start,
            end=end,
            columns=(
                "slot_utc",
                "pv_power_w",
                "house_consumption_w",
                "grid_power_w",
                "battery_power_w",
                "battery_mode",
            ),
        )

    flow_history = observation_rows

    def summary(self, *, days: int | None = None, limit: int = 10) -> dict[str, Any]:
        end = datetime.now(UTC)
        start = end - timedelta(days=days) if days is not None else None
        rows = self.observation_rows(start=start)
        domains = ("telemetry", "price", "solar", "weather", "flow")
        missing_columns = (
            "battery_soc_percent",
            "battery_power_w",
            "pv_power_w",
            "house_consumption_w",
            "grid_power_w",
            "amber_import_price_per_kwh",
            "amber_export_price_per_kwh",
        )
        hourly: dict[int, list[float]] = {}
        weekday: dict[int, list[float]] = {}
        for row in rows:
            local = _as_datetime(row["observed_at_local"])
            value = row["house_consumption_w"]
            if value is not None:
                hourly.setdefault(local.hour, []).append(float(value) / 1000)
            if value is not None and row["telemetry_is_healthy"]:
                weekday.setdefault(local.weekday(), []).append(float(value) / 1000)
        health_rows = []
        for row in rows:
            item = dict(row)
            item["overall_health_score"] = item.get("health_score")
            health_rows.append(item)
        return {
            "database_path": str(self.engine.url.render_as_string(hide_password=True)),
            "total": len(rows),
            "healthy": sum(bool(row["is_healthy"]) for row in rows),
            "unhealthy": sum(not bool(row["is_healthy"]) for row in rows),
            "health_domains": {
                domain: {
                    "healthy": sum(bool(row[f"{domain}_is_healthy"]) for row in rows),
                    "unhealthy": sum(
                        not bool(row[f"{domain}_is_healthy"]) for row in rows
                    ),
                }
                for domain in domains
            },
            "earliest": _iso(rows[0]["slot_utc"]) if rows else None,
            "latest": _iso(rows[-1]["slot_utc"]) if rows else None,
            "missing": {
                name: sum(row[name] is None for row in rows) for name in missing_columns
            },
            "average_house_kw_by_hour": [
                {
                    "hour": hour,
                    "average_kw": sum(values) / len(values),
                    "samples": len(values),
                }
                for hour, values in sorted(hourly.items())
            ],
            "average_house_kw_by_weekday": [
                {
                    "day_of_week": day,
                    "average_kw": sum(values) / len(values),
                    "samples": len(values),
                }
                for day, values in sorted(weekday.items())
            ],
            "recent": [dict(row) for row in reversed(rows[-limit:])],
            "gap_report": calculate_gap_report(
                [_as_datetime(row["slot_utc"]) for row in rows],
                start=start,
                end=end if days is not None else None,
            ),
            "health_issue_summary": summarize_health_issues(health_rows),
        }

    def save_forecast_run(self, run: ForecastRunModel) -> int:
        """Atomically insert one immutable run and all of its points."""
        run_values = {
            "created_at_utc": run.created_at_utc.astimezone(UTC),
            "forecast_type": run.forecast_type,
            "source": run.source,
            "horizon_start_utc": run.horizon_start_utc.astimezone(UTC),
            "horizon_end_utc": run.horizon_end_utc.astimezone(UTC),
            "model_version": run.model_version,
            "metadata_json": run.metadata,
        }
        with self.transaction() as session:
            result = session.execute(
                insert(ForecastRun.__table__)
                .values(**run_values)
                .returning(ForecastRun.id)
            )
            run_id = int(result.scalar_one())
            if run.points:
                session.execute(
                    insert(ForecastPoint.__table__),
                    [
                        {
                            "forecast_run_id": run_id,
                            "period_start_utc": point.period_start_utc.astimezone(UTC),
                            "period_end_utc": point.period_end_utc.astimezone(UTC),
                            "expected_value": point.expected_value,
                            "lower_value": point.lower_value,
                            "upper_value": point.upper_value,
                            "unit": point.unit,
                            "actual_value": point.actual_value,
                            "error_value": point.error_value,
                            "metadata_json": point.metadata,
                        }
                        for point in run.points
                    ],
                )
        return run_id

    def claim_forecast_operation(
        self, *, scheduled_for: datetime, started_at: datetime
    ) -> int | None:
        """Atomically claim one aligned boundary; duplicates survive restarts."""
        _require_aware(scheduled_for)
        _require_aware(started_at)
        table = ForecastOperationAttempt.__table__
        statement = (
            postgresql_insert(table)
            if self.backend == "postgresql"
            else sqlite_insert(table)
        ).values(
            operation="forecast_cycle",
            scheduled_for_utc=scheduled_for.astimezone(UTC),
            started_at_utc=started_at.astimezone(UTC),
            status="running",
            forecast_point_count=0,
            metadata_json={},
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=[table.c.operation, table.c.scheduled_for_utc]
        ).returning(table.c.id)
        with self.transaction() as session:
            return session.execute(statement).scalar_one_or_none()

    def finish_forecast_operation(
        self,
        attempt_id: int,
        *,
        status: str,
        finished_at: datetime,
        duration_seconds: float,
        forecast_run_id: int | None = None,
        reserve_run_id: int | None = None,
        forecast_point_count: int = 0,
        failure_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if status not in {"success", "failed", "skipped"}:
            raise ValueError("invalid forecast operation status")
        _require_aware(finished_at)
        with self.transaction() as session:
            session.execute(
                update(ForecastOperationAttempt)
                .where(ForecastOperationAttempt.id == attempt_id)
                .values(
                    status=status,
                    finished_at_utc=finished_at.astimezone(UTC),
                    duration_seconds=max(duration_seconds, 0),
                    forecast_run_id=forecast_run_id,
                    reserve_run_id=reserve_run_id,
                    forecast_point_count=forecast_point_count,
                    failure_summary=(failure_summary or None),
                    metadata_json=metadata or {},
                )
            )

    def recover_stale_forecast_operations(
        self, *, before: datetime, recovered_at: datetime
    ) -> int:
        """Mark crash-interrupted claims failed without replaying their boundary."""
        _require_aware(before)
        _require_aware(recovered_at)
        with self.transaction() as session:
            result = session.execute(
                update(ForecastOperationAttempt)
                .where(
                    ForecastOperationAttempt.status == "running",
                    ForecastOperationAttempt.started_at_utc < before.astimezone(UTC),
                )
                .values(
                    status="failed",
                    finished_at_utc=recovered_at.astimezone(UTC),
                    failure_summary="Interrupted before completion",
                )
            )
            return result.rowcount

    def forecast_operations_status_read_only(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            attempts = list(
                session.execute(
                    select(ForecastOperationAttempt.__table__)
                    .order_by(ForecastOperationAttempt.scheduled_for_utc.desc())
                    .limit(100)
                ).mappings()
            )
        latest = dict(attempts[0]) if attempts else None
        success = next(
            (dict(row) for row in attempts if row["status"] == "success"), None
        )
        return {"last_attempt": latest, "last_success": success}

    def forecast_accuracy_rows_read_only(
        self,
        *,
        after: datetime,
        before: datetime,
        forecast_run_id: int | None = None,
        limit: int = 2500,
    ) -> list[dict[str, Any]]:
        _require_aware(after)
        _require_aware(before)
        if after >= before or not 1 <= limit <= 2500:
            raise ValueError("invalid bounded forecast accuracy query")
        statement = (
            select(
                ForecastRun.id.label("forecast_run_id"),
                ForecastRun.created_at_utc,
                ForecastRun.forecast_type,
                ForecastRun.source,
                ForecastRun.model_version,
                ForecastRun.metadata_json.label("run_metadata_json"),
                ForecastPoint.period_start_utc,
                ForecastPoint.period_end_utc,
                ForecastPoint.expected_value,
                ForecastPoint.lower_value,
                ForecastPoint.upper_value,
                ForecastPoint.metadata_json,
                ForecastPointScore.actual_value,
                ForecastPointScore.absolute_error,
                ForecastPointScore.signed_error,
                ForecastPointScore.squared_error,
                ForecastPointScore.actual_available,
                ForecastPointScore.health_eligible,
                ForecastPointScore.missing_reason,
            )
            .join(ForecastPoint, ForecastPoint.forecast_run_id == ForecastRun.id)
            .outerjoin(
                ForecastPointScore,
                ForecastPointScore.forecast_point_id == ForecastPoint.id,
            )
            .where(
                ForecastRun.forecast_type == "baseline_household_load",
                ForecastPoint.period_start_utc >= after.astimezone(UTC),
                ForecastPoint.period_start_utc < before.astimezone(UTC),
            )
        )
        if forecast_run_id is not None:
            statement = statement.where(ForecastRun.id == forecast_run_id)
        statement = statement.order_by(ForecastPoint.period_start_utc).limit(limit)
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    def forecast_calibration_rows_read_only(
        self, *, after: datetime, before: datetime, limit: int = 25000
    ) -> list[dict[str, Any]]:
        """Return a bounded recent calibration sample without widening chart APIs."""
        _require_aware(after)
        _require_aware(before)
        if after >= before or not 1 <= limit <= 25000:
            raise ValueError("invalid bounded forecast calibration query")
        statement = (
            select(
                ForecastRun.id.label("forecast_run_id"),
                ForecastRun.created_at_utc,
                ForecastRun.forecast_type,
                ForecastRun.source,
                ForecastRun.model_version,
                ForecastRun.metadata_json.label("run_metadata_json"),
                ForecastPoint.period_start_utc,
                ForecastPoint.period_end_utc,
                ForecastPoint.expected_value,
                ForecastPointScore.actual_value,
                ForecastPointScore.actual_available,
                ForecastPointScore.health_eligible,
            )
            .join(ForecastPoint, ForecastPoint.forecast_run_id == ForecastRun.id)
            .outerjoin(
                ForecastPointScore,
                ForecastPointScore.forecast_point_id == ForecastPoint.id,
            )
            .where(
                ForecastRun.forecast_type == "baseline_household_load",
                ForecastPoint.period_start_utc >= after.astimezone(UTC),
                ForecastPoint.period_start_utc < before.astimezone(UTC),
            )
            .order_by(ForecastPoint.period_start_utc.desc())
            .limit(limit)
        )
        with Session(self.engine) as session:
            rows = [dict(row) for row in session.execute(statement).mappings()]
        rows.reverse()
        return rows

    def reserve_history_read_only(
        self, *, after: datetime, before: datetime, limit: int = 1000
    ) -> list[dict[str, Any]]:
        _require_aware(after)
        _require_aware(before)
        if after >= before or not 1 <= limit <= 1000:
            raise ValueError("invalid bounded reserve history query")
        statement = (
            select(ReserveRun.__table__)
            .where(
                ReserveRun.evaluation_timestamp_utc >= after.astimezone(UTC),
                ReserveRun.evaluation_timestamp_utc < before.astimezone(UTC),
            )
            .order_by(ReserveRun.evaluation_timestamp_utc.desc())
            .limit(limit)
        )
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    def latest_reserve_audit_read_only(self) -> dict[str, Any] | None:
        statement = (
            select(ReserveRun.__table__)
            .order_by(ReserveRun.evaluation_timestamp_utc.desc())
            .limit(1)
        )
        with Session(self.engine) as session:
            row = session.execute(statement).mappings().first()
            return dict(row) if row else None

    def score_completed_forecast_points(
        self,
        *,
        now: datetime,
        delay_minutes: int,
        limit: int = 2500,
        runtime_guard: Callable[[], None] | None = None,
    ) -> int:
        """Materialize eligible completed-point scores without changing forecasts."""
        _require_aware(now)
        if not 1 <= limit <= 2500:
            raise ValueError("score limit must be 1-2500")
        cutoff = now.astimezone(UTC) - timedelta(minutes=delay_minutes)
        with self.transaction() as session:
            points = list(
                session.execute(
                    select(ForecastPoint, ForecastRun.metadata_json)
                    .join(ForecastRun, ForecastRun.id == ForecastPoint.forecast_run_id)
                    .outerjoin(
                        ForecastPointScore,
                        ForecastPointScore.forecast_point_id == ForecastPoint.id,
                    )
                    .where(
                        ForecastPoint.period_end_utc <= cutoff,
                        ForecastPointScore.forecast_point_id.is_(None),
                        ForecastRun.forecast_type == "baseline_household_load",
                    )
                    .order_by(ForecastPoint.period_end_utc)
                    .limit(limit)
                )
            )
            for point, run_metadata in points:
                if runtime_guard is not None:
                    runtime_guard()
                rows = list(
                    session.execute(
                        select(
                            Observation.baseline_house_consumption_w,
                            Observation.telemetry_is_healthy,
                            Observation.baseline_training_eligible,
                        ).where(*_actual_slot_conditions(point, run_metadata))
                    )
                )
                available = [float(row[0]) for row in rows if row[0] is not None]
                eligible = [
                    float(row[0])
                    for row in rows
                    if row[0] is not None and bool(row[1]) and bool(row[2])
                ]
                actual = sum(available) / len(available) if available else None
                health_eligible = bool(eligible)
                scored_actual = sum(eligible) / len(eligible) if eligible else None
                signed = (
                    scored_actual - point.expected_value
                    if scored_actual is not None
                    else None
                )
                missing_reason = None
                if not rows:
                    missing_reason = "no_observation"
                elif not available:
                    missing_reason = "actual_value_missing"
                elif not health_eligible:
                    missing_reason = "actual_unhealthy_or_ineligible"
                session.add(
                    ForecastPointScore(
                        forecast_point_id=point.id,
                        scored_at_utc=now.astimezone(UTC),
                        actual_value=(
                            scored_actual if scored_actual is not None else actual
                        ),
                        absolute_error=abs(signed) if signed is not None else None,
                        signed_error=signed,
                        squared_error=signed * signed if signed is not None else None,
                        actual_available=actual is not None,
                        health_eligible=health_eligible,
                        missing_reason=missing_reason,
                        metadata_json={"eligible_sample_count": len(eligible)},
                    )
                )
        return len(points)

    def save_reserve_run(
        self, estimate: Any, *, forecast_run_id: int, model_version: str
    ) -> int:
        """Persist every typed reserve field plus each evaluated opportunity."""
        expected_replenishment = next(
            (
                item.expected_total_replenishment_kwh
                for item in estimate.evaluated_opportunities
                if item.expected_total_replenishment_kwh is not None
            ),
            None,
        )
        values = {
            "forecast_run_id": forecast_run_id,
            "evaluation_timestamp_utc": estimate.evaluation_time_local.astimezone(UTC),
            "observation_timestamp_utc": estimate.observation_timestamp.astimezone(UTC),
            "observation_source": estimate.current_state_source,
            "observation_age_seconds": estimate.observation_age_seconds,
            "observation_is_stale": estimate.observation_is_stale,
            "battery_soc_percent": estimate.battery_soc_percent,
            "battery_energy_kwh": estimate.battery_energy_kwh,
            "usable_battery_capacity_kwh": estimate.usable_battery_capacity_kwh,
            "forecast_start_utc": estimate.forecast_start_local.astimezone(UTC),
            "forecast_end_utc": estimate.forecast_end_local.astimezone(UTC),
            "forecast_horizon_minutes": estimate.forecast_horizon_minutes,
            "forecast_horizon_hours": estimate.forecast_horizon_hours,
            "household_demand_kwh": estimate.expected_house_demand_kwh,
            "ev_demand_kwh": estimate.expected_ev_demand_kwh,
            "technical_reserve_kwh": estimate.technical_reserve_kwh,
            "emergency_reserve_kwh": estimate.emergency_reserve_kwh,
            "uncertainty_buffer_kwh": estimate.uncertainty_buffer_kwh,
            "gross_reserve_requirement_kwh": estimate.gross_reserve_requirement_kwh,
            "capacity_capped_reserve_kwh": estimate.capacity_capped_reserve_kwh,
            "unmet_reserve_requirement_kwh": estimate.unmet_reserve_requirement_kwh,
            "current_reserve_shortfall_kwh": estimate.current_reserve_shortfall_kwh,
            "recommended_reserve_kwh": estimate.recommended_reserve_kwh,
            "potentially_tradable_kwh": estimate.potentially_tradable_kwh,
            "confidence": estimate.confidence,
            "confidence_score": estimate.confidence_score,
            "ready_for_manual_review": estimate.ready_for_manual_review,
            "opportunity_state": estimate.next_opportunity.state,
            "first_candidate_json": estimate.next_opportunity.model_dump(mode="json"),
            "effective_boundary_json": (
                estimate.effective_reserve_boundary.model_dump(mode="json")
                if estimate.effective_reserve_boundary
                else None
            ),
            "skipped_candidate_count": estimate.skipped_insufficient_opportunity_count,
            "expected_replenishment_kwh": expected_replenishment,
            "command_issued": False,
            "model_version": model_version,
            "reasons_json": {
                "reasoning": estimate.reasoning,
                "horizon_is_valid": estimate.horizon_is_valid,
                "horizon_validation_issues": estimate.horizon_validation_issues,
                "observation_warning": estimate.observation_warning,
            },
            "confidence_json": {
                "data_availability": estimate.data_availability_confidence.model_dump(),
                "household_demand": estimate.household_demand_confidence.model_dump(),
                "opportunity": estimate.opportunity_forecast_confidence.model_dump(),
                "overall": estimate.overall_reserve_confidence.model_dump(),
            },
            "health_json": estimate.health,
            "operational_context_json": estimate.operational_context,
            "demand_forecast_json": estimate.demand_forecast.model_dump(mode="json"),
            "estimate_json": estimate.model_dump(mode="json"),
        }
        with self.transaction() as session:
            result = session.execute(
                insert(ReserveRun.__table__).values(**values).returning(ReserveRun.id)
            )
            reserve_id = int(result.scalar_one())
            if estimate.evaluated_opportunities:
                session.execute(
                    insert(ReserveOpportunityEvaluation.__table__),
                    [
                        {
                            "reserve_run_id": reserve_id,
                            "sequence_number": index,
                            "opportunity_json": item.opportunity.model_dump(
                                mode="json"
                            ),
                            "analysis_json": item.model_dump(mode="json"),
                        }
                        for index, item in enumerate(
                            estimate.evaluated_opportunities, start=1
                        )
                    ],
                )
        return reserve_id

    def forecast_run(self, run_id: int) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            run = (
                session.execute(
                    select(ForecastRun.__table__).where(ForecastRun.id == run_id)
                )
                .mappings()
                .first()
            )
            if run is None:
                return None
            points = session.execute(
                select(ForecastPoint.__table__)
                .where(ForecastPoint.forecast_run_id == run_id)
                .order_by(ForecastPoint.period_start_utc)
            ).mappings()
            return {**dict(run), "points": [dict(point) for point in points]}

    def forecast_run_summaries_read_only(
        self,
        *,
        forecast_type: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """List bounded persisted forecast-run metadata without loading points."""
        if limit < 1 or limit > 100:
            raise ValueError("forecast run limit must be 1-100")
        if after is not None:
            _require_aware(after)
        if before is not None:
            _require_aware(before)
        statement = (
            select(
                ForecastRun.id,
                ForecastRun.created_at_utc,
                ForecastRun.forecast_type,
                ForecastRun.source,
                ForecastRun.horizon_start_utc,
                ForecastRun.horizon_end_utc,
                ForecastRun.model_version,
                func.count(ForecastPoint.id).label("point_count"),
                func.count(ForecastPoint.actual_value).label("actual_point_count"),
            )
            .outerjoin(ForecastPoint, ForecastPoint.forecast_run_id == ForecastRun.id)
            .group_by(
                ForecastRun.id,
                ForecastRun.created_at_utc,
                ForecastRun.forecast_type,
                ForecastRun.source,
                ForecastRun.horizon_start_utc,
                ForecastRun.horizon_end_utc,
                ForecastRun.model_version,
            )
        )
        if forecast_type:
            statement = statement.where(ForecastRun.forecast_type == forecast_type)
        if after is not None:
            statement = statement.where(
                ForecastRun.created_at_utc >= after.astimezone(UTC)
            )
        if before is not None:
            statement = statement.where(
                ForecastRun.created_at_utc <= before.astimezone(UTC)
            )
        statement = statement.order_by(ForecastRun.created_at_utc.desc()).limit(limit)
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    def latest_scheduled_forecast_metadata_read_only(self) -> dict[str, Any] | None:
        statement = (
            select(ForecastRun.__table__)
            .where(ForecastRun.source == "scheduled_forecast_operations")
            .order_by(ForecastRun.created_at_utc.desc())
            .limit(1)
        )
        with Session(self.engine) as session:
            row = session.execute(statement).mappings().first()
            return dict(row) if row else None

    def forecast_comparison_read_only(
        self,
        *,
        forecast_run_id: int | None = None,
        forecast_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 2500,
    ) -> dict[str, Any] | None:
        """Compare one persisted run with observations without materializing writes."""
        if limit < 1 or limit > 2500:
            raise ValueError("forecast comparison limit must be 1-2500")
        if start is not None:
            _require_aware(start)
        if end is not None:
            _require_aware(end)
        run_statement = select(ForecastRun.__table__)
        if forecast_run_id is not None:
            run_statement = run_statement.where(ForecastRun.id == forecast_run_id)
        if forecast_type:
            run_statement = run_statement.where(
                ForecastRun.forecast_type == forecast_type
            )
        run_statement = run_statement.order_by(ForecastRun.created_at_utc.desc()).limit(
            1
        )
        with Session(self.engine) as session:
            run = session.execute(run_statement).mappings().first()
            if run is None:
                return None
            actual_columns = {
                "solar_power": Observation.pv_power_w,
                "household_load": Observation.house_consumption_w,
                "baseline_household_load": Observation.baseline_house_consumption_w,
                "battery_soc": Observation.battery_soc_percent,
                "grid_import": Observation.grid_import_power_w,
                "grid_export": Observation.grid_export_power_w,
                "buy_price": Observation.amber_import_price_per_kwh,
                "sell_price": Observation.amber_export_price_per_kwh,
            }
            actual_column = actual_columns.get(str(run["forecast_type"]))
            if actual_column is None:
                return {**dict(run), "points": [], "unsupported_actual_type": True}
            actual = (
                select(func.avg(actual_column))
                .where(
                    *_actual_slot_conditions(
                        ForecastPoint,
                        run.get("metadata_json"),
                    )
                )
                .correlate(ForecastPoint)
                .scalar_subquery()
            )
            statement = select(
                ForecastPoint.period_start_utc,
                ForecastPoint.period_end_utc,
                ForecastPoint.expected_value,
                ForecastPoint.lower_value,
                ForecastPoint.upper_value,
                ForecastPoint.unit,
                ForecastPoint.metadata_json,
                actual.label("actual_value"),
            ).where(ForecastPoint.forecast_run_id == run["id"])
            if start is not None:
                statement = statement.where(
                    ForecastPoint.period_start_utc >= start.astimezone(UTC)
                )
            if end is not None:
                statement = statement.where(
                    ForecastPoint.period_end_utc <= end.astimezone(UTC)
                )
            statement = statement.order_by(ForecastPoint.period_start_utc).limit(limit)
            points = []
            for point in session.execute(statement).mappings():
                item = dict(point)
                observed = item["actual_value"]
                item["error_value"] = (
                    float(observed) - float(item["expected_value"])
                    if observed is not None
                    else None
                )
                points.append(item)
            return {**dict(run), "points": points, "unsupported_actual_type": False}

    def latest_reserve_run_read_only(self) -> dict[str, Any] | None:
        """Return the latest persisted reserve-estimator run and bounded summaries."""
        statement = (
            select(ForecastRun.__table__)
            .where(ForecastRun.source == "reserve_estimator")
            .order_by(ForecastRun.created_at_utc.desc())
            .limit(1)
        )
        with Session(self.engine) as session:
            run = session.execute(statement).mappings().first()
            if run is None:
                return None
            points = list(
                session.execute(
                    select(
                        ForecastPoint.period_start_utc,
                        ForecastPoint.period_end_utc,
                        ForecastPoint.expected_value,
                        ForecastPoint.metadata_json,
                    )
                    .where(ForecastPoint.forecast_run_id == run["id"])
                    .order_by(ForecastPoint.period_start_utc)
                    .limit(2500)
                ).mappings()
            )
        expected_energy_kwh = 0.0
        tier_counts: dict[str, int] = {}
        for point in points:
            start_utc = _as_datetime(point["period_start_utc"])
            end_utc = _as_datetime(point["period_end_utc"])
            hours = (end_utc - start_utc).total_seconds() / 3600
            expected_energy_kwh += float(point["expected_value"]) * hours / 1000
            metadata = point["metadata_json"] or {}
            tier = str(metadata.get("tier", "unknown"))
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        return {
            **dict(run),
            "point_count": len(points),
            "expected_household_demand_kwh": expected_energy_kwh,
            "tier_counts": tier_counts,
        }

    def compare_forecast_run(self, run_id: int) -> dict[str, Any]:
        actual_columns = {
            "solar_power": Observation.pv_power_w,
            "household_load": Observation.house_consumption_w,
            "baseline_household_load": Observation.baseline_house_consumption_w,
            "battery_soc": Observation.battery_soc_percent,
            "grid_import": Observation.grid_import_power_w,
            "grid_export": Observation.grid_export_power_w,
            "buy_price": Observation.amber_import_price_per_kwh,
            "sell_price": Observation.amber_export_price_per_kwh,
        }
        with self.transaction() as session:
            run = session.get(ForecastRun, run_id)
            if run is None:
                raise ValueError(f"Forecast run {run_id} does not exist")
            actual_column = actual_columns[run.forecast_type]
            points = session.scalars(
                select(ForecastPoint).where(ForecastPoint.forecast_run_id == run_id)
            ).all()
            for point in points:
                actual = session.scalar(
                    select(func.avg(actual_column)).where(
                        *_actual_slot_conditions(point, run.metadata_json)
                    )
                )
                point.actual_value = actual
                point.error_value = (
                    actual - point.expected_value if actual is not None else None
                )
        return self.forecast_metrics(run_id)

    def forecast_metrics(self, run_id: int) -> dict[str, Any]:
        with Session(self.engine) as session:
            errors = list(
                session.scalars(
                    select(ForecastPoint.error_value).where(
                        ForecastPoint.forecast_run_id == run_id,
                        ForecastPoint.error_value.is_not(None),
                    )
                )
            )
        return {
            "forecast_run_id": run_id,
            "sample_count": len(errors),
            "mae": (
                sum(abs(value) for value in errors) / len(errors) if errors else None
            ),
            "bias": sum(errors) / len(errors) if errors else None,
        }

    def prior_reserve_forecast_mape_read_only(self) -> float | None:
        with Session(self.engine) as session:
            points = session.execute(
                select(ForecastPoint.error_value, ForecastPoint.expected_value)
                .join(ForecastRun, ForecastRun.id == ForecastPoint.forecast_run_id)
                .where(
                    ForecastRun.source == "reserve_estimator",
                    ForecastPoint.error_value.is_not(None),
                    func.abs(ForecastPoint.expected_value) > 1,
                )
            )
            values = [abs(error) / abs(expected) for error, expected in points]
        return sum(values) / len(values) if values else None

    def score_reserve_forecast(self, run_id: int) -> dict[str, Any]:
        run = self.forecast_run(run_id)
        if run is None or run["source"] != "reserve_estimator":
            raise ValueError(f"Reserve forecast run {run_id} does not exist")
        if _as_datetime(run["horizon_end_utc"]) > datetime.now(UTC):
            raise ValueError("Reserve forecast horizon has not ended")
        totals: dict[str, dict[str, float]] = {}
        forecast_energy = actual_energy = 0.0
        scored = 0
        with self.transaction() as session:
            points = session.scalars(
                select(ForecastPoint).where(ForecastPoint.forecast_run_id == run_id)
            ).all()
            for point in points:
                actual = session.scalar(
                    select(func.avg(Observation.baseline_house_consumption_w)).where(
                        Observation.slot_utc >= point.period_start_utc,
                        Observation.slot_utc < point.period_end_utc,
                        Observation.telemetry_is_healthy.is_(True),
                        Observation.baseline_training_eligible.is_(True),
                    )
                )
                point.actual_value = actual
                point.error_value = (
                    actual - point.expected_value if actual is not None else None
                )
                hours = (
                    point.period_end_utc - point.period_start_utc
                ).total_seconds() / 3600
                metadata = point.metadata_json or {}
                tier = metadata.get("tier", "unknown")
                bucket = totals.setdefault(
                    tier, {"forecast_kwh": 0.0, "actual_kwh": 0.0, "slots": 0.0}
                )
                predicted = point.expected_value * hours / 1000
                if actual is not None:
                    measured = actual * hours / 1000
                    forecast_energy += predicted
                    actual_energy += measured
                    bucket["forecast_kwh"] += predicted
                    bucket["actual_kwh"] += measured
                    bucket["slots"] += 1
                    scored += 1
        error = actual_energy - forecast_energy if scored else None
        return {
            "forecast_run_id": run_id,
            "scored_slots": scored,
            "total_slots": len(points),
            "scored_slot_coverage": round(scored / len(points), 4) if points else 0.0,
            "forecast_household_energy_kwh": round(forecast_energy, 3),
            "actual_household_energy_kwh": round(actual_energy, 3) if scored else None,
            "forecast_error_kwh": round(error, 3) if error is not None else None,
            "absolute_percentage_error": (
                round(abs(error) / forecast_energy, 4)
                if error is not None and forecast_energy > 0
                else None
            ),
            "bias_kwh": round(error, 3) if error is not None else None,
            "error_by_tier": {
                tier: {
                    **{key: round(value, 3) for key, value in values.items()},
                    "error_kwh": round(
                        values["actual_kwh"] - values["forecast_kwh"], 3
                    ),
                }
                for tier, values in totals.items()
            },
        }

    def forecast_comparison_rows(
        self,
        *,
        forecast_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        statement = select(
            ForecastRun.id.label("forecast_run_id"),
            ForecastRun.created_at_utc,
            ForecastRun.forecast_type,
            ForecastRun.source,
            ForecastRun.model_version,
            ForecastPoint.period_start_utc,
            ForecastPoint.period_end_utc,
            ForecastPoint.expected_value,
            ForecastPoint.lower_value,
            ForecastPoint.upper_value,
            ForecastPoint.unit,
            ForecastPoint.actual_value,
            ForecastPoint.error_value,
            ForecastPoint.metadata_json,
        ).join(ForecastPoint, ForecastPoint.forecast_run_id == ForecastRun.id)
        if forecast_type:
            statement = statement.where(ForecastRun.forecast_type == forecast_type)
        if start:
            statement = statement.where(
                ForecastPoint.period_start_utc >= start.astimezone(UTC)
            )
        if end:
            statement = statement.where(
                ForecastPoint.period_end_utc <= end.astimezone(UTC)
            )
        with Session(self.engine) as session:
            return [
                dict(row)
                for row in session.execute(
                    statement.order_by(ForecastPoint.period_start_utc)
                ).mappings()
            ]

    forecast_runs = forecast_run
    forecast_points = forecast_comparison_rows

    def add_derivation_audit(self, values: Mapping[str, Any]) -> bool:
        table = ObservationDerivation.__table__
        statement = (
            postgresql_insert(table)
            if self.backend == "postgresql"
            else sqlite_insert(table)
        ).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                table.c.slot_utc,
                table.c.model_version,
                table.c.input_fingerprint,
            ]
        )
        with self.transaction() as session:
            result = session.execute(statement)
            return result.rowcount > 0

    def reprocessing_rows(self, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        return self.observation_rows(columns=columns)

    def apply_reprocessing_results(
        self,
        results: list[dict[str, Any]],
        *,
        model_version: str,
        conventions: Mapping[str, Any],
        timestamp: datetime,
        update_columns: tuple[str, ...],
    ) -> int:
        """Atomically write derivation audits and derived-only observation updates."""
        audit = ObservationDerivation.__table__
        count = 0
        with self.transaction() as session:
            for result in results:
                statement = (
                    postgresql_insert(audit)
                    if self.backend == "postgresql"
                    else sqlite_insert(audit)
                ).values(
                    slot_utc=self._slot_value(result["slot_utc"]),
                    derived_at_utc=timestamp,
                    model_version=model_version,
                    input_fingerprint=result["fingerprint"],
                    conventions_json=dict(conventions),
                    previous_derived_json={
                        name: result["original"].get(name)
                        for name in update_columns
                        if name in result["original"]
                    },
                    result_derived_json=result["derived"],
                    originally_legacy=bool(result["originally_legacy"]),
                )
                statement = statement.on_conflict_do_nothing(
                    index_elements=[
                        audit.c.slot_utc,
                        audit.c.model_version,
                        audit.c.input_fingerprint,
                    ]
                ).returning(audit.c.id)
                audit_created = (
                    session.execute(statement).scalar_one_or_none() is not None
                )
                count += int(audit_created)
                if audit_created:
                    session.execute(
                        update(Observation)
                        .where(
                            Observation.slot_utc == self._slot_value(result["slot_utc"])
                        )
                        .values(
                            **{
                                name: _coerce_column_value(
                                    Observation.__table__.c[name],
                                    result["derived"].get(name),
                                )
                                for name in update_columns
                            }
                        )
                    )
        return count

    def ev_annotation_rows(self, session_id: str) -> list[dict[str, Any]]:
        statement = (
            select(EVSessionAnnotation.__table__)
            .where(EVSessionAnnotation.session_id == session_id)
            .order_by(EVSessionAnnotation.annotation_timestamp_utc)
        )
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    def apply_ev_annotation(
        self,
        *,
        rows: list[dict[str, Any]],
        start: datetime,
        end: datetime,
        session_id: str,
        note: str | None,
        now: datetime,
        state_columns: tuple[str, ...],
    ) -> None:
        """Atomically snapshot, audit, and update one manual EV session."""
        previous = _eligibility_counts(rows)
        new = _eligibility_counts(rows, projected=True)
        with self.transaction() as session:
            annotation_id = int(
                session.execute(
                    insert(EVSessionAnnotation.__table__)
                    .values(
                        annotation_timestamp_utc=now.astimezone(UTC),
                        range_start_utc=start.astimezone(UTC),
                        range_end_utc=end.astimezone(UTC),
                        affected_row_count=len(rows),
                        session_id=session_id,
                        note=note,
                        previous_eligibility_json=previous,
                        new_eligibility_json=new,
                        annotation_source="manual_annotation",
                        action="apply",
                    )
                    .returning(EVSessionAnnotation.id)
                ).scalar_one()
            )
            for row in rows:
                session.execute(
                    insert(EVSessionAnnotationRow.__table__).values(
                        annotation_id=annotation_id,
                        slot_utc=self._slot_value(row["slot_utc"]),
                        previous_state_json={name: row[name] for name in state_columns},
                    )
                )
                direct = row["ev_power_w"]
                eligible = bool(
                    direct is not None
                    and row["telemetry_is_healthy"]
                    and row["house_consumption_w"] is not None
                )
                baseline = (
                    max(float(row["house_consumption_w"]) - float(direct), 0.0)
                    if eligible
                    else row["baseline_house_consumption_w"]
                )
                session.execute(
                    update(Observation)
                    .where(Observation.slot_utc == self._slot_value(row["slot_utc"]))
                    .values(
                        ev_charging_active=True,
                        ev_source="manual_annotation",
                        ev_session_id=session_id,
                        ev_detection_confidence="confirmed_manual",
                        baseline_house_consumption_w=baseline,
                        baseline_training_eligible=eligible,
                        baseline_exclusion_reason=(
                            None if eligible else "known_ev_session_without_ev_power"
                        ),
                    )
                )

    def removable_ev_session_rows(self, session_id: str) -> list[dict[str, Any]]:
        latest = (
            select(EVSessionAnnotation.id)
            .where(
                EVSessionAnnotation.session_id == session_id,
                EVSessionAnnotation.action == "apply",
            )
            .order_by(EVSessionAnnotation.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(
                *Observation.__table__.c,
                EVSessionAnnotationRow.previous_state_json,
                EVSessionAnnotation.range_start_utc,
                EVSessionAnnotation.range_end_utc,
            )
            .join(
                EVSessionAnnotationRow,
                EVSessionAnnotationRow.slot_utc == Observation.slot_utc,
            )
            .join(
                EVSessionAnnotation,
                EVSessionAnnotation.id == EVSessionAnnotationRow.annotation_id,
            )
            .where(
                EVSessionAnnotationRow.annotation_id == latest,
                Observation.ev_session_id == session_id,
            )
            .order_by(Observation.slot_utc)
        )
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    def remove_ev_annotation(
        self,
        *,
        rows: list[dict[str, Any]],
        session_id: str,
        note: str | None,
        now: datetime,
        state_columns: tuple[str, ...],
    ) -> None:
        previous = _eligibility_counts(rows)
        restored = [
            {
                **row,
                "baseline_training_eligible": row["previous_state_json"][
                    "baseline_training_eligible"
                ],
            }
            for row in rows
        ]
        with self.transaction() as session:
            removal_id = int(
                session.execute(
                    insert(EVSessionAnnotation.__table__)
                    .values(
                        annotation_timestamp_utc=now.astimezone(UTC),
                        range_start_utc=_as_datetime(rows[0]["range_start_utc"]),
                        range_end_utc=_as_datetime(rows[0]["range_end_utc"]),
                        affected_row_count=len(rows),
                        session_id=session_id,
                        note=note,
                        previous_eligibility_json=previous,
                        new_eligibility_json=_eligibility_counts(restored),
                        annotation_source="manual_annotation",
                        action="remove",
                    )
                    .returning(EVSessionAnnotation.id)
                ).scalar_one()
            )
            for row in rows:
                session.execute(
                    insert(EVSessionAnnotationRow.__table__).values(
                        annotation_id=removal_id,
                        slot_utc=self._slot_value(row["slot_utc"]),
                        previous_state_json={name: row[name] for name in state_columns},
                    )
                )
                session.execute(
                    update(Observation)
                    .where(Observation.slot_utc == self._slot_value(row["slot_utc"]))
                    .values(**row["previous_state_json"])
                )

    def table_counts(self) -> DatabaseCounts:
        models = (
            Observation,
            ForecastRun,
            ForecastPoint,
            ObservationDerivation,
            EVSessionAnnotation,
            EVSessionAnnotationRow,
            ForecastPointScore,
            ForecastOperationAttempt,
            ReserveRun,
            ReserveOpportunityEvaluation,
            ForecastAccuracyRollup,
            ForecastMaintenanceRun,
        )
        with Session(self.engine) as session:
            values = [
                session.scalar(select(func.count()).select_from(model)) or 0
                for model in models
            ]
        return DatabaseCounts(*values)

    def duplicate_slot_count(self) -> int:
        grouped = (
            select(Observation.slot_utc)
            .group_by(Observation.slot_utc)
            .having(func.count() > 1)
            .subquery()
        )
        with Session(self.engine) as session:
            return int(session.scalar(select(func.count()).select_from(grouped)) or 0)

    def integrity_counts(self) -> dict[str, int]:
        checks = {
            "orphan_forecast_points": select(func.count())
            .select_from(ForecastPoint)
            .where(~ForecastPoint.forecast_run_id.in_(select(ForecastRun.id))),
            "orphan_derivations": select(func.count())
            .select_from(ObservationDerivation)
            .where(~ObservationDerivation.slot_utc.in_(select(Observation.slot_utc))),
            "orphan_annotation_rows": select(func.count())
            .select_from(EVSessionAnnotationRow)
            .where(
                (
                    ~EVSessionAnnotationRow.annotation_id.in_(
                        select(EVSessionAnnotation.id)
                    )
                )
                | (~EVSessionAnnotationRow.slot_utc.in_(select(Observation.slot_utc)))
            ),
        }
        with Session(self.engine) as session:
            return {
                name: int(session.scalar(statement) or 0)
                for name, statement in checks.items()
            }


def observation_values(observation: EnergyObservation) -> dict[str, Any]:
    """Map the typed collector result without rounding or filling missing values."""
    dump = observation.model_dump(mode="python")
    json_dump = observation.model_dump(mode="json")
    health = observation.data_health
    flow = observation.energy_flow
    vehicle = observation.ev_vehicle
    values: dict[str, Any] = {
        "slot_utc": observation.slot_utc.astimezone(UTC),
        "observed_at_utc": observation.observed_at_utc.astimezone(UTC),
        "observed_at_local": observation.observed_at_local,
        **{
            name: dump[name]
            for name in (
                "battery_soc_percent",
                "battery_energy_estimate_kwh",
                "battery_power_w",
                "battery_mode",
                "pv_power_w",
                "house_consumption_w",
                "grid_power_w",
                "work_mode",
                "amber_import_price_per_kwh",
                "amber_export_price_per_kwh",
                "amber_price_spike",
                "solcast_power_now_w",
                "temperature_c",
                "weather_condition",
                "ev_charging_active",
                "ev_power_w",
                "ev_session_id",
                "ev_energy_required_kwh",
                "ev_ready_by_local",
                "ev_source",
                "ev_detection_confidence",
                "baseline_house_consumption_w",
                "baseline_training_eligible",
                "baseline_exclusion_reason",
                "event_label_confidence",
            )
        },
        "amber_import_forecast_json": json_dump["amber_import_forecast"],
        "amber_export_forecast_json": json_dump["amber_export_forecast"],
        "is_healthy": health.is_healthy,
        "health_score": health.health_score,
        "health_issues_json": [item.model_dump(mode="json") for item in health.issues],
        "telemetry_is_healthy": health.telemetry.is_healthy,
        "telemetry_health_score": health.telemetry.score,
        "price_is_healthy": health.price.is_healthy,
        "price_health_score": health.price.score,
        "solar_is_healthy": health.solar.is_healthy,
        "solar_health_score": health.solar.score,
        "weather_is_healthy": health.weather.is_healthy,
        "weather_health_score": health.weather.score,
        "flow_is_healthy": health.flow.is_healthy,
        "flow_health_score": health.flow.score,
        "health_domains_json": health.model_dump(mode="json"),
        "event_labels_json": dump["event_labels"],
        "event_label_evidence_json": dump["event_label_evidence"],
        "ev_vehicle_soc_percent": vehicle.vehicle_soc_percent,
        "ev_vehicle_battery_power_w_raw": vehicle.vehicle_battery_power_w_raw,
        "ev_plugged_in": vehicle.plugged_in,
        "ev_vehicle_online": vehicle.vehicle_online,
        "ev_at_home": vehicle.at_home,
        "ev_telemetry_updated_at_utc": vehicle.telemetry_updated_at_utc,
        "ev_telemetry_age_seconds": vehicle.telemetry_age_seconds,
        "ev_telemetry_fresh": vehicle.telemetry_fresh,
        "ev_vehicle_status": vehicle.status if vehicle.source != "none" else None,
    }
    for source in ("remaining_today", "tomorrow", "next_hour", "this_hour", "today"):
        values[f"solcast_{source}_kwh_json"] = json_dump[f"solcast_{source}_kwh"]
        values[f"solcast_{source}_json"] = None
    for name in (
        "grid_import_power_w",
        "grid_export_power_w",
        "battery_charge_power_w",
        "battery_discharge_power_w",
        "solar_to_house_power_w",
        "solar_to_battery_power_w",
        "solar_to_grid_power_w",
        "battery_to_house_power_w",
        "battery_to_grid_power_w",
        "grid_to_house_power_w",
        "grid_to_battery_power_w",
        "balance_residual_w",
        "sign_convention_status",
        "sign_convention_confidence",
    ):
        values[name] = getattr(flow, name)
    values["sign_supporting_sample_count"] = flow.supporting_sample_count
    values.update(
        derivation_model_version=None,
        reprocessed_at_utc=None,
        derivation_metadata_json=None,
        originally_legacy=False,
    )
    return values


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database query timestamps must be timezone-aware")


def _as_datetime(value: datetime | str) -> datetime:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _iso(value: datetime | str) -> str:
    return _as_datetime(value).isoformat()


def _eligibility_counts(
    rows: list[dict[str, Any]], *, projected: bool = False
) -> dict[str, int]:
    result = {"eligible": 0, "ineligible": 0}
    for row in rows:
        eligible = (
            row["ev_power_w"] is not None
            and bool(row["telemetry_is_healthy"])
            and row["house_consumption_w"] is not None
            if projected
            else bool(row["baseline_training_eligible"])
        )
        result["eligible" if eligible else "ineligible"] += 1
    return result


def _actual_slot_conditions(point: Any, run_metadata: Any) -> tuple[Any, ...]:
    """Return the SQL form of the canonical alignment-aware slot rule."""
    if forecast_alignment_version(run_metadata) == FULL_FIVE_MINUTE_ALIGNMENT:
        return (Observation.slot_utc == point.period_start_utc,)
    return (
        Observation.slot_utc >= point.period_start_utc,
        Observation.slot_utc < point.period_end_utc,
    )


def _coerce_column_value(column, value):
    if value is None:
        return None
    if column.type.python_type is datetime and isinstance(value, str):
        return _as_datetime(value)
    if column.type.__class__.__name__ in {"JSON", "JSONB"} and isinstance(value, str):
        import json

        return json.loads(value)
    return value
