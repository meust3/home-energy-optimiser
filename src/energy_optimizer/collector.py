"""Orchestration for producing read-only energy observations."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from energy_optimizer import entity_ids as ids
from energy_optimizer.energy_flow import derive_energy_flow, derive_event_labels
from energy_optimizer.ev import calculate_baseline_load, parse_vehicle_telemetry
from energy_optimizer.health import evaluate_data_health
from energy_optimizer.home_assistant import HomeAssistantClient
from energy_optimizer.models import (
    CollectorConfig,
    EnergyObservation,
    HomeAssistantState,
)
from energy_optimizer.parsing import (
    parse_amber_intervals,
    parse_bool,
    parse_number,
    parse_solar_summary,
    parse_text,
)


def align_to_five_minute_slot(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("slot alignment requires a timezone-aware datetime")
    utc = value.astimezone(UTC)
    return utc.replace(minute=(utc.minute // 5) * 5, second=0, microsecond=0)


def battery_energy_estimate_kwh(
    soc_percent: float | None, capacity_kwh: float
) -> float | None:
    return None if soc_percent is None else capacity_kwh * soc_percent / 100


def _state(
    states: dict[str, HomeAssistantState], entity_id: str
) -> HomeAssistantState | None:
    return states.get(entity_id)


def build_observation(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    *,
    observed_at: datetime | None = None,
) -> EnergyObservation:
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    now_utc = now.astimezone(UTC)
    soc_state = _state(states, ids.GOODWE_BATTERY_SOC)
    soc = parse_number(soc_state.state) if soc_state else None

    def number(entity_id: str) -> float | None:
        item = _state(states, entity_id)
        return parse_number(item.state) if item else None

    def text(entity_id: str) -> str | None:
        item = _state(states, entity_id)
        return parse_text(item.state) if item else None

    temperature = (
        number(config.weather_temperature_entity_id)
        if config.weather_temperature_entity_id
        else None
    )
    weather_condition = (
        text(config.weather_condition_entity_id)
        if config.weather_condition_entity_id
        else None
    )
    battery_power = number(ids.GOODWE_BATTERY_POWER)
    pv_power = number(ids.GOODWE_PV_POWER)
    house_consumption = number(ids.GOODWE_HOUSE_CONSUMPTION)
    grid_power = number(ids.GOODWE_GRID_POWER)
    legacy_ev_active = (
        parse_bool(states[config.ev_charging_active_entity_id].state)
        if config.ev_charging_active_entity_id in states
        else None
    )
    vehicle, ev_health = parse_vehicle_telemetry(states, config, now=now_utc)
    ev_active = (
        vehicle.charging_active if config.ev_vehicle_enabled else legacy_ev_active
    )
    ev_power = (
        number(config.ev_charging_power_entity_id)
        if config.ev_charging_power_entity_id
        else None
    )
    ev_energy_required = (
        number(config.ev_energy_required_entity_id)
        if config.ev_energy_required_entity_id
        else None
    )
    ev_ready_by = _parse_local_datetime(
        text(config.ev_ready_by_entity_id) if config.ev_ready_by_entity_id else None,
        config.timezone,
    )
    if ev_power is not None:
        ev_source = "charger"
        ev_confidence = "high"
    elif config.ev_vehicle_enabled:
        ev_source = "byd_vehicle_cloud"
        ev_confidence = vehicle.confidence
    elif any(
        (
            config.ev_charging_active_entity_id,
            config.ev_energy_required_entity_id,
            config.ev_ready_by_entity_id,
        )
    ):
        ev_source = "home_assistant_helper"
        ev_confidence = "high" if ev_active is not None else "low"
    else:
        ev_source = "none"
        ev_confidence = "unconfirmed"
    baseline, baseline_eligible, exclusion_reason = calculate_baseline_load(
        house_consumption,
        ev_charging_active=ev_active,
        ev_power_w=ev_power,
        active_without_power_reason=(
            "known_ev_session_without_ac_power"
            if config.ev_vehicle_enabled
            else "ev_active_power_unknown"
        ),
    )
    energy_flow = derive_energy_flow(
        pv_power_w=pv_power,
        house_consumption_w=house_consumption,
        grid_power_w=grid_power,
        battery_power_w=battery_power,
        config=config,
    )
    event_labels, event_confidence, event_evidence = derive_event_labels(
        energy_flow,
        ev_active=ev_active,
        ev_power_w=ev_power,
        tolerance_w=config.balance_tolerance_w,
    )
    if vehicle.telemetry_fresh:
        vehicle_labels = []
        if vehicle.charging_active is True:
            vehicle_labels.append("ev_charging_confirmed")
        elif vehicle.plugged_in is True and vehicle.charging_active is False:
            vehicle_labels.append("ev_plugged_idle")
        if vehicle.at_home is True:
            vehicle_labels.append("ev_at_home")
        if vehicle_labels:
            event_labels = [label for label in event_labels if label != "unknown"]
            event_labels.extend(
                label for label in vehicle_labels if label not in event_labels
            )
            event_confidence = "high"
            event_evidence["vehicle"] = {
                "source": vehicle.source,
                "status": vehicle.status,
                "fresh": vehicle.telemetry_fresh,
            }
    health = evaluate_data_health(
        states,
        config,
        now=now_utc,
        energy_flow=energy_flow,
        ev_active=ev_active,
        ev_power_w=ev_power,
        ev_health=ev_health,
    )

    return EnergyObservation(
        slot_utc=align_to_five_minute_slot(now_utc),
        observed_at_utc=now_utc,
        observed_at_local=now_utc.astimezone(ZoneInfo(config.timezone)),
        battery_soc_percent=soc,
        battery_energy_estimate_kwh=battery_energy_estimate_kwh(
            soc, config.usable_battery_capacity_kwh
        ),
        battery_power_w=battery_power,
        battery_mode=text(ids.GOODWE_BATTERY_MODE),
        pv_power_w=pv_power,
        house_consumption_w=house_consumption,
        grid_power_w=grid_power,
        work_mode=text(ids.GOODWE_WORK_MODE),
        amber_import_price_per_kwh=number(ids.AMBER_IMPORT_PRICE),
        amber_export_price_per_kwh=number(ids.AMBER_EXPORT_PRICE),
        amber_price_spike=(
            parse_bool(states[ids.AMBER_PRICE_SPIKE].state)
            if ids.AMBER_PRICE_SPIKE in states
            else None
        ),
        amber_import_forecast=parse_amber_intervals(
            _state(states, ids.AMBER_IMPORT_FORECAST)
        ),
        amber_export_forecast=parse_amber_intervals(
            _state(states, ids.AMBER_EXPORT_FORECAST)
        ),
        solcast_remaining_today_kwh=parse_solar_summary(
            _state(states, ids.SOLCAST_REMAINING_TODAY)
        ),
        solcast_tomorrow_kwh=parse_solar_summary(_state(states, ids.SOLCAST_TOMORROW)),
        solcast_next_hour_kwh=parse_solar_summary(
            _state(states, ids.SOLCAST_NEXT_HOUR)
        ),
        solcast_this_hour_kwh=parse_solar_summary(
            _state(states, ids.SOLCAST_THIS_HOUR)
        ),
        solcast_today_kwh=parse_solar_summary(_state(states, ids.SOLCAST_TODAY)),
        solcast_power_now_w=number(ids.SOLCAST_POWER_NOW),
        temperature_c=temperature,
        weather_condition=weather_condition,
        energy_flow=energy_flow,
        ev_charging_active=ev_active,
        ev_power_w=ev_power,
        ev_energy_required_kwh=ev_energy_required,
        ev_ready_by_local=ev_ready_by,
        ev_source=ev_source,
        ev_detection_confidence=ev_confidence,
        ev_vehicle=vehicle,
        baseline_house_consumption_w=baseline,
        baseline_training_eligible=baseline_eligible,
        baseline_exclusion_reason=exclusion_reason,
        event_labels=event_labels,
        event_label_confidence=event_confidence,
        event_label_evidence=event_evidence,
        data_health=health,
    )


class Collector:
    def __init__(self, client: HomeAssistantClient, config: CollectorConfig) -> None:
        self._client = client
        self._config = config

    def collect(self, *, observed_at: datetime | None = None) -> EnergyObservation:
        optional_entities = tuple(
            entity_id
            for entity_id in (
                self._config.weather_temperature_entity_id,
                self._config.weather_condition_entity_id,
                self._config.ev_charging_active_entity_id,
                self._config.ev_charging_power_entity_id,
                self._config.ev_plugged_in_entity_id,
                self._config.ev_energy_required_entity_id,
                self._config.ev_ready_by_entity_id,
                self._config.ev_vehicle_charging_entity_id,
                self._config.ev_vehicle_plugged_entity_id,
                self._config.ev_vehicle_online_entity_id,
                self._config.ev_vehicle_soc_entity_id,
                self._config.ev_vehicle_battery_power_entity_id,
                self._config.ev_vehicle_telemetry_updated_entity_id,
                self._config.ev_vehicle_location_entity_id,
            )
            if entity_id
        )
        states = self._client.get_states(ids.ALL_ENTITY_IDS + optional_entities)
        return build_observation(states, self._config, observed_at=observed_at)


def _parse_local_datetime(value: str | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed
