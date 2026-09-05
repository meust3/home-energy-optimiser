"""Read-only replay of an immutable shadow-decision boundary."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from energy_optimizer.shadow_decisioning import (
    CalibrationGate,
    ShadowDecisionConfig,
    evaluate_shadow_decision,
)
from energy_optimizer.timestamps import aware_datetime, json_safe, native_json


def replay_persisted_shadow_decision(
    repository: Any, decision_run_id: int
) -> dict[str, Any]:
    """Re-evaluate one stored boundary using only its time-bounded inputs.

    The repository is queried only through read-only methods.  Calibration and
    configuration are reconstructed from the immutable decision snapshot so
    evidence that arrived after the boundary cannot leak into the replay.
    """
    stored = repository.shadow_decision_detail_read_only(decision_run_id)
    if stored is None:
        raise LookupError(f"shadow decision {decision_run_id} does not exist")
    forecast = repository.forecast_run(int(stored["forecast_run_id"]))
    reserve = repository.reserve_audit_read_only(int(stored["reserve_run_id"]))
    created_at = _timestamp(stored["created_at_utc"])
    observation = repository.observation_as_of_read_only(created_at)
    if forecast is None or reserve is None or observation is None:
        raise LookupError("immutable replay inputs are no longer available")

    input_snapshot = _mapping(stored.get("input_snapshot_json"))
    constraint_snapshot = _mapping(stored.get("constraint_snapshot_json"))
    assumption_snapshot = _mapping(stored.get("assumption_snapshot_json"))
    calibration_value = _mapping(input_snapshot.get("calibration"))
    assumptions = {
        str(item.get("name")): item.get("value")
        for item in assumption_snapshot.get("items", [])
        if isinstance(item, dict) and item.get("name")
    }
    calibration = CalibrationGate(
        identity={
            str(key): str(value)
            for key, value in _mapping(calibration_value.get("identity")).items()
        },
        identity_matches=bool(calibration_value.get("identity_matches")),
        status=str(calibration_value.get("status") or "insufficient_evidence"),
        independent_evidence_sufficient=bool(
            calibration_value.get("independent_evidence_sufficient")
        ),
        required_horizons_present=bool(
            calibration_value.get("required_horizons_present")
        ),
        quality_blocks=tuple(calibration_value.get("quality_blocks") or ()),
        rollup_backfill_complete=bool(
            calibration_value.get("rollup_backfill_complete")
        ),
    )
    interval_minutes = max(
        int(
            (
                _timestamp(stored["selected_end_utc"])
                - _timestamp(stored["decision_boundary_utc"])
            ).total_seconds()
            // 60
        ),
        5,
    )
    config = ShadowDecisionConfig(
        enabled=True,
        allow_non_hold_recommendations=(
            "non_hold_selection_disabled" not in (stored.get("reason_codes_json") or ())
        ),
        decision_interval_minutes=interval_minutes,
        minimum_expected_value_aud=float(
            assumptions.get("minimum_expected_gross_value") or 0.25
        ),
        maximum_export_power_w=float(
            constraint_snapshot.get("maximum_export_power_w") or 0.0
        ),
        maximum_discharge_power_w=float(
            constraint_snapshot.get("maximum_discharge_power_w") or 0.0
        ),
        import_limit_w=float(constraint_snapshot.get("import_limit_w") or 0.0),
        discharge_efficiency=float(assumptions.get("discharge_efficiency") or 0.95),
    )
    collector_config = SimpleNamespace(
        usable_battery_capacity_kwh=float(
            assumptions.get("usable_battery_capacity") or 40.0
        ),
        battery_charge_efficiency=float(assumptions.get("charge_efficiency") or 0.95),
        reserve_max_charge_power_w=float(
            assumptions.get("maximum_grid_charge_power") or 9999.0
        ),
        battery_soc_freshness_minutes=10,
    )
    replay = evaluate_shadow_decision(
        decision_boundary_utc=_timestamp(stored["decision_boundary_utc"]),
        created_at_utc=created_at,
        observation=observation,
        forecast_run=forecast,
        reserve_run=reserve,
        calibration=calibration,
        collector_config=collector_config,
        config=config,
        synthetic_replay=True,
    )
    return json_safe(
        {
            **asdict(replay),
            "synthetic_replay": True,
            "source_decision_run_id": decision_run_id,
            "source_input_hash": stored["input_hash"],
            "replay_input_hash": replay.input_hash,
            "database_write_performed": False,
        }
    )


def _mapping(value: Any) -> dict[str, Any]:
    parsed = native_json(value)
    return dict(parsed) if isinstance(parsed, dict) else {}


def _timestamp(value: datetime | str) -> datetime:
    return aware_datetime(value, assume_utc=True)
