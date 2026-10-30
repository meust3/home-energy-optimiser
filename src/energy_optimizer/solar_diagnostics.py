"""Cautious daily Solcast-versus-realised-PV diagnostics."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

EXPECTED_DAILY_SLOTS = 288


def calculate_solar_diagnostics(
    rows: list[dict[str, Any]],
    *,
    coverage_percent: float = 95,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = now or datetime.now(UTC)
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
        day_start = datetime.combine(
            day, time.min, tzinfo=values[0]["observed_at_local"].tzinfo
        )
        day_complete = current >= day_start + timedelta(days=1)
        forecast = None
        snapshot_at = None
        for row in values:
            candidate = _forecast_values(row.get("solcast_today_kwh_json"))
            if candidate is not None:
                forecast = candidate
                snapshot_at = row["observed_at_local"]
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
            day_complete
            and coverage >= coverage_percent
            and forecast is not None
            and actual is not None
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
                "day_complete": day_complete,
                "comparison_status": (
                    "complete_day"
                    if sufficient
                    else (
                        "incomplete_day"
                        if not day_complete
                        else "insufficient_coverage_or_forecast"
                    )
                ),
                "forecast_snapshot_observed_at": snapshot_at,
                "forecast_snapshot_policy": "first_available_local_day",
                "forecast_issue_time_verified": False,
                "error_convention": "actual_minus_forecast",
                "actual_pv_kwh": actual,
                "solcast_p10_kwh": forecast[0] if forecast else None,
                "solcast_p50_kwh": forecast[1] if forecast else None,
                "solcast_p90_kwh": forecast[2] if forecast else None,
                "actual_minus_p50_kwh": (actual - forecast[1] if sufficient else None),
                "actual_in_solcast_range": (
                    forecast[0] is not None
                    and forecast[2] is not None
                    and forecast[0] <= actual <= forecast[2]
                    if sufficient
                    else None
                ),
                "p50_percentage_error": (
                    (forecast[1] - actual) / actual * 100
                    if sufficient and actual > 0
                    else None
                ),
                "signed_percentage_error_percent": (
                    (actual - forecast[1]) / actual * 100
                    if sufficient and actual > 0
                    else None
                ),
                "legacy_p50_percentage_error_convention": "forecast_minus_actual",
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
    # Current persistence is explicitly normalized to kWh.  Older rows written
    # during the transition may retain the legacy key names in this normalized
    # column, so those are accepted only after the unit provenance is considered.
    p50 = value.get("estimate_kwh")
    normalized_p50 = _number(p50)
    if normalized_p50 is not None:
        return (
            _number(value.get("estimate10_kwh")),
            normalized_p50,
            _number(value.get("estimate90_kwh")),
        )
    p50 = value.get("estimate")
    legacy_p50 = _number(p50)
    if legacy_p50 is None:
        return None
    source_unit = str(
        value.get("source_unit") or value.get("unit_of_measurement") or ""
    ).casefold()
    factor = 0.001 if source_unit == "wh" else 1.0
    return (
        _scaled(value.get("estimate10"), factor),
        legacy_p50 * factor,
        _scaled(value.get("estimate90"), factor),
    )


def _scaled(value: Any, factor: float) -> float | None:
    number = _number(value)
    return number * factor if number is not None else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
