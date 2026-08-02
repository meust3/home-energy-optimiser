from energy_optimizer import entity_ids as ids
from energy_optimizer.collector import build_observation
from energy_optimizer.ev import calculate_baseline_load, infer_ev_sessions
from energy_optimizer.historian import Historian


def test_baseline_subtracts_direct_ev_power():
    baseline, eligible, reason = calculate_baseline_load(
        9000, ev_charging_active=True, ev_power_w=7000
    )
    assert baseline == 2000
    assert eligible
    assert reason is None


def test_inactive_ev_keeps_measured_house_load():
    assert calculate_baseline_load(2200, ev_charging_active=False, ev_power_w=None) == (
        2200,
        True,
        None,
    )


def test_inferred_unknown_power_is_excluded_not_subtracted():
    baseline, eligible, reason = calculate_baseline_load(
        9000,
        ev_charging_active=None,
        ev_power_w=None,
        inferred_session=True,
        inference_confidence="high",
    )
    assert baseline == 9000
    assert not eligible
    assert "inferred_ev_session" in reason


def test_optional_ev_entities_absent_do_not_affect_collection(
    healthy_states, config, now
):
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.ev_charging_active is None
    assert observation.ev_power_w is None
    assert observation.ev_source == "none"
    assert observation.baseline_house_consumption_w == 1800
    assert observation.baseline_training_eligible
    assert observation.data_health.overall.is_healthy


def test_direct_ev_entities_set_baseline(healthy_states, config, now):
    active_id = "binary_sensor.ev_charging"
    power_id = "sensor.ev_power"
    config.ev_charging_active_entity_id = active_id
    config.ev_charging_power_entity_id = power_id
    healthy_states[active_id] = healthy_states[ids.AMBER_PRICE_SPIKE].model_copy(
        update={"entity_id": active_id, "state": "on"}
    )
    healthy_states[power_id] = healthy_states[ids.GOODWE_PV_POWER].model_copy(
        update={"entity_id": power_id, "state": "1200"}
    )
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.ev_charging_active is True
    assert observation.ev_power_w == 1200
    assert observation.baseline_house_consumption_w == 600
    assert observation.ev_source == "charger"
    historian = Historian(config.database_path)
    historian.save(observation)
    samples = historian.healthy_load_samples()
    assert len(samples) == 1
    assert samples[0]["house_consumption_w"] == 600


def test_ev_inference_disabled_by_default():
    rows = [
        {"slot_utc": str(index), "house_consumption_w": 7000} for index in range(12)
    ]
    assert not infer_ev_sessions(
        rows,
        enabled=False,
        plausible_min_w=6000,
        plausible_max_w=8000,
        minimum_samples=6,
    )
