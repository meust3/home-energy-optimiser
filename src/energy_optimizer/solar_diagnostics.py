"""Cautious daily Solcast-versus-realised-PV diagnostics."""

from collections import defaultdict
from datetime import date
from typing import Any

EXPECTED_DAILY_SLOTS = 288


def calculate_solar_diagnostics(
    rows: list[dict[str, Any]], *, coverage_percent: float = 95
) -> list[dict[str, Any]]:
    groups: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        local = row.get("observed_at_local")
        if local is not None:
            groups[local.date()].append(row)
    result = []
    for day, values in sorted(groups.items()):
        values = sorted(values, key=lambda row: row["observed_at_local"])
        pv = [
            float(r["pv_power_w"])
            for r in values
            if r.get("pv_power_w") is not None and bool(r.get("telemetry_is_healthy"))
        ]
        coverage = len(pv) / EXPECTED_DAILY_SLOTS * 100
        forecast = None
        for row in values:
            candidate = _forecast_values(row.get("solcast_today_kwh_json"))
            if candidate is not None:
                forecast = candidate
                break
        actual = sum(max(value, 0) for value in pv) / 12_000 if pv else None
        soc_values = [
            float(r["battery_soc_percent"])
            for r in values
            if r.get("battery_soc_percent") is not None
        ]
        near_full_slots = sum(
            float(r.get("battery_soc_percent") or 0) >= 95 for r in values
        )
        charge_slots = sum(
            float(r.get("battery_charge_power_w") or 0) > 100 for r in values
        )
        discharge_slots = sum(
            float(r.get("battery_discharge_power_w") or 0) > 100 for r in values
        )
        clipping_slots = sum(float(r.get("pv_power_w") or 0) >= 9499 for r in values)
        export_slots = sum(
            float(r.get("grid_export_power_w") or 0) > 100 for r in values
        )
        sustained_exports = [
            float(r["grid_export_power_w"])
            for r in values
            if r.get("grid_export_power_w") is not None
            and float(r["grid_export_power_w"]) >= 1000
        ]
        possible_export_ceiling = (
            len(sustained_exports) >= 12
            and max(sustained_exports) - min(sustained_exports)
            <= max(sustained_exports) * 0.05
        )
        sufficient = (
            coverage >= coverage_percent and forecast is not None and actual is not None
        )
        if not sufficient:
            classification = "insufficient_context"
        elif (
            sum((near_full_slots >= 12, clipping_slots >= 6, possible_export_ceiling))
            >= 2
        ):
            classification = "multiple_constraints_possible"
        elif near_full_slots >= 12:
            classification = "possible_battery_saturation"
        elif clipping_slots >= 6:
            classification = "possible_inverter_clipping"
        elif possible_export_ceiling:
            classification = "possible_export_constraint"
        else:
            classification = "likely_unconstrained"
        result.append(
            {
                "local_date": day,
                "coverage_percent": coverage,
                "coverage_sufficient": sufficient,
                "actual_pv_kwh": actual,
                "solcast_p10_kwh": forecast[0] if forecast else None,
                "solcast_p50_kwh": forecast[1] if forecast else None,
                "solcast_p90_kwh": forecast[2] if forecast else None,
                "actual_minus_p50_kwh": (
                    actual - forecast[1] if actual is not None and forecast else None
                ),
                "actual_in_solcast_range": (
                    forecast[0] is not None
                    and forecast[2] is not None
                    and forecast[0] <= actual <= forecast[2]
                    if actual is not None and forecast
                    else None
                ),
                "p50_percentage_error": (
                    (forecast[1] - actual) / actual * 100
                    if actual is not None and actual > 0 and forecast
                    else None
                ),
                "near_full_battery_minutes": near_full_slots * 5,
                "minimum_battery_headroom_percent": (
                    max(0.0, 100 - max(soc_values)) if soc_values else None
                ),
                "battery_charge_minutes": charge_slots * 5,
                "battery_discharge_minutes": discharge_slots * 5,
                "possible_inverter_clipping_minutes": clipping_slots * 5,
                "export_minutes": export_slots * 5,
                "possible_export_ceiling": possible_export_ceiling,
                "observed_work_modes": sorted(
                    {str(r["work_mode"]) for r in values if r.get("work_mode")}
                ),
                "classification": classification,
                "interpretation": (
                    "Contextual diagnostic only; it does not prove curtailment and "
                    "no automatic Solcast derating is applied."
                ),
            }
        )
    return result


def _forecast_values(value: Any) -> tuple[float | None, float, float | None] | None:
    if not isinstance(value, dict):
        return None
    p50 = value.get("estimate")
    if p50 is None:
        return None
    return (
        _number(value.get("estimate10")),
        float(p50),
        _number(value.get("estimate90")),
    )


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
