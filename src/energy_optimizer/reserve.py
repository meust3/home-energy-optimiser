"""Strictly advisory battery reserve estimation."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from energy_optimizer.collector import Collector
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.demand_forecast import DemandForecast, forecast_household_demand
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
from energy_optimizer.timestamps import native_json

ConfidenceRating = Literal["low", "medium_low", "medium", "high"]


class ConfidenceComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    rating: ConfidenceRating
    factors: list[str]
    ceilings: list[str] = Field(default_factory=list)


class ActiveOpportunityAnalysis(BaseModel):
    opportunity: ReplenishmentOpportunity
    opportunity_remaining_minutes: float = Field(ge=0)
    solar_forecast_resolution: Literal["coarse", "missing", "not_applicable"]
    expected_solar_generation_remaining_kwh: float | None = Field(default=None, ge=0)
    expected_household_demand_during_opportunity_kwh: float = Field(ge=0)
    expected_solar_surplus_kwh: float | None = Field(default=None, ge=0)
    battery_headroom_kwh: float | None = Field(default=None, ge=0)
    projected_battery_headroom_kwh: float | None = Field(default=None, ge=0)
    charge_efficiency: float = Field(gt=0, le=1)
    max_permitted_charge_power_kw: float = Field(gt=0)
    maximum_import_energy_kwh: float = Field(ge=0)
    maximum_grid_replenishment_kwh: float = Field(ge=0)
    maximum_solar_replenishment_kwh: float | None = Field(default=None, ge=0)
    expected_grid_replenishment_kwh: float = Field(ge=0)
    expected_battery_replenishment_kwh: float | None = Field(default=None, ge=0)
    maximum_battery_replenishment_kwh: float | None = Field(default=None, ge=0)
    physical_maximum_replenishment_kwh: float | None = Field(default=None, ge=0)
    expected_total_replenishment_kwh: float | None = Field(default=None, ge=0)
    usable_replenishment_kwh: float | None = Field(default=None, ge=0)
    energy_requirement_after_opportunity_kwh: float = Field(ge=0)
    projected_battery_energy_at_opportunity_end_kwh: float | None = Field(
        default=None, ge=0
    )
    opportunity_sufficient: bool | None
    next_opportunity_after_active: ReplenishmentOpportunity
    limitations: list[str]

    @model_validator(mode="after")
    def expected_replenishment_respects_physical_limits(self):
        expected = self.expected_total_replenishment_kwh
        if expected is None:
            return self
        for name, limit in (
            ("physical maximum", self.physical_maximum_replenishment_kwh),
            ("projected battery headroom", self.projected_battery_headroom_kwh),
        ):
            if limit is not None and expected > limit + 0.001:
                raise ValueError(f"expected replenishment exceeds {name}")
        return self


class ReserveEstimate(BaseModel):
    calculated_at_local: datetime
    evaluation_time_local: datetime
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
    forecast_horizon_minutes: float = Field(ge=0)
    forecast_start_local: datetime
    forecast_end_local: datetime
    forecast_slot_count: int = Field(ge=0)
    horizon_is_valid: bool
    horizon_validation_issues: list[str]
    average_forecast_load_kw: float = Field(ge=0)
    recommended_reserve_kwh: float = Field(ge=0)
    potentially_tradable_kwh: float | None = Field(default=None, ge=0)
    next_opportunity: ReplenishmentOpportunity
    effective_reserve_boundary: ReplenishmentOpportunity | None
    planning_horizon_end_local: datetime
    evaluated_opportunities: list[ActiveOpportunityAnalysis]
    skipped_insufficient_opportunity_count: int = Field(ge=0)
    active_opportunity: ActiveOpportunityAnalysis | None = None
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
    historian: DatabaseRepository,
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
    observed_at = _observation_timestamp(observation).astimezone(local_zone)
    if as_of is not None:
        current = as_of.astimezone(local_zone)
    elif now is not None:
        current = now.astimezone(local_zone)
    elif source == "history":
        current = observed_at
    else:
        current = datetime.now(local_zone)
    age_seconds = max((current - observed_at).total_seconds(), 0.0)
    planning_horizon_end = current + timedelta(hours=config.reserve_max_horizon_hours)
    opportunity = find_next_opportunity(
        observation,
        now_local=current,
        cheap_import_price_per_kwh=config.cheap_import_price_per_kwh,
        solar_surplus_threshold_kwh=config.solar_surplus_threshold_kwh,
        max_horizon_hours=config.reserve_max_horizon_hours,
    )
    if (
        opportunity.state == "inside_opportunity"
        and opportunity.opportunity_type in {"solar", "both"}
        and _conservative_solar_remaining(observation) is None
    ):
        opportunity.confidence = "low"
        opportunity.explanation += (
            " Conservative remaining-generation uncertainty is unavailable."
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
    history_rows = list(rows)
    battery_energy = _number(observation.get("battery_energy_estimate_kwh"))
    soc = _number(observation.get("battery_soc_percent"))
    if battery_energy is None:
        battery_energy = (
            config.usable_battery_capacity_kwh * soc / 100 if soc is not None else None
        )
    technical = config.usable_battery_capacity_kwh * config.minimum_soc_percent / 100
    expected_ev = _expected_ev_demand(observation)
    safety_floor = max(technical, config.emergency_reserve_kwh)
    next_after_active = None
    evaluated_opportunities: list[ActiveOpportunityAnalysis] = []
    skipped_replenishment = 0.0
    effective_boundary: ReplenishmentOpportunity | None = opportunity
    if opportunity.state == "inside_opportunity":
        next_after_active = find_next_opportunity(
            observation,
            now_local=opportunity.expected_end_local,
            cheap_import_price_per_kwh=config.cheap_import_price_per_kwh,
            solar_surplus_threshold_kwh=config.solar_surplus_threshold_kwh,
            max_horizon_hours=config.reserve_max_horizon_hours,
        )
        forecast_end = next_after_active.expected_start_local
    elif opportunity.state == "before_opportunity":
        (
            effective_boundary,
            evaluated_opportunities,
            skipped_replenishment,
        ) = _evaluate_upcoming_opportunities(
            observation,
            first=opportunity,
            evaluation_time=current,
            history_rows=history_rows,
            battery_energy_kwh=battery_energy,
            safety_floor_kwh=safety_floor,
            expected_ev_kwh=expected_ev,
            config=config,
            prior_mape=prior_mape,
            planning_horizon_end=planning_horizon_end,
        )
        forecast_end = (
            effective_boundary.expected_start_local
            if effective_boundary is not None
            else planning_horizon_end
        )
    else:
        effective_boundary = None
        forecast_end = planning_horizon_end
    demand = _forecast_demand(
        history_rows, current, forecast_end, config, prior_mape=prior_mape
    )
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
    active_analysis = None
    expected_replenishment = 0.0
    active_requirement = demand.expected_energy_kwh
    if next_after_active is not None:
        active_demand = _forecast_demand(
            history_rows,
            current,
            opportunity.expected_end_local,
            config,
            prior_mape=prior_mape,
        )
        future_demand = _forecast_demand(
            history_rows,
            opportunity.expected_end_local,
            next_after_active.expected_start_local,
            config,
            prior_mape=prior_mape,
        )
        active_analysis = _active_opportunity_analysis(
            observation,
            opportunity=opportunity,
            next_opportunity=next_after_active,
            evaluation_time=current,
            active_house_demand_kwh=active_demand.expected_energy_kwh,
            future_house_demand_kwh=future_demand.expected_energy_kwh,
            battery_energy_kwh=battery_energy,
            safety_floor_kwh=safety_floor,
            expected_ev_kwh=expected_ev,
            uncertainty_kwh=uncertainty,
            config=config,
        )
        evaluated_opportunities.append(active_analysis)
        if active_analysis.opportunity_sufficient is not True:
            (
                effective_boundary,
                subsequent_analyses,
                subsequent_replenishment,
            ) = _evaluate_upcoming_opportunities(
                observation,
                first=next_after_active,
                evaluation_time=opportunity.expected_end_local,
                history_rows=history_rows,
                battery_energy_kwh=(
                    active_analysis.projected_battery_energy_at_opportunity_end_kwh
                ),
                safety_floor_kwh=safety_floor,
                expected_ev_kwh=expected_ev,
                config=config,
                prior_mape=prior_mape,
                planning_horizon_end=planning_horizon_end,
            )
            evaluated_opportunities.extend(subsequent_analyses)
            skipped_replenishment = (
                active_analysis.usable_replenishment_kwh or 0.0
            ) + subsequent_replenishment
            expected_replenishment = 0.0
            forecast_end = (
                effective_boundary.expected_start_local
                if effective_boundary is not None
                else planning_horizon_end
            )
            demand = _forecast_demand(
                history_rows,
                current,
                forecast_end,
                config,
                prior_mape=prior_mape,
            )
            uncertainty = demand.expected_energy_kwh * uncertainty_ratio
        expected_replenishment = (
            (active_analysis.usable_replenishment_kwh or 0.0)
            if active_analysis.opportunity_sufficient is True
            else 0.0
        )
        solar_generation = active_analysis.expected_solar_generation_remaining_kwh
        active_requirement = (
            active_demand.expected_energy_kwh
            if solar_generation is None
            else max(active_demand.expected_energy_kwh - solar_generation, 0.0)
        )
    future_demand_energy = (
        demand.expected_energy_kwh - active_demand.expected_energy_kwh
        if active_analysis
        else 0.0
    )
    gross_requirement = max(
        safety_floor
        + active_requirement
        + future_demand_energy
        + expected_ev
        + uncertainty
        - expected_replenishment
        - skipped_replenishment,
        safety_floor,
    )
    recommended = min(config.usable_battery_capacity_kwh, gross_requirement)
    unmet_requirement = max(gross_requirement - config.usable_battery_capacity_kwh, 0.0)
    reserve_shortfall = max(recommended - (battery_energy or 0.0), 0.0)
    horizon_hours = max((demand.end_local - current).total_seconds() / 3600, 0.0)
    average_load = demand.expected_energy_kwh / horizon_hours if horizon_hours else 0.0
    horizon_issues = _horizon_validation_issues(demand, horizon_hours)
    horizon_valid = not horizon_issues
    effective_boundary_is_sufficient = effective_boundary is not None
    tradable = (
        max((battery_energy or 0.0) - recommended, 0.0)
        if horizon_valid and effective_boundary_is_sufficient
        else None
    )
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
    if not horizon_valid:
        reasoning += (
            " Forecast-horizon validation failed; potentially tradable energy is "
            "unavailable and the advisory is not ready for manual review."
        )
    return ReserveEstimate(
        calculated_at_local=current,
        evaluation_time_local=current,
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
        forecast_horizon_minutes=round(horizon_hours * 60, 3),
        forecast_start_local=demand.start_local,
        forecast_end_local=demand.end_local,
        forecast_slot_count=len(demand.slot_decisions),
        horizon_is_valid=horizon_valid,
        horizon_validation_issues=horizon_issues,
        average_forecast_load_kw=_rounded(average_load),
        recommended_reserve_kwh=_rounded(recommended),
        potentially_tradable_kwh=_rounded(tradable),
        next_opportunity=opportunity,
        effective_reserve_boundary=effective_boundary,
        planning_horizon_end_local=planning_horizon_end,
        evaluated_opportunities=evaluated_opportunities,
        skipped_insufficient_opportunity_count=(
            len(evaluated_opportunities)
            if effective_boundary is None
            else max(len(evaluated_opportunities) - 1, 0)
        ),
        active_opportunity=active_analysis,
        demand_forecast=demand,
        data_availability_confidence=availability_component,
        household_demand_confidence=ConfidenceComponent(
            score=demand.confidence_score,
            rating=demand.confidence,
            factors=[
                f"complete_days={demand.diagnostics.complete_daily_periods}",
                f"exact_share={_share(demand.diagnostics.exact_history_share)}",
                f"weak_share={_share(demand.diagnostics.weak_estimate_share)}",
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
        ready_for_manual_review=(
            ready and horizon_valid and effective_boundary_is_sufficient
        ),
    )


def estimate_live_battery_reserve(
    historian: DatabaseRepository,
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


def store_reserve_forecast(
    historian: DatabaseRepository, estimate: ReserveEstimate
) -> int:
    """Persist the advisory household-demand horizon for later actual scoring."""
    points = [
        ForecastPoint(
            period_start_utc=slot.period_start_local.astimezone(UTC),
            period_end_utc=slot.period_end_local.astimezone(UTC),
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
    structured = native_json(raw) if raw else {}
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


def _share(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _forecast_demand(
    rows: list[Any],
    start: datetime,
    end: datetime,
    config: CollectorConfig,
    *,
    prior_mape: float | None,
) -> DemandForecast:
    return forecast_household_demand(
        rows,
        start_local=start,
        end_local=end,
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
        training_policy=config.demand_training_policy,
    )


def _evaluate_upcoming_opportunities(
    observation: dict[str, Any],
    *,
    first: ReplenishmentOpportunity,
    evaluation_time: datetime,
    history_rows: list[Any],
    battery_energy_kwh: float | None,
    safety_floor_kwh: float,
    expected_ev_kwh: float,
    config: CollectorConfig,
    prior_mape: float | None,
    planning_horizon_end: datetime | None = None,
) -> tuple[ReplenishmentOpportunity | None, list[ActiveOpportunityAnalysis], float]:
    horizon_end = planning_horizon_end or evaluation_time + timedelta(
        hours=config.reserve_max_horizon_hours
    )
    candidate = first
    cursor = evaluation_time
    projected = battery_energy_kwh
    analyses: list[ActiveOpportunityAnalysis] = []
    expected_replenishment_total = 0.0
    for _ in range(32):
        if (
            candidate.opportunity_type == "overnight_reserve"
            or candidate.expected_start_local >= horizon_end
            or candidate.expected_end_local <= candidate.expected_start_local
        ):
            break
        demand_before = _forecast_demand(
            history_rows,
            cursor,
            candidate.expected_start_local,
            config,
            prior_mape=prior_mape,
        )
        if projected is not None:
            projected = max(projected - demand_before.expected_energy_kwh, 0.0)
        following = _next_opportunity_after(observation, candidate, config)
        future_end = min(following.expected_start_local, horizon_end)
        active_demand = _forecast_demand(
            history_rows,
            candidate.expected_start_local,
            min(candidate.expected_end_local, horizon_end),
            config,
            prior_mape=prior_mape,
        )
        future_demand = _forecast_demand(
            history_rows,
            min(candidate.expected_end_local, horizon_end),
            future_end,
            config,
            prior_mape=prior_mape,
        )
        conservative_uncertainty = (
            (active_demand.expected_energy_kwh + future_demand.expected_energy_kwh)
            * config.reserve_uncertainty_ratio
            * 1.75
        )
        analysis = _active_opportunity_analysis(
            observation,
            opportunity=candidate,
            next_opportunity=following,
            evaluation_time=candidate.expected_start_local,
            active_house_demand_kwh=active_demand.expected_energy_kwh,
            future_house_demand_kwh=future_demand.expected_energy_kwh,
            battery_energy_kwh=projected,
            safety_floor_kwh=safety_floor_kwh,
            expected_ev_kwh=expected_ev_kwh,
            uncertainty_kwh=conservative_uncertainty,
            config=config,
        )
        analyses.append(analysis)
        if analysis.opportunity_sufficient is True:
            return candidate, analyses, expected_replenishment_total
        expected_replenishment_total += analysis.usable_replenishment_kwh or 0.0
        projected = analysis.projected_battery_energy_at_opportunity_end_kwh
        cursor = candidate.expected_end_local
        if following.expected_start_local <= cursor:
            break
        candidate = following
    return None, analyses, expected_replenishment_total


def _next_opportunity_after(
    observation: dict[str, Any],
    candidate: ReplenishmentOpportunity,
    config: CollectorConfig,
) -> ReplenishmentOpportunity:
    cursor = candidate.expected_end_local
    for _ in range(8):
        following = find_next_opportunity(
            observation,
            now_local=cursor,
            cheap_import_price_per_kwh=config.cheap_import_price_per_kwh,
            solar_surplus_threshold_kwh=config.solar_surplus_threshold_kwh,
            max_horizon_hours=config.reserve_max_horizon_hours,
        )
        if following.expected_start_local >= cursor:
            return following
        cursor = max(cursor, following.expected_end_local)
    return ReplenishmentOpportunity(
        opportunity_type="overnight_reserve",
        expected_start_local=cursor + timedelta(hours=config.reserve_max_horizon_hours),
        expected_end_local=cursor + timedelta(hours=config.reserve_max_horizon_hours),
        confidence="low",
        explanation="No later non-overlapping opportunity was available.",
        state="waiting_for_next_opportunity",
    )


def _active_opportunity_analysis(
    observation: dict[str, Any],
    *,
    opportunity: ReplenishmentOpportunity,
    next_opportunity: ReplenishmentOpportunity,
    evaluation_time: datetime,
    active_house_demand_kwh: float,
    future_house_demand_kwh: float,
    battery_energy_kwh: float | None,
    safety_floor_kwh: float,
    expected_ev_kwh: float,
    uncertainty_kwh: float,
    config: CollectorConfig,
) -> ActiveOpportunityAnalysis:
    duration_hours = max(
        (
            opportunity.expected_end_local
            - max(opportunity.expected_start_local, evaluation_time)
        ).total_seconds()
        / 3600,
        0.0,
    )
    remaining_minutes = duration_hours * 60
    headroom = (
        max(config.usable_battery_capacity_kwh - battery_energy_kwh, 0.0)
        if battery_energy_kwh is not None
        else None
    )
    max_charge_input = config.reserve_max_charge_power_w / 1000 * duration_hours
    maximum_import = (
        max_charge_input
        if opportunity.opportunity_type in {"cheap_grid", "both"}
        else 0.0
    )
    expected_solar = None
    solar_surplus = None
    solar_replenishment = None
    resolution: Literal["coarse", "missing", "not_applicable"] = (
        "not_applicable" if opportunity.opportunity_type == "cheap_grid" else "missing"
    )
    limitations = ["No charging command or automatic charging behaviour is assumed."]
    if opportunity.opportunity_type in {"solar", "both"}:
        conservative_solar = _conservative_solar_for_opportunity(
            observation, opportunity
        )
        if conservative_solar is not None:
            expected_solar = conservative_solar
            solar_surplus = max(expected_solar - active_house_demand_kwh, 0.0)
            solar_replenishment = min(
                solar_surplus * config.battery_charge_efficiency,
                max_charge_input * config.battery_charge_efficiency,
                headroom if headroom is not None else float("inf"),
            )
            resolution = "coarse"
            limitations.append(
                "Solar uses the conservative remaining-today estimate10 total; "
                "no intraday forecast series is stored."
            )
        else:
            limitations.append(
                "Conservative interval solar generation is unavailable; no solar "
                "replenishment was assumed."
            )
    expected_replenishment = solar_replenishment
    if opportunity.opportunity_type == "cheap_grid":
        expected_replenishment = 0.0
    maximum_grid = min(
        maximum_import * config.battery_charge_efficiency,
        max(
            (headroom if headroom is not None else 0.0) - (solar_replenishment or 0.0),
            0.0,
        ),
    )
    maximum_replenishment = (
        min(
            (solar_replenishment or 0.0) + maximum_grid,
            headroom if headroom is not None else 0.0,
        )
        if headroom is not None
        else None
    )
    house_deficit = (
        active_house_demand_kwh
        if expected_solar is None
        else max(active_house_demand_kwh - expected_solar, 0.0)
    )
    future_requirement = (
        safety_floor_kwh + future_house_demand_kwh + expected_ev_kwh + uncertainty_kwh
    )
    projected = (
        max(
            min(
                battery_energy_kwh - house_deficit + (expected_replenishment or 0.0),
                config.usable_battery_capacity_kwh,
            ),
            0.0,
        )
        if battery_energy_kwh is not None
        else None
    )
    required_replenishment = future_house_demand_kwh + expected_ev_kwh + uncertainty_kwh
    sufficient = (
        expected_replenishment >= required_replenishment
        if expected_replenishment is not None
        else None
    )
    return ActiveOpportunityAnalysis(
        opportunity=opportunity,
        opportunity_remaining_minutes=round(remaining_minutes, 3),
        solar_forecast_resolution=resolution,
        expected_solar_generation_remaining_kwh=_rounded(expected_solar),
        expected_household_demand_during_opportunity_kwh=_rounded(
            active_house_demand_kwh
        ),
        expected_solar_surplus_kwh=_rounded(solar_surplus),
        battery_headroom_kwh=_rounded(headroom),
        projected_battery_headroom_kwh=_rounded(headroom),
        charge_efficiency=config.battery_charge_efficiency,
        max_permitted_charge_power_kw=config.reserve_max_charge_power_w / 1000,
        maximum_import_energy_kwh=_rounded(maximum_import),
        maximum_grid_replenishment_kwh=_rounded(maximum_grid),
        maximum_solar_replenishment_kwh=_rounded(solar_replenishment),
        expected_grid_replenishment_kwh=0.0,
        expected_battery_replenishment_kwh=_rounded(expected_replenishment),
        maximum_battery_replenishment_kwh=_rounded(maximum_replenishment),
        physical_maximum_replenishment_kwh=_rounded(maximum_replenishment),
        expected_total_replenishment_kwh=_rounded(expected_replenishment),
        usable_replenishment_kwh=_rounded(expected_replenishment),
        energy_requirement_after_opportunity_kwh=_rounded(future_requirement),
        projected_battery_energy_at_opportunity_end_kwh=_rounded(projected),
        opportunity_sufficient=sufficient,
        next_opportunity_after_active=next_opportunity,
        limitations=limitations,
    )


def _conservative_solar_remaining(observation: dict[str, Any]) -> float | None:
    summary = native_json(observation.get("solcast_remaining_today_kwh_json"))
    if not isinstance(summary, dict) or not isinstance(
        summary.get("estimate10_kwh"), (int, float)
    ):
        return None
    return max(float(summary["estimate10_kwh"]), 0.0)


def _conservative_solar_for_opportunity(
    observation: dict[str, Any],
    opportunity: ReplenishmentOpportunity,
) -> float | None:
    if opportunity.state == "inside_opportunity":
        return _conservative_solar_remaining(observation)
    observation_date = (
        _observation_timestamp(observation)
        .astimezone(opportunity.expected_start_local.tzinfo)
        .date()
    )
    if opportunity.expected_start_local.date() == observation_date:
        return None
    summary = native_json(observation.get("solcast_tomorrow_kwh_json"))
    if not isinstance(summary, dict) or not isinstance(
        summary.get("estimate10_kwh"), (int, float)
    ):
        return None
    return max(float(summary["estimate10_kwh"]), 0.0)


def _horizon_validation_issues(
    demand: DemandForecast, horizon_hours: float
) -> list[str]:
    issues: list[str] = []
    slots = demand.slot_decisions
    for slot in slots:
        if (
            slot.period_start_local.tzinfo is None
            or slot.period_end_local.tzinfo is None
        ):
            issues.append("forecast_slot_timestamp_not_timezone_aware")
        if slot.period_end_local <= slot.period_start_local:
            issues.append("forecast_slot_not_positive_duration")
    for previous, current in zip(slots, slots[1:], strict=False):
        if current.period_start_local != previous.period_end_local:
            issues.append("forecast_slots_not_contiguous")
            break
    slot_hours = sum(slot.duration_minutes for slot in slots) / 60
    if abs(slot_hours - horizon_hours) > 1e-6:
        issues.append("forecast_slot_duration_mismatch")
    slot_energy = sum(slot.expected_energy_kwh for slot in slots)
    if abs(slot_energy - demand.expected_energy_kwh) > 0.002:
        issues.append("forecast_slot_energy_mismatch")
    if demand.end_local < demand.start_local:
        issues.append("forecast_horizon_negative")
    return list(dict.fromkeys(issues))
