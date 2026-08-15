from datetime import UTC, timedelta

from energy_optimizer import entity_ids as ids
from energy_optimizer.collector import align_to_five_minute_slot, build_observation
from energy_optimizer.health import evaluate_data_health, is_ready_for


def test_timezone_slot_and_battery_estimate(healthy_states, config, now):
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.slot_utc.minute == 5
    assert observation.slot_utc.tzinfo == UTC
    assert observation.observed_at_local.utcoffset() == timedelta(hours=10)
    assert observation.battery_energy_estimate_kwh == 20
    assert observation.battery_power_w == -1200
    assert observation.grid_power_w == -900
    assert observation.solcast_next_hour_kwh.estimate_kwh == 1.8
    assert observation.solcast_next_hour_kwh.source_unit == "Wh"
    assert observation.solcast_remaining_today_kwh.estimate_kwh == 12.5


def test_alignment_rejects_naive_datetime(now):
    try:
        align_to_five_minute_slot(now.replace(tzinfo=None))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive datetime was accepted")


def test_healthy_score_and_optional_power_now(healthy_states, config, now):
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.is_healthy
    assert health.health_score == 100
    assert ids.SOLCAST_POWER_NOW not in healthy_states


def test_health_scoring_stale_and_malformed(healthy_states, config, now):
    healthy_states[ids.GOODWE_BATTERY_SOC].state = "bad"
    healthy_states[ids.GOODWE_PV_POWER].last_updated = now - timedelta(hours=1)
    health = evaluate_data_health(healthy_states, config, now=now)
    codes = {issue.code for issue in health.telemetry.issues}
    assert {"malformed_number", "source_update_stale"} <= codes
    assert health.telemetry.score == 75
    assert not health.is_healthy


def test_unavailable_state_is_not_zero(healthy_states, config, now):
    healthy_states[ids.GOODWE_HOUSE_CONSUMPTION].state = "unavailable"
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.house_consumption_w is None
    assert not observation.data_health.is_healthy


def test_stale_modes_do_not_reduce_telemetry_health(healthy_states, config, now):
    healthy_states[ids.GOODWE_BATTERY_MODE].last_updated = now - timedelta(days=5)
    healthy_states[ids.GOODWE_WORK_MODE].last_updated = now - timedelta(days=5)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.telemetry.is_healthy
    assert health.telemetry.score == 100


def test_unchanged_soc_remains_available_with_entity_specific_grace(
    healthy_states, config, now
):
    healthy_states[ids.GOODWE_BATTERY_SOC].last_updated = now - timedelta(minutes=30)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.telemetry.entity_freshness[ids.GOODWE_BATTERY_SOC] == (
        "available_but_unchanged"
    )
    assert not any(
        issue.entity_id == ids.GOODWE_BATTERY_SOC for issue in health.telemetry.issues
    )


def test_zero_pv_can_remain_unchanged_but_active_pv_must_advance(
    healthy_states, config, now
):
    pv = healthy_states[ids.GOODWE_PV_POWER]
    pv.state = "0"
    pv.last_updated = now - timedelta(hours=3)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.telemetry.entity_freshness[ids.GOODWE_PV_POWER] == (
        "available_but_unchanged"
    )
    pv.state = "4200"
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.telemetry.entity_freshness[ids.GOODWE_PV_POWER] == (
        "source_update_stale"
    )


def test_unknown_and_unavailable_remain_failures(healthy_states, config, now):
    healthy_states[ids.GOODWE_BATTERY_SOC].state = "unknown"
    healthy_states[ids.GOODWE_PV_POWER].state = "unavailable"
    health = evaluate_data_health(healthy_states, config, now=now)
    assert not health.telemetry.is_healthy
    assert health.telemetry.entity_freshness[ids.GOODWE_BATTERY_SOC] == "unknown"
    assert health.telemetry.entity_freshness[ids.GOODWE_PV_POWER] == "unavailable"


def test_stale_price_spike_does_not_reduce_price_health(healthy_states, config, now):
    healthy_states[ids.AMBER_PRICE_SPIKE].last_updated = now - timedelta(days=5)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.price.is_healthy
    assert health.price.score == 100


def test_missing_amber_forecast_isolated_from_telemetry(healthy_states, config, now):
    healthy_states.pop(ids.AMBER_IMPORT_FORECAST)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.telemetry.is_healthy
    assert not health.price.is_healthy
    assert health.overall.is_healthy


def test_missing_solcast_forecast_isolated_from_telemetry(healthy_states, config, now):
    healthy_states.pop(ids.SOLCAST_TOMORROW)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert health.telemetry.is_healthy
    assert not health.solar.is_healthy
    assert health.overall.is_healthy


def test_action_specific_readiness(healthy_states, config, now):
    healthy_states.pop(ids.AMBER_EXPORT_FORECAST)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert is_ready_for(health, "load_profile")
    assert not is_ready_for(health, "grid_charge")
    assert not is_ready_for(health, "battery_export")


def test_configured_weather_is_collected_but_remains_optional(
    healthy_states, config, now
):
    temperature_id = "sensor.outdoor_temperature"
    condition_id = "sensor.outdoor_condition"
    config.weather_temperature_entity_id = temperature_id
    config.weather_condition_entity_id = condition_id
    healthy_states[temperature_id] = healthy_states[ids.AMBER_IMPORT_PRICE].model_copy(
        update={"entity_id": temperature_id, "state": "24.5"}
    )
    healthy_states[condition_id] = healthy_states[ids.GOODWE_WORK_MODE].model_copy(
        update={"entity_id": condition_id, "state": "sunny"}
    )
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.temperature_c == 24.5
    assert observation.weather_condition == "sunny"
    assert observation.data_health.weather.is_healthy
    healthy_states.pop(temperature_id)
    missing_weather = build_observation(healthy_states, config, observed_at=now)
    assert not missing_weather.data_health.weather.is_healthy
    assert missing_weather.data_health.overall.is_healthy


def test_unknown_signs_only_block_flow_health(healthy_states, config, now):
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.data_health.telemetry.is_healthy
    assert observation.data_health.overall.is_healthy
    assert not observation.data_health.flow.is_healthy
    assert observation.energy_flow.sign_convention_status == "unconfirmed"


def test_configured_signs_populate_new_observation_flows_and_baseline(
    healthy_states, config, now
):
    config.grid_power_sign_convention = "positive_export"
    config.battery_power_sign_convention = "positive_discharge"
    config.sign_convention_confidence = "high"
    config.sign_convention_supporting_samples = 175
    config.balance_tolerance_w = 250
    observation = build_observation(healthy_states, config, observed_at=now)
    flow = observation.energy_flow
    assert observation.grid_power_w == -900
    assert observation.battery_power_w == -1200
    assert observation.house_consumption_w == 1800
    assert observation.pv_power_w == 4200
    assert flow.grid_import_power_w == 900
    assert flow.grid_export_power_w == 0
    assert flow.battery_charge_power_w == 1200
    assert flow.battery_discharge_power_w == 0
    assert flow.balance_residual_w == 2100
    assert flow.sign_convention_status == "confirmed"
    assert observation.baseline_house_consumption_w == 1800
    assert observation.baseline_training_eligible


def test_large_balance_residual_only_blocks_flow_health(healthy_states, config, now):
    config.grid_power_sign_convention = "positive_export"
    config.battery_power_sign_convention = "positive_discharge"
    config.balance_tolerance_w = 100
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.data_health.telemetry.is_healthy
    assert not observation.data_health.flow.is_healthy
    assert {issue.code for issue in observation.data_health.flow.issues} == {
        "balance_residual_too_large"
    }
