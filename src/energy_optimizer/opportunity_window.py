"""Find the next advisory battery-replenishment opportunity."""

import json
from datetime import datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel


class ReplenishmentOpportunity(BaseModel):
    opportunity_type: Literal["solar", "cheap_grid", "both", "overnight_reserve"]
    expected_start_local: datetime
    expected_end_local: datetime
    confidence: Literal["low", "medium", "high"]
    explanation: str


def find_next_opportunity(
    observation: dict[str, Any],
    *,
    now_local: datetime,
    cheap_import_price_per_kwh: float,
    solar_surplus_threshold_kwh: float,
    max_horizon_hours: int,
) -> ReplenishmentOpportunity:
    """Choose the earliest plausible solar or cheap-grid opportunity."""
    if now_local.tzinfo is None:
        raise ValueError("opportunity time must be timezone-aware")
    horizon = now_local + timedelta(hours=max_horizon_hours)
    solar = _solar_window(
        observation,
        now_local=now_local,
        threshold_kwh=solar_surplus_threshold_kwh,
    )
    grid = _cheap_grid_window(
        observation,
        now_local=now_local,
        threshold=cheap_import_price_per_kwh,
    )
    candidates = [item for item in (solar, grid) if item and item[0] <= horizon]
    if not candidates:
        return ReplenishmentOpportunity(
            opportunity_type="overnight_reserve",
            expected_start_local=horizon,
            expected_end_local=horizon,
            confidence="low",
            explanation="No qualifying solar or cheap import window was available.",
        )
    candidates.sort(key=lambda item: item[0])
    start, end, kind, confidence, explanation = candidates[0]
    if len(candidates) > 1:
        other = candidates[1]
        if max(start, other[0]) < min(end, other[1]):
            kind = "both"
            start = min(start, other[0])
            end = max(end, other[1])
            confidence = min(confidence, other[3], key=_confidence_rank)
            explanation = f"Solar and cheap-import windows overlap. {explanation}"
    return ReplenishmentOpportunity(
        opportunity_type=kind,
        expected_start_local=start,
        expected_end_local=end,
        confidence=confidence,
        explanation=explanation,
    )


def _solar_window(
    observation: dict[str, Any], *, now_local: datetime, threshold_kwh: float
) -> tuple[datetime, datetime, str, str, str] | None:
    remaining = _summary_estimate(observation.get("solcast_remaining_today_kwh_json"))
    tomorrow = _summary_estimate(observation.get("solcast_tomorrow_kwh_json"))
    pv = observation.get("pv_power_w") or 0.0
    house = observation.get("house_consumption_w") or 0.0
    sunset = datetime.combine(now_local.date(), time(17, 30), now_local.tzinfo)
    if remaining is not None and remaining >= threshold_kwh and now_local < sunset:
        start = now_local if pv > house else min(now_local + timedelta(hours=1), sunset)
        return (
            start,
            sunset,
            "solar",
            "medium",
            f"Solcast reports {remaining:.2f} kWh remaining today; "
            "timing is heuristic.",
        )
    if tomorrow is not None and tomorrow >= threshold_kwh:
        day = now_local.date() + timedelta(days=1)
        return (
            datetime.combine(day, time(7), now_local.tzinfo),
            datetime.combine(day, time(17, 30), now_local.tzinfo),
            "solar",
            "medium",
            f"Solcast reports {tomorrow:.2f} kWh tomorrow; timing is heuristic.",
        )
    return None


def _cheap_grid_window(
    observation: dict[str, Any], *, now_local: datetime, threshold: float
) -> tuple[datetime, datetime, str, str, str] | None:
    raw = observation.get("amber_import_forecast_json")
    try:
        intervals = json.loads(raw) if raw else []
    except (TypeError, json.JSONDecodeError):
        return None
    candidates = []
    for interval in intervals:
        price = interval.get("per_kwh")
        start = _aware_datetime(interval.get("start_time"), now_local)
        end = _aware_datetime(interval.get("end_time"), now_local)
        if price is None or start is None or end is None or end <= now_local:
            continue
        if float(price) <= threshold:
            candidates.append((max(start, now_local), end, float(price)))
    if not candidates:
        return None
    start, end, price = min(candidates, key=lambda item: item[0])
    return (
        start,
        end,
        "cheap_grid",
        "high",
        f"Amber import price is {price:.3f}/kWh, at or below {threshold:.3f}/kWh.",
    )


def _summary_estimate(raw: Any) -> float | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    estimate = value.get("estimate_kwh")
    return float(estimate) if isinstance(estimate, (int, float)) else None


def _aware_datetime(value: Any, now_local: datetime) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(now_local.tzinfo)


def _confidence_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}[value]
