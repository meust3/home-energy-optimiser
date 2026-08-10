"""Auditable reprocessing of stored raw observations into derived fields."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.energy_flow import derive_energy_flow, derive_event_labels
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
    "event_labels_json",
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
    "event_labels_json",
    "event_label_confidence",
    "event_label_evidence_json",
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
    rows_eligible_for_reprocessing: int = Field(ge=0)
    rows_becoming_baseline_eligible: int = Field(ge=0)
    rows_remaining_ineligible: int = Field(ge=0)
    exclusion_reasons: dict[str, int]
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
    now: datetime | None = None,
) -> ReprocessingReport:
    """Recompute derivations; dry-run by default and never alter raw columns."""
    _validate_conventions(config)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    rows = _read_rows(historian)
    results = [_derive(dict(row), config, timestamp) for row in rows]
    audit_added = 0
    if apply:
        audit_added = historian.apply_reprocessing_results(
            results,
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
        for result in results
        if result["derived"]["balance_residual_w"] is not None
    ]
    reasons = Counter(
        result["derived"]["baseline_exclusion_reason"]
        for result in results
        if not result["derived"]["baseline_training_eligible"]
    )
    eligible = sum(result["can_derive"] for result in results)
    becoming = sum(
        result["derived"]["baseline_training_eligible"]
        and not bool(result["original"].get("baseline_training_eligible"))
        for result in results
    )
    return ReprocessingReport(
        applied=apply,
        model_version=DERIVATION_MODEL_VERSION,
        rows_examined=len(results),
        rows_eligible_for_reprocessing=eligible,
        rows_becoming_baseline_eligible=becoming,
        rows_remaining_ineligible=len(results)
        - sum(result["derived"]["baseline_training_eligible"] for result in results),
        exclusion_reasons={str(key): value for key, value in sorted(reasons.items())},
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
    row: dict[str, Any], config: CollectorConfig, timestamp: datetime
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
    labels, label_confidence, label_evidence = derive_event_labels(
        flow,
        ev_active=_bool_or_none(row.get("ev_charging_active")),
        ev_power_w=row.get("ev_power_w"),
        tolerance_w=config.balance_tolerance_w,
    )
    can_derive = None not in raw_values and flow.sign_convention_status == "confirmed"
    exclusion: str | None = None
    if not can_derive:
        exclusion = "required_raw_telemetry_missing"
    elif not bool(row.get("telemetry_is_healthy")):
        exclusion = "data_quality_insufficient"
    elif flow.balance_residual_w is None or (
        abs(flow.balance_residual_w) > config.balance_tolerance_w
    ):
        exclusion = "balance_residual_outside_tolerance"
    elif bool(row.get("ev_charging_active")) and row.get("ev_power_w") is None:
        exclusion = "ev_active_power_unknown"
    baseline, baseline_eligible, baseline_reason = calculate_baseline_load(
        row.get("house_consumption_w"),
        ev_charging_active=_bool_or_none(row.get("ev_charging_active")),
        ev_power_w=row.get("ev_power_w"),
    )
    if exclusion is not None:
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
        "event_labels_json": _json(labels),
        "event_label_confidence": label_confidence,
        "event_label_evidence_json": _json(label_evidence),
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
    return {
        "slot_utc": row["slot_utc"],
        "original": row,
        "derived": derived,
        "metadata": metadata,
        "fingerprint": fingerprint,
        "can_derive": can_derive,
        "originally_legacy": originally_legacy,
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
