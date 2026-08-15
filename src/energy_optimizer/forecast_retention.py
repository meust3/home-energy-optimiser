"""Bounded transactional forecast retention run by the existing coordinator."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from energy_optimizer.db.models import (
    ForecastAccuracyRollup,
    ForecastMaintenanceRun,
    ForecastOperationAttempt,
    ForecastPoint,
    ForecastPointScore,
    ForecastRun,
    ReserveOpportunityEvaluation,
    ReserveRun,
)
from energy_optimizer.forecast_alignment import alignment_version

RETENTION_OPERATION = "forecast_retention"
DETAIL_BATCH_SIZE = 5000
MAX_DETAIL_BATCHES_PER_RUN = 6
METADATA_BATCH_SIZE = 500
MAX_METADATA_BATCHES_PER_RUN = 6
ESTIMATED_DAILY_DETAIL_CREATION_RATE = 13_824


def run_forecast_retention(
    repository: Any,
    *,
    now: datetime,
    point_retention_days: int,
    run_retention_days: int,
    batch_size: int = DETAIL_BATCH_SIZE,
    max_batches_per_table: int = MAX_DETAIL_BATCHES_PER_RUN,
    estimated_daily_creation_rate: int = ESTIMATED_DAILY_DETAIL_CREATION_RATE,
    runtime_guard: Callable[[], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Roll up and prune bounded, independently committed detail batches."""
    if batch_size <= 0 or max_batches_per_table <= 0:
        raise ValueError("retention batch size and maximum batches must be positive")
    if estimated_daily_creation_rate < 0:
        raise ValueError("estimated daily creation rate must not be negative")
    current = now.astimezone(UTC)
    point_cutoff = current - timedelta(days=point_retention_days)
    run_cutoff = current - timedelta(days=run_retention_days)
    capacity = batch_size * max_batches_per_table
    before = _detail_counts(repository, point_cutoff)
    base_diagnostics = _retention_diagnostics(
        eligible=before,
        pruned={"forecast_points": 0, "forecast_point_scores": 0},
        remaining=before,
        batches_executed=0,
        batch_size=batch_size,
        maximum_rows_per_run=capacity,
        estimated_daily_creation_rate=estimated_daily_creation_rate,
    )
    claim_id = _claim_daily_run(
        repository,
        current=current,
        point_cutoff=point_cutoff,
        run_cutoff=run_cutoff,
        metadata=base_diagnostics,
    )
    if claim_id is None:
        existing = _daily_run(repository, current)
        metadata = dict(existing.get("metadata_json") or {}) if existing else {}
        return {
            "status": "already_completed",
            "boundary_date": current.date(),
            "maintenance_status": existing.get("status") if existing else None,
            **metadata,
        }

    totals = {
        "rows_rolled_up": 0,
        "scores_deleted": 0,
        "points_deleted": 0,
        "runs_deleted": 0,
        "reserve_runs_deleted": 0,
        "attempts_deleted": 0,
    }
    batches_executed = 0
    interrupted = False
    try:
        for _ in range(max_batches_per_table):
            if should_stop is not None and should_stop():
                interrupted = True
                break
            if runtime_guard is not None:
                runtime_guard()
            batch = _prune_detail_batch(
                repository,
                claim_id=claim_id,
                point_cutoff=point_cutoff,
                batch_size=batch_size,
            )
            if batch["points_deleted"] == 0:
                break
            batches_executed += 1
            for name in ("rows_rolled_up", "scores_deleted", "points_deleted"):
                totals[name] += batch[name]
            if batch["points_deleted"] < batch_size:
                break

        if not interrupted:
            for _ in range(MAX_METADATA_BATCHES_PER_RUN):
                if should_stop is not None and should_stop():
                    interrupted = True
                    break
                if runtime_guard is not None:
                    runtime_guard()
                deleted = _prune_attempt_batch(
                    repository, claim_id=claim_id, run_cutoff=run_cutoff
                )
                totals["attempts_deleted"] += deleted
                if deleted < METADATA_BATCH_SIZE:
                    break

        if not interrupted:
            for _ in range(MAX_METADATA_BATCHES_PER_RUN):
                if should_stop is not None and should_stop():
                    interrupted = True
                    break
                if runtime_guard is not None:
                    runtime_guard()
                batch = _prune_run_batch(
                    repository, claim_id=claim_id, run_cutoff=run_cutoff
                )
                totals["runs_deleted"] += batch["runs_deleted"]
                totals["reserve_runs_deleted"] += batch["reserve_runs_deleted"]
                if batch["runs_deleted"] < METADATA_BATCH_SIZE:
                    break
    except Exception as exc:
        remaining = _detail_counts(repository, point_cutoff)
        diagnostics = _retention_diagnostics(
            eligible=before,
            pruned={
                "forecast_points": totals["points_deleted"],
                "forecast_point_scores": totals["scores_deleted"],
            },
            remaining=remaining,
            batches_executed=batches_executed,
            batch_size=batch_size,
            maximum_rows_per_run=capacity,
            estimated_daily_creation_rate=estimated_daily_creation_rate,
        )
        diagnostics["failure_class"] = type(exc).__name__
        _finish_daily_run(
            repository,
            claim_id=claim_id,
            current=current,
            status="failed",
            metadata=diagnostics,
        )
        raise

    remaining = _detail_counts(repository, point_cutoff)
    diagnostics = _retention_diagnostics(
        eligible=before,
        pruned={
            "forecast_points": totals["points_deleted"],
            "forecast_point_scores": totals["scores_deleted"],
        },
        remaining=remaining,
        batches_executed=batches_executed,
        batch_size=batch_size,
        maximum_rows_per_run=capacity,
        estimated_daily_creation_rate=estimated_daily_creation_rate,
    )
    if interrupted:
        diagnostics["interrupted"] = True
    _finish_daily_run(
        repository,
        claim_id=claim_id,
        current=current,
        status="failed" if interrupted else "success",
        metadata=diagnostics,
    )
    return {
        "status": "interrupted" if interrupted else "success",
        **totals,
        **diagnostics,
    }


def inspect_forecast_retention(
    repository: Any,
    *,
    now: datetime,
    point_retention_days: int,
    batch_size: int = DETAIL_BATCH_SIZE,
    max_batches_per_table: int = MAX_DETAIL_BATCHES_PER_RUN,
    estimated_daily_creation_rate: int = ESTIMATED_DAILY_DETAIL_CREATION_RATE,
) -> dict[str, Any]:
    cutoff = now.astimezone(UTC) - timedelta(days=point_retention_days)
    tables = (ForecastRun, ForecastPoint, ForecastPointScore, ReserveRun)
    report = []
    with repository.transaction() as session:
        for model in tables:
            table = model.__table__
            timestamp = {
                ForecastRun: ForecastRun.created_at_utc,
                ForecastPoint: ForecastPoint.period_start_utc,
                ForecastPointScore: ForecastPointScore.scored_at_utc,
                ReserveRun: ReserveRun.evaluation_timestamp_utc,
            }[model]
            report.append(
                {
                    "table": table.name,
                    "row_count": session.scalar(select(func.count()).select_from(model))
                    or 0,
                    "oldest": session.scalar(select(func.min(timestamp))),
                    "newest": session.scalar(select(func.max(timestamp))),
                    "rows_eligible_for_pruning": session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(timestamp < cutoff)
                    )
                    or 0,
                }
            )
        latest = (
            session.execute(
                select(ForecastMaintenanceRun.__table__)
                .order_by(ForecastMaintenanceRun.started_at_utc.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        latest_rollup = session.scalar(
            select(func.max(ForecastAccuracyRollup.rollup_date))
        )
    detail = _detail_counts(repository, cutoff)
    capacity = batch_size * max_batches_per_table
    diagnostics = _retention_diagnostics(
        eligible=detail,
        pruned={"forecast_points": 0, "forecast_point_scores": 0},
        remaining=detail,
        batches_executed=0,
        batch_size=batch_size,
        maximum_rows_per_run=capacity,
        estimated_daily_creation_rate=estimated_daily_creation_rate,
    )
    size = None
    if repository.backend == "postgresql":
        with repository.engine.connect() as connection:
            size = connection.scalar(
                text("SELECT pg_database_size(current_database())")
            )
    elif repository.engine.url.database not in {None, "", ":memory:"}:
        path = Path(repository.engine.url.database)
        size = path.stat().st_size if path.exists() else None
    return {
        "point_cutoff_utc": cutoff,
        "tables": report,
        "latest_retention_run": dict(latest) if latest else None,
        "latest_rollup_date": latest_rollup,
        "database_size_bytes": size,
        "retention_diagnostics": diagnostics,
    }


def _claim_daily_run(
    repository: Any,
    *,
    current: datetime,
    point_cutoff: datetime,
    run_cutoff: datetime,
    metadata: dict[str, Any],
) -> int | None:
    maintenance = ForecastMaintenanceRun.__table__
    dialect_insert = (
        postgresql_insert(maintenance)
        if repository.backend == "postgresql"
        else sqlite_insert(maintenance)
    )
    with repository.transaction() as session:
        claim = (
            dialect_insert.values(
                operation=RETENTION_OPERATION,
                boundary_date=current.date(),
                started_at_utc=current,
                status="running",
                rows_rolled_up=0,
                scores_deleted=0,
                points_deleted=0,
                runs_deleted=0,
                reserve_runs_deleted=0,
                attempts_deleted=0,
                metadata_json={
                    "point_cutoff_utc": point_cutoff.isoformat(),
                    "run_cutoff_utc": run_cutoff.isoformat(),
                    **metadata,
                },
            )
            .on_conflict_do_nothing(
                index_elements=[maintenance.c.operation, maintenance.c.boundary_date]
            )
            .returning(maintenance.c.id)
        )
        return session.execute(claim).scalar_one_or_none()


def _daily_run(repository: Any, current: datetime) -> dict[str, Any] | None:
    with repository.transaction() as session:
        row = (
            session.execute(
                select(ForecastMaintenanceRun.__table__).where(
                    ForecastMaintenanceRun.operation == RETENTION_OPERATION,
                    ForecastMaintenanceRun.boundary_date == current.date(),
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


def _detail_counts(repository: Any, cutoff: datetime) -> dict[str, int]:
    with repository.transaction() as session:
        points = session.scalar(
            select(func.count())
            .select_from(ForecastPoint)
            .where(ForecastPoint.period_start_utc < cutoff)
        )
        scores = session.scalar(
            select(func.count())
            .select_from(ForecastPointScore)
            .join(
                ForecastPoint,
                ForecastPoint.id == ForecastPointScore.forecast_point_id,
            )
            .where(ForecastPoint.period_start_utc < cutoff)
        )
    return {
        "forecast_points": int(points or 0),
        "forecast_point_scores": int(scores or 0),
    }


def _prune_detail_batch(
    repository: Any, *, claim_id: int, point_cutoff: datetime, batch_size: int
) -> dict[str, int]:
    with repository.transaction() as session:
        detail_rows = list(
            session.execute(
                select(
                    ForecastPoint.id,
                    ForecastPoint.period_start_utc,
                    ForecastPoint.expected_value,
                    ForecastRun.forecast_type,
                    ForecastRun.model_version,
                    ForecastRun.metadata_json.label("run_metadata"),
                    ForecastRun.created_at_utc,
                    ForecastPointScore.actual_value,
                    ForecastPointScore.signed_error,
                    ForecastPointScore.absolute_error,
                    ForecastPointScore.squared_error,
                    ForecastPointScore.actual_available,
                    ForecastPointScore.health_eligible,
                )
                .join(ForecastRun, ForecastRun.id == ForecastPoint.forecast_run_id)
                .outerjoin(
                    ForecastPointScore,
                    ForecastPointScore.forecast_point_id == ForecastPoint.id,
                )
                .where(ForecastPoint.period_start_utc < point_cutoff)
                .order_by(ForecastPoint.period_start_utc, ForecastPoint.id)
                .limit(batch_size)
            ).mappings()
        )
        groups = _rollup_groups(detail_rows)
        rollup = ForecastAccuracyRollup.__table__
        for key, values in groups.items():
            statement = (
                postgresql_insert(rollup)
                if repository.backend == "postgresql"
                else sqlite_insert(rollup)
            ).values(
                rollup_date=key[0],
                forecast_type=key[1],
                model_version=key[2],
                alignment_version=key[3],
                training_policy=key[4],
                horizon_bucket=key[5],
                day_type=key[6],
                **values,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    rollup.c.rollup_date,
                    rollup.c.forecast_type,
                    rollup.c.model_version,
                    rollup.c.alignment_version,
                    rollup.c.training_policy,
                    rollup.c.horizon_bucket,
                    rollup.c.day_type,
                ],
                set_={
                    name: rollup.c[name] + getattr(statement.excluded, name)
                    for name in values
                },
            )
            session.execute(statement)
        point_ids = [int(row["id"]) for row in detail_rows]
        scores_deleted = points_deleted = 0
        if point_ids:
            scores_deleted = session.execute(
                delete(ForecastPointScore).where(
                    ForecastPointScore.forecast_point_id.in_(point_ids)
                )
            ).rowcount
            points_deleted = session.execute(
                delete(ForecastPoint).where(ForecastPoint.id.in_(point_ids))
            ).rowcount
            session.execute(
                update(ForecastMaintenanceRun)
                .where(ForecastMaintenanceRun.id == claim_id)
                .values(
                    rows_rolled_up=(
                        ForecastMaintenanceRun.rows_rolled_up + len(detail_rows)
                    ),
                    scores_deleted=(
                        ForecastMaintenanceRun.scores_deleted + scores_deleted
                    ),
                    points_deleted=(
                        ForecastMaintenanceRun.points_deleted + points_deleted
                    ),
                )
            )
    return {
        "rows_rolled_up": len(detail_rows),
        "scores_deleted": int(scores_deleted or 0),
        "points_deleted": int(points_deleted or 0),
    }


def _rollup_groups(
    detail_rows: list[dict[str, Any]],
) -> dict[tuple[Any, ...], dict[str, float | int]]:
    groups: dict[tuple[Any, ...], dict[str, float | int]] = defaultdict(
        lambda: {
            "eligible_points": 0,
            "missing_points": 0,
            "total_points": 0,
            "sum_signed_error": 0.0,
            "sum_absolute_error": 0.0,
            "sum_squared_error": 0.0,
            "forecast_energy_kwh": 0.0,
            "actual_energy_kwh": 0.0,
        }
    )
    for row in detail_rows:
        metadata = row["run_metadata"] or {}
        period = row["period_start_utc"]
        horizon = (period - row["created_at_utc"]).total_seconds() / 3600
        key = (
            period.date(),
            row["forecast_type"],
            row["model_version"],
            alignment_version(metadata),
            str(metadata.get("training_policy", "legacy_all_eligible")),
            _horizon_bucket(horizon),
            (
                "weekend"
                if period.astimezone(ZoneInfo("Australia/Brisbane")).weekday() >= 5
                else "weekday"
            ),
        )
        aggregate = groups[key]
        aggregate["total_points"] += 1
        eligible = bool(row["actual_available"] and row["health_eligible"])
        if not eligible or row["actual_value"] is None:
            aggregate["missing_points"] += 1
            continue
        aggregate["eligible_points"] += 1
        aggregate["sum_signed_error"] += float(row["signed_error"] or 0)
        aggregate["sum_absolute_error"] += float(row["absolute_error"] or 0)
        aggregate["sum_squared_error"] += float(row["squared_error"] or 0)
        aggregate["forecast_energy_kwh"] += float(row["expected_value"]) / 12000
        aggregate["actual_energy_kwh"] += float(row["actual_value"]) / 12000
    return groups


def _prune_attempt_batch(
    repository: Any, *, claim_id: int, run_cutoff: datetime
) -> int:
    with repository.transaction() as session:
        attempt_ids = list(
            session.scalars(
                select(ForecastOperationAttempt.id)
                .where(ForecastOperationAttempt.scheduled_for_utc < run_cutoff)
                .order_by(ForecastOperationAttempt.scheduled_for_utc)
                .limit(METADATA_BATCH_SIZE)
            )
        )
        deleted = (
            session.execute(
                delete(ForecastOperationAttempt).where(
                    ForecastOperationAttempt.id.in_(attempt_ids)
                )
            ).rowcount
            if attempt_ids
            else 0
        )
        if deleted:
            session.execute(
                update(ForecastMaintenanceRun)
                .where(ForecastMaintenanceRun.id == claim_id)
                .values(
                    attempts_deleted=(ForecastMaintenanceRun.attempts_deleted + deleted)
                )
            )
    return int(deleted or 0)


def _prune_run_batch(
    repository: Any, *, claim_id: int, run_cutoff: datetime
) -> dict[str, int]:
    with repository.transaction() as session:
        old_run_ids = list(
            session.scalars(
                select(ForecastRun.id)
                .where(
                    ForecastRun.created_at_utc < run_cutoff,
                    ~select(ForecastPoint.id)
                    .where(ForecastPoint.forecast_run_id == ForecastRun.id)
                    .exists(),
                )
                .order_by(ForecastRun.created_at_utc)
                .limit(METADATA_BATCH_SIZE)
            )
        )
        reserve_ids = (
            list(
                session.scalars(
                    select(ReserveRun.id).where(
                        ReserveRun.forecast_run_id.in_(old_run_ids)
                    )
                )
            )
            if old_run_ids
            else []
        )
        if reserve_ids:
            session.execute(
                delete(ReserveOpportunityEvaluation).where(
                    ReserveOpportunityEvaluation.reserve_run_id.in_(reserve_ids)
                )
            )
        reserve_deleted = (
            session.execute(
                delete(ReserveRun).where(ReserveRun.id.in_(reserve_ids))
            ).rowcount
            if reserve_ids
            else 0
        )
        runs_deleted = (
            session.execute(
                delete(ForecastRun).where(ForecastRun.id.in_(old_run_ids))
            ).rowcount
            if old_run_ids
            else 0
        )
        if reserve_deleted or runs_deleted:
            session.execute(
                update(ForecastMaintenanceRun)
                .where(ForecastMaintenanceRun.id == claim_id)
                .values(
                    reserve_runs_deleted=(
                        ForecastMaintenanceRun.reserve_runs_deleted + reserve_deleted
                    ),
                    runs_deleted=ForecastMaintenanceRun.runs_deleted + runs_deleted,
                )
            )
    return {
        "reserve_runs_deleted": int(reserve_deleted or 0),
        "runs_deleted": int(runs_deleted or 0),
    }


def _finish_daily_run(
    repository: Any,
    *,
    claim_id: int,
    current: datetime,
    status: str,
    metadata: dict[str, Any],
) -> None:
    with repository.transaction() as session:
        session.execute(
            update(ForecastMaintenanceRun)
            .where(ForecastMaintenanceRun.id == claim_id)
            .values(
                finished_at_utc=current,
                status=status,
                metadata_json=metadata,
            )
        )


def _retention_diagnostics(
    *,
    eligible: dict[str, int],
    pruned: dict[str, int],
    remaining: dict[str, int],
    batches_executed: int,
    batch_size: int,
    maximum_rows_per_run: int,
    estimated_daily_creation_rate: int,
) -> dict[str, Any]:
    capacity_ok = maximum_rows_per_run > estimated_daily_creation_rate
    largest_remaining = max(remaining.values(), default=0)
    net_daily_reduction = maximum_rows_per_run - estimated_daily_creation_rate
    return {
        "detail_rows_eligible": dict(eligible),
        "rows_pruned_this_run": dict(pruned),
        "rows_remaining_eligible": dict(remaining),
        "batches_executed": batches_executed,
        "batch_size": batch_size,
        "maximum_rows_per_run": maximum_rows_per_run,
        "estimated_daily_creation_rate": estimated_daily_creation_rate,
        "steady_state_capacity_ok": capacity_ok,
        "estimated_days_to_clear_backlog": (
            0
            if largest_remaining == 0
            else (
                ceil(largest_remaining / net_daily_reduction)
                if net_daily_reduction > 0
                else None
            )
        ),
    }


def _horizon_bucket(hours: float) -> str:
    if hours < 3:
        return "0-3h"
    if hours < 6:
        return "3-6h"
    if hours < 12:
        return "6-12h"
    return "12-24h" if hours < 24 else "24h+"
