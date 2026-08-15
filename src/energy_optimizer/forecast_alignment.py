"""Canonical operational forecast and actual-slot alignment rules."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

AlignmentVersion = Literal["legacy_execution_time", "full_5m_v1"]
LEGACY_ALIGNMENT: AlignmentVersion = "legacy_execution_time"
FULL_FIVE_MINUTE_ALIGNMENT: AlignmentVersion = "full_5m_v1"


@dataclass(frozen=True)
class OperationalForecastWindow:
    created_at_utc: datetime
    start_utc: datetime
    end_utc: datetime
    interval_minutes: int

    @property
    def point_count(self) -> int:
        seconds = (self.end_utc - self.start_utc).total_seconds()
        return int(seconds // (self.interval_minutes * 60))


def operational_forecast_window(
    created_at: datetime, *, horizon_hours: int, interval_minutes: int = 5
) -> OperationalForecastWindow:
    """Return the first complete interval boundary at or after creation."""
    _require_aware(created_at)
    if horizon_hours <= 0 or interval_minutes <= 0 or 60 % interval_minutes:
        raise ValueError("operational forecast interval and horizon must be positive")
    created = created_at.astimezone(UTC)
    floor = created.replace(
        minute=(created.minute // interval_minutes) * interval_minutes,
        second=0,
        microsecond=0,
    )
    start = floor if floor == created else floor + timedelta(minutes=interval_minutes)
    return OperationalForecastWindow(
        created_at_utc=created,
        start_utc=start,
        end_utc=start + timedelta(hours=horizon_hours),
        interval_minutes=interval_minutes,
    )


def alignment_version(metadata: Any) -> AlignmentVersion:
    """Return explicit provenance, treating missing legacy metadata truthfully."""
    value = metadata.get("alignment_version") if isinstance(metadata, dict) else None
    return (
        FULL_FIVE_MINUTE_ALIGNMENT
        if value == FULL_FIVE_MINUTE_ALIGNMENT
        else LEGACY_ALIGNMENT
    )


def is_full_five_minute_interval(start: datetime, end: datetime) -> bool:
    _require_aware(start)
    _require_aware(end)
    start_utc = start.astimezone(UTC)
    return (
        start_utc.second == 0
        and start_utc.microsecond == 0
        and start_utc.minute % 5 == 0
        and end.astimezone(UTC) - start_utc == timedelta(minutes=5)
    )


def actual_slot_matches(
    slot_utc: datetime,
    *,
    period_start_utc: datetime,
    period_end_utc: datetime,
    version: AlignmentVersion,
) -> bool:
    """Canonical in-memory rule mirrored by repository SQL predicates."""
    slot = slot_utc.astimezone(UTC)
    start = period_start_utc.astimezone(UTC)
    end = period_end_utc.astimezone(UTC)
    return (
        slot == start if version == FULL_FIVE_MINUTE_ALIGNMENT else start <= slot < end
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("forecast alignment requires timezone-aware timestamps")
