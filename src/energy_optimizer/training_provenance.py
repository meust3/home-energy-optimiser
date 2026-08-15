"""Sample-level EV provenance for explainable demand-model training."""

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from energy_optimizer.timestamps import aware_datetime

TrainingCohort = Literal[
    "verified_non_ev",
    "verified_ev_excluded",
    "direct_ev_separated",
    "manual_historical_ev",
    "pre_ev_telemetry_unknown",
    "suspected_historical_ev",
    "unknown",
]
TrainingPolicy = Literal["legacy_all_eligible", "verified_preferred", "verified_only"]

VERIFIED_CLEAN_COHORTS: frozenset[str] = frozenset(
    {"verified_non_ev", "direct_ev_separated"}
)


class TrainingProvenanceSummary(BaseModel):
    training_policy: TrainingPolicy
    training_sample_count: int = Field(ge=0)
    verified_non_ev_count: int = Field(ge=0)
    verified_ev_excluded_count: int = Field(ge=0)
    direct_ev_separated_count: int = Field(ge=0)
    manual_ev_excluded_count: int = Field(ge=0)
    pre_ev_unknown_count: int = Field(ge=0)
    suspected_unreviewed_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    verified_share: float = Field(ge=0, le=1)
    unverified_share: float = Field(ge=0, le=1)
    first_verified_ev_telemetry_utc: datetime | None = None
    verified_history_start_utc: datetime | None = None
    unidentified_ev_contamination_risk: bool
    contamination_reason: str | None


def classify_training_cohort(row: dict[str, Any]) -> TrainingCohort:
    """Classify one row without inferring EV truth from load magnitude."""
    source = str(row.get("ev_source") or "none")
    reason = str(row.get("baseline_exclusion_reason") or "")
    fresh = row.get("ev_telemetry_fresh") is True
    active = row.get("ev_charging_active")
    confidence = str(row.get("ev_detection_confidence") or "")
    direct_power = row.get("ev_power_w") is not None
    if source == "manual_annotation" or reason == "known_ev_session_without_ev_power":
        return "manual_historical_ev"
    if (
        row.get("suspected_historical_ev") is True
        or row.get("historical_ev_candidate") is True
    ):
        return "suspected_historical_ev"
    if direct_power and source == "charger":
        return "direct_ev_separated"
    authoritative = (
        source == "byd_vehicle_cloud"
        and fresh
        and confidence == "direct_fresh"
        and active in {True, False}
    )
    if authoritative and active is True:
        return "verified_ev_excluded"
    if authoritative and active is False:
        return "verified_non_ev"
    if source in {"none", "byd_vehicle_cloud", "home_assistant_helper"}:
        return "pre_ev_telemetry_unknown"
    return "unknown"


def verified_telemetry_boundary(rows: list[Any]) -> datetime | None:
    verified: list[datetime] = []
    for original in rows:
        row = dict(original)
        if classify_training_cohort(row) not in {
            "verified_non_ev",
            "verified_ev_excluded",
        }:
            continue
        value = row.get("slot_utc") or row.get("observed_at_utc")
        if value is not None:
            verified.append(aware_datetime(value).astimezone(UTC))
    return min(verified) if verified else None


def summarize_training_provenance(
    *,
    all_rows: list[Any],
    selected_rows: list[tuple[datetime, TrainingCohort]],
    policy: TrainingPolicy,
) -> TrainingProvenanceSummary:
    unique = {
        (timestamp.astimezone(UTC), cohort) for timestamp, cohort in selected_rows
    }
    counts = Counter(cohort for _, cohort in unique)
    total = len(unique)
    verified = sum(counts[name] for name in VERIFIED_CLEAN_COHORTS)
    unverified = total - verified
    boundary = verified_telemetry_boundary(all_rows)
    suspected = counts["suspected_historical_ev"]
    reason = None
    if suspected:
        reason = (
            "Unreviewed suspected historical EV candidates contributed to training."
        )
    elif unverified:
        reason = (
            "Selected training history includes observations without authoritative "
            "fresh EV state; unidentified charging may remain embedded."
        )
    return TrainingProvenanceSummary(
        training_policy=policy,
        training_sample_count=total,
        verified_non_ev_count=counts["verified_non_ev"],
        verified_ev_excluded_count=sum(
            classify_training_cohort(dict(row)) == "verified_ev_excluded"
            for row in all_rows
        ),
        direct_ev_separated_count=counts["direct_ev_separated"],
        manual_ev_excluded_count=sum(
            classify_training_cohort(dict(row)) == "manual_historical_ev"
            for row in all_rows
        ),
        pre_ev_unknown_count=counts["pre_ev_telemetry_unknown"],
        suspected_unreviewed_count=suspected,
        unknown_count=counts["unknown"],
        verified_share=round(verified / total, 4) if total else 0.0,
        unverified_share=round(unverified / total, 4) if total else 0.0,
        first_verified_ev_telemetry_utc=boundary,
        verified_history_start_utc=boundary,
        unidentified_ev_contamination_risk=unverified > 0,
        contamination_reason=reason,
    )
