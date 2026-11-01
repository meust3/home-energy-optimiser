"""Receipt-time provenance and explicit target semantics for optional weather."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

UNKNOWN = "UNKNOWN"
MAX_BYTES = 5_000_000


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("weather timestamps require a timezone")
    return value.astimezone(UTC)


def epoch(value: Any) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid weather epoch timestamp")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        raise ValueError("invalid weather epoch timestamp") from None


@dataclass(frozen=True)
class Point:
    series: str
    variable: str
    valid_at: datetime
    interval_start: datetime
    interval_end: datetime
    semantics: str
    value: float | str | None
    unit: str
    source_path: str
    output_step_seconds: int | None
    native_resolution: str = UNKNOWN
    presence: str = "VALUE"

    def __post_init__(self) -> None:
        start, end, valid = map(
            utc, (self.interval_start, self.interval_end, self.valid_at)
        )
        if start > end or not start <= valid <= end:
            raise ValueError("invalid target interval")
        if isinstance(self.value, bool) or (
            isinstance(self.value, (int, float)) and not math.isfinite(self.value)
        ):
            raise ValueError("invalid normalized weather value")

    def as_dict(self) -> dict[str, Any]:
        return {
            k: v.isoformat() if isinstance(v, datetime) else v
            for k, v in asdict(self).items()
        }


@dataclass(frozen=True)
class Capture:
    provider: str
    product: str
    site_ref: str
    requested_at: datetime
    received_at: datetime
    raw: bytes = field(repr=False)
    points: tuple[Point, ...]
    requested_model: str = UNKNOWN
    model_identity: str = UNKNOWN
    provider_issue_time: datetime | None = None
    attribution: str = ""
    licence: str = ""
    parser_version: str = "weather-v1"
    normalization_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.site_ref):
            raise ValueError("use an opaque site reference")
        if utc(self.received_at) < utc(self.requested_at):
            raise ValueError("receipt precedes request")
        if not self.raw or len(self.raw) > MAX_BYTES or not self.points:
            raise ValueError("empty or oversized weather capture")
        keys = [(p.series, p.variable, p.valid_at) for p in self.points]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate weather target/variable")

    @property
    def raw_sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def version_sha256(self) -> str:
        """Normalized content version; every raw response is retained separately."""
        content = {
            "provider": self.provider,
            "product": self.product,
            "site_ref": self.site_ref,
            "requested_model": self.requested_model,
            "model_identity": self.model_identity,
            "issue_time": (
                utc(self.provider_issue_time).isoformat()
                if self.provider_issue_time
                else UNKNOWN
            ),
            "parser_version": self.parser_version,
            "points": sorted(
                (p.as_dict() for p in self.points),
                key=lambda p: (p["series"], p["variable"], p["valid_at"]),
            ),
        }
        return hashlib.sha256(
            json.dumps(content, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()


def body_from_bytes(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("empty or oversized weather response")
    try:

        def reject_constant(_value: str) -> None:
            raise ValueError("nonfinite weather JSON value")

        body = json.loads(raw, parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("invalid weather JSON") from None
    if not isinstance(body, dict):
        raise ValueError("weather response must be an object")
    return body


def numeric(
    value: Any, *, percent: bool = False, positive: bool = False
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid numeric weather value")
    if not math.isfinite(value) or (percent and not 0 <= value <= 100):
        raise ValueError("invalid numeric weather range")
    if positive and value < 0:
        raise ValueError("negative weather amount")
    return float(value)


Product = Literal[
    "open_meteo_hourly",
    "onecall4_current",
    "onecall4_1min",
    "onecall4_15min",
    "onecall4_1h",
    "onecall4_1day",
]
