"""Bounded in-process forecast operations for the read-only Home Assistant App."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from energy_optimizer.demand_forecast import forecast_household_demand
from energy_optimizer.models import CollectorConfig, ForecastPoint, ForecastRun
from energy_optimizer.reserve import estimate_battery_reserve

LOGGER = logging.getLogger(__name__)
FORECAST_MODEL_VERSION = "household-demand-hierarchy-v1"
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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repository_factory = repository_factory
        self.collector_config = collector_config
        self.config = operations_config
        self.health = health
        self.clock = clock
        self.monotonic = monotonic
        self._active = threading.Lock()

    def run(self, stop_event: threading.Event) -> None:
        if not self.config.enabled:
            self.health.configure_forecast_scheduler(enabled=False, next_run=None)
            return
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
            reserve_run_id = None
            if self.config.reserve_snapshot_enabled:
                estimate = estimate_battery_reserve(
                    repository,
                    self.collector_config,
                    now=started_at,
                    source="history",
                    as_of=started_at,
                )
                reserve_run_id = repository.save_reserve_run(
                    estimate,
                    forecast_run_id=forecast_run_id,
                    model_version=RESERVE_MODEL_VERSION,
                )
                self.health.record_reserve_success(started_at)
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
                metadata={"scored_point_count": scored},
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
        local_start = created_at.astimezone(ZoneInfo(self.config.timezone))
        local_end = local_start + timedelta(hours=self.config.horizon_hours)
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


def _safe_failure(exc: Exception) -> str:
    """Return a bounded class-only failure summary with no option/secret values."""
    if isinstance(exc, TimeoutError):
        return "Configured forecast runtime exceeded"
    return f"{type(exc).__name__} during forecast operation"[:500]
