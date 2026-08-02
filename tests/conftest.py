from datetime import UTC, datetime, timedelta

import pytest

from energy_optimizer import entity_ids as ids
from energy_optimizer.models import CollectorConfig, HomeAssistantState


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 1, 2, 7, 41, tzinfo=UTC)


@pytest.fixture
def config(tmp_path) -> CollectorConfig:
    return CollectorConfig(
        ha_url="http://homeassistant.test:8123",
        ha_token="test-secret-token",
        database_path=tmp_path / "history.db",
    )


def make_state(
    entity_id: str, value: str, now: datetime, attributes=None
) -> HomeAssistantState:
    return HomeAssistantState(
        entity_id=entity_id,
        state=value,
        attributes=attributes or {},
        last_changed=now - timedelta(seconds=10),
        last_updated=now - timedelta(seconds=5),
    )


@pytest.fixture
def healthy_states(now) -> dict[str, HomeAssistantState]:
    values = {
        ids.AMBER_IMPORT_PRICE: "0.21",
        ids.AMBER_IMPORT_FORECAST: "0.22",
        ids.AMBER_EXPORT_PRICE: "0.08",
        ids.AMBER_EXPORT_FORECAST: "0.09",
        ids.AMBER_PRICE_SPIKE: "off",
        ids.SOLCAST_REMAINING_TODAY: "12.5",
        ids.SOLCAST_TOMORROW: "28.0",
        ids.SOLCAST_NEXT_HOUR: "1800",
        ids.SOLCAST_THIS_HOUR: "1200",
        ids.SOLCAST_TODAY: "32.0",
        ids.GOODWE_BATTERY_SOC: "50",
        ids.GOODWE_BATTERY_POWER: "-1200",
        ids.GOODWE_BATTERY_MODE: "Normal",
        ids.GOODWE_PV_POWER: "4200",
        ids.GOODWE_HOUSE_CONSUMPTION: "1800",
        ids.GOODWE_GRID_POWER: "-900",
        ids.GOODWE_WORK_MODE: "General mode",
    }
    states = {key: make_state(key, value, now) for key, value in values.items()}
    forecast = [
        {
            "duration": 30,
            "start_time": "2026-08-01T02:00:00Z",
            "end_time": "2026-08-01T02:30:00Z",
            "per_kwh": 0.22,
            "spot_per_kwh": 0.18,
            "renewables": 55,
            "descriptor": "neutral",
            "spike_status": "none",
        }
    ]
    states[ids.AMBER_IMPORT_FORECAST].attributes["forecasts"] = forecast
    states[ids.AMBER_EXPORT_FORECAST].attributes["forecasts"] = forecast
    for entity_id in ids.SOLCAST_REQUIRED_ENTITIES:
        states[entity_id].attributes.update(
            {
                "estimate": float(states[entity_id].state),
                "estimate10": 1.0,
                "estimate90": 3.0,
            }
        )
        states[entity_id].attributes["unit_of_measurement"] = "kWh"
    for entity_id in (ids.SOLCAST_NEXT_HOUR, ids.SOLCAST_THIS_HOUR):
        states[entity_id].attributes["unit_of_measurement"] = "Wh"
    return states
