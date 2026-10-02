"""Explicit, offline morning-export diagnostic. No scheduler or execution path.

Compares two assumed battery trajectories on identical forecast load/P10 solar.
The comparison is a model estimate, never measured savings or validated HOLD.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite, sqrt
from typing import Any

from energy_optimizer.timestamps import aware_datetime, json_safe

POLICY_VERSION = "morning-solar-export-diagnostic-v1"


@dataclass(frozen=True)
class ExportConfig:
    capacity_kwh: float = 40.0
    minimum_soc_percent: float = 20.0
    recharge_target_soc_percent: float = 100.0
    charge_efficiency: float = sqrt(0.95)
    discharge_efficiency: float = sqrt(0.95)
    maximum_charge_kw: float = 0.0
    maximum_discharge_kw: float = 0.0
    maximum_export_kw: float = 0.0
    degradation_aud_per_battery_kwh: float = 0.08
    minimum_margin_aud_per_export_kwh: float = 0.10
    minimum_value_aud: float = 0.25

    def __post_init__(self) -> None:
        if any(not isfinite(value) for value in asdict(self).values()):
            raise ValueError("configuration must be finite")
        if self.capacity_kwh <= 0 or not (
            0 <= self.minimum_soc_percent < self.recharge_target_soc_percent <= 100
        ):
            raise ValueError("invalid capacity or SOC targets")
        if not (0 < self.charge_efficiency <= 1 and 0 < self.discharge_efficiency <= 1):
            raise ValueError("efficiencies must be in (0, 1]")
        if any(
            value < 0
            for key, value in asdict(self).items()
            if "kw" in key or "aud" in key
        ):
            raise ValueError("limits and costs must not be negative")


@dataclass(frozen=True)
class ForecastSlot:
    start_utc: datetime
    end_utc: datetime
    solar_p10_kw: float
    household_kw: float
    import_aud_per_kwh: float
    export_aud_per_kwh: float

    def __post_init__(self) -> None:
        start = aware_datetime(self.start_utc).astimezone(UTC)
        end = aware_datetime(self.end_utc).astimezone(UTC)
        if not 0 < (end - start).total_seconds() <= 1800:
            raise ValueError("slots must be positive and at most half an hour")
        for value in (
            self.solar_p10_kw,
            self.household_kw,
            self.import_aud_per_kwh,
            self.export_aud_per_kwh,
        ):
            if not isfinite(value):
                raise ValueError("forecast values must be finite")
        if min(self.solar_p10_kw, self.household_kw) < 0:
            raise ValueError("power must not be negative")
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)


def plan_morning_export(
    *,
    created_at_utc: datetime,
    initial_energy_kwh: float,
    reserve_kwh: float,
    slots: list[ForecastSlot],
    export_before_utc: datetime,
    recharge_deadline_utc: datetime,
    calibrated: bool,
    config: ExportConfig,
) -> dict[str, Any]:
    """Greedily add useful export slots, constrained by conservative recharge.

    The reserve is supplied by the linked persisted run, never recalculated.
    No grid charging is assumed. Household deficits use battery above reserve,
    then grid; surplus solar charges, then exports to the configured limit.
    Candidate export must not cause additional grid imports versus that baseline.
    """
    created = aware_datetime(created_at_utc).astimezone(UTC)
    before = aware_datetime(export_before_utc).astimezone(UTC)
    deadline = aware_datetime(recharge_deadline_utc).astimezone(UTC)
    result: dict[str, Any] = {
        "policy_version": POLICY_VERSION,
        "synthetic_replay": True,
        "no_command_issued": True,
        "database_write_performed": False,
        "execution_ready": False,
        "action": "HOLD",
        "status": "blocked",
        "blockers": [],
        "warnings": [
            "physical_response_and_baseline_unvalidated",
            "forecast_value_is_not_measured_savings",
            "p10_curve_is_not_a_joint_probability_guarantee",
            "load_and_power_limits_require_validation",
            "ev_demand_must_be_explicit_in_input",
        ],
        "assumptions": asdict(config),
        "calibrated": calibrated,
        "created_at_utc": created,
        "reserve_kwh": reserve_kwh,
        "export_before_utc": before,
        "recharge_deadline_utc": deadline,
        "initial_energy_kwh": initial_energy_kwh,
        "export_windows": [],
        "export_kwh": None,
        "expected_incremental_model_value_aud": None,
        "projected_recharge_at_utc": None,
    }
    blockers = result["blockers"]
    if (
        not isfinite(initial_energy_kwh)
        or not 0 <= initial_energy_kwh <= config.capacity_kwh
    ):
        blockers.append("battery_energy_invalid")
    if not isfinite(reserve_kwh) or not 0 <= reserve_kwh <= config.capacity_kwh:
        blockers.append("reserve_invalid")
    floor = max(reserve_kwh, config.capacity_kwh * config.minimum_soc_percent / 100)
    if initial_energy_kwh < floor:
        blockers.append("battery_below_reserve")
    if (
        min(
            config.maximum_charge_kw,
            config.maximum_discharge_kw,
            config.maximum_export_kw,
        )
        <= 0
    ):
        blockers.append("power_limits_unknown")
    if not created < before <= deadline or not slots:
        blockers.append("planning_horizon_invalid_or_missing")
    elif (
        slots[0].start_utc != created
        or slots[-1].end_utc != deadline
        or any(a.end_utc != b.start_utc for a, b in zip(slots, slots[1:], strict=False))
    ):
        blockers.append("forecast_coverage_incomplete")
    if blockers:
        if not calibrated:
            blockers.append("calibration_evidence_insufficient")
        return json_safe(result)

    baseline = _trajectory(slots, {}, initial_energy_kwh, floor, config)
    result["baseline"] = baseline
    plan: dict[int, float] = {}
    trajectory = baseline
    # Each greedy step considers all eligible slots; no mathematical optimality claim.
    remaining = [
        i
        for i, slot in enumerate(slots)
        if slot.end_utc <= before and slot.export_aud_per_kwh > 0
    ]
    last_value = 0.0
    while remaining:
        best = None
        for index in remaining:
            hours = (
                slots[index].end_utc - slots[index].start_utc
            ).total_seconds() / 3600
            low, high = (
                0.0,
                min(config.maximum_export_kw, config.maximum_discharge_kw) * hours,
            )
            for _ in range(24):
                energy = (low + high) / 2
                trial = {**plan, index: energy}
                projected = _trajectory(slots, trial, initial_energy_kwh, floor, config)
                if _safe(projected, baseline, trial, slots):
                    low = energy
                else:
                    high = energy
            if low < 0.001:
                continue
            trial = {**plan, index: low}
            projected = _trajectory(slots, trial, initial_energy_kwh, floor, config)
            value = _value(projected, baseline, slots, config)
            increment = value - last_value
            if increment < config.minimum_margin_aud_per_export_kwh * low:
                continue
            if best is None or increment > best[0] + 1e-9:
                best = (increment, index, low, projected, value)
        if best is None:
            break
        _, index, energy, trajectory, last_value = best
        plan[index] = energy
        remaining.remove(index)

    result["export_kwh"] = sum(plan.values())
    result["expected_incremental_model_value_aud"] = last_value
    result["projection"] = trajectory
    result["projected_recharge_at_utc"] = _recharge_after(trajectory, plan, slots)
    result["minimum_projected_soc_percent"] = (
        trajectory["minimum_energy_kwh"] / config.capacity_kwh * 100
    )
    result["export_windows"] = [
        {
            "start_utc": slots[i].start_utc,
            "end_utc": slots[i].end_utc,
            "battery_export_kwh": plan[i],
            "expected_export_aud_per_kwh": slots[i].export_aud_per_kwh,
        }
        for i in sorted(plan)
    ]
    if not plan:
        result["status"] = "hold"
        result["blockers"].append("no_export_with_safe_recharge_and_margin")
    elif last_value < config.minimum_value_aud:
        result["status"] = "hold"
        result["blockers"].append("expected_value_below_threshold")
    elif not calibrated:
        result["blockers"].append("calibration_evidence_insufficient")
    else:
        result["status"] = "advisory"
        result["action"] = "EXPORT_BATTERY"
    return json_safe(result)


def _trajectory(
    slots: list[ForecastSlot],
    plan: dict[int, float],
    initial: float,
    floor: float,
    config: ExportConfig,
) -> dict[str, Any]:
    energy = initial
    minimum = initial
    imports = exports = discharged = revenue = import_cost = spill = 0.0
    feasible = True
    points = []
    for index, slot in enumerate(slots):
        hours = (slot.end_utc - slot.start_utc).total_seconds() / 3600
        surplus = max(slot.solar_p10_kw - slot.household_kw, 0) * hours
        deficit = max(slot.household_kw - slot.solar_p10_kw, 0) * hours
        home = min(
            deficit,
            config.maximum_discharge_kw * hours,
            max(energy - floor, 0) * config.discharge_efficiency,
        )
        energy -= home / config.discharge_efficiency
        grid_import = deficit - home
        requested = plan.get(index, 0.0)
        charge_ac = min(
            surplus,
            config.maximum_charge_kw * hours,
            max(config.capacity_kwh - energy, 0) / config.charge_efficiency,
        )
        # An explicit export window replaces charging; there is never a modelled
        # simultaneous battery charge/discharge, even if solar is producing.
        if requested > 1e-9:
            charge_ac = 0.0
        energy += charge_ac * config.charge_efficiency
        solar_export = min(surplus - charge_ac, config.maximum_export_kw * hours)
        actual = min(
            requested,
            max(config.maximum_discharge_kw * hours - home, 0),
            max(config.maximum_export_kw * hours - solar_export, 0),
            max(energy - floor, 0) * config.discharge_efficiency,
        )
        feasible &= actual >= requested - 1e-8
        energy -= actual / config.discharge_efficiency
        minimum = min(minimum, energy)
        grid_export = solar_export + actual
        imports += grid_import
        exports += grid_export
        discharged += (home + actual) / config.discharge_efficiency
        revenue += grid_export * slot.export_aud_per_kwh
        import_cost += grid_import * slot.import_aud_per_kwh
        spill += surplus - charge_ac - solar_export
        points.append(
            {
                "end_utc": slot.end_utc,
                "battery_energy_kwh": energy,
                "soc_percent": energy / config.capacity_kwh * 100,
                "grid_import_kwh": grid_import,
                "grid_export_kwh": grid_export,
                "battery_export_kwh": actual,
                "solar_charge_kwh": charge_ac,
                "battery_to_house_kwh": home,
                "reserve_margin_kwh": energy - floor,
                "recharge_target_met": energy
                >= config.capacity_kwh * config.recharge_target_soc_percent / 100
                - 1e-6,
            }
        )
    return {
        "feasible": feasible,
        "minimum_energy_kwh": minimum,
        "terminal_energy_kwh": energy,
        "grid_import_kwh": imports,
        "grid_export_kwh": exports,
        "battery_discharge_kwh": discharged,
        "export_revenue_aud": revenue,
        "import_cost_aud": import_cost,
        "curtailed_solar_kwh": spill,
        "points": points,
    }


def _recharge_after(
    trajectory: dict[str, Any],
    plan: dict[int, float],
    slots: list[ForecastSlot],
) -> datetime | None:
    if not plan:
        return None
    last_end = max(slots[i].end_utc for i in plan)
    return next(
        (
            point["end_utc"]
            for point in trajectory["points"]
            if point["end_utc"] > last_end and point["recharge_target_met"]
        ),
        None,
    )


def _safe(
    projected: dict[str, Any],
    baseline: dict[str, Any],
    plan: dict[int, float],
    slots: list[ForecastSlot],
) -> bool:
    return (
        projected["feasible"]
        and _recharge_after(projected, plan, slots) is not None
        and all(
            p["grid_import_kwh"] <= b["grid_import_kwh"] + 1e-8
            for p, b in zip(projected["points"], baseline["points"], strict=True)
        )
    )


def _value(
    projected: dict[str, Any],
    baseline: dict[str, Any],
    slots: list[ForecastSlot],
    config: ExportConfig,
) -> float:
    terminal_price = max(0, *(slot.import_aud_per_kwh for slot in slots))
    terminal_loss = max(
        baseline["terminal_energy_kwh"] - projected["terminal_energy_kwh"], 0
    )
    wear = (
        projected["battery_discharge_kwh"] - baseline["battery_discharge_kwh"]
    ) * config.degradation_aud_per_battery_kwh
    return (
        projected["export_revenue_aud"]
        - baseline["export_revenue_aud"]
        - projected["import_cost_aud"]
        + baseline["import_cost_aud"]
        - wear
        - terminal_loss * config.discharge_efficiency * terminal_price
    )
