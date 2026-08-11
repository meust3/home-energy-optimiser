from datetime import timedelta
from pathlib import Path

import pytest

from energy_optimizer.collector import Collector, build_observation
from energy_optimizer.config import ConfigurationError, load_config
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.repository import DatabaseRepository, observation_values
from energy_optimizer.home_assistant_app import HomeAssistantAppOptions, app_environment

EV_IDS = {
    "charging": "binary_sensor.test_vehicle_charging",
    "plugged": "binary_sensor.test_vehicle_plugged",
    "online": "binary_sensor.test_vehicle_online",
    "soc": "sensor.test_vehicle_soc",
    "power": "sensor.test_vehicle_battery_power",
    "updated": "sensor.test_vehicle_updated",
    "location": "device_tracker.test_vehicle_location",
}


def _configure(config):
    config.ev_vehicle_enabled = True
    config.ev_vehicle_charging_entity_id = EV_IDS["charging"]
    config.ev_vehicle_plugged_entity_id = EV_IDS["plugged"]
    config.ev_vehicle_online_entity_id = EV_IDS["online"]
    config.ev_vehicle_soc_entity_id = EV_IDS["soc"]
    config.ev_vehicle_battery_power_entity_id = EV_IDS["power"]
    config.ev_vehicle_telemetry_updated_entity_id = EV_IDS["updated"]
    config.ev_vehicle_location_entity_id = EV_IDS["location"]
    return config


def _vehicle_states(healthy_states, now, **updates):
    template = next(iter(healthy_states.values()))
    values = {
        "charging": "off",
        "plugged": "on",
        "online": "on",
        "soc": "64",
        "power": "-18.5",
        "updated": now.isoformat(),
        "location": "home",
    }
    values.update(updates)
    for role, value in values.items():
        healthy_states[EV_IDS[role]] = template.model_copy(
            deep=True,
            update={"entity_id": EV_IDS[role], "state": value, "attributes": {}},
        )
    return healthy_states


def test_vehicle_disabled_leaves_existing_collection_unchanged(
    healthy_states, config, now
):
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.ev_vehicle.source == "none"
    assert not observation.data_health.ev.configured
    assert observation.ev_charging_active is None
    assert observation.baseline_training_eligible


def test_fresh_confirmed_charging_excludes_without_inventing_ac_power(
    healthy_states, config, now
):
    _configure(config)
    states = _vehicle_states(healthy_states, now, charging="on", plugged="on")
    observation = build_observation(states, config, observed_at=now)
    assert observation.ev_charging_active is True
    assert observation.ev_power_w is None
    assert observation.ev_vehicle.vehicle_battery_power_w_raw == -18.5
    assert observation.house_consumption_w == 1800
    assert observation.baseline_house_consumption_w == 1800
    assert not observation.baseline_training_eligible
    assert observation.baseline_exclusion_reason == "known_ev_session_without_ac_power"
    assert observation.ev_source == "byd_vehicle_cloud"
    assert observation.ev_detection_confidence == "direct_fresh"
    assert observation.ev_vehicle.status == "charging"
    assert "ev_charging_confirmed" in observation.event_labels
    assert "ev_at_home" in observation.event_labels


def test_fresh_plugged_idle_remains_baseline_eligible(healthy_states, config, now):
    _configure(config)
    observation = build_observation(
        _vehicle_states(healthy_states, now), config, observed_at=now
    )
    assert observation.ev_vehicle.plugged_in is True
    assert observation.ev_charging_active is False
    assert observation.ev_vehicle.status == "plugged_idle"
    assert observation.baseline_training_eligible
    assert observation.baseline_house_consumption_w == 1800
    assert "ev_plugged_idle" in observation.event_labels


def test_stale_off_is_unknown_and_does_not_make_core_health_unhealthy(
    healthy_states, config, now
):
    _configure(config)
    stale = now - timedelta(seconds=config.ev_telemetry_stale_seconds + 1)
    observation = build_observation(
        _vehicle_states(healthy_states, now, updated=stale.isoformat()),
        config,
        observed_at=now,
    )
    assert observation.ev_charging_active is None
    assert observation.ev_vehicle.plugged_in is None
    assert observation.ev_vehicle.status == "stale"
    assert observation.ev_detection_confidence == "direct_stale"
    assert {issue.code for issue in observation.data_health.ev.issues} >= {
        "ev_telemetry_stale"
    }
    assert observation.data_health.overall.is_healthy
    assert observation.baseline_training_eligible


def test_offline_and_invalid_optional_values_are_nonfatal(healthy_states, config, now):
    _configure(config)
    observation = build_observation(
        _vehicle_states(
            healthy_states,
            now,
            online="off",
            soc="101",
            power="invalid",
            location="unavailable",
        ),
        config,
        observed_at=now,
    )
    assert observation.ev_charging_active is None
    assert observation.ev_vehicle.status == "offline"
    assert observation.ev_vehicle.vehicle_soc_percent is None
    assert observation.ev_vehicle.vehicle_battery_power_w_raw is None
    assert observation.ev_vehicle.at_home is None
    assert {issue.code for issue in observation.ev_vehicle.issues} >= {
        "ev_soc_invalid",
        "ev_power_invalid",
        "ev_location_unavailable",
    }
    assert observation.data_health.overall.is_healthy


def test_location_attributes_and_vin_are_never_persisted(healthy_states, config, now):
    _configure(config)
    states = _vehicle_states(healthy_states, now)
    states[EV_IDS["location"]].attributes = {
        "latitude": "SENTINEL-LATITUDE-NOT-STORED",
        "longitude": "SENTINEL-LONGITUDE-NOT-STORED",
        "vin": "PRIVATE-VEHICLE-ID",
    }
    observation = build_observation(states, config, observed_at=now)
    values = observation_values(observation)
    serialized = repr(values)
    assert observation.ev_vehicle.at_home is True
    assert "PRIVATE-VEHICLE-ID" not in serialized
    assert "SENTINEL-LATITUDE-NOT-STORED" not in serialized
    assert "SENTINEL-LONGITUDE-NOT-STORED" not in serialized
    assert "latitude" not in serialized
    assert "longitude" not in serialized


def test_vehicle_fields_round_trip_with_timezone_and_null_semantics(
    healthy_states, config, now
):
    _configure(config)
    repository = DatabaseRepository(
        create_database_engine(f"sqlite:///{config.database_path}")
    )
    repository.create_schema_for_tests()
    observation = build_observation(
        _vehicle_states(healthy_states, now), config, observed_at=now
    )
    repository.save_observation(observation)
    row = repository.latest_observation()
    assert row["ev_vehicle_soc_percent"] == 64
    assert row["ev_vehicle_battery_power_w_raw"] == -18.5
    assert row["ev_plugged_in"] is True
    assert row["ev_charging_active"] is False
    assert row["ev_telemetry_updated_at_utc"].utcoffset() is not None
    assert row["ev_power_w"] is None
    repository.engine.dispose()


def test_collector_uses_one_bulk_get_and_missing_vehicle_entities_are_nonfatal(
    healthy_states, config, now
):
    _configure(config)

    class Client:
        calls = 0

        def get_states(self, entity_ids):
            self.calls += 1
            assert set(EV_IDS.values()) <= set(entity_ids)
            return healthy_states

    client = Client()
    observation = Collector(client, config).collect(observed_at=now)
    assert client.calls == 1
    assert observation.data_health.overall.is_healthy
    assert observation.data_health.ev.configured
    assert not observation.data_health.ev.available


def test_windows_environment_and_app_options_map_optional_vehicle_config(
    monkeypatch,
):
    variables = {
        "HA_URL": "http://example.invalid",
        "HA_TOKEN": "test-only",
        "EV_VEHICLE_ENABLED": "true",
        "EV_CHARGING_ENTITY": EV_IDS["charging"],
        "EV_PLUGGED_ENTITY": EV_IDS["plugged"],
        "EV_ONLINE_ENTITY": EV_IDS["online"],
        "EV_SOC_ENTITY": EV_IDS["soc"],
        "EV_BATTERY_POWER_ENTITY": EV_IDS["power"],
        "EV_TELEMETRY_UPDATED_ENTITY": EV_IDS["updated"],
        "EV_LOCATION_ENTITY": EV_IDS["location"],
        "EV_HOME_STATE": "home",
        "EV_TELEMETRY_STALE_SECONDS": "900",
    }
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    config = load_config(None)
    assert config.ev_vehicle_enabled
    assert config.ev_vehicle_charging_entity_id == EV_IDS["charging"]
    assert config.ev_telemetry_stale_seconds == 900

    options = HomeAssistantAppOptions(
        db_host="db.example.invalid",
        db_password="test-only",
        ev_vehicle_enabled=True,
        ev_charging_entity=EV_IDS["charging"],
    )
    environment = app_environment(options, supervisor_token="test-token")
    assert environment["EV_VEHICLE_ENABLED"] == "true"
    assert environment["EV_CHARGING_ENTITY"] == EV_IDS["charging"]


def test_invalid_vehicle_freshness_threshold_is_rejected(monkeypatch):
    monkeypatch.setenv("HA_URL", "http://example.invalid")
    monkeypatch.setenv("HA_TOKEN", "test-only")
    monkeypatch.setenv("EV_TELEMETRY_STALE_SECONDS", "0")
    with pytest.raises(ConfigurationError, match="positive integer"):
        load_config(None)


def test_incomplete_vehicle_configuration_is_warning_only(healthy_states, config, now):
    config.ev_vehicle_enabled = True
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.ev_vehicle.status == "unknown"
    assert not observation.data_health.ev.available
    assert {issue.code for issue in observation.data_health.ev.issues} == {
        "ev_entity_missing"
    }
    assert observation.data_health.overall.is_healthy


def test_no_vehicle_control_entities_or_write_client_are_introduced():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (Path("src"), Path("home_energy_optimiser"))
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".js", ".html", ".yaml", ".sh"}
    )
    forbidden_entities = {
        "button.byd_sealion_7_start_charging",
        "button.byd_sealion_7_stop_charging",
        "switch.byd_sealion_7_charge_to_full",
        "switch.byd_sealion_7_schedule_enabled",
        "switch.byd_sealion_7_repeat_daily",
        "time.byd_sealion_7_start_time",
        "time.byd_sealion_7_end_time",
        "button.byd_sealion_7_force_poll",
        "number.byd_sealion_7_telemetry_poll_interval",
        "number.byd_sealion_7_gps_poll_interval",
        "lock.byd_sealion_7_lock",
        "climate.byd_sealion_7_climate",
    }
    assert not any(entity_id in source for entity_id in forbidden_entities)
    client_source = Path("src/energy_optimizer/home_assistant.py").read_text(
        encoding="utf-8"
    )
    assert "self._session.post" not in client_source
    assert "self._session.put" not in client_source
    assert "self._session.patch" not in client_source
    assert "self._session.delete" not in client_source
