"""Strictly advisory battery reserve estimation."""

import json
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from energy_optimizer.demand_forecast import DemandForecast, forecast_household_demand
from energy_optimizer.historian import Historian
from energy_optimizer.models import CollectorConfig
from energy_optimizer.opportunity_window import (
    ReplenishmentOpportunity,
    find_next_opportunity,
)


class ReserveEstimate(BaseModel):
    calculated_at_local: datetime
    battery_energy_kwh: float | None
    expected_house_demand_kwh: float = Field(ge=0)
    expected_ev_demand_kwh: float = Field(ge=0)
    technical_reserve_kwh: float = Field(ge=0)
    emergency_reserve_kwh: float = Field(ge=0)
    uncertainty_buffer_kwh: float = Field(ge=0)
    recommended_reserve_kwh: float = Field(ge=0)
    potentially_tradable_kwh: float = Field(ge=0)
    next_opportunity: ReplenishmentOpportunity
    demand_forecast: DemandForecast
    confidence: Literal["low", "medium", "high"]
    confidence_score: int = Field(ge=0, le=100)
    reasoning: str
    health: dict[str, Any]
    operational_context: dict[str, Any]
    ready_for_manual_review: bool
    command_issued: Literal[False] = False


def estimate_battery_reserve(
    historian: Historian,
    config: CollectorConfig,
    *,
    now: datetime | None = None,
) -> ReserveEstimate:
    """Estimate held and potentially tradable energy from local stored data only."""
    observation = historian.latest_observation_read_only()
    if observation is None:
        raise ValueError("No observations are available in the history database")
    local_zone = ZoneInfo(config.timezone)
    current = (now or datetime.now(local_zone)).astimezone(local_zone)
    opportunity = find_next_opportunity(
        observation,
        now_local=current,
        cheap_import_price_per_kwh=config.cheap_import_price_per_kwh,
        solar_surplus_threshold_kwh=config.solar_surplus_threshold_kwh,
        max_horizon_hours=config.reserve_max_horizon_hours,
    )
    rows = historian.healthy_load_samples_read_only(
        days=config.reserve_history_days, now=current
    )
    demand = forecast_household_demand(
        list(rows),
        start_local=current,
        end_local=opportunity.expected_start_local,
        minimum_samples=config.load_profile_minimum_samples,
        fallback_kw=config.conservative_fallback_household_load_kw,
        recent_days=config.reserve_recent_days,
    )
    battery_energy = _number(observation.get("battery_energy_estimate_kwh"))
    if battery_energy is None:
        soc = _number(observation.get("battery_soc_percent"))
        battery_energy = (
            config.usable_battery_capacity_kwh * soc / 100 if soc is not None else None
        )
    technical = config.usable_battery_capacity_kwh * config.minimum_soc_percent / 100
    expected_ev = _expected_ev_demand(observation)
    health = _health_summary(observation)
    score, confidence = _confidence(
        observation,
        demand=demand,
        health=health,
        opportunity=opportunity,
    )
    uncertainty_ratio = config.reserve_uncertainty_ratio
    if confidence == "low":
        uncertainty_ratio *= 1.75
    elif confidence == "medium":
        uncertainty_ratio *= 1.25
    uncertainty = demand.expected_energy_kwh * uncertainty_ratio
    safety_floor = max(technical, config.emergency_reserve_kwh)
    recommended = min(
        config.usable_battery_capacity_kwh,
        safety_floor + demand.expected_energy_kwh + expected_ev + uncertainty,
    )
    tradable = max((battery_energy or 0.0) - recommended, 0.0)
    telemetry_ok = bool(health["telemetry"]["is_healthy"])
    ready = telemetry_ok and battery_energy is not None
    reasoning = _reasoning(
        opportunity,
        demand,
        confidence=confidence,
        health=health,
        expected_ev_kwh=expected_ev,
        technical_kwh=technical,
        emergency_kwh=config.emergency_reserve_kwh,
    )
    return ReserveEstimate(
        calculated_at_local=current,
        battery_energy_kwh=_rounded(battery_energy),
        expected_house_demand_kwh=_rounded(demand.expected_energy_kwh),
        expected_ev_demand_kwh=_rounded(expected_ev),
        technical_reserve_kwh=_rounded(technical),
        emergency_reserve_kwh=_rounded(config.emergency_reserve_kwh),
        uncertainty_buffer_kwh=_rounded(uncertainty),
        recommended_reserve_kwh=_rounded(recommended),
        potentially_tradable_kwh=_rounded(tradable),
        next_opportunity=opportunity,
        demand_forecast=demand,
        confidence=confidence,
        confidence_score=score,
        reasoning=reasoning,
        health=health,
        operational_context=_operational_context(observation),
        ready_for_manual_review=ready,
    )


def _expected_ev_demand(observation: dict[str, Any]) -> float:
    required = _number(observation.get("ev_energy_required_kwh"))
    return max(required or 0.0, 0.0)


def _operational_context(observation: dict[str, Any]) -> dict[str, Any]:
    """Expose relevant stored context without turning it into control logic."""
    return {
        "battery_mode": observation.get("battery_mode"),
        "battery_charge_power_w": observation.get("battery_charge_power_w"),
        "battery_discharge_power_w": observation.get("battery_discharge_power_w"),
        "sign_convention_status": observation.get("sign_convention_status"),
        "amber_import_price_per_kwh": observation.get("amber_import_price_per_kwh"),
        "amber_export_price_per_kwh": observation.get("amber_export_price_per_kwh"),
        "temperature_c": observation.get("temperature_c"),
        "weather_condition": observation.get("weather_condition"),
        "ev_charging_active": (
            None
            if observation.get("ev_charging_active") is None
            else bool(observation["ev_charging_active"])
        ),
        "ev_ready_by_local": observation.get("ev_ready_by_local"),
    }


def _health_summary(observation: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for domain in ("telemetry", "price", "solar", "weather", "flow"):
        result[domain] = {
            "is_healthy": bool(observation.get(f"{domain}_is_healthy")),
            "score": int(observation.get(f"{domain}_health_score") or 0),
        }
    raw = observation.get("health_domains_json")
    try:
        structured = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        structured = {}
    if isinstance(structured, dict):
        for domain in result:
            value = structured.get(domain)
            if isinstance(value, dict):
                result[domain]["issues"] = value.get("issues", [])
    return result


def _confidence(
    observation: dict[str, Any],
    *,
    demand: DemandForecast,
    health: dict[str, Any],
    opportunity: ReplenishmentOpportunity,
) -> tuple[int, Literal["low", "medium", "high"]]:
    score = 0
    score += 30 if health["telemetry"]["is_healthy"] else 0
    if demand.confidence == "high":
        score += 25
    elif demand.confidence == "medium":
        score += 15
    else:
        score += 5
    score += 15 if health["solar"]["is_healthy"] else 3
    score += 15 if health["price"]["is_healthy"] else 3
    score += 5 if health["weather"]["is_healthy"] else 0
    if observation.get("sign_convention_status") == "confirmed" and observation.get(
        "sign_convention_confidence"
    ) in {"medium", "high"}:
        score += 5
    if opportunity.confidence == "high":
        score += 5
    elif opportunity.confidence == "medium":
        score += 3
    score = min(score, 100)
    if score >= 80 and demand.confidence == "high":
        return score, "high"
    if score >= 55:
        return score, "medium"
    return score, "low"


def _reasoning(
    opportunity: ReplenishmentOpportunity,
    demand: DemandForecast,
    *,
    confidence: str,
    health: dict[str, Any],
    expected_ev_kwh: float,
    technical_kwh: float,
    emergency_kwh: float,
) -> str:
    limitations = []
    if demand.confidence == "low":
        limitations.append("household history is insufficient")
    if not health["solar"]["is_healthy"]:
        limitations.append("Solcast data is incomplete")
    if not health["price"]["is_healthy"]:
        limitations.append("Amber data is incomplete")
    if not health["weather"]["is_healthy"]:
        limitations.append("weather context is unavailable")
    suffix = "; ".join(limitations) if limitations else "required inputs are available"
    return (
        f"The next opportunity is {opportunity.opportunity_type} at "
        f"{opportunity.expected_start_local.isoformat()}. {demand.explanation} "
        f"The safety floor is the larger of the {technical_kwh:.2f} kWh technical "
        f"minimum and {emergency_kwh:.2f} kWh emergency reserve. Known EV demand "
        f"adds {expected_ev_kwh:.2f} kWh. Confidence is {confidence}: {suffix}. "
        "This estimate is advisory; no command was issued."
    )


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _rounded(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None
