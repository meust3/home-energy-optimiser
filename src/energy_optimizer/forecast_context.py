"""Optional cached context collection. No feature use, inference or network calls."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from energy_optimizer.models import HomeAssistantState
from energy_optimizer.timestamps import aware_datetime, json_safe

PARSER_VERSION = "forecast-context-v1"
MAX_MAPPING_BYTES = 16384
MAX_SNAPSHOT_BYTES = 65536
MAX_STORED_SNAPSHOT_BYTES = 262144
QUANTITIES = Literal[
    "temperature",
    "humidity",
    "setpoint",
    "mode",
    "activity",
    "power",
    "energy",
    "condition",
    "dew_point",
    "cloud_coverage",
    "precipitation",
    "precipitation_probability",
]
EVIDENCE = Literal[
    "sensor_measured",
    "commanded_assumed",
    "integration_reported",
    "electrically_measured",
    "remote_modelled",
]


class ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextSource(ContextModel):
    source_id: str = Field(min_length=1, max_length=64)
    entity_id: str = Field(pattern=r"^(sensor|climate|weather)\.[a-z0-9_]+$")
    zone: str = Field(min_length=1, max_length=64)
    scope: Literal["indoor", "remote_weather"]
    integration: str = Field(min_length=1, max_length=64)
    quantity: QUANTITIES
    attribute: (
        Literal[
            "current_temperature",
            "current_humidity",
            "temperature",
            "humidity",
            "hvac_action",
            "dew_point",
            "cloud_coverage",
        ]
        | None
    ) = None
    source_unit: str | None = Field(default=None, max_length=16)
    unit_attribute: Literal["temperature_unit", "unit_of_measurement"] = (
        "unit_of_measurement"
    )
    evidence: EVIDENCE
    measurement_time_attribute: Literal["measurement_time", "measured_at"] | None = None
    stale_after_seconds: int = Field(default=7200, ge=300, le=86400)
    duplicate_group: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def roles_are_explicit(self) -> Self:
        if any(
            x in self.entity_id for x in ("byd_", "vehicle_", "sealion", "electric_car")
        ):
            raise ValueError("vehicle context is excluded")
        if self.scope == "remote_weather" and self.evidence != "remote_modelled":
            raise ValueError("remote weather must be labelled modelled")
        if self.scope == "remote_weather" and not self.entity_id.startswith("weather."):
            raise ValueError(
                "modelled current conditions must come from a weather entity"
            )
        if self.scope == "indoor" and self.entity_id.startswith("weather."):
            raise ValueError("weather entities are not indoor measurements")
        if self.quantity in {"power", "energy"} and (
            self.evidence != "electrically_measured"
            or not self.entity_id.startswith("sensor.")
        ):
            raise ValueError("electrical evidence requires an explicitly mapped meter")
        if (
            self.quantity in {"mode", "setpoint"}
            and self.evidence != "commanded_assumed"
        ):
            raise ValueError("climate mode/setpoint are requested or assumed states")
        if self.quantity == "activity" and self.evidence != "integration_reported":
            raise ValueError("HVAC activity is integration-reported, not metering")
        if (
            self.scope == "indoor"
            and self.quantity in {"temperature", "humidity"}
            and self.evidence != "sensor_measured"
        ):
            raise ValueError("indoor ambient values require sensor evidence")
        if self.quantity in {
            "mode",
            "setpoint",
            "activity",
        } and not self.entity_id.startswith("climate."):
            raise ValueError("HVAC attributes require an explicit climate source")
        if self.quantity == "setpoint" and self.attribute != "temperature":
            raise ValueError(
                "requested setpoint must use the climate temperature attribute"
            )
        if self.quantity == "activity" and self.attribute != "hvac_action":
            raise ValueError(
                "reported activity must use the climate hvac_action attribute"
            )
        return self


class WeatherCacheSource(ContextModel):
    entity_id: str = Field(pattern=r"^sensor\.[a-z0-9_]+$")
    weather_entity_id: str = Field(pattern=r"^weather\.[a-z0-9_]+$")
    provider: str = Field(min_length=1, max_length=64)
    integration: str = Field(min_length=1, max_length=64)
    max_age_seconds: int = Field(default=10800, ge=3600, le=86400)


class ContextMapping(ContextModel):
    version: str = Field(min_length=1, max_length=64)
    effective_from_utc: datetime
    physical_outdoor_sensor: Literal["absent"] = "absent"
    sources: tuple[ContextSource, ...] = Field(default=(), max_length=32)
    weather_cache: WeatherCacheSource | None = None

    @model_validator(mode="after")
    def bounded_mapping(self) -> Self:
        aware_datetime(self.effective_from_utc)
        if len({s.zone for s in self.sources if s.scope == "indoor"}) > 6:
            raise ValueError("at most six indoor zones")
        keys = [(s.entity_id, s.attribute, s.quantity) for s in self.sources]
        if len(keys) != len(set(keys)) or len(
            {s.source_id for s in self.sources}
        ) != len(keys):
            raise ValueError(
                "duplicate source mapping; use duplicate_group for distinct devices"
            )
        return self

    @property
    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    @property
    def entity_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {s.entity_id for s in self.sources}
                | ({self.weather_cache.entity_id} if self.weather_cache else set())
            )
        )


class ContextReading(ContextModel):
    source: ContextSource
    raw_value: float | str | None
    source_unit: str | None
    value: float | str | None
    unit: str | None
    conversion: str | None
    availability: Literal["valid", "missing", "invalid"]
    reason: str | None
    measurement_time_utc: datetime | None
    ha_last_changed: datetime | None
    ha_last_updated: datetime | None
    ha_last_reported: datetime | None
    freshness: Literal["measurement_recent", "measurement_stale", "unknown"]
    freshness_reason: str
    ha_report_age_seconds: float | None


class WeatherSnapshot(ContextModel):
    source: WeatherCacheSource
    cache_success_utc: datetime
    provider_issue_utc: datetime | None
    provider_version: str | None
    model_version: str | None
    received_at_utc: datetime
    parser_version: str = PARSER_VERSION
    native_type: Literal["hourly"] = "hourly"
    points: tuple[dict[str, Any], ...]
    semantic_hash: str
    payload_hash: str
    diagnostics: dict[str, Any]


class ContextBatch(ContextModel):
    slot_utc: datetime
    received_at_utc: datetime
    mapping_version: str
    mapping_hash: str
    parser_version: str = PARSER_VERSION
    readings: tuple[ContextReading, ...] = ()
    weather_source: WeatherCacheSource | None = None
    weather: WeatherSnapshot | None = None
    diagnostic: dict[str, Any]


def content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def parse_mapping(value: str) -> ContextMapping:
    if len(value.encode()) > MAX_MAPPING_BYTES:
        raise ValueError("context mapping exceeds 16 KiB")
    return ContextMapping.model_validate_json(value)


def timestamp(value: Any) -> datetime | None:
    try:
        return aware_datetime(value).astimezone(UTC) if value is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def convert_value(
    raw: Any, quantity: str, unit: str | None
) -> tuple[float | str | None, str | None, str | None, str | None]:
    if raw is None or str(raw).casefold() in {"unknown", "unavailable", "none", ""}:
        return None, None, None, "value_unavailable"
    if quantity in {"mode", "activity", "condition"}:
        if not isinstance(raw, str) or len(raw) > 64:
            return None, None, None, "invalid_text"
        return raw, None, "identity", None
    try:
        number = float(raw) if not isinstance(raw, bool) else float("nan")
    except (ValueError, TypeError, OverflowError):
        return None, None, None, "invalid_number"
    if not isfinite(number):
        return None, None, None, "nonfinite_number"
    conversions = {
        "temperature": {"°C": (1, 0, "°C"), "°F": (5 / 9, -32 * 5 / 9, "°C")},
        "dew_point": {"°C": (1, 0, "°C"), "°F": (5 / 9, -32 * 5 / 9, "°C")},
        "setpoint": {"°C": (1, 0, "°C"), "°F": (5 / 9, -32 * 5 / 9, "°C")},
        "humidity": {"%": (1, 0, "%")},
        "cloud_coverage": {"%": (1, 0, "%")},
        "precipitation_probability": {"%": (1, 0, "%")},
        "power": {"W": (1, 0, "W"), "kW": (1000, 0, "W")},
        "energy": {"Wh": (0.001, 0, "kWh"), "kWh": (1, 0, "kWh")},
        "precipitation": {"mm": (1, 0, "mm"), "in": (25.4, 0, "mm")},
    }
    conversion = conversions[quantity].get(unit)
    if conversion is None:
        return None, None, None, "unit_unknown_or_unsupported"
    factor, offset, canonical = conversion
    value = number * factor + offset
    low, high = (
        (-60, 70) if canonical == "°C" else ((0, 100) if canonical == "%" else (0, 1e7))
    )
    if not low <= value <= high:
        return None, canonical, None, "implausible_value"
    return value, canonical, f"value*{factor:g}+{offset:g}", None


def _reading(
    source: ContextSource, state: HomeAssistantState | None, receipt: datetime
) -> ContextReading:
    raw = (
        None
        if state is None
        else (
            state.attributes.get(source.attribute) if source.attribute else state.state
        )
    )
    source_available = (
        state is not None
        and state.state not in {"unknown", "unavailable"}
        and not state.attributes.get("restored", False)
    )
    reported_unit = state.attributes.get(source.unit_attribute) if state else None
    unit = reported_unit if isinstance(reported_unit, str) else source.source_unit
    if not isinstance(unit, str) or len(unit) > 16:
        unit = None
    value, canonical, conversion, reason = convert_value(
        raw if source_available else None, source.quantity, unit
    )
    if source.source_unit and reported_unit and reported_unit != source.source_unit:
        value, reason = None, "configured_and_reported_units_disagree"
    measurement = (
        timestamp(state.attributes.get(source.measurement_time_attribute))
        if state and source.measurement_time_attribute
        else None
    )
    reported = timestamp(state.last_reported) if state else None
    freshness = "unknown"
    freshness_reason = (
        "physical_measurement_time_not_provided; HA times are not measurement proof"
    )
    if measurement is not None:
        age = (receipt - measurement).total_seconds()
        if age < 0:
            value, reason = None, "measurement_time_in_future"
        else:
            freshness = (
                "measurement_stale"
                if age > source.stale_after_seconds
                else "measurement_recent"
            )
            freshness_reason = "explicit_source_measurement_time"
    safe_raw = (
        raw
        if isinstance(raw, str) and len(raw) <= 64
        else (
            raw
            if isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and isfinite(raw)
            else None
        )
    )
    return ContextReading(
        source=source,
        raw_value=safe_raw,
        source_unit=unit,
        value=value,
        unit=canonical,
        conversion=conversion,
        availability=(
            "valid"
            if reason is None
            else ("missing" if reason == "value_unavailable" else "invalid")
        ),
        reason=("missing_or_invalid_entity" if state is None else reason),
        measurement_time_utc=measurement,
        ha_last_changed=timestamp(state.last_changed) if state else None,
        ha_last_updated=timestamp(state.last_updated) if state else None,
        ha_last_reported=reported,
        freshness=freshness,
        freshness_reason=freshness_reason,
        ha_report_age_seconds=(
            (receipt - reported).total_seconds() if reported else None
        ),
    )


def parse_weather_cache(
    source: WeatherCacheSource, state: HomeAssistantState | None, receipt: datetime
) -> tuple[WeatherSnapshot | None, dict[str, Any]]:
    snapshot, diagnostic = _parse_weather_payload(source, state, receipt)
    availability = (
        "missing"
        if state is None
        else (
            "restored"
            if state.attributes.get("restored", False)
            else (
                "unavailable"
                if state.state in {"unknown", "unavailable"}
                else "available"
            )
        )
    )
    diagnostic = {
        **diagnostic,
        "cache_availability": availability,
        "cache_ha_last_changed": timestamp(state.last_changed) if state else None,
        "cache_ha_last_updated": timestamp(state.last_updated) if state else None,
        "cache_ha_last_reported": timestamp(state.last_reported) if state else None,
        "cache_last_attempt_utc": (
            timestamp(state.attributes.get("last_attempt_utc")) if state else None
        ),
        "cache_ha_times_are_not_provider_issuance": True,
    }
    if snapshot is not None:
        snapshot = snapshot.model_copy(update={"diagnostics": diagnostic})
        if len(snapshot.model_dump_json().encode()) > MAX_STORED_SNAPSHOT_BYTES:
            return None, {"status": "normalized_snapshot_size_bound_exceeded"}
    return snapshot, diagnostic


def _parse_weather_payload(
    source: WeatherCacheSource,
    state: HomeAssistantState | None,
    receipt: datetime,
) -> tuple[WeatherSnapshot | None, dict[str, Any]]:
    if (
        state is None
        or state.state in {"unknown", "unavailable"}
        or state.attributes.get("restored", False)
    ):
        return None, {"status": "pending_setup_or_unavailable"}
    attrs = state.attributes
    success = timestamp(attrs.get("cache_success_utc"))
    if (
        success is None
        or success > receipt
        or attrs.get("forecast_type") != "hourly"
        or attrs.get("provider") != source.provider
        or attrs.get("integration") != source.integration
        or attrs.get("weather_entity_id") != source.weather_entity_id
    ):
        return None, {"status": "invalid_cache_identity_or_time"}
    forecast = attrs.get("forecast")
    units = attrs.get("units")
    if not isinstance(forecast, list) or not forecast or not isinstance(units, dict):
        return None, {"status": "empty_or_malformed_cache"}
    if len(forecast) > 96:
        return None, {
            "status": "payload_entry_bound_exceeded",
            "received_entries": len(forecast),
        }
    allowed = {
        "datetime",
        "temperature",
        "humidity",
        "dew_point",
        "condition",
        "precipitation",
        "cloud_coverage",
        "precipitation_probability",
    }
    filtered = [
        {k: v for k, v in row.items() if k in allowed}
        for row in forecast
        if isinstance(row, dict)
    ]
    # Only small scalar quantities cross the persistence boundary. Reject nested
    # values instead of storing arbitrary attributes under an allowed field name.
    if any(
        not isinstance(v, (str, int, float, type(None)))
        or isinstance(v, bool)
        or (isinstance(v, str) and len(v) > 64)
        for row in filtered
        for v in row.values()
    ):
        return None, {"status": "invalid_forecast_scalar"}
    if any(
        units.get(k) is not None
        and (not isinstance(units[k], str) or len(units[k]) > 16)
        for k in allowed - {"datetime"}
    ):
        return None, {"status": "invalid_forecast_unit"}
    try:
        payload = json.dumps(filtered, allow_nan=False)
    except (ValueError, TypeError):
        return None, {"status": "nonfinite_or_malformed_payload"}
    if len(payload.encode()) > MAX_SNAPSHOT_BYTES or len(filtered) != len(forecast):
        return None, {"status": "payload_size_or_shape_invalid"}
    points = []
    seen = set()
    outside = 0
    invalid_values = 0
    for row in filtered:
        target = timestamp(row.get("datetime"))
        if target is None or target in seen:
            return None, {"status": "invalid_or_duplicate_target_time"}
        seen.add(target)
        if not success <= target < success + timedelta(hours=48):
            outside += 1
            continue
        values = {}
        for field in allowed - {"datetime"}:
            if field in row:
                quantity = "cloud_coverage" if field == "cloud_coverage" else field
                value, unit, conversion, reason = convert_value(
                    row[field], quantity, units.get(field)
                )
                invalid_values += int(reason is not None)
                semantics = (
                    "accumulation_period_unspecified"
                    if field == "precipitation"
                    else (
                        "probability_period_unspecified"
                        if field == "precipitation_probability"
                        else "point_at_native_target"
                    )
                )
                values[field] = {
                    "raw_value": row[field],
                    "source_unit": units.get(field),
                    "value": value,
                    "unit": unit,
                    "conversion": conversion,
                    "reason": reason,
                    "semantics": semantics,
                    "period_end_utc": None,
                }
        points.append({"target_utc": target, "values": values})
    if not points:
        return None, {"status": "no_native_points_in_window"}
    points.sort(key=lambda p: p["target_utc"])
    issue = timestamp(attrs.get("provider_issue_utc"))
    if attrs.get("provider_issue_utc") is not None and (
        issue is None or issue > success
    ):
        return None, {"status": "invalid_provider_issue_time"}
    version = attrs.get("provider_version")
    model = attrs.get("model_version")
    if any(
        v is not None and (not isinstance(v, str) or len(v) > 64)
        for v in (version, model)
    ):
        return None, {"status": "invalid_version_metadata"}
    diagnostic = {
        "status": "received",
        "cache_age_seconds": (receipt - success).total_seconds(),
        "cache_stale": (receipt - success).total_seconds() > source.max_age_seconds,
        "upstream_freshness": "unknown",
        "issuance_time_known": issue is not None,
        "cache_retrieval_is_not_issuance": True,
        "received_entries": len(forecast),
        "retained_entries": len(points),
        "outside_window_entries": outside,
        "truncated": bool(outside or attrs.get("truncated")),
        "invalid_values": invalid_values,
        "cache_received_entries": (
            attrs.get("received_entries")
            if isinstance(attrs.get("received_entries"), int)
            and not isinstance(attrs.get("received_entries"), bool)
            else None
        ),
        "first_target_utc": points[0]["target_utc"],
        "last_target_utc": points[-1]["target_utc"],
        "native_spacing_seconds": sorted(
            {
                (b["target_utc"] - a["target_utc"]).total_seconds()
                for a, b in zip(points, points[1:], strict=False)
            }
        ),
    }
    snapshot = WeatherSnapshot(
        source=source,
        cache_success_utc=success,
        provider_issue_utc=issue,
        provider_version=version,
        model_version=model,
        received_at_utc=receipt,
        points=tuple(points),
        semantic_hash=content_hash(
            {
                "source": source.model_dump(),
                "points": points,
                "issue": issue,
                "version": version,
                "model": model,
            }
        ),
        payload_hash=content_hash(filtered),
        diagnostics=diagnostic,
    )
    if len(snapshot.model_dump_json().encode()) > MAX_STORED_SNAPSHOT_BYTES:
        return None, {"status": "normalized_snapshot_size_bound_exceeded"}
    return snapshot, diagnostic


def collect_context(
    states: dict[str, HomeAssistantState],
    mapping: ContextMapping,
    *,
    slot: datetime,
    receipt: datetime,
) -> ContextBatch:
    receipt = aware_datetime(receipt).astimezone(UTC)
    if receipt < mapping.effective_from_utc:
        return ContextBatch(
            slot_utc=slot,
            received_at_utc=receipt,
            mapping_version=mapping.version,
            mapping_hash=mapping.fingerprint,
            diagnostic={"status": "mapping_not_effective"},
        )
    readings = tuple(
        _reading(source, states.get(source.entity_id), receipt)
        for source in mapping.sources
    )
    weather, weather_diagnostic = (
        parse_weather_cache(
            mapping.weather_cache, states.get(mapping.weather_cache.entity_id), receipt
        )
        if mapping.weather_cache
        else (None, {"status": "pending_setup"})
    )
    counts = {
        status: sum(r.availability == status for r in readings)
        for status in ("valid", "invalid", "missing")
    }
    return ContextBatch(
        slot_utc=slot,
        received_at_utc=receipt,
        mapping_version=mapping.version,
        mapping_hash=mapping.fingerprint,
        readings=readings,
        weather_source=mapping.weather_cache,
        weather=weather,
        diagnostic={
            "status": "operating",
            "mapped_sources": len(readings),
            "source_types": sorted({s.evidence for s in mapping.sources}),
            **counts,
            "known_measurement_freshness": sum(
                r.freshness != "unknown" for r in readings
            ),
            "unknown_measurement_freshness": sum(
                r.freshness == "unknown" for r in readings
            ),
            "physical_outdoor_sensor": mapping.physical_outdoor_sensor,
            "weather": weather_diagnostic,
        },
    )
