"""Auditable reprocessing of stored raw observations into derived fields."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.energy_flow import derive_energy_flow
from energy_optimizer.ev import calculate_baseline_load
from energy_optimizer.models import CollectorConfig

DERIVATION_MODEL_VERSION = "energy-flow-v1"
RAW_COLUMNS = (
    "slot_utc",
    "pv_power_w",
    "house_consumption_w",
    "grid_power_w",
    "battery_power_w",
    "telemetry_is_healthy",
    "ev_charging_active",
    "ev_power_w",
    "ev_source",
    "ev_session_id",
    "sign_convention_status",
    "grid_import_power_w",
    "grid_export_power_w",
    "battery_charge_power_w",
    "battery_discharge_power_w",
    "solar_to_house_power_w",
    "solar_to_battery_power_w",
    "solar_to_grid_power_w",
    "battery_to_house_power_w",
    "battery_to_grid_power_w",
    "grid_to_house_power_w",
    "grid_to_battery_power_w",
    "balance_residual_w",
    "baseline_house_consumption_w",
    "baseline_training_eligible",
    "baseline_exclusion_reason",
    "flow_is_healthy",
    "flow_health_score",
)
DERIVED_UPDATE_COLUMNS = (
    "grid_import_power_w",
    "grid_export_power_w",
    "battery_charge_power_w",
    "battery_discharge_power_w",
    "solar_to_house_power_w",
    "solar_to_battery_power_w",
    "solar_to_grid_power_w",
    "battery_to_house_power_w",
    "battery_to_grid_power_w",
    "grid_to_house_power_w",
    "grid_to_battery_power_w",
    "balance_residual_w",
    "sign_convention_status",
    "sign_convention_confidence",
    "sign_supporting_sample_count",
    "baseline_house_consumption_w",
    "baseline_training_eligible",
    "baseline_exclusion_reason",
    "flow_is_healthy",
    "flow_health_score",
    "derivation_model_version",
    "reprocessed_at_utc",
    "derivation_metadata_json",
    "originally_legacy",
)


class ReprocessingReport(BaseModel):
    applied: bool
    model_version: str
    rows_examined: int = Field(ge=0)
    rows_repairable: int = Field(ge=0)
    rows_unchanged: int = Field(ge=0)
    rows_excluded: int = Field(ge=0)
    rows_eligible_for_reprocessing: int = Field(ge=0)
    rows_becoming_baseline_eligible: int = Field(ge=0)
    rows_remaining_ineligible: int = Field(ge=0)
    exclusion_reasons: dict[str, int]
    row_exclusion_reasons: dict[str, int]
    residual_sample_count: int = Field(ge=0)
    mean_absolute_residual_w: float | None
    median_absolute_residual_w: float | None
    maximum_absolute_residual_w: float | None
    rows_exceeding_tolerance: int = Field(ge=0)
    audit_records_added: int = Field(ge=0)


def reprocess_observations(
    historian: DatabaseRepository,
    config: CollectorConfig,
    *,
    apply: bool = False,
    backup_verified: bool = False,
    override_confirmed: bool = False,
    now: datetime | None = None,
) -> ReprocessingReport:
    """Recompute derivations; dry-run by default and never alter raw columns."""
    _validate_conventions(config)
    if apply and not backup_verified:
        raise ValueError("--apply requires a verified, restore-tested database backup")
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    rows = _read_rows(historian)
    results = [
        _derive(
            dict(row),
            config,
            timestamp,
            override_confirmed=override_confirmed,
        )
        for row in rows
    ]
    repairable = [
        result for result in results if result["repair_status"] == "repairable"
    ]
    audit_added = 0
    if apply:
        audit_added = historian.apply_reprocessing_results(
            repairable,
            model_version=DERIVATION_MODEL_VERSION,
            conventions={
                "grid": config.grid_power_sign_convention,
                "battery": config.battery_power_sign_convention,
                "confidence": config.sign_convention_confidence,
                "supporting_samples": config.sign_convention_supporting_samples,
            },
            timestamp=timestamp,
            update_columns=DERIVED_UPDATE_COLUMNS,
        )
    residuals = [
        abs(result["derived"]["balance_residual_w"])
        for result in repairable
        if result["derived"]["balance_residual_w"] is not None
    ]
    reasons = Counter(
        result["derived"]["baseline_exclusion_reason"]
        for result in repairable
        if not result["derived"]["baseline_training_eligible"]
    )
    eligible = len(repairable)
    becoming = sum(
        result["derived"]["baseline_training_eligible"]
        and not bool(result["original"].get("baseline_training_eligible"))
        for result in repairable
    )
    row_exclusions = Counter(
        str(result["repair_exclusion_reason"])
        for result in results
        if result["repair_status"] == "excluded"
    )
    return ReprocessingReport(
        applied=apply,
        model_version=DERIVATION_MODEL_VERSION,
        rows_examined=len(results),
        rows_repairable=len(repairable),
        rows_unchanged=sum(
            result["repair_status"] == "unchanged" for result in results
        ),
        rows_excluded=sum(result["repair_status"] == "excluded" for result in results),
        rows_eligible_for_reprocessing=eligible,
        rows_becoming_baseline_eligible=becoming,
        rows_remaining_ineligible=len(repairable)
        - sum(result["derived"]["baseline_training_eligible"] for result in repairable),
        exclusion_reasons={str(key): value for key, value in sorted(reasons.items())},
        row_exclusion_reasons={
            str(key): value for key, value in sorted(row_exclusions.items())
        },
        residual_sample_count=len(residuals),
        mean_absolute_residual_w=(
            round(sum(residuals) / len(residuals), 3) if residuals else None
        ),
        median_absolute_residual_w=round(median(residuals), 3) if residuals else None,
        maximum_absolute_residual_w=round(max(residuals), 3) if residuals else None,
        rows_exceeding_tolerance=sum(
            value > config.balance_tolerance_w for value in residuals
        ),
        audit_records_added=audit_added,
    )


def _read_rows(historian: DatabaseRepository) -> list[Any]:
    existing = set(historian.observation_columns())
    columns = RAW_COLUMNS + (
        ("originally_legacy",) if "originally_legacy" in existing else ()
    )
    return historian.reprocessing_rows(columns)


def _derive(
    row: dict[str, Any],
    config: CollectorConfig,
    timestamp: datetime,
    *,
    override_confirmed: bool,
) -> dict[str, Any]:
    raw_values = tuple(
        row.get(name)
        for name in (
            "pv_power_w",
            "house_consumption_w",
            "grid_power_w",
            "battery_power_w",
        )
    )
    flow = derive_energy_flow(
        pv_power_w=row.get("pv_power_w"),
        house_consumption_w=row.get("house_consumption_w"),
        grid_power_w=row.get("grid_power_w"),
        battery_power_w=row.get("battery_power_w"),
        config=config,
    )
    can_derive = None not in raw_values and flow.sign_convention_status == "confirmed"
    manual_annotation = row.get("ev_source") == "manual_annotation" or bool(
        row.get("ev_session_id")
    )
    exclusion: str | None = None
    if not can_derive:
        exclusion = "required_raw_telemetry_missing"
    elif not bool(row.get("telemetry_is_healthy")):
        exclusion = "data_quality_insufficient"
    elif flow.balance_residual_w is None or (
        abs(flow.balance_residual_w) > config.balance_tolerance_w
    ):
        exclusion = "balance_residual_outside_tolerance"
    elif (
        not manual_annotation
        and bool(row.get("ev_charging_active"))
        and row.get("ev_power_w") is None
    ):
        exclusion = (
            "known_ev_session_without_ac_power"
            if row.get("ev_source") == "byd_vehicle_cloud"
            else "ev_active_power_unknown"
        )
    if manual_annotation:
        baseline = row.get("baseline_house_consumption_w")
        baseline_eligible = bool(row.get("baseline_training_eligible"))
        baseline_reason = row.get("baseline_exclusion_reason")
    else:
        baseline, baseline_eligible, baseline_reason = calculate_baseline_load(
            row.get("house_consumption_w"),
            ev_charging_active=_bool_or_none(row.get("ev_charging_active")),
            ev_power_w=row.get("ev_power_w"),
            active_without_power_reason=(
                "known_ev_session_without_ac_power"
                if row.get("ev_source") == "byd_vehicle_cloud"
                else "ev_active_power_unknown"
            ),
        )
    if exclusion is not None and not manual_annotation:
        baseline_eligible = False
        baseline_reason = exclusion
    residual_ok = (
        can_derive
        and flow.balance_residual_w is not None
        and abs(flow.balance_residual_w) <= config.balance_tolerance_w
    )
    flow_healthy = bool(residual_ok)
    originally_legacy = bool(row.get("originally_legacy")) or (
        row.get("sign_convention_status") != "confirmed"
    )
    metadata = {
        "model_version": DERIVATION_MODEL_VERSION,
        "reprocessed_at_utc": timestamp.isoformat(),
        "grid_power_sign": config.grid_power_sign_convention,
        "battery_power_sign": config.battery_power_sign_convention,
        "sign_confidence": config.sign_convention_confidence,
        "supporting_sample_count": config.sign_convention_supporting_samples,
        "originally_legacy": originally_legacy,
        "ev_limitation": (
            "No direct EV telemetry; measured house load preserved without subtraction."
            if row.get("ev_charging_active") is None and row.get("ev_power_w") is None
            else None
        ),
    }
    derived = {
        **{
            name: getattr(flow, name)
            for name in DERIVED_UPDATE_COLUMNS
            if hasattr(flow, name)
        },
        "sign_convention_status": flow.sign_convention_status,
        "sign_convention_confidence": config.sign_convention_confidence,
        "sign_supporting_sample_count": config.sign_convention_supporting_samples,
        "baseline_house_consumption_w": baseline,
        "baseline_training_eligible": int(baseline_eligible),
        "baseline_exclusion_reason": baseline_reason,
        "flow_is_healthy": int(flow_healthy),
        "flow_health_score": 100 if flow_healthy else 80,
        "derivation_model_version": DERIVATION_MODEL_VERSION,
        "reprocessed_at_utc": timestamp.isoformat(),
        "derivation_metadata_json": _json(metadata),
        "originally_legacy": int(originally_legacy),
    }
    fingerprint_payload = {
        "raw": {
            name: row.get(name)
            for name in (
                "pv_power_w",
                "house_consumption_w",
                "grid_power_w",
                "battery_power_w",
                "telemetry_is_healthy",
                "ev_charging_active",
                "ev_power_w",
            )
        },
        "conventions": {
            key: value for key, value in metadata.items() if key != "reprocessed_at_utc"
        },
    }
    fingerprint = hashlib.sha256(_json(fingerprint_payload).encode()).hexdigest()
    primary_directions = (
        "grid_import_power_w",
        "grid_export_power_w",
        "battery_charge_power_w",
        "battery_discharge_power_w",
    )
    confirmed = row.get("sign_convention_status") == "confirmed"
    normalized_missing = any(row.get(name) is None for name in primary_directions)
    if not can_derive:
        repair_status = "excluded"
        repair_exclusion_reason = "required_raw_telemetry_missing"
    elif confirmed and not override_confirmed:
        if normalized_missing:
            repair_status = "excluded"
            repair_exclusion_reason = "confirmed_row_requires_explicit_override"
        else:
            repair_status = "unchanged"
            repair_exclusion_reason = None
    else:
        repair_status = "repairable"
        repair_exclusion_reason = None
    return {
        "slot_utc": row["slot_utc"],
        "original": row,
        "derived": derived,
        "metadata": metadata,
        "fingerprint": fingerprint,
        "can_derive": can_derive,
        "originally_legacy": originally_legacy,
        "repair_status": repair_status,
        "repair_exclusion_reason": repair_exclusion_reason,
    }


def _validate_conventions(config: CollectorConfig) -> None:
    if config.grid_power_sign_convention == "unknown" or (
        config.battery_power_sign_convention == "unknown"
    ):
        raise ValueError("Confirmed grid and battery sign conventions are required")
    if config.sign_convention_confidence not in {"medium", "high"}:
        raise ValueError("Sign convention confidence must be medium or high")


def _bool_or_none(value: Any) -> bool | None:
    return None if value is None else bool(value)


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
