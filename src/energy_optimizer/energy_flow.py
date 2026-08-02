"""Explicit, non-mutating normalization of raw inverter power values."""

from typing import Any

from energy_optimizer.models import CollectorConfig, EnergyFlow, EventLabel


def derive_energy_flow(
    *,
    pv_power_w: float | None,
    house_consumption_w: float | None,
    grid_power_w: float | None,
    battery_power_w: float | None,
    config: CollectorConfig,
) -> EnergyFlow:
    """Derive directional flows only when both configured signs are confirmed."""
    raw = {
        "raw_pv_power_w": pv_power_w,
        "raw_house_consumption_w": house_consumption_w,
        "raw_grid_power_w": grid_power_w,
        "raw_battery_power_w": battery_power_w,
    }
    if config.grid_power_sign_convention == "unknown" or (
        config.battery_power_sign_convention == "unknown"
    ):
        return EnergyFlow(
            **raw,
            sign_convention_status="unconfirmed",
            sign_convention_confidence="unconfirmed",
            supporting_sample_count=config.sign_convention_supporting_samples,
        )
    if None in (pv_power_w, house_consumption_w, grid_power_w, battery_power_w):
        return EnergyFlow(
            **raw,
            sign_convention_status="unavailable",
            sign_convention_confidence=config.sign_convention_confidence,
            supporting_sample_count=config.sign_convention_supporting_samples,
        )
    assert pv_power_w is not None
    assert house_consumption_w is not None
    assert grid_power_w is not None
    assert battery_power_w is not None
    if config.grid_power_sign_convention == "positive_import":
        grid_import = max(grid_power_w, 0.0)
        grid_export = max(-grid_power_w, 0.0)
    else:
        grid_import = max(-grid_power_w, 0.0)
        grid_export = max(grid_power_w, 0.0)
    if config.battery_power_sign_convention == "positive_charge":
        battery_charge = max(battery_power_w, 0.0)
        battery_discharge = max(-battery_power_w, 0.0)
    else:
        battery_charge = max(-battery_power_w, 0.0)
        battery_discharge = max(battery_power_w, 0.0)
    pv = max(pv_power_w, 0.0)
    house = max(house_consumption_w, 0.0)
    solar_to_house = min(pv, house)
    solar_remaining = max(pv - solar_to_house, 0.0)
    solar_to_battery = min(solar_remaining, battery_charge)
    solar_to_grid = min(max(solar_remaining - solar_to_battery, 0.0), grid_export)
    house_remaining = max(house - solar_to_house, 0.0)
    battery_to_house = min(battery_discharge, house_remaining)
    battery_to_grid = max(battery_discharge - battery_to_house, 0.0)
    grid_to_house = min(grid_import, max(house_remaining - battery_to_house, 0.0))
    grid_to_battery = max(battery_charge - solar_to_battery, 0.0)
    residual = (
        pv + grid_import + battery_discharge - house - grid_export - battery_charge
    )
    return EnergyFlow(
        **raw,
        grid_import_power_w=grid_import,
        grid_export_power_w=grid_export,
        battery_charge_power_w=battery_charge,
        battery_discharge_power_w=battery_discharge,
        solar_to_house_power_w=solar_to_house,
        solar_to_battery_power_w=solar_to_battery,
        solar_to_grid_power_w=solar_to_grid,
        battery_to_house_power_w=battery_to_house,
        battery_to_grid_power_w=battery_to_grid,
        grid_to_house_power_w=grid_to_house,
        grid_to_battery_power_w=grid_to_battery,
        balance_residual_w=residual,
        sign_convention_status="confirmed",
        sign_convention_confidence=config.sign_convention_confidence,
        supporting_sample_count=config.sign_convention_supporting_samples,
    )


def derive_event_labels(
    flow: EnergyFlow,
    *,
    ev_active: bool | None,
    ev_power_w: float | None,
    tolerance_w: float,
) -> tuple[list[EventLabel], str, dict[str, Any]]:
    """Return conservative derived labels and transparent evidence."""
    if flow.sign_convention_status != "confirmed":
        return ["unknown"], "unconfirmed", {"reason": "signs_unconfirmed"}
    values = flow.model_dump()
    labels: list[EventLabel] = []
    threshold = max(tolerance_w, 1.0)
    if (flow.solar_to_battery_power_w or 0) > threshold:
        labels.append("solar_battery_charge")
    if (flow.grid_to_battery_power_w or 0) > threshold:
        labels.append("grid_battery_charge")
    if (flow.solar_to_grid_power_w or 0) > threshold:
        labels.append("solar_export")
    if (flow.battery_to_grid_power_w or 0) > threshold:
        labels.append("battery_export")
    if ev_active and ev_power_w is not None and ev_power_w > threshold:
        solar = flow.solar_to_house_power_w or 0
        grid = flow.grid_to_house_power_w or 0
        if solar >= ev_power_w - threshold and grid <= threshold:
            labels.append("ev_charge_solar")
        elif grid >= ev_power_w - threshold and solar <= threshold:
            labels.append("ev_charge_grid")
        else:
            labels.append("ev_charge_mixed")
    if not labels and (flow.solar_to_house_power_w or 0) > threshold:
        labels.append("normal_self_consumption")
    if not labels:
        labels = ["unknown"]
    residual = abs(flow.balance_residual_w or 0)
    confidence = "high" if residual <= tolerance_w else "low"
    return (
        labels,
        confidence,
        {
            "balance_residual_w": flow.balance_residual_w,
            "tolerance_w": tolerance_w,
            "derived_flows": values,
        },
    )
