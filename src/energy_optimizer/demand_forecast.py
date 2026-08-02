"""Explainable household-demand forecast for battery reserve estimation."""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field


class DemandForecast(BaseModel):
    start_local: datetime
    end_local: datetime
    expected_energy_kwh: float = Field(ge=0)
    history_sample_count: int = Field(ge=0)
    historical_slot_count: int = Field(ge=0)
    fallback_slot_count: int = Field(ge=0)
    recent_adjustment: float = Field(gt=0)
    confidence: Literal["low", "medium", "high"]
    explanation: str


def forecast_household_demand(
    rows: list[Any],
    *,
    start_local: datetime,
    end_local: datetime,
    minimum_samples: int,
    fallback_kw: float,
    recent_days: int = 7,
) -> DemandForecast:
    """Integrate weekday/five-minute baseline power until the opportunity window."""
    if start_local.tzinfo is None or end_local.tzinfo is None:
        raise ValueError("demand forecast datetimes must be timezone-aware")
    if end_local < start_local:
        raise ValueError("demand forecast end must not precede start")

    grouped: dict[tuple[int, int], list[float]] = defaultdict(list)
    parsed: list[tuple[datetime, float]] = []
    for row in rows:
        value = row["house_consumption_w"]
        if value is None:
            continue
        local = datetime.fromisoformat(row["observed_at_local"])
        power_kw = max(float(value), 0.0) / 1000
        grouped[(local.weekday(), local.hour * 12 + local.minute // 5)].append(power_kw)
        parsed.append((local, power_kw))

    recent_cutoff = start_local - timedelta(days=recent_days)
    recent_values = [power for local, power in parsed if local >= recent_cutoff]
    all_values = [power for _, power in parsed]
    if recent_values and all_values:
        recent_adjustment = _clamp(
            (sum(recent_values) / len(recent_values))
            / max(sum(all_values) / len(all_values), 0.05),
            0.75,
            1.25,
        )
    else:
        recent_adjustment = 1.0

    current = _floor_five_minutes(start_local)
    energy = 0.0
    historical_slots = 0
    fallback_slots = 0
    while current < end_local:
        samples = grouped[(current.weekday(), current.hour * 12 + current.minute // 5)]
        if len(samples) >= minimum_samples:
            power_kw = (sum(samples) / len(samples)) * recent_adjustment
            historical_slots += 1
        else:
            power_kw = fallback_kw
            fallback_slots += 1
        period_end = min(current + timedelta(minutes=5), end_local)
        hours = (period_end - max(current, start_local)).total_seconds() / 3600
        if hours > 0:
            energy += power_kw * hours
        current += timedelta(minutes=5)

    total_slots = historical_slots + fallback_slots
    coverage = historical_slots / total_slots if total_slots else 0.0
    distinct_days = len({local.date() for local, _ in parsed})
    if coverage >= 0.8 and distinct_days >= 21:
        confidence = "high"
    elif coverage >= 0.4 and distinct_days >= 7:
        confidence = "medium"
    else:
        confidence = "low"
    explanation = (
        f"{historical_slots}/{total_slots} forecast slots used weekday history; "
        f"{fallback_slots} used the {fallback_kw:g} kW fallback. "
        f"Recent adjustment was {recent_adjustment:.2f}."
    )
    return DemandForecast(
        start_local=start_local,
        end_local=end_local,
        expected_energy_kwh=round(max(energy, 0.0), 3),
        history_sample_count=len(parsed),
        historical_slot_count=historical_slots,
        fallback_slot_count=fallback_slots,
        recent_adjustment=round(recent_adjustment, 3),
        confidence=confidence,
        explanation=explanation,
    )


def _floor_five_minutes(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 5) * 5, second=0, microsecond=0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))
