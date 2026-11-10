from datetime import timedelta

import pytest
from test_byd_vehicle import EV_IDS, _configure, _vehicle_states
from test_reprocessing import APPLY, _legacy_database

from energy_optimizer import entity_ids as ids
from energy_optimizer.collector import build_observation
from energy_optimizer.reprocessing import reprocess_observations


@pytest.mark.parametrize(
    "variant",
    [
        "stale_on",
        "stale_off",
        "unknown",
        "unavailable",
        "missing_charging",
        "missing_timestamp",
        "invalid_timestamp",
        "offline_off",
    ],
)
def test_unreliable_configured_vehicle_excludes_baseline(
    healthy_states, config, now, variant
):
    _configure(config)
    states = _vehicle_states(healthy_states, now, charging="on")
    if variant.startswith("stale"):
        states[EV_IDS["updated"]].state = (now - timedelta(seconds=901)).isoformat()
        states[EV_IDS["charging"]].state = "off" if variant == "stale_off" else "on"
    elif variant in ("unknown", "unavailable"):
        states[EV_IDS["charging"]].state = variant
    elif variant == "missing_charging":
        del states[EV_IDS["charging"]]
    elif variant == "missing_timestamp":
        del states[EV_IDS["updated"]]
    elif variant == "invalid_timestamp":
        states[EV_IDS["updated"]].state = "invalid"
    else:
        states[EV_IDS["charging"]].state = "off"
        states[EV_IDS["online"]].state = "off"
    obs = build_observation(states, config, observed_at=now)
    assert obs.ev_charging_active is None
    assert not obs.baseline_training_eligible
    assert (
        obs.baseline_exclusion_reason == "configured_ev_status_unknown_without_ac_power"
    )
    assert obs.house_consumption_w == obs.baseline_house_consumption_w == 1800
    assert obs.ev_power_w is None
    assert obs.data_health.overall.is_healthy


def test_exact_freshness_boundary_remains_charging(healthy_states, config, now):
    _configure(config)
    states = _vehicle_states(
        healthy_states,
        now,
        charging="on",
        updated=(now - timedelta(seconds=900)).isoformat(),
    )
    obs = build_observation(states, config, observed_at=now)
    assert obs.ev_charging_active is True
    assert obs.baseline_exclusion_reason == "known_ev_session_without_ac_power"


def test_separate_direct_ac_power_still_allows_subtraction(healthy_states, config, now):
    _configure(config)
    states = _vehicle_states(
        healthy_states, now, updated=(now - timedelta(seconds=901)).isoformat()
    )
    config.ev_charging_power_entity_id = "sensor.synthetic_ac_power"
    states[config.ev_charging_power_entity_id] = states[
        ids.GOODWE_HOUSE_CONSUMPTION
    ].model_copy(
        update={"entity_id": config.ev_charging_power_entity_id, "state": "1000"}
    )
    obs = build_observation(states, config, observed_at=now)
    assert obs.ev_charging_active is None
    assert obs.house_consumption_w == 1800
    assert obs.baseline_house_consumption_w == 800
    assert obs.baseline_training_eligible


def test_configured_missing_helper_excludes(healthy_states, config, now):
    config.ev_charging_active_entity_id = "binary_sensor.missing_charger"
    obs = build_observation(healthy_states, config, observed_at=now)
    assert not obs.baseline_training_eligible


def test_missing_configured_ac_power_keeps_source_provenance(
    healthy_states, config, now
):
    config.ev_charging_power_entity_id = "sensor.missing_ac_power"
    obs = build_observation(healthy_states, config, observed_at=now)
    assert not obs.baseline_training_eligible
    assert obs.ev_source == "home_assistant_helper"
    assert obs.ev_power_w is None


@pytest.mark.parametrize(
    "source", ["byd_vehicle_cloud", "home_assistant_helper", "charger"]
)
def test_reprocessing_cannot_readmit_unknown_ev(healthy_states, config, now, source):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as con:
        con.execute(
            "UPDATE observations SET ev_source=?, ev_charging_active=NULL, "
            "ev_power_w=NULL, baseline_training_eligible=1",
            (source,),
        )
    reprocess_observations(historian, config, **APPLY, now=now)
    row = historian.latest_observation()
    assert not row["baseline_training_eligible"]
    assert (
        row["baseline_exclusion_reason"]
        == "configured_ev_status_unknown_without_ac_power"
    )
