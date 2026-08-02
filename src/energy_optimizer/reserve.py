"""Strictly advisory battery reserve estimation."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from energy_optimizer.collector import Collector
from energy_optimizer.demand_forecast import DemandForecast, forecast_household_demand
from energy_optimizer.historian import Historian
from energy_optimizer.home_assistant import HomeAssistantClient
from energy_optimizer.models import (
    CollectorConfig,
    EnergyObservation,
    ForecastPoint,
    ForecastRun,
)
from energy_optimizer.opportunity_window import (
    ReplenishmentOpportunity,
    find_next_opportunity,
)

ConfidenceRating = Literal["low", "medium_low", "medium", "high"]


class ConfidenceComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    rating: ConfidenceRating
    factors: list[str]
    ceilings: list[str] = Field(default_factory=list)


class ReserveEstimate(BaseModel):
    calculated_at_local: datetime
    current_state_source: Literal["live", "history"]
    observation_timestamp: datetime
    observation_age_seconds: float = Field(ge=0)
    observation_is_stale: bool
    observation_warning: str | None
    battery_soc_percent: float | None
    usable_battery_capacity_kwh: float = Field(gt=0)
    battery_energy_kwh: float | None
    expected_house_demand_kwh: float = Field(ge=0)
    expected_ev_demand_kwh: float = Field(ge=0)
    technical_reserve_kwh: float = Field(ge=0)
    emergency_reserve_kwh: float = Field(ge=0)
    uncertainty_buffer_kwh: float = Field(ge=0)
    gross_reserve_requirement_kwh: float = Field(ge=0)
    capacity_capped_reserve_kwh: float = Field(ge=0)
    unmet_reserve_requirement_kwh: float = Field(ge=0)
    current_reserve_shortfall_kwh: float = Field(ge=0)
    forecast_horizon_hours: float = Field(ge=0)
    average_forecast_load_kw: float = Field(ge=0)
    recommended_reserve_kwh: float = Field(ge=0)
    potentially_tradable_kwh: float = Field(ge=0)
    next_opportunity: ReplenishmentOpportunity
    demand_forecast: DemandForecast
    data_availability_confidence: ConfidenceComponent
    household_demand_confidence: ConfidenceComponent
    opportunity_forecast_confidence: ConfidenceComponent
    overall_reserve_confidence: ConfidenceComponent
    confidence: ConfidenceRating
    confidence_score: int = Field(ge=0, le=100)
    reasoning: str
    health: dict[str, Any]
    operational_context: dict[str, Any]
    ready_for_manual_review: bool
    forecast_run_id: int | None = None
    command_issued: Literal[False] = False


def estimate_battery_reserve(
    historian: Historian,
    config: CollectorConfig,
    *,
    now: datetime | None = None,
    current_observation: EnergyObservation | dict[str, Any] | None = None,
    source: Literal["live", "history"] = "history",
    as_of: datetime | None = None,
) -> ReserveEstimate:
    """Estimate reserve from explicit current state plus read-only load history."""
    if source == "live" and as_of is not None:
        raise ValueError("as_of is only valid for history source")
    if current_observation is None:
        observation = historian.observation_as_of_read_only(as_of)
    elif isinstance(current_observation, EnergyObservation):
        observation = observation_to_reserve_input(current_observation)
    else:
        observation = current_observation
    if observation is None:
        raise ValueError("No observations are available in the history database")
    local_zone = ZoneInfo(config.timezone)
    current = (as_of or now or datetime.now(local_zone)).astimezone(local_zone)
    observed_at = _observation_timestamp(observation).astimezone(local_zone)
    age_seconds = max((current - observed_at).total_seconds(), 0.0)
    opportunity = find_next_opportunity(
        observation,
        now_local=current,
        cheap_import_price_per_kwh=config.cheap_import_price_per_kwh,
        solar_surplus_threshold_kwh=config.solar_surplus_threshold_kwh,
        max_horizon_hours=config.reserve_max_horizon_hours,
    )
    rows = historian.reserve_history_rows_read_only(
        days=config.reserve_history_days,
        now=current,
        as_of=as_of or current,
    )
    prior_mape = (
        historian.prior_reserve_forecast_mape_read_only()
        if hasattr(historian, "prior_reserve_forecast_mape_read_only")
        else None
    )
    demand = forecast_household_demand(
        list(rows),
        start_local=current,
        end_local=opportunity.expected_start_local,
        minimum_samples=config.load_profile_minimum_samples,
        fallback_kw=config.conservative_fallback_household_load_kw,
        fallback_mode=config.reserve_fallback_mode,
        fallback_band_powers_kw={
            "overnight": config.reserve_fallback_overnight_kw,
            "morning": config.reserve_fallback_morning_kw,
            "daytime": config.reserve_fallback_daytime_kw,
            "evening": config.reserve_fallback_evening_kw,
            "late_evening": config.reserve_fallback_late_evening_kw,
        },
        recent_days=config.reserve_recent_days,
        tier2_minimum_samples=config.demand_tier2_minimum_samples,
        tier3_minimum_samples=config.demand_tier3_minimum_samples,
        tier4_minimum_samples=config.demand_tier4_minimum_samples,
        tier4_lookback_days=config.demand_tier4_lookback_days,
        weekend_days=config.demand_weekend_days,
        complete_period_fraction=config.demand_complete_period_fraction,
        low_ceiling_complete_days=config.demand_low_ceiling_complete_days,
        medium_low_ceiling_complete_days=config.demand_medium_low_ceiling_complete_days,
        weak_tier_share_ceiling=config.demand_weak_tier_share_ceiling,
        prior_forecast_mape=prior_mape,
    )
    battery_energy = _number(observation.get("battery_energy_estimate_kwh"))
    soc = _number(observation.get("battery_soc_percent"))
    if battery_energy is None:
        battery_energy = (
            config.usable_battery_capacity_kwh * soc / 100 if soc is not None else None
        )
    technical = config.usable_battery_capacity_kwh * config.minimum_soc_percent / 100
    expected_ev = _expected_ev_demand(observation)
    health = _health_summary(observation)
    availability_component, opportunity_component, overall_component = _confidence(
        observation,
        demand=demand,
        health=health,
        opportunity=opportunity,
    )
    uncertainty_ratio = config.reserve_uncertainty_ratio
    confidence = overall_component.rating
    score = overall_component.score
    if confidence == "low":
        uncertainty_ratio *= 1.75
    elif confidence == "medium_low":
        uncertainty_ratio *= 1.5
    elif confidence == "medium":
        uncertainty_ratio *= 1.25
    uncertainty = demand.expected_energy_kwh * uncertainty_ratio
    safety_floor = max(technical, config.emergency_reserve_kwh)
    gross_requirement = (
        safety_floor + demand.expected_energy_kwh + expected_ev + uncertainty
    )
    recommended = min(config.usable_battery_capacity_kwh, gross_requirement)
    unmet_requirement = max(gross_requirement - config.usable_battery_capacity_kwh, 0.0)
    reserve_shortfall = max(recommended - (battery_energy or 0.0), 0.0)
    horizon_hours = max(
        (opportunity.expected_start_local - current).total_seconds() / 3600, 0.0
    )
    average_load = demand.expected_energy_kwh / horizon_hours if horizon_hours else 0.0
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
        current_state_source=source,
        observation_timestamp=observed_at,
        observation_age_seconds=round(age_seconds, 1),
        observation_is_stale=age_seconds > 600,
        observation_warning=(
            "Stored observation is older than 10 minutes; current Home Assistant "
            "state may differ."
            if source == "history" and age_seconds > 600
            else None
        ),
        battery_soc_percent=_rounded(soc),
        usable_battery_capacity_kwh=config.usable_battery_capacity_kwh,
        battery_energy_kwh=_rounded(battery_energy),
        expected_house_demand_kwh=_rounded(demand.expected_energy_kwh),
        expected_ev_demand_kwh=_rounded(expected_ev),
        technical_reserve_kwh=_rounded(technical),
        emergency_reserve_kwh=_rounded(config.emergency_reserve_kwh),
        uncertainty_buffer_kwh=_rounded(uncertainty),
        gross_reserve_requirement_kwh=_rounded(gross_requirement),
        capacity_capped_reserve_kwh=_rounded(recommended),
        unmet_reserve_requirement_kwh=_rounded(unmet_requirement),
        current_reserve_shortfall_kwh=_rounded(reserve_shortfall),
        forecast_horizon_hours=round(horizon_hours, 3),
        average_forecast_load_kw=_rounded(average_load),
        recommended_reserve_kwh=_rounded(recommended),
        potentially_tradable_kwh=_rounded(tradable),
        next_opportunity=opportunity,
        demand_forecast=demand,
        data_availability_confidence=availability_component,
        household_demand_confidence=ConfidenceComponent(
            score=demand.confidence_score,
            rating=demand.confidence,
            factors=[
                f"complete_days={demand.diagnostics.complete_daily_periods}",
                f"exact_share={demand.diagnostics.exact_history_share:.1%}",
                f"weak_share={demand.diagnostics.weak_estimate_share:.1%}",
                f"prior_mape={demand.diagnostics.prior_forecast_mape}",
            ],
            ceilings=demand.confidence_ceilings,
        ),
        opportunity_forecast_confidence=opportunity_component,
        overall_reserve_confidence=overall_component,
        confidence=confidence,
        confidence_score=score,
        reasoning=reasoning,
        health=health,
        operational_context=_operational_context(observation),
        ready_for_manual_review=ready,
    )


def estimate_live_battery_reserve(
    historian: Historian,
    config: CollectorConfig,
    client: HomeAssistantClient,
    *,
    save_observation: bool = False,
    now: datetime | None = None,
) -> ReserveEstimate:
    """Collect one GET-only observation and estimate without saving by default."""
    observation = Collector(client, config).collect(observed_at=now)
    if save_observation:
        historian.save(observation)
    return estimate_battery_reserve(
        historian,
        config,
        now=observation.observed_at_local,
        current_observation=observation,
        source="live",
    )


def store_reserve_forecast(historian: Historian, estimate: ReserveEstimate) -> int:
    """Persist the advisory household-demand horizon for later actual scoring."""
    points = [
        ForecastPoint(
            period_start_utc=slot.period_start_local.astimezone(UTC),
            period_end_utc=(slot.period_start_local + timedelta(minutes=5)).astimezone(
                UTC
            ),
            expected_value=slot.estimated_power_kw * 1000,
            unit="W",
            metadata={
                "tier": slot.tier,
                "sample_count": slot.sample_count,
                "variability": slot.variability,
            },
        )
        for slot in estimate.demand_forecast.slot_decisions
    ]
    run = ForecastRun(
        created_at_utc=estimate.calculated_at_local.astimezone(UTC),
        forecast_type="baseline_household_load",
        source="reserve_estimator",
        horizon_start_utc=estimate.demand_forecast.start_local.astimezone(UTC),
        horizon_end_utc=estimate.demand_forecast.end_local.astimezone(UTC),
        model_version="hierarchical-demand-v1",
        metadata={
            "current_state_source": estimate.current_state_source,
            "gross_reserve_requirement_kwh": estimate.gross_reserve_requirement_kwh,
            "capacity_capped_reserve_kwh": estimate.capacity_capped_reserve_kwh,
            "household_demand_confidence": (
                estimate.household_demand_confidence.model_dump()
            ),
            "overall_reserve_confidence": (
                estimate.overall_reserve_confidence.model_dump()
            ),
        },
        points=points,
    )
    run_id = historian.save_forecast_run(run)
    estimate.forecast_run_id = run_id
    return run_id


def observation_to_reserve_input(observation: EnergyObservation) -> dict[str, Any]:
    """Adapt a fresh typed observation to the historian-shaped reserve input."""
    health = observation.data_health
    flow = observation.energy_flow
    return {
        **observation.model_dump(mode="json"),
        "amber_import_forecast_json": _json(observation.amber_import_forecast),
        "amber_export_forecast_json": _json(observation.amber_export_forecast),
        "solcast_remaining_today_kwh_json": _json(
            observation.solcast_remaining_today_kwh
        ),
        "solcast_tomorrow_kwh_json": _json(observation.solcast_tomorrow_kwh),
        "telemetry_is_healthy": int(health.telemetry.is_healthy),
        "telemetry_health_score": health.telemetry.score,
        "price_is_healthy": int(health.price.is_healthy),
        "price_health_score": health.price.score,
        "solar_is_healthy": int(health.solar.is_healthy),
        "solar_health_score": health.solar.score,
        "weather_is_healthy": int(health.weather.is_healthy),
        "weather_health_score": health.weather.score,
        "flow_is_healthy": int(health.flow.is_healthy),
        "flow_health_score": health.flow.score,
        "health_domains_json": _json(health),
        "battery_charge_power_w": flow.battery_charge_power_w,
        "battery_discharge_power_w": flow.battery_discharge_power_w,
        "sign_convention_status": flow.sign_convention_status,
        "sign_convention_confidence": flow.sign_convention_confidence,
    }


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
) -> tuple[ConfidenceComponent, ConfidenceComponent, ConfidenceComponent]:
    availability_score = 0
    availability_factors = []
    for domain, points in (
        ("telemetry", 40),
        ("price", 20),
        ("solar", 20),
        ("flow", 15),
        ("weather", 5),
    ):
        if health[domain]["is_healthy"]:
            availability_score += points
            availability_factors.append(f"{domain}_healthy")
        else:
            availability_factors.append(f"{domain}_unhealthy")
    availability = ConfidenceComponent(
        score=availability_score,
        rating=_rating(availability_score),
        factors=availability_factors,
    )
    opportunity_score = {"low": 30, "medium": 65, "high": 85}[opportunity.confidence]
    opportunity_factors = [f"window_confidence={opportunity.confidence}"]
    if health["solar"]["is_healthy"]:
        opportunity_score += 5
        opportunity_factors.append("solar_healthy")
    if health["price"]["is_healthy"]:
        opportunity_score += 5
        opportunity_factors.append("price_healthy")
    opportunity_score = min(opportunity_score, 100)
    opportunity_component = ConfidenceComponent(
        score=opportunity_score,
        rating=_rating(opportunity_score),
        factors=opportunity_factors,
    )
    if observation.get("sign_convention_status") == "confirmed" and observation.get(
        "sign_convention_confidence"
    ) in {"medium", "high"}:
        availability.factors.append("sign_conventions_confirmed")
    weighted = round(
        availability.score * 0.25
        + demand.confidence_score * 0.55
        + opportunity_component.score * 0.20
    )
    overall_ceilings = list(demand.confidence_ceilings)
    overall_score = min(weighted, demand.confidence_score)
    if overall_score < weighted:
        overall_ceilings.append("overall_capped_by_household_demand_confidence")
    overall = ConfidenceComponent(
        score=overall_score,
        rating=_rating(overall_score),
        factors=[
            f"availability={availability.score}",
            f"household_demand={demand.confidence_score}",
            f"opportunity={opportunity_component.score}",
        ],
        ceilings=overall_ceilings,
    )
    return availability, opportunity_component, overall


def _rating(score: int) -> ConfidenceRating:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    if score >= 40:
        return "medium_low"
    return "low"


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


def _observation_timestamp(observation: dict[str, Any]) -> datetime:
    value = observation.get("observed_at_utc") or observation.get("slot_utc")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        raise ValueError("Observation has no valid timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Observation timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _rounded(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None
