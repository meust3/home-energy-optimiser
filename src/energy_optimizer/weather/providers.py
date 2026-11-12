"""Offline adapters for actual provider JSON; no HTTP client or live entry point."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from energy_optimizer.weather.domain import (
    UNKNOWN,
    Capture,
    Point,
    Product,
    body_from_bytes,
    epoch,
    numeric,
)

# Includes the eight variables in the immutable earlier property pilot.
METEO_FIELDS = {
    "temperature_2m": ("temperature", "\u00b0C", "point", False, False),
    "cloud_cover": ("cloud_cover", "%", "point", True, False),
    "cloud_cover_low": ("cloud_cover_low", "%", "point", True, False),
    "cloud_cover_mid": ("cloud_cover_mid", "%", "point", True, False),
    "cloud_cover_high": ("cloud_cover_high", "%", "point", True, False),
    "shortwave_radiation": ("ghi", "W/mÂ²", "preceding_hour_mean", False, True),
    "direct_radiation": (
        "direct_horizontal",
        "W/mÂ²",
        "preceding_hour_mean",
        False,
        True,
    ),
    "diffuse_radiation": (
        "diffuse_horizontal",
        "W/mÂ²",
        "preceding_hour_mean",
        False,
        True,
    ),
    "relative_humidity_2m": ("relative_humidity", "%", "point", True, False),
    "precipitation": ("precipitation", "mm", "preceding_hour_sum", False, True),
    "pressure_msl": ("pressure_msl", "hPa", "point", False, True),
    "wind_speed_10m": ("wind_speed_10m", "m/s", "point", False, True),
    "wind_gusts_10m": ("wind_gusts_10m", "m/s", "preceding_hour_max", False, True),
}
PILOT_FIELDS = tuple(METEO_FIELDS)[:8]

ONECALL_PATHS = {
    "onecall4_current": (
        "current",
        "current_valid_time_not_station_observation",
        None,
        1,
    ),
    "onecall4_1min": ("timeline/1min", "forecast_valid_time", 60, 60),
    "onecall4_15min": ("timeline/15min", "forecast_valid_time", 900, 50),
    "onecall4_1h": ("timeline/1h", "forecast_valid_time", 3600, 20),
    "onecall4_1day": ("timeline/1day", "daily_period_bounds_unknown", 86400, 10),
}
ONECALL_FIELDS = {
    "temp": ("temperature", "\u00b0C", False, False),
    "feels_like": ("feels_like", "\u00b0C", False, False),
    "pressure": ("pressure", "hPa", False, True),
    "humidity": ("relative_humidity", "%", True, False),
    "dew_point": ("dew_point", "\u00b0C", False, False),
    "uvi": ("uvi", "index", False, True),
    "clouds": ("cloud_cover", "%", True, False),
    "visibility": ("visibility", "m", False, True),
    "wind_speed": ("wind_speed", "m/s", False, True),
    "wind_gust": ("wind_gust", "m/s", False, True),
    "wind_deg": ("wind_direction", "degree", False, True),
    "pop": ("precipitation_probability", "fraction", False, True),
}


def _times(values: Any) -> list[datetime]:
    if not isinstance(values, list) or not values or len(values) > 1000:
        raise ValueError("missing or oversized weather timeline")
    times = [epoch(t) for t in values]
    if any(a >= b for a, b in zip(times, times[1:], strict=False)):
        raise ValueError("weather timeline must be strictly increasing")
    return times


def _point(
    *,
    series: str,
    variable: str,
    time: datetime,
    value: Any,
    unit: str,
    source_path: str,
    step: int | None,
    semantics: str = "point",
    duration: int = 0,
    present: bool = True,
    percent: bool = False,
    positive: bool = False,
) -> Point:
    return Point(
        series=series,
        variable=variable,
        valid_at=time,
        interval_start=time - timedelta(seconds=duration),
        interval_end=time,
        semantics=semantics,
        value=numeric(value, percent=percent, positive=positive),
        unit=unit,
        source_path=source_path,
        output_step_seconds=step,
        presence=("MISSING" if not present else "NULL" if value is None else "VALUE"),
    )


def parse_meteo(
    raw: bytes,
    *,
    requested_at: datetime,
    received_at: datetime,
    site_ref: str,
    requested_fields: tuple[str, ...] = PILOT_FIELDS,
    requested_model: str = "best_match",
) -> Capture:
    body = body_from_bytes(raw)
    if body.get("error") or body.get("utc_offset_seconds") != 0:
        raise ValueError("Open-Meteo API error or non-UTC response")
    if not requested_fields or set(requested_fields) - METEO_FIELDS.keys():
        raise ValueError("unsupported Open-Meteo requested variable")
    hourly, units = body.get("hourly"), body.get("hourly_units")
    if not isinstance(hourly, dict) or not isinstance(units, dict):
        raise ValueError("missing Open-Meteo hourly data/units")
    if units.get("time") != "unixtime":
        raise ValueError("Open-Meteo time must be UTC Unix seconds")
    times = _times(hourly.get("time"))
    if any(
        (b - a).total_seconds() != 3600 for a, b in zip(times, times[1:], strict=False)
    ):
        raise ValueError("Open-Meteo hourly timeline has missing/irregular rows")
    points: list[Point] = []
    for field in requested_fields:
        variable, unit, semantics, percent, positive = METEO_FIELDS[field]
        present = field in hourly
        values = hourly.get(field, [None] * len(times))
        if not isinstance(values, list) or len(values) != len(times):
            raise ValueError("Open-Meteo hourly array length mismatch")
        if present and units.get(field) != unit:
            raise ValueError("Open-Meteo unit mismatch")
        for i, (time, value) in enumerate(zip(times, values, strict=True)):
            points.append(
                _point(
                    series="hourly",
                    variable=variable,
                    time=time,
                    value=value,
                    unit=unit,
                    source_path=f"hourly.{field}[{i}]",
                    step=3600,
                    semantics=semantics,
                    duration=3600 if semantics != "point" else 0,
                    present=present,
                    percent=percent,
                    positive=positive,
                )
            )
    return Capture(
        provider="open-meteo",
        product="open_meteo_hourly",
        site_ref=site_ref,
        requested_at=requested_at,
        received_at=received_at,
        raw=raw,
        points=tuple(points),
        requested_model=requested_model,
        attribution="Weather data by Open-Meteo.com",
        licence="CC BY 4.0",
    )


def parse_onecall4(
    raw: bytes,
    *,
    product: str,
    requested_at: datetime,
    received_at: datetime,
    site_ref: str,
    requested_units: str,
) -> Capture:
    if product not in ONECALL_PATHS or requested_units != "metric":
        raise ValueError("One Call 4.0 product and explicit metric units required")
    body = body_from_bytes(raw)
    if "cod" in body or "error" in body:
        raise ValueError("OpenWeather error envelope")
    records = body.get("data")
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("One Call 4.0 data[] required; legacy schema is unsupported")
    _, time_semantics, step, max_rows = ONECALL_PATHS[product]
    if len(records) > max_rows:
        raise ValueError("One Call 4.0 page exceeds documented row bound")
    times = _times([r.get("dt") for r in records])
    points: list[Point] = []
    issues: set[str] = set()
    for i, (time, record) in enumerate(zip(times, records, strict=True)):
        if product == "onecall4_1min":
            points.append(
                _point(
                    series="1min",
                    variable="precipitation_rate",
                    time=time,
                    value=record.get("precipitation"),
                    unit="mm/h",
                    step=step,
                    semantics="forecast_precipitation_rate",
                    positive=True,
                    present="precipitation" in record,
                    source_path=f"data[{i}].precipitation",
                )
            )
            continue
        series = product.removeprefix("onecall4_")
        for field, (variable, unit, percent, positive) in ONECALL_FIELDS.items():
            # Daily temperatures are nested in the official example. Unsupported
            # scalar daily shapes remain raw and are flagged, never mislabelled.
            value = record.get(field)
            if product == "onecall4_1day" and field in {"temp", "feels_like"}:
                if value is not None and not isinstance(value, dict):
                    issues.add(f"DAILY_{field.upper()}_SCHEMA_AMBIGUOUS_RAW_RETAINED")
                    value = {}
                for part in ("day", "min", "max", "night", "eve", "morn"):
                    nested = value or {}
                    points.append(
                        _point(
                            series=series,
                            variable=f"{variable}_{part}",
                            time=time,
                            value=nested.get(part),
                            unit=unit,
                            step=step,
                            semantics="daily_period_bounds_unknown",
                            present=part in nested,
                            source_path=f"data[{i}].{field}.{part}",
                        )
                    )
                continue
            normalized = _point(
                series=series,
                variable=variable,
                time=time,
                value=value,
                unit=unit,
                step=step,
                semantics=time_semantics,
                percent=percent,
                positive=positive,
                present=field in record,
                source_path=f"data[{i}].{field}",
            )
            if field == "pop" and normalized.value is not None and normalized.value > 1:
                raise ValueError("OpenWeather probability must be a fraction")
            if (
                field == "wind_deg"
                and normalized.value is not None
                and normalized.value > 360
            ):
                raise ValueError("invalid OpenWeather wind direction")
            points.append(normalized)
        if product == "onecall4_1day":
            for field in ("rain", "snow"):
                if field in record:
                    issues.add(
                        f"DAILY_{field.upper()}_UNITS_INTERVAL_UNKNOWN_RAW_RETAINED"
                    )
            # Do not invent calendar-day accumulation bounds from daily dt.
            for field in ("sunrise", "sunset", "moonrise", "moonset"):
                if record.get(field) is not None:
                    event_time = epoch(record[field])
                    points.append(
                        Point(
                            series=series,
                            variable=field,
                            valid_at=event_time,
                            interval_start=event_time,
                            interval_end=event_time,
                            semantics="astronomical_event_time",
                            value=event_time.isoformat(),
                            unit="UTC",
                            source_path=f"data[{i}].{field}",
                            output_step_seconds=step,
                        )
                    )
        if product != "onecall4_1day":
            for field in ("rain", "snow"):
                group = record.get(field)
                if group is not None and not isinstance(group, dict):
                    raise ValueError("invalid One Call precipitation shape")
                group = group or {}
                points.append(
                    _point(
                        series=series,
                        variable=f"{field}_1h_rate",
                        time=time,
                        value=group.get("1h"),
                        unit="mm/h",
                        step=step,
                        semantics="documented_1h_precipitation_rate",
                        duration=3600,
                        positive=True,
                        present="1h" in group,
                        source_path=f"data[{i}].{field}.1h",
                    )
                )
        weather = record.get("weather", [])
        if not isinstance(weather, list):
            raise ValueError("invalid One Call weather conditions")
        for j, condition in enumerate(weather):
            if not isinstance(condition, dict):
                raise ValueError("invalid One Call weather condition")
            points.append(
                _point(
                    series=series,
                    variable=f"openweather_condition_id_{j}",
                    time=time,
                    value=condition.get("id"),
                    unit="openweather_code",
                    step=step,
                    semantics=time_semantics,
                    present="id" in condition,
                    source_path=f"data[{i}].weather[{j}].id",
                )
            )
    return Capture(
        provider="openweather",
        product=product,
        site_ref=site_ref,
        requested_at=requested_at,
        received_at=received_at,
        raw=raw,
        points=tuple(points),
        requested_model=UNKNOWN,
        attribution="Weather data provided by OpenWeather",
        licence="ODbL 1.0",
        normalization_issues=tuple(sorted(issues)),
    )


def request_plan(product: Product) -> dict[str, Any]:
    """No coordinates/key; account setup and location are still live gates."""
    if product == "open_meteo_hourly":
        return {
            "endpoint": "https://api.open-meteo.com/v1/forecast",
            "public_parameters": {
                "timezone": "UTC",
                "timeformat": "unixtime",
                "models": "best_match",
                "hourly": ",".join(PILOT_FIELDS),
                "forecast_days": 2,
                "temperature_unit": "celsius",
                "wind_speed_unit": "ms",
                "precipitation_unit": "mm",
            },
            "private_parameters_required": ["latitude", "longitude"],
            "live_enabled": False,
        }
    if product not in ONECALL_PATHS:
        raise ValueError("unsupported weather product")
    return {
        "endpoint": f"https://api.openweathermap.org/data/4.0/onecall/{ONECALL_PATHS[product][0]}",
        "public_parameters": {"units": "metric", "lang": "en"},
        "private_parameters_required": ["lat", "lon", "appid"],
        "provider_hard_cap_required": 1000,
        "local_rolling_24h_cap": 900,
        "live_enabled": False,
        "pagination": "separate bounded requests; never follow next/prev URLs",
    }
