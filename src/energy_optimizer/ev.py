"""Conservative EV baseline handling and optional session inference."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from energy_optimizer.models import (
    CollectorConfig,
    EVTelemetryHealth,
    EVVehicleTelemetry,
    HealthIssue,
    HomeAssistantState,
)
from energy_optimizer.parsing import (
    is_missing_state,
    parse_bool,
    parse_datetime,
    parse_number,
)


def calculate_baseline_load(
    house_consumption_w: float | None,
    *,
    ev_charging_active: bool | None,
    ev_power_w: float | None,
    inferred_session: bool = False,
    inference_confidence: str = "unconfirmed",
    active_without_power_reason: str = "ev_active_power_unknown",
) -> tuple[float | None, bool, str | None]:
    if house_consumption_w is None:
        return None, False, "house_consumption_missing"
    if ev_power_w is not None:
        return max(house_consumption_w - max(ev_power_w, 0.0), 0.0), True, None
    if ev_charging_active is False:
        return house_consumption_w, True, None
    if inferred_session:
        return (
            house_consumption_w,
            False,
            f"inferred_ev_session_{inference_confidence}_power_unknown",
        )
    if ev_charging_active is True:
        return house_consumption_w, False, active_without_power_reason
    return house_consumption_w, True, None


def parse_vehicle_telemetry(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    *,
    now: datetime,
) -> tuple[EVVehicleTelemetry, EVTelemetryHealth]:
    """Interpret configured vehicle-cloud states without retaining attributes."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("vehicle telemetry evaluation requires an aware timestamp")
    if not config.ev_vehicle_enabled:
        telemetry = EVVehicleTelemetry()
        return telemetry, EVTelemetryHealth()

    issues: list[HealthIssue] = []
    configured_ids = {
        "charging": config.ev_vehicle_charging_entity_id,
        "plugged": config.ev_vehicle_plugged_entity_id,
        "online": config.ev_vehicle_online_entity_id,
        "soc": config.ev_vehicle_soc_entity_id,
        "battery power": config.ev_vehicle_battery_power_entity_id,
        "telemetry timestamp": config.ev_vehicle_telemetry_updated_entity_id,
        "location": config.ev_vehicle_location_entity_id,
    }
    if not any(configured_ids.values()):
        issues.append(_ev_issue("ev_entity_missing", "No EV entities are configured"))
    for label, entity_id in configured_ids.items():
        if entity_id and entity_id not in states:
            issues.append(
                _ev_issue(
                    "ev_entity_missing",
                    f"Configured EV {label} entity is absent",
                    entity_id,
                )
            )

    def state_for(entity_id: str | None) -> HomeAssistantState | None:
        return states.get(entity_id) if entity_id else None

    def bool_state(entity_id: str | None) -> bool | None:
        state = state_for(entity_id)
        if state is None:
            return None
        parsed = parse_bool(state.state)
        if parsed is None:
            issues.append(
                _ev_issue(
                    "ev_state_unavailable",
                    "Configured EV binary state is unavailable or invalid",
                    entity_id,
                )
            )
        return parsed

    charging_raw = bool_state(config.ev_vehicle_charging_entity_id)
    plugged_raw = bool_state(config.ev_vehicle_plugged_entity_id)
    online = bool_state(config.ev_vehicle_online_entity_id)

    soc_state = state_for(config.ev_vehicle_soc_entity_id)
    soc = parse_number(soc_state.state) if soc_state else None
    if soc_state and is_missing_state(soc_state.state):
        issues.append(
            _ev_issue(
                "ev_state_unavailable",
                "Vehicle SOC is unavailable",
                config.ev_vehicle_soc_entity_id,
            )
        )
    elif soc_state and (soc is None or not 0 <= soc <= 100):
        issues.append(
            _ev_issue(
                "ev_soc_invalid",
                "Vehicle SOC is malformed or outside 0-100%",
                config.ev_vehicle_soc_entity_id,
            )
        )
        soc = None

    power_state = state_for(config.ev_vehicle_battery_power_entity_id)
    raw_power = parse_number(power_state.state) if power_state else None
    if power_state and is_missing_state(power_state.state):
        issues.append(
            _ev_issue(
                "ev_state_unavailable",
                "Raw vehicle battery power is unavailable",
                config.ev_vehicle_battery_power_entity_id,
            )
        )
    elif power_state and raw_power is None:
        issues.append(
            _ev_issue(
                "ev_power_invalid",
                "Raw vehicle battery power is malformed",
                config.ev_vehicle_battery_power_entity_id,
            )
        )

    updated_state = state_for(config.ev_vehicle_telemetry_updated_entity_id)
    updated = parse_datetime(updated_state.state) if updated_state else None
    if updated_state and updated is None:
        issues.append(
            _ev_issue(
                "ev_state_unavailable",
                "Vehicle telemetry timestamp is unavailable or invalid",
                config.ev_vehicle_telemetry_updated_entity_id,
            )
        )
    current = now.astimezone(UTC)
    age_seconds = None
    fresh = False
    if updated is not None:
        signed_age = (current - updated.astimezone(UTC)).total_seconds()
        if signed_age < -60:
            issues.append(
                _ev_issue(
                    "ev_status_inconsistent",
                    "Vehicle telemetry timestamp is in the future",
                    config.ev_vehicle_telemetry_updated_entity_id,
                )
            )
        age_seconds = max(signed_age, 0.0)
        fresh = age_seconds <= config.ev_telemetry_stale_seconds
        if not fresh:
            issues.append(
                _ev_issue(
                    "ev_telemetry_stale",
                    "Vehicle telemetry exceeds the configured freshness threshold",
                    config.ev_vehicle_telemetry_updated_entity_id,
                )
            )

    location_state = state_for(config.ev_vehicle_location_entity_id)
    at_home = None
    if location_state:
        if is_missing_state(location_state.state):
            issues.append(
                _ev_issue(
                    "ev_location_unavailable",
                    "Vehicle home/away state is unavailable",
                    config.ev_vehicle_location_entity_id,
                )
            )
        else:
            at_home = (
                location_state.state.strip().casefold()
                == config.ev_home_state.strip().casefold()
            )

    authoritative = fresh and (
        online is True or config.ev_vehicle_online_entity_id is None
    )
    charging = (
        True
        if charging_raw is True and fresh
        else False if charging_raw is False and authoritative else None
    )
    plugged = (
        True
        if plugged_raw is True and fresh
        else False if plugged_raw is False and authoritative else None
    )
    if charging is True and plugged is False:
        issues.append(
            _ev_issue(
                "ev_status_inconsistent",
                "Vehicle reports charging while unplugged",
                config.ev_vehicle_charging_entity_id,
            )
        )
    if charging is True and online is False:
        issues.append(
            _ev_issue(
                "ev_status_inconsistent",
                "Vehicle reports charging while offline",
                config.ev_vehicle_online_entity_id,
            )
        )

    configured_states = [
        state_for(entity_id) for entity_id in configured_ids.values() if entity_id
    ]
    available = any(
        state is not None and not is_missing_state(state.state)
        for state in configured_states
    )
    if not available:
        status = "unknown"
    elif not fresh:
        status = "stale"
    elif online is False:
        status = "offline"
    elif charging is True:
        status = "charging"
    elif plugged is True and charging is False:
        status = "plugged_idle"
    elif at_home is True and plugged is False:
        status = "home_unplugged"
    elif at_home is False:
        status = "away"
    else:
        status = "unknown"

    confidence = (
        "direct_fresh" if fresh else "direct_stale" if available else "unavailable"
    )
    telemetry = EVVehicleTelemetry(
        vehicle_soc_percent=soc,
        vehicle_battery_power_w_raw=raw_power,
        charging_active=charging,
        plugged_in=plugged,
        vehicle_online=online,
        at_home=at_home,
        telemetry_updated_at_utc=updated.astimezone(UTC) if updated else None,
        telemetry_age_seconds=age_seconds,
        telemetry_fresh=fresh,
        source="byd_vehicle_cloud",
        confidence=confidence,
        status=status,
        issues=issues,
    )
    health = EVTelemetryHealth(
        configured=True,
        available=available,
        fresh=fresh,
        online=online,
        status=status,
        issues=issues,
    )
    return telemetry, health


def _ev_issue(code: str, message: str, entity_id: str | None = None) -> HealthIssue:
    return HealthIssue(
        code=code,
        message=message,
        severity="warning",
        entity_id=entity_id,
        deduction=5,
    )


def infer_ev_sessions(
    rows: Sequence[dict[str, Any]],
    *,
    enabled: bool,
    plausible_min_w: float,
    plausible_max_w: float,
    minimum_samples: int,
) -> list[dict[str, Any]]:
    """Identify low-variability sustained candidates; never changes observations."""
    if not enabled or len(rows) < minimum_samples:
        return []
    sessions: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []
    for row in rows:
        power = row.get("house_consumption_w")
        if (
            isinstance(power, (int, float))
            and plausible_min_w <= power <= plausible_max_w
        ):
            run.append(row)
        else:
            if len(run) >= minimum_samples:
                sessions.append(_candidate(run))
            run = []
    if len(run) >= minimum_samples:
        sessions.append(_candidate(run))
    return [session for session in sessions if session["confidence"] != "low"]


def _candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["house_consumption_w"]) for row in rows]
    mean = sum(values) / len(values)
    spread = max(values) - min(values)
    variability = spread / max(mean, 1.0)
    confidence = (
        "high" if variability <= 0.05 else "medium" if variability <= 0.1 else "low"
    )
    return {
        "start_slot_utc": rows[0].get("slot_utc"),
        "end_slot_utc": rows[-1].get("slot_utc"),
        "sample_count": len(rows),
        "average_house_consumption_w": round(mean, 2),
        "variability_ratio": round(variability, 4),
        "confidence": confidence,
        "evidence": "sustained plausible-band load with low variability",
    }
