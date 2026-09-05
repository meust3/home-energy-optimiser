"""Bounded in-process forecast operations for the read-only Home Assistant App."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from energy_optimizer.demand_forecast import forecast_household_demand
from energy_optimizer.forecast_alignment import (
    FULL_FIVE_MINUTE_ALIGNMENT,
    operational_forecast_window,
)
from energy_optimizer.forecast_calibration import (
    CURRENT_FORECAST_MODEL_VERSION,
    HORIZON_NAMES,
    CalibrationIdentity,
    calculate_forecast_calibration_from_rollups,
)
from energy_optimizer.forecast_retention import run_forecast_retention
from energy_optimizer.forecast_rollups import (
    forecast_rollup_backfill_status,
    refresh_forecast_accuracy_rollups,
)
from energy_optimizer.models import CollectorConfig, ForecastPoint, ForecastRun
from energy_optimizer.reserve import estimate_battery_reserve
from energy_optimizer.shadow_decisioning import (
    OUTCOME_SCORING_VERSION,
    CalibrationGate,
    ShadowDecisionConfig,
    evaluate_shadow_decision,
    score_shadow_outcome,
)

LOGGER = logging.getLogger(__name__)
FORECAST_MODEL_VERSION = CURRENT_FORECAST_MODEL_VERSION
RESERVE_MODEL_VERSION = "reserve-estimator-v1"


@dataclass(frozen=True)
class ForecastOperationsConfig:
    enabled: bool = False
    interval_minutes: int = 30
    horizon_hours: int = 24
    alignment_minutes: int = 30
    scoring_delay_minutes: int = 10
    max_runtime_seconds: int = 120
    reserve_snapshot_enabled: bool = True
    timezone: str = "Australia/Brisbane"
    collector_grace_seconds: int = 20

    def __post_init__(self) -> None:
        if not 15 <= self.interval_minutes <= 1440:
            raise ValueError("forecast interval must be 15-1440 minutes")
        if not 1 <= self.horizon_hours <= 168:
            raise ValueError("forecast horizon must be 1-168 hours")
        if self.alignment_minutes not in {5, 10, 15, 20, 30, 60}:
            raise ValueError("forecast alignment must divide an hour")
        if 60 % self.alignment_minutes:
            raise ValueError("forecast alignment must divide an hour")
        if self.interval_minutes % self.alignment_minutes:
            raise ValueError("forecast interval must be a multiple of alignment")
        if not 0 <= self.scoring_delay_minutes <= 1440:
            raise ValueError("forecast scoring delay must be 0-1440 minutes")
        if not 30 <= self.max_runtime_seconds <= 900:
            raise ValueError("forecast runtime must be 30-900 seconds")


def next_aligned_boundary(
    now: datetime, *, timezone_name: str, alignment_minutes: int
) -> datetime:
    """Return the next strict local wall-clock boundary, represented in UTC."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scheduler time must be timezone-aware")
    local = now.astimezone(ZoneInfo(timezone_name)).replace(second=0, microsecond=0)
    minutes = local.hour * 60 + local.minute
    next_minutes = ((minutes // alignment_minutes) + 1) * alignment_minutes
    day_offset, minute_of_day = divmod(next_minutes, 24 * 60)
    boundary = local.replace(hour=0, minute=0) + timedelta(
        days=day_offset, minutes=minute_of_day
    )
    return boundary.astimezone(UTC)


class ForecastCoordinator:
    """One cooperative scheduling thread; no workers, processes, or HA writes."""

    def __init__(
        self,
        *,
        repository_factory: Callable[[], Any],
        collector_config: CollectorConfig,
        operations_config: ForecastOperationsConfig,
        health: Any,
        shadow_config: ShadowDecisionConfig | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repository_factory = repository_factory
        self.collector_config = collector_config
        self.config = operations_config
        self.health = health
        self.shadow_config = shadow_config or ShadowDecisionConfig()
        self.clock = clock
        self.monotonic = monotonic
        self._active = threading.Lock()
        self._stop_requested: Callable[[], bool] = lambda: False

    def run(self, stop_event: threading.Event) -> None:
        self._stop_requested = stop_event.is_set
        if not self.config.enabled:
            self.health.configure_forecast_scheduler(enabled=False, next_run=None)
            if hasattr(self.health, "configure_shadow_decisioning"):
                self.health.configure_shadow_decisioning(enabled=False)
            return
        if hasattr(self.health, "configure_shadow_decisioning"):
            self.health.configure_shadow_decisioning(enabled=self.shadow_config.enabled)
        recovered_at = self.clock().astimezone(UTC)
        try:
            repository = self.repository_factory()
            try:
                repository.recover_stale_forecast_operations(
                    before=recovered_at
                    - timedelta(seconds=self.config.max_runtime_seconds),
                    recovered_at=recovered_at,
                )
            finally:
                repository.close()
        except Exception:
            self.health.record_forecast_failure(
                reserve=self.config.reserve_snapshot_enabled
            )
            LOGGER.error("Forecast recovery audit failed; next boundary will retry")
        while not stop_event.is_set():
            boundary = next_aligned_boundary(
                self.clock(),
                timezone_name=self.config.timezone,
                alignment_minutes=self.config.interval_minutes,
            )
            self.health.configure_forecast_scheduler(enabled=True, next_run=boundary)
            wake_at = boundary + timedelta(seconds=self.config.collector_grace_seconds)
            delay = max((wake_at - self.clock().astimezone(UTC)).total_seconds(), 0)
            if stop_event.wait(delay):
                break
            try:
                self.run_boundary(boundary)
            except Exception:
                self.health.record_forecast_failure(
                    reserve=self.config.reserve_snapshot_enabled
                )
                LOGGER.error("Forecast boundary failed before a claim was recorded")

    def run_boundary(self, scheduled_for: datetime) -> bool:
        """Claim and execute one boundary; return false for duplicate/overlap."""
        started_at = self.clock().astimezone(UTC)
        repository = self.repository_factory()
        attempt_id: int | None = None
        if not self._active.acquire(blocking=False):
            try:
                attempt_id = repository.claim_forecast_operation(
                    scheduled_for=scheduled_for, started_at=started_at
                )
                if attempt_id is not None:
                    repository.finish_forecast_operation(
                        attempt_id,
                        status="skipped",
                        finished_at=started_at,
                        duration_seconds=0,
                        failure_summary="Prior forecast operation still active",
                    )
            finally:
                repository.close()
            return False
        started_monotonic = self.monotonic()
        durable_lock: Any = None
        forecast_run_id: int | None = None
        forecast_point_count = 0
        try:
            durable_lock = repository.try_forecast_operation_lock()
            if durable_lock is False:
                attempt_id = repository.claim_forecast_operation(
                    scheduled_for=scheduled_for, started_at=started_at
                )
                if attempt_id is not None:
                    repository.finish_forecast_operation(
                        attempt_id,
                        status="skipped",
                        finished_at=started_at,
                        duration_seconds=0,
                        failure_summary="Another forecast operation holds the lock",
                    )
                return False
            attempt_id = repository.claim_forecast_operation(
                scheduled_for=scheduled_for, started_at=started_at
            )
            if attempt_id is None:
                return False
            forecast_run = self._build_forecast(repository, started_at)
            forecast_run_id = repository.save_forecast_run(forecast_run)
            forecast_point_count = len(forecast_run.points)
            self._check_deadline(started_monotonic)
            scored = repository.score_completed_forecast_points(
                now=started_at,
                delay_minutes=self.config.scoring_delay_minutes,
                runtime_guard=lambda: self._check_deadline(started_monotonic),
            )
            self._check_deadline(started_monotonic)
            rollup_result: dict[str, Any] | None = None
            rollup_status: dict[str, Any] | None = None
            try:
                local_today = started_at.astimezone(
                    ZoneInfo(self.config.timezone)
                ).date()
                window_start = local_today - timedelta(
                    days=self.collector_config.calibration_window_days
                )
                rollup_status = forecast_rollup_backfill_status(
                    repository,
                    forecast_type="baseline_household_load",
                    model_version=FORECAST_MODEL_VERSION,
                    alignment_version_name=FULL_FIVE_MINUTE_ALIGNMENT,
                    training_policy=self.collector_config.demand_training_policy,
                    window_start=window_start,
                    window_end=local_today,
                    timezone_name=self.config.timezone,
                )
                if (
                    rollup_status["detail_query_truncated"]
                    or rollup_status["rollup_query_truncated"]
                ):
                    raise RuntimeError("calibration rollup inventory truncated")
                missing_dates = rollup_status["remaining_local_dates"][:2]
                refresh_dates = list(missing_dates)
                yesterday = local_today - timedelta(days=1)
                if yesterday >= window_start and yesterday not in refresh_dates:
                    refresh_dates.append(yesterday)
                rollup_result = refresh_forecast_accuracy_rollups(
                    repository,
                    local_dates=refresh_dates,
                    timezone_name=self.config.timezone,
                    complete_day_coverage_percent=(
                        self.collector_config.calibration_complete_day_coverage_percent
                    ),
                    now=started_at,
                )
                rollup_status = forecast_rollup_backfill_status(
                    repository,
                    forecast_type="baseline_household_load",
                    model_version=FORECAST_MODEL_VERSION,
                    alignment_version_name=FULL_FIVE_MINUTE_ALIGNMENT,
                    training_policy=self.collector_config.demand_training_policy,
                    window_start=window_start,
                    window_end=local_today,
                    timezone_name=self.config.timezone,
                )
                rollup_result["backfill"] = {
                    key: value
                    for key, value in rollup_status.items()
                    if key != "remaining_local_dates"
                }
                LOGGER.info(
                    "Calibration rollup refresh succeeded dates=%s rollups=%s "
                    "identity=%s/%s/%s/%s",
                    rollup_result["dates_rebuilt"],
                    rollup_result["rollups_rebuilt"],
                    "baseline_household_load",
                    FORECAST_MODEL_VERSION,
                    FULL_FIVE_MINUTE_ALIGNMENT,
                    self.collector_config.demand_training_policy,
                )
                if hasattr(self.health, "record_calibration_rollup"):
                    self.health.record_calibration_rollup(
                        successful=True, progress=rollup_status
                    )
            except Exception as exc:
                # Analytical maintenance must never stop collection/forecasting.
                LOGGER.warning(
                    "Calibration rollup refresh failed: %s", _safe_failure(exc)
                )
                if hasattr(self.health, "record_calibration_rollup"):
                    self.health.record_calibration_rollup(
                        successful=False,
                        progress={
                            "rollup_backfill_status": "warning",
                            "last_failure": _safe_failure(exc),
                        },
                    )
            reserve_run_id = None
            if self.config.reserve_snapshot_enabled:
                estimate = estimate_battery_reserve(
                    repository,
                    self.collector_config,
                    now=started_at,
                    source="history",
                    as_of=started_at,
                )
                estimate.operational_context["linked_forecast_reconciliation"] = (
                    build_reserve_forecast_reconciliation(estimate, forecast_run)
                )
                reserve_run_id = repository.save_reserve_run(
                    estimate,
                    forecast_run_id=forecast_run_id,
                    model_version=RESERVE_MODEL_VERSION,
                )
                self.health.record_reserve_success(started_at)
            self._check_deadline(started_monotonic)
            decision_run_id = None
            outcome_count = 0
            if self.shadow_config.enabled and reserve_run_id is not None:
                decision_started = self.monotonic()
                try:
                    forecast_snapshot = repository.forecast_run(forecast_run_id)
                    reserve_snapshot = repository.reserve_audit_read_only(
                        reserve_run_id
                    )
                    observation_snapshot = repository.observation_as_of_read_only(
                        started_at
                    )
                    calibration_gate = _decision_calibration_gate(
                        repository,
                        forecast_snapshot=forecast_snapshot,
                        rollup_status=rollup_status,
                        collector_config=self.collector_config,
                        timezone_name=self.config.timezone,
                        now=started_at,
                    )
                    result = evaluate_shadow_decision(
                        decision_boundary_utc=scheduled_for,
                        created_at_utc=started_at,
                        observation=observation_snapshot,
                        forecast_run=forecast_snapshot,
                        reserve_run=reserve_snapshot,
                        calibration=calibration_gate,
                        collector_config=self.collector_config,
                        config=self.shadow_config,
                    )
                    if (
                        self.monotonic() - decision_started
                        > self.shadow_config.max_runtime_seconds
                    ):
                        raise TimeoutError("Shadow decision runtime exceeded")
                    decision_run_id = repository.save_shadow_decision(
                        result,
                        forecast_run_id=forecast_run_id,
                        reserve_run_id=reserve_run_id,
                        shadow_enabled=True,
                        non_hold_enabled=(
                            self.shadow_config.allow_non_hold_recommendations
                        ),
                    )
                    if hasattr(self.health, "record_shadow_decision"):
                        self.health.record_shadow_decision(
                            timestamp=started_at,
                            status=result.status,
                            successful=decision_run_id is not None,
                        )
                    LOGGER.info(
                        "Shadow decision boundary=%s action=%s candidates=%s "
                        "no_command_issued=true expected_gross_value_aud=%s",
                        scheduled_for.isoformat(),
                        result.selected_action,
                        len(result.candidates),
                        (
                            result.selected_candidate.gross_incremental_value_aud
                            if result.selected_candidate
                            else None
                        ),
                    )
                except Exception as exc:
                    if hasattr(self.health, "record_shadow_decision"):
                        self.health.record_shadow_decision(
                            timestamp=started_at,
                            status="exception",
                            successful=False,
                        )
                    LOGGER.warning(
                        "Shadow decision failed; forecast and collection remain "
                        "active: %s",
                        _safe_failure(exc),
                    )
                try:
                    outcome_count = self._score_shadow_outcomes(
                        repository, now=started_at, started=started_monotonic
                    )
                    if outcome_count and hasattr(
                        self.health, "record_shadow_outcome_success"
                    ):
                        self.health.record_shadow_outcome_success(started_at)
                except Exception as exc:
                    if hasattr(self.health, "record_shadow_outcome_failure"):
                        self.health.record_shadow_outcome_failure()
                    LOGGER.warning(
                        "Shadow outcome scoring failed; collection remains active: %s",
                        _safe_failure(exc),
                    )
            elif self.shadow_config.enabled and hasattr(
                self.health, "record_shadow_decision"
            ):
                self.health.record_shadow_decision(
                    timestamp=started_at,
                    status="reserve_missing",
                    successful=False,
                )
            self._check_deadline(started_monotonic)
            finished = self.clock().astimezone(UTC)
            duration = self.monotonic() - started_monotonic
            repository.finish_forecast_operation(
                attempt_id,
                status="success",
                finished_at=finished,
                duration_seconds=duration,
                forecast_run_id=forecast_run_id,
                reserve_run_id=reserve_run_id,
                forecast_point_count=len(forecast_run.points),
                metadata={
                    "scored_point_count": scored,
                    "calibration_rollup": rollup_result,
                    "shadow_decision_run_id": decision_run_id,
                    "shadow_outcomes_scored": outcome_count,
                },
            )
            repository.release_forecast_operation_lock(durable_lock)
            durable_lock = None
            if self.collector_config.retention_enabled:
                try:
                    retention = run_forecast_retention(
                        repository,
                        now=finished,
                        point_retention_days=(
                            self.collector_config.forecast_point_retention_days
                        ),
                        run_retention_days=(
                            self.collector_config.forecast_run_retention_days
                        ),
                        runtime_guard=lambda: self._check_deadline(started_monotonic),
                        should_stop=self._stop_requested,
                    )
                    LOGGER.info(
                        "Forecast retention status=%s points_deleted=%s",
                        retention["status"],
                        retention.get("points_deleted", 0),
                    )
                except Exception:
                    LOGGER.error(
                        "Forecast retention failed; forecast and collection remain "
                        "active"
                    )
            self.health.record_forecast_success(started_at)
            return True
        except Exception as exc:
            finished = self.clock().astimezone(UTC)
            if attempt_id is not None:
                try:
                    repository.finish_forecast_operation(
                        attempt_id,
                        status="failed",
                        finished_at=finished,
                        duration_seconds=self.monotonic() - started_monotonic,
                        forecast_run_id=forecast_run_id,
                        forecast_point_count=forecast_point_count,
                        failure_summary=_safe_failure(exc),
                    )
                except Exception:
                    LOGGER.error("Forecast failure audit could not be stored")
            self.health.record_forecast_failure(
                reserve=self.config.reserve_snapshot_enabled
            )
            LOGGER.error("Forecast operation failed; details withheld")
            return False
        finally:
            repository.release_forecast_operation_lock(durable_lock)
            repository.close()
            self._active.release()

    def _build_forecast(self, repository: Any, created_at: datetime) -> ForecastRun:
        window = operational_forecast_window(
            created_at, horizon_hours=self.config.horizon_hours
        )
        local_start = window.start_utc.astimezone(ZoneInfo(self.config.timezone))
        local_end = window.end_utc.astimezone(ZoneInfo(self.config.timezone))
        rows = repository.reserve_history_rows_read_only(
            days=self.collector_config.reserve_history_days,
            now=created_at,
            as_of=created_at,
        )
        demand = forecast_household_demand(
            rows,
            start_local=local_start,
            end_local=local_end,
            minimum_samples=self.collector_config.load_profile_minimum_samples,
            fallback_kw=self.collector_config.conservative_fallback_household_load_kw,
            fallback_mode=self.collector_config.reserve_fallback_mode,
            fallback_band_powers_kw={
                "overnight": self.collector_config.reserve_fallback_overnight_kw,
                "morning": self.collector_config.reserve_fallback_morning_kw,
                "daytime": self.collector_config.reserve_fallback_daytime_kw,
                "evening": self.collector_config.reserve_fallback_evening_kw,
                "late_evening": self.collector_config.reserve_fallback_late_evening_kw,
            },
            recent_days=self.collector_config.reserve_recent_days,
            tier2_minimum_samples=self.collector_config.demand_tier2_minimum_samples,
            tier3_minimum_samples=self.collector_config.demand_tier3_minimum_samples,
            tier4_minimum_samples=self.collector_config.demand_tier4_minimum_samples,
            tier4_lookback_days=self.collector_config.demand_tier4_lookback_days,
            weekend_days=self.collector_config.demand_weekend_days,
            complete_period_fraction=self.collector_config.demand_complete_period_fraction,
            low_ceiling_complete_days=self.collector_config.demand_low_ceiling_complete_days,
            medium_low_ceiling_complete_days=(
                self.collector_config.demand_medium_low_ceiling_complete_days
            ),
            weak_tier_share_ceiling=(
                self.collector_config.demand_weak_tier_share_ceiling
            ),
            training_policy=self.collector_config.demand_training_policy,
        )
        points = [
            ForecastPoint(
                period_start_utc=slot.period_start_local.astimezone(UTC),
                period_end_utc=slot.period_end_local.astimezone(UTC),
                expected_value=slot.estimated_power_kw * 1000,
                unit="W",
                metadata={
                    "tier": slot.tier,
                    "sample_count": slot.sample_count,
                    "variability": slot.variability,
                    "source": slot.explanation,
                    "local_hour": slot.period_start_local.hour,
                    "day_type": (
                        "weekend"
                        if slot.period_start_local.weekday()
                        in self.collector_config.demand_weekend_days
                        else "weekday"
                    ),
                },
            )
            for slot in demand.slot_decisions
        ]
        return ForecastRun(
            created_at_utc=created_at,
            forecast_type="baseline_household_load",
            source="scheduled_forecast_operations",
            horizon_start_utc=local_start.astimezone(UTC),
            horizon_end_utc=local_end.astimezone(UTC),
            model_version=FORECAST_MODEL_VERSION,
            metadata={
                "run_kind": "genuine_out_of_sample",
                "alignment_version": FULL_FIVE_MINUTE_ALIGNMENT,
                "training_policy": self.collector_config.demand_training_policy,
                "training_cohort_counts": (demand.diagnostics.training_cohort_counts),
                "training_cohort_shares": {
                    "verified": demand.diagnostics.verified_share,
                    "unverified": demand.diagnostics.unverified_share,
                },
                "contamination_risk": (
                    demand.diagnostics.unidentified_ev_contamination_risk
                ),
                "configuration": {
                    "horizon_hours": self.config.horizon_hours,
                    "history_days": self.collector_config.reserve_history_days,
                    "fallback_mode": self.collector_config.reserve_fallback_mode,
                },
                "input_summary": demand.diagnostics.model_dump(mode="json"),
                "confidence": demand.confidence,
                "confidence_score": demand.confidence_score,
            },
            points=points,
        )

    def _check_deadline(self, started: float) -> None:
        if self.monotonic() - started > self.config.max_runtime_seconds:
            raise TimeoutError("Forecast operation exceeded configured runtime")

    def _score_shadow_outcomes(
        self, repository: Any, *, now: datetime, started: float
    ) -> int:
        pending = repository.pending_shadow_decisions_for_scoring(
            now=now,
            delay_minutes=self.shadow_config.outcome_scoring_delay_minutes,
            scoring_version=OUTCOME_SCORING_VERSION,
        )
        stored = 0
        for decision in pending:
            self._check_deadline(started)
            detail = repository.shadow_decision_detail_read_only(int(decision["id"]))
            if detail is None:
                continue
            rows = repository.shadow_outcome_observations_read_only(
                start=decision["selected_start_utc"],
                end=decision["selected_end_utc"],
            )
            outcome = score_shadow_outcome(
                decision_run=decision,
                candidates=detail["candidates"],
                observations=rows,
                scored_at_utc=now,
            )
            if repository.save_shadow_outcome(outcome) is not None:
                stored += 1
        if pending:
            LOGGER.info(
                "Shadow outcome scoring matured=%s stored=%s", len(pending), stored
            )
        return stored


def _represented_calibration_rollup_dates(
    rows: list[dict[str, Any]], *, training_policy: str
) -> set[date]:
    """Return dates with all current-identity horizon rollups."""
    represented_horizons: dict[date, set[str]] = {}
    for row in rows:
        if (
            row.get("forecast_type") == "baseline_household_load"
            and row.get("model_version") == FORECAST_MODEL_VERSION
            and row.get("alignment_version") == FULL_FIVE_MINUTE_ALIGNMENT
            and row.get("training_policy") == training_policy
            and row.get("calculated_at_utc") is not None
        ):
            represented_horizons.setdefault(row["rollup_date"], set()).add(
                str(row.get("horizon_bucket"))
            )
    return {
        rollup_date
        for rollup_date, horizons in represented_horizons.items()
        if horizons == set(HORIZON_NAMES)
    }


def _decision_calibration_gate(
    repository: Any,
    *,
    forecast_snapshot: dict[str, Any] | None,
    rollup_status: dict[str, Any] | None,
    collector_config: CollectorConfig,
    timezone_name: str,
    now: datetime,
) -> CalibrationGate:
    """Bind the gate to the exact linked run and completed local-date evidence."""
    zone = ZoneInfo(timezone_name)
    local_today = now.astimezone(zone).date()
    start_date = local_today - timedelta(days=collector_config.calibration_window_days)
    rows, truncated = repository.forecast_rollup_rows_read_only(
        after_date=start_date,
        before_date=local_today,
    )
    identity = CalibrationIdentity(
        forecast_type="baseline_household_load",
        model_version=FORECAST_MODEL_VERSION,
        alignment_version=FULL_FIVE_MINUTE_ALIGNMENT,
        training_policy=collector_config.demand_training_policy,
    )
    report = calculate_forecast_calibration_from_rollups(
        rows,
        current_identity=identity,
        minimum_complete_dates=collector_config.calibration_min_complete_days,
        complete_day_coverage_percent=(
            collector_config.calibration_complete_day_coverage_percent
        ),
        minimum_weekday_dates=collector_config.calibration_min_weekday_days,
        minimum_weekend_dates=collector_config.calibration_min_weekend_days,
        requested_start=datetime.combine(
            start_date, datetime.min.time(), zone
        ).astimezone(UTC),
        requested_end=datetime.combine(
            local_today, datetime.min.time(), zone
        ).astimezone(UTC),
        truncated=truncated,
    )
    metadata = (forecast_snapshot or {}).get("metadata_json") or {}
    matches = bool(
        forecast_snapshot
        and forecast_snapshot.get("forecast_type") == identity.forecast_type
        and forecast_snapshot.get("model_version") == identity.model_version
        and metadata.get("alignment_version") == identity.alignment_version
        and metadata.get("training_policy") == identity.training_policy
    )
    backfill_complete = bool(
        rollup_status and rollup_status.get("current_identity_complete")
    )
    blocks = list(report.quality_blocks)
    if not backfill_complete and "rollup_backfill_incomplete" not in blocks:
        blocks.append("rollup_backfill_incomplete")
    return CalibrationGate(
        identity=identity.model_dump(),
        identity_matches=matches,
        status=report.status,
        independent_evidence_sufficient=report.independent_evidence_sufficient,
        required_horizons_present=report.required_horizons_present,
        quality_blocks=tuple(blocks),
        rollup_backfill_complete=backfill_complete,
    )


def _safe_failure(exc: Exception) -> str:
    """Return a bounded class-only failure summary with no option/secret values."""
    if isinstance(exc, TimeoutError):
        return "Configured forecast runtime exceeded"
    return f"{type(exc).__name__} during forecast operation"[:500]


def build_reserve_forecast_reconciliation(
    estimate: Any, forecast_run: ForecastRun
) -> dict[str, Any]:
    """Explain how reserve demand spans the linked forecast's aligned start."""
    evaluation = estimate.evaluation_time_local.astimezone(UTC)
    reserve_end = estimate.forecast_end_local.astimezone(UTC)
    linked_start = forecast_run.horizon_start_utc.astimezone(UTC)
    linked_end = forecast_run.horizon_end_utc.astimezone(UTC)
    linked_intervals = {
        (
            point.period_start_utc.astimezone(UTC),
            point.period_end_utc.astimezone(UTC),
        ): point
        for point in forecast_run.points
    }
    gap_end = min(linked_start, reserve_end)
    gap_energy = 0.0
    shared_reserve_energy = 0.0
    shared_linked_energy = 0.0
    shared_count = 0
    for slot in estimate.demand_forecast.slot_decisions:
        start = slot.period_start_local.astimezone(UTC)
        end = slot.period_end_local.astimezone(UTC)
        if end <= gap_end:
            gap_energy += slot.expected_energy_kwh
        linked_point = linked_intervals.get((start, end))
        if linked_point is not None:
            shared_count += 1
            shared_reserve_energy += slot.expected_energy_kwh
            shared_linked_energy += float(linked_point.expected_value) / 12_000
    total = float(estimate.demand_forecast.expected_energy_kwh)
    boundary_remainder = max(total - gap_energy - shared_reserve_energy, 0.0)
    reconciled = gap_energy + shared_reserve_energy + boundary_remainder
    return {
        "semantics": "reserve_starts_at_evaluation_with_partial_boundaries",
        "evaluation_time_utc": evaluation.isoformat(),
        "reserve_horizon_start_utc": (
            estimate.forecast_start_local.astimezone(UTC).isoformat()
        ),
        "reserve_horizon_end_utc": reserve_end.isoformat(),
        "linked_forecast_start_utc": linked_start.isoformat(),
        "linked_forecast_end_utc": linked_end.isoformat(),
        "history_as_of_utc": evaluation.isoformat(),
        "alignment_gap_minutes": round(
            max((gap_end - evaluation).total_seconds() / 60, 0.0), 6
        ),
        "alignment_gap_demand_kwh": round(gap_energy, 6),
        "shared_full_interval_count": shared_count,
        "shared_full_interval_reserve_demand_kwh": round(shared_reserve_energy, 6),
        "shared_full_interval_linked_demand_kwh": round(shared_linked_energy, 6),
        "reserve_only_boundary_demand_kwh": round(boundary_remainder, 6),
        "reserve_expected_household_demand_kwh": round(total, 6),
        "reconciled_reserve_demand_kwh": round(reconciled, 6),
        "reconciliation_error_kwh": round(total - reconciled, 9),
        "linked_operational_point_count": len(forecast_run.points),
        "linked_operational_points_are_full_five_minutes": all(
            point.period_end_utc - point.period_start_utc == timedelta(minutes=5)
            for point in forecast_run.points
        ),
        "linked_forecast_demand_is_not_added_to_reserve_total": True,
    }
