"""Orchestration for producing read-only energy observations."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from energy_optimizer import entity_ids as ids
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
    health = evaluate_data_health(
        states,
        config,
        now=now_utc,
    )

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

    return EnergyObservation(
        slot_utc=align_to_five_minute_slot(now_utc),
        observed_at_utc=now_utc,
        observed_at_local=now_utc.astimezone(ZoneInfo(config.timezone)),
        battery_soc_percent=soc,
        battery_energy_estimate_kwh=battery_energy_estimate_kwh(
            soc, config.usable_battery_capacity_kwh
        ),
        battery_power_w=number(ids.GOODWE_BATTERY_POWER),
        battery_mode=text(ids.GOODWE_BATTERY_MODE),
        pv_power_w=number(ids.GOODWE_PV_POWER),
        house_consumption_w=number(ids.GOODWE_HOUSE_CONSUMPTION),
        grid_power_w=number(ids.GOODWE_GRID_POWER),
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
        solcast_remaining_today=parse_solar_summary(
            _state(states, ids.SOLCAST_REMAINING_TODAY)
        ),
        solcast_tomorrow=parse_solar_summary(_state(states, ids.SOLCAST_TOMORROW)),
        solcast_next_hour=parse_solar_summary(_state(states, ids.SOLCAST_NEXT_HOUR)),
        solcast_this_hour=parse_solar_summary(_state(states, ids.SOLCAST_THIS_HOUR)),
        solcast_today=parse_solar_summary(_state(states, ids.SOLCAST_TODAY)),
        solcast_power_now_w=number(ids.SOLCAST_POWER_NOW),
        temperature_c=temperature,
        weather_condition=weather_condition,
        data_health=health,
    )


class Collector:
    def __init__(self, client: HomeAssistantClient, config: CollectorConfig) -> None:
        self._client = client
        self._config = config

    def collect(self, *, observed_at: datetime | None = None) -> EnergyObservation:
        weather_entities = tuple(
            entity_id
            for entity_id in (
                self._config.weather_temperature_entity_id,
                self._config.weather_condition_entity_id,
            )
            if entity_id
        )
        states = self._client.get_states(ids.ALL_ENTITY_IDS + weather_entities)
        return build_observation(states, self._config, observed_at=observed_at)
