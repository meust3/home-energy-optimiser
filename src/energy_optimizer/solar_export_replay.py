"""Replay time-bounded, local snapshots; no database or Home Assistant access."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime, time
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from energy_optimizer.shadow_decisioning import CalibrationGate
from energy_optimizer.solar_export import (
    POLICY_VERSION,
    ExportConfig,
    ForecastSlot,
    plan_morning_export,
)
from energy_optimizer.timestamps import aware_datetime, json_safe, native_json


def replay_solar_export_snapshot(
    snapshot: dict[str, Any],
    *,
    timezone_name: str = "Australia/Brisbane",
    export_before: time = time(12),
    recharge_deadline: time = time(17, 30),
    load_multiplier: float = 1.2,
    scenario_config: ExportConfig | None = None,
) -> dict[str, Any]:
    """Consume only forecasts visible at the recorded decision timestamp.

    Input contains decision, observation, linked forecast and linked reserve.
    Scored actuals and later observations are ignored. Missing interval solar is
    a blocker, not reconstructed from actual PV or daily totals.
    """
    if not isfinite(load_multiplier) or load_multiplier < 1:
        raise ValueError("load multiplier must be finite and at least one")
    decision = snapshot["decision"]
    observation = snapshot["observation"]
    forecast = snapshot["forecast"]
    reserve = snapshot["reserve"]
    created = _utc(decision["created_at_utc"])
    local = created.astimezone(ZoneInfo(timezone_name))
    before = datetime.combine(local.date(), export_before, local.tzinfo).astimezone(UTC)
    deadline = datetime.combine(
        local.date(), recharge_deadline, local.tzinfo
    ).astimezone(UTC)
    blockers = []
    observed = _utc(observation["observed_at_utc"])
    if not 0 <= (created - observed).total_seconds() <= 600:
        blockers.append("observation_stale_or_future")
    health = _mapping(observation.get("health_domains_json"))
    for name in ("telemetry", "price", "solar"):
        if _mapping(health.get(name)).get("is_healthy") is not True:
            blockers.append(f"{name}_health_unverified")
    if (
        _utc(forecast["created_at_utc"]) > created
        or _utc(reserve["evaluation_timestamp_utc"]) > created
    ):
        blockers.append("future_input_rejected")
    if forecast.get("id") != decision.get("forecast_run_id") or reserve.get(
        "id"
    ) != decision.get("reserve_run_id"):
        blockers.append("linked_identity_mismatch")
    if reserve.get("observation_is_stale") is not False:
        blockers.append("reserve_observation_unverified")
    ev = reserve.get("ev_demand_kwh")
    if ev is None or ev > 0:
        blockers.append("ev_required_energy_timing_unknown")

    calibration = _mapping(
        _mapping(decision.get("input_snapshot_json")).get("calibration")
    )
    gate = CalibrationGate(
        identity=calibration.get("identity") or {},
        identity_matches=calibration.get("identity_matches") is True,
        status=calibration.get("status") or "insufficient_evidence",
        independent_evidence_sufficient=calibration.get(
            "independent_evidence_sufficient"
        )
        is True,
        required_horizons_present=calibration.get("required_horizons_present") is True,
        quality_blocks=tuple(calibration.get("quality_blocks") or ()),
        rollup_backfill_complete=calibration.get("rollup_backfill_complete") is True,
    )
    metadata = _mapping(forecast.get("metadata_json"))
    actual_identity = {
        "forecast_type": forecast.get("forecast_type"),
        "model_version": forecast.get("model_version"),
        "alignment_version": metadata.get("alignment_version"),
        "training_policy": metadata.get("training_policy"),
    }
    calibrated = gate.permits_non_hold and actual_identity == gate.identity
    assumptions = {
        item["name"]: item.get("value")
        for item in _mapping(decision.get("assumption_snapshot_json")).get("items", [])
    }
    constraints = _mapping(decision.get("constraint_snapshot_json"))
    # Use persisted physical limits; missing stays unknown. An explicit scenario
    # is labelled hypothetical and never opens calibration or runtime gates.
    config = scenario_config or ExportConfig()
    if scenario_config is None:
        config = replace(
            config,
            capacity_kwh=float(reserve["usable_battery_capacity_kwh"]),
            maximum_charge_kw=float(assumptions.get("maximum_grid_charge_power") or 0)
            / 1000,
            maximum_discharge_kw=float(
                constraints.get("maximum_discharge_power_w") or 0
            )
            / 1000,
            maximum_export_kw=float(constraints.get("maximum_export_power_w") or 0)
            / 1000,
            charge_efficiency=float(
                assumptions.get("charge_efficiency") or config.charge_efficiency
            ),
            discharge_efficiency=float(
                assumptions.get("discharge_efficiency") or config.discharge_efficiency
            ),
        )
    if (
        min(
            config.maximum_charge_kw,
            config.maximum_discharge_kw,
            config.maximum_export_kw,
        )
        <= 0
    ):
        blockers.append("power_limits_unknown")
    energy = reserve.get("battery_energy_kwh")
    floor = reserve.get("recommended_reserve_kwh")
    if energy is None or floor is None:
        blockers.append("battery_or_reserve_missing")
    elif energy <= floor:
        blockers.append("no_energy_above_linked_reserve")

    solar_summary = _mapping(observation.get("solcast_today_kwh_json"))
    # Only a same-observation today series; never splice in a later forecast.
    solar = solar_summary.get("intervals") or []
    if not solar:
        blockers.append("timed_solar_forecast_missing")
    if solar_summary.get("interval_issues"):
        blockers.append("timed_solar_forecast_invalid")
    load = []
    for point in forecast.get("points") or []:
        if point.get("unit") != "W":
            blockers.append("household_forecast_unit_unsupported")
            continue
        expected = _number(point.get("expected_value"))
        upper = _number(point.get("upper_value"))
        value = (
            None
            if expected is None
            else max(expected * load_multiplier, upper or 0) / 1000
        )
        load.append(
            {
                "start": point["period_start_utc"],
                "end": point["period_end_utc"],
                "value": value,
            }
        )
    # The linked reserve holds the exact partial creation-to-first-full-slot
    # projection. Use only this prefix, never overwrite operational forecasts.
    first_full = min((_utc(row["start"]) for row in load), default=deadline)
    for point in (
        _mapping(reserve.get("demand_forecast_json")).get("slot_decisions") or []
    ):
        start, end = _utc(point["period_start_local"]), _utc(point["period_end_local"])
        if start == created and end <= first_full:
            expected = _number(point.get("estimated_power_kw"))
            load.insert(
                0,
                {
                    "start": start,
                    "end": end,
                    "value": (
                        expected * load_multiplier if expected is not None else None
                    ),
                },
            )
    series = {
        "solar": [
            {
                "start": p["period_start_utc"],
                "end": p["period_end_utc"],
                "value": p.get("estimate10_kw"),
            }
            for p in solar
        ],
        "load": load,
        "import": _prices(observation.get("amber_import_forecast_json")),
        "export": _prices(observation.get("amber_export_forecast_json")),
    }
    slots = []
    if created >= before or before > deadline:
        blockers.append("outside_morning_planning_window")
    elif solar:
        boundaries = {created, before, deadline}
        for rows in series.values():
            for row in rows:
                for key in ("start", "end"):
                    boundary = _utc(row[key])
                    if created < boundary < deadline:
                        boundaries.add(boundary)
        ordered = sorted(boundaries)
        if len(ordered) > 600:
            blockers.append("forecast_payload_exceeds_bound")
        else:
            try:
                for start, end in zip(ordered, ordered[1:], strict=False):
                    values = {
                        key: _cover(rows, start, end) for key, rows in series.items()
                    }
                    slots.append(
                        ForecastSlot(
                            start,
                            end,
                            values["solar"],
                            values["load"],
                            values["import"],
                            values["export"],
                        )
                    )
            except ValueError as exc:
                blockers.append(str(exc))

    provenance = {
        "source_decision_run_id": decision.get("id"),
        "source_input_hash": decision.get("input_hash"),
        "source_forecast_run_id": forecast.get("id"),
        "source_reserve_run_id": reserve.get("id"),
        "observation_timestamp_utc": observed,
        "calibration": calibration,
        "load_multiplier": load_multiplier,
        "hypothetical_limits": scenario_config is not None,
    }
    if blockers:
        if not calibrated:
            blockers.append("calibration_evidence_insufficient")
        return json_safe(
            {
                "policy_version": POLICY_VERSION,
                "synthetic_replay": True,
                "created_at_utc": created,
                "action": "HOLD",
                "status": "blocked",
                "no_command_issued": True,
                "database_write_performed": False,
                "execution_ready": False,
                "blockers": sorted(set(blockers)),
                "export_kwh": None,
                "export_windows": [],
                "expected_incremental_model_value_aud": None,
                "projected_recharge_at_utc": None,
                "assumptions": asdict(config),
                "provenance": provenance,
            }
        )
    result = plan_morning_export(
        created_at_utc=created,
        initial_energy_kwh=float(energy),
        reserve_kwh=float(floor),
        slots=slots,
        export_before_utc=before,
        recharge_deadline_utc=deadline,
        calibrated=calibrated,
        config=config,
    )
    if scenario_config is not None:
        result["action"] = "HOLD"
        result["status"] = "hypothetical_scenario"
        result["blockers"].append("hypothetical_limits_not_a_recommendation")
    result["provenance"] = json_safe(provenance)
    return result


def replay_report(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not 1 <= len(snapshots) <= 200:
        raise ValueError("provide 1-200 bounded local snapshots")
    results = [replay_solar_export_snapshot(snapshot) for snapshot in snapshots]
    return {
        "policy_version": POLICY_VERSION,
        "synthetic_replay": True,
        "no_command_issued": True,
        "database_write_performed": False,
        "snapshot_count": len(results),
        "blocker_counts": dict(
            Counter(reason for result in results for reason in result["blockers"])
        ),
        "results": results,
    }


def _mapping(value: Any) -> dict[str, Any]:
    parsed = native_json(value)
    return dict(parsed) if isinstance(parsed, dict) else {}


def _utc(value: datetime | str) -> datetime:
    return aware_datetime(value).astimezone(UTC)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _prices(value: Any) -> list[dict[str, Any]]:
    return [
        {"start": p["start_time"], "end": p["end_time"], "value": p.get("per_kwh")}
        for p in native_json(value) or []
    ]


def _cover(rows: list[dict[str, Any]], start: datetime, end: datetime) -> float:
    matches = [
        row for row in rows if _utc(row["start"]) <= start and _utc(row["end"]) >= end
    ]
    if len(matches) != 1:
        raise ValueError("forecast_gap_or_overlap")
    value = _number(matches[0]["value"])
    if value is None:
        raise ValueError("forecast_value_missing_or_invalid")
    return value
