"""Shared observation eligibility for stored scores and read-only comparisons."""

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from energy_optimizer.data_validation import (
    INVALID_ACTUAL_NEGATIVE_HOUSEHOLD_DEMAND,
    INVALID_NEGATIVE_HOUSEHOLD_DEMAND,
    materially_negative_household_demand,
)


@dataclass(frozen=True)
class ActualEvidence:
    actual_value: float | None
    actual_available: bool
    health_eligible: bool
    missing_reason: str | None
    eligible_sample_count: int
    exclusion_reason: str | None = None


def evaluate_actual_rows(rows: Sequence[Mapping[str, Any]]) -> ActualEvidence:
    """Preserve the scorer's raw evidence and baseline eligibility semantics."""
    available = [
        float(r["baseline_house_consumption_w"])
        for r in rows
        if r["baseline_house_consumption_w"] is not None
    ]
    invalid = any(
        materially_negative_household_demand(r["house_consumption_w"])
        or r["baseline_exclusion_reason"] == INVALID_NEGATIVE_HOUSEHOLD_DEMAND
        for r in rows
    )
    eligible = [
        float(r["baseline_house_consumption_w"])
        for r in rows
        if r["baseline_house_consumption_w"] is not None
        and not materially_negative_household_demand(r["house_consumption_w"])
        and r["telemetry_is_healthy"]
        and r["baseline_training_eligible"]
    ]
    negative = [
        float(r["house_consumption_w"])
        for r in rows
        if materially_negative_household_demand(r["house_consumption_w"])
    ]
    actual = (
        sum(negative) / len(negative)
        if invalid and negative
        else sum(available) / len(available) if available else None
    )
    reason = None
    if not rows:
        reason = "no_observation"
    elif invalid:
        reason = INVALID_ACTUAL_NEGATIVE_HOUSEHOLD_DEMAND
    elif not available:
        reason = "actual_value_missing"
    elif not eligible:
        reason = "actual_unhealthy_or_ineligible"
    valid = bool(eligible) and not invalid
    return ActualEvidence(
        actual_value=sum(eligible) / len(eligible) if valid else actual,
        actual_available=actual is not None,
        health_eligible=valid,
        missing_reason=reason,
        eligible_sample_count=len(eligible),
        exclusion_reason=next(
            (
                r["baseline_exclusion_reason"]
                for r in rows
                if r["baseline_exclusion_reason"]
            ),
            None,
        ),
    )


def interval_rows(
    rows: Sequence[Mapping[str, Any]],
    slots: Sequence[datetime],
    start: datetime,
    end: datetime,
    *,
    full_five_minute: bool,
) -> Sequence[Mapping[str, Any]]:
    """Select exact target slots for v1, or the legacy half-open interval."""
    first = bisect_left(slots, start)
    if full_five_minute:
        return (
            rows[first : first + 1]
            if first < len(slots) and slots[first] == start
            else []
        )
    return rows[first : bisect_left(slots, end)]
