"""Timezone-aware CLI date and datetime range parsing."""

from datetime import datetime, time
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
