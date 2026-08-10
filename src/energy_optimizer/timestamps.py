"""Canonical timezone-aware application timestamp handling."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.types import TypeDecorator


def aware_datetime(value: datetime | str, *, assume_utc: bool = False) -> datetime:
    """Return an aware datetime from a database/domain value."""
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if not isinstance(parsed, datetime):
        raise TypeError("timestamp must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if not assume_utc:
            raise ValueError("timestamp must include a timezone offset")
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def utc_datetime(value: datetime | str) -> datetime:
    return aware_datetime(value, assume_utc=True).astimezone(UTC)


def iso_timestamp(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return aware_datetime(value, assume_utc=True).isoformat()


def compact_timestamp(value: datetime | str) -> str:
    return aware_datetime(value, assume_utc=True).strftime("%m-%d %H:%M")


def json_safe(value: Any) -> Any:
    """Recursively convert timestamps at a JSON serialization boundary."""
    if isinstance(value, datetime):
        return aware_datetime(value, assume_utc=True).isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def native_json(value: Any) -> Any:
    """Normalize legacy serialized JSON while retaining native JSON values."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def terminal_value(value: Any, *, none: str = "N/A") -> str:
    """Render database/domain values safely at a terminal boundary."""
    if value is None:
        return none
    normalized = native_json(value)
    if isinstance(normalized, (list, dict)):
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return str(normalized)


class AwareDateTime(TypeDecorator[datetime]):
    """TIMESTAMPTZ on PostgreSQL and offset-preserving ISO text on SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self):
        return datetime

    def __init__(self, *, utc: bool = True) -> None:
        super().__init__()
        self.utc = utc

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String())
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        parsed = aware_datetime(value, assume_utc=self.utc)
        if self.utc:
            parsed = parsed.astimezone(UTC)
        return parsed.isoformat() if dialect.name == "sqlite" else parsed

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        parsed = aware_datetime(value, assume_utc=self.utc)
        return parsed.astimezone(UTC) if self.utc else parsed
