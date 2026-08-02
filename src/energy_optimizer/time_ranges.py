"""Timezone-aware CLI date and datetime range parsing."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_range_value(value: str, timezone_name: str, *, end: bool = False) -> datetime:
    """Parse ISO date/datetime; naive inputs use the configured local timezone."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date or datetime: {value}") from exc
    if "T" not in value and " " not in value:
        parsed = datetime.combine(
            parsed.date(), time.max if end else time.min, tzinfo=ZoneInfo(timezone_name)
        )
    elif parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def resolve_history_range(
    *,
    from_value: str | None,
    to_value: str | None,
    days: int | None,
    timezone_name: str,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Resolve mutually exclusive relative or explicit inclusive ranges."""
    if days is not None and (from_value or to_value):
        raise ValueError("--days cannot be combined with --from or --to")
    if days is not None:
        if days <= 0:
            raise ValueError("--days must be positive")
        range_end = (now or datetime.now(UTC)).astimezone(UTC)
        return range_end - timedelta(days=days), range_end
    range_start = parse_range_value(from_value, timezone_name) if from_value else None
    range_end = (
        parse_range_value(to_value, timezone_name, end=True) if to_value else None
    )
    if range_start and range_end and range_end < range_start:
        raise ValueError("--to must not be before --from")
    return range_start, range_end
