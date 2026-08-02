from energy_optimizer.energy_flow import derive_energy_flow, derive_event_labels


def _config(config, grid_sign, battery_sign):
    config.grid_power_sign_convention = grid_sign
    config.battery_power_sign_convention = battery_sign
    config.sign_convention_confidence = "high"
    config.sign_convention_supporting_samples = 175
    return config


def test_unknown_signs_preserve_raw_values_and_block_derivation(config):
    flow = derive_energy_flow(
        pv_power_w=1000,
        house_consumption_w=3000,
        grid_power_w=-1500,
        battery_power_w=500,
        config=config,
    )
    assert flow.raw_grid_power_w == -1500
    assert flow.raw_battery_power_w == 500
    assert flow.grid_import_power_w is None
    assert flow.battery_discharge_power_w is None
    assert flow.sign_convention_status == "unconfirmed"


def test_positive_import_and_positive_discharge(config):
    flow = derive_energy_flow(
        pv_power_w=1000,
        house_consumption_w=3000,
        grid_power_w=1500,
        battery_power_w=500,
        config=_config(config, "positive_import", "positive_discharge"),
    )
    assert flow.grid_import_power_w == 1500
    assert flow.grid_export_power_w == 0
    assert flow.battery_discharge_power_w == 500
    assert flow.battery_charge_power_w == 0
    assert flow.balance_residual_w == 0
    assert flow.supporting_sample_count == 175


def test_positive_export_and_positive_charge(config):
    flow = derive_energy_flow(
        pv_power_w=1000,
        house_consumption_w=3000,
        grid_power_w=-1500,
        battery_power_w=-500,
        config=_config(config, "positive_export", "positive_charge"),
    )
    assert flow.grid_import_power_w == 1500
    assert flow.grid_export_power_w == 0
    assert flow.battery_discharge_power_w == 500
    assert flow.battery_charge_power_w == 0
    assert flow.balance_residual_w == 0


def test_export_charge_and_event_label_evidence(config):
    flow = derive_energy_flow(
        pv_power_w=4000,
        house_consumption_w=1000,
        grid_power_w=1000,
        battery_power_w=-2000,
        config=_config(config, "positive_export", "positive_discharge"),
    )
    assert flow.grid_export_power_w == 1000
    assert flow.battery_charge_power_w == 2000
    assert flow.solar_to_battery_power_w == 2000
    labels, confidence, evidence = derive_event_labels(
        flow, ev_active=False, ev_power_w=None, tolerance_w=100
    )
    assert {"solar_battery_charge", "solar_export"} <= set(labels)
    assert confidence == "high"
    assert evidence["balance_residual_w"] == 0
