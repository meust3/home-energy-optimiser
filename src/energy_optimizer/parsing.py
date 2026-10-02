"""Safe conversion of Home Assistant string and attribute values."""

from datetime import UTC, datetime, timedelta
from typing import Any

from energy_optimizer.models import (
    AmberPriceInterval,
    HomeAssistantState,
    SolarForecastInterval,
    SolarForecastSummary,
)

MISSING_STATES = {"", "unknown", "unavailable", "none", "null"}


def is_missing_state(value: Any) -> bool:
    return value is None or str(value).strip().lower() in MISSING_STATES


def parse_number(value: Any) -> float | None:
    if is_missing_state(value) or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return (
        result
        if result == result and result not in (float("inf"), float("-inf"))
        else None
    )


def parse_text(value: Any) -> str | None:
    return None if is_missing_state(value) else str(value).strip()


def parse_bool(value: Any) -> bool | None:
    if is_missing_state(value):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"on", "true", "yes", "1"}:
        return True
    if normalized in {"off", "false", "no", "0"}:
        return False
    return None


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    )


def parse_amber_intervals(state: HomeAssistantState | None) -> list[AmberPriceInterval]:
    if state is None:
        return []
    raw = state.attributes.get("forecasts", [])
    if not isinstance(raw, list):
        return []
    intervals: list[AmberPriceInterval] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        intervals.append(
            AmberPriceInterval(
                duration=item.get("duration"),
                start_time=parse_datetime(item.get("start_time")),
                end_time=parse_datetime(item.get("end_time")),
                per_kwh=parse_number(item.get("per_kwh")),
                spot_per_kwh=parse_number(item.get("spot_per_kwh")),
                renewables=parse_number(item.get("renewables")),
                descriptor=parse_text(item.get("descriptor")),
                spike_status=item.get("spike_status"),
            )
        )
    return intervals


def parse_solar_summary(
    state: HomeAssistantState | None,
) -> SolarForecastSummary | None:
    if state is None or is_missing_state(state.state):
        return None
    attrs = state.attributes
    source_estimate = parse_number(attrs.get("estimate"))
    if source_estimate is None:
        source_estimate = parse_number(state.state)
    source_estimate10 = parse_number(attrs.get("estimate10"))
    source_estimate90 = parse_number(attrs.get("estimate90"))
    if (
        source_estimate is None
        and source_estimate10 is None
        and source_estimate90 is None
    ):
        return None

    source_unit = parse_text(attrs.get("unit_of_measurement"))
    normalized_unit = source_unit.casefold() if source_unit else None
    if normalized_unit == "wh":
        factor = 0.001
        conversion_status = "converted_from_wh"
    elif normalized_unit == "kwh":
        factor = 1.0
        conversion_status = "native_kwh"
    else:
        factor = None
        conversion_status = (
            "unit_missing" if source_unit is None else "unit_unsupported"
        )

    def to_kwh(value: float | None) -> float | None:
        return None if value is None or factor is None else value * factor

    intervals, interval_issues = parse_solar_intervals(attrs.get("detailedForecast"))
    return SolarForecastSummary(
        estimate_kwh=to_kwh(source_estimate),
        estimate10_kwh=to_kwh(source_estimate10),
        estimate90_kwh=to_kwh(source_estimate90),
        source_estimate=source_estimate,
        source_estimate10=source_estimate10,
        source_estimate90=source_estimate90,
        source_unit=source_unit,
        conversion_status=conversion_status,
        intervals=intervals,
        interval_issues=interval_issues,
    )


def parse_solar_intervals(
    detail: Any,
) -> tuple[list[SolarForecastInterval], list[str]]:
    """BJReplay detailedForecast has half-hour average kW, independent of total unit.

    Missing or malformed optional detail cannot affect core telemetry health.
    Do not use hourly/site-specific arrays, duplicate them, or replace missing P10.
    """
    if detail is None:
        return [], []
    if not isinstance(detail, list) or len(detail) > 96:
        return [], ["solar_interval_payload_invalid"]
    intervals = []
    issues = []
    previous_end = None
    for item in detail:
        if not isinstance(item, dict):
            issues.append("solar_interval_invalid")
            continue
        try:
            start = datetime.fromisoformat(str(item.get("period_start")))
            if start.tzinfo is None or start.utcoffset() is None:
                raise ValueError("timezone required")
            start = start.astimezone(UTC)
        except (TypeError, ValueError):
            issues.append("solar_interval_timestamp_invalid")
            continue
        end = start + timedelta(minutes=30)
        if previous_end is not None and start != previous_end:
            issues.append("solar_interval_gap_or_overlap")
        previous_end = end
        values = [
            parse_number(item.get(key))
            for key in ("pv_estimate", "pv_estimate10", "pv_estimate90")
        ]
        if any(value is not None and value < 0 for value in values):
            issues.append("solar_interval_power_invalid")
            values = [
                None if value is not None and value < 0 else value for value in values
            ]
        p50, p10, p90 = values
        if p10 is None:
            issues.append("solar_interval_p10_missing")
        if (p10 is not None and p50 is not None and p10 > p50) or (
            p50 is not None and p90 is not None and p50 > p90
        ):
            issues.append("solar_interval_uncertainty_invalid")
        intervals.append(
            SolarForecastInterval(
                period_start_utc=start,
                period_end_utc=end,
                estimate_kw=p50,
                estimate10_kw=p10,
                estimate90_kw=p90,
            )
        )
    return intervals, sorted(set(issues))
