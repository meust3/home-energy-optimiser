"""Domain-specific data health and action-readiness evaluation."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from energy_optimizer import entity_ids as ids
from energy_optimizer.models import (
    CollectorConfig,
    DataHealth,
    EnergyFlow,
    EVTelemetryHealth,
    HealthDomain,
    HealthIssue,
    HealthUse,
    HomeAssistantState,
)
from energy_optimizer.parsing import (
    is_missing_state,
    parse_amber_intervals,
    parse_number,
    parse_solar_summary,
)

TELEMETRY_ENTITIES = (
    ids.GOODWE_BATTERY_SOC,
    ids.GOODWE_BATTERY_POWER,
    ids.GOODWE_PV_POWER,
    ids.GOODWE_HOUSE_CONSUMPTION,
    ids.GOODWE_GRID_POWER,
)
POWER_ENTITIES = (
    ids.GOODWE_BATTERY_POWER,
    ids.GOODWE_PV_POWER,
    ids.GOODWE_HOUSE_CONSUMPTION,
    ids.GOODWE_GRID_POWER,
)
PRICE_ENTITIES = (
    ids.AMBER_IMPORT_PRICE,
    ids.AMBER_EXPORT_PRICE,
    ids.AMBER_IMPORT_FORECAST,
    ids.AMBER_EXPORT_FORECAST,
)
SOLAR_REQUIRED_ENTITIES = (
    ids.SOLCAST_REMAINING_TODAY,
    ids.SOLCAST_TOMORROW,
    ids.SOLCAST_NEXT_HOUR,
)


def _issue(
    code: str,
    message: str,
    entity_id: str | None = None,
    *,
    warning: bool = False,
) -> HealthIssue:
    return HealthIssue(
        code=code,
        message=message,
        entity_id=entity_id,
        severity="warning" if warning else "error",
        deduction=5 if warning else 20,
    )


def _domain(issues: list[HealthIssue], required_for: list[HealthUse]) -> HealthDomain:
    return HealthDomain(
        is_healthy=not any(issue.severity == "error" for issue in issues),
        score=max(0, 100 - sum(issue.deduction for issue in issues)),
        issues=issues,
        required_for=required_for,
    )


def _check_numeric_entity(
    states: dict[str, HomeAssistantState],
    entity_id: str,
    *,
    current: datetime,
    freshness_minutes: int,
) -> list[HealthIssue]:
    state = states.get(entity_id)
    if state is None:
        return [_issue("missing_entity", "Required entity is absent", entity_id)]
    issues: list[HealthIssue] = []
    if is_missing_state(state.state):
        issues.append(
            _issue("unavailable_state", f"State is {state.state!r}", entity_id)
        )
    elif parse_number(state.state) is None:
        issues.append(
            _issue("malformed_number", "Numeric state could not be parsed", entity_id)
        )
    if current - state.last_updated.astimezone(UTC) > timedelta(
        minutes=freshness_minutes
    ):
        issues.append(
            _issue(
                "stale_state",
                f"Entity update exceeds {freshness_minutes}-minute policy",
                entity_id,
                warning=True,
            )
        )
    return issues


def _telemetry_health(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    current: datetime,
) -> HealthDomain:
    issues: list[HealthIssue] = []
    for entity_id in TELEMETRY_ENTITIES:
        freshness = (
            config.battery_soc_freshness_minutes
            if entity_id == ids.GOODWE_BATTERY_SOC
            else config.live_power_freshness_minutes
        )
        issues.extend(
            _check_numeric_entity(
                states,
                entity_id,
                current=current,
                freshness_minutes=freshness,
            )
        )
    soc_state = states.get(ids.GOODWE_BATTERY_SOC)
    soc = parse_number(soc_state.state) if soc_state else None
    if soc is not None and not 0 <= soc <= 100:
        issues.append(
            _issue(
                "soc_out_of_range",
                "Battery SOC is outside 0-100%",
                ids.GOODWE_BATTERY_SOC,
            )
        )
    for entity_id in POWER_ENTITIES:
        state = states.get(entity_id)
        power = parse_number(state.state) if state else None
        if power is not None and abs(power) > config.maximum_plausible_inverter_power_w:
            issues.append(
                _issue(
                    "implausible_power",
                    "Absolute power exceeds configured plausible maximum",
                    entity_id,
                )
            )
    return _domain(issues, ["display", "load_profile", "grid_charge", "battery_export"])


def _price_health(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    current: datetime,
) -> HealthDomain:
    issues: list[HealthIssue] = []
    for entity_id in (ids.AMBER_IMPORT_PRICE, ids.AMBER_EXPORT_PRICE):
        issues.extend(
            _check_numeric_entity(
                states,
                entity_id,
                current=current,
                freshness_minutes=config.amber_current_price_freshness_minutes,
            )
        )
    for entity_id in (ids.AMBER_IMPORT_FORECAST, ids.AMBER_EXPORT_FORECAST):
        state = states.get(entity_id)
        if state is None:
            issues.append(
                _issue("missing_entity", "Required entity is absent", entity_id)
            )
            continue
        if not parse_amber_intervals(state):
            issues.append(
                _issue(
                    "missing_amber_forecast",
                    "Forecast attribute is missing or empty",
                    entity_id,
                )
            )
        if current - state.last_updated.astimezone(UTC) > timedelta(
            minutes=config.amber_forecast_freshness_minutes
        ):
            issues.append(
                _issue(
                    "stale_state",
                    "Amber forecast exceeds freshness policy",
                    entity_id,
                    warning=True,
                )
            )
    return _domain(issues, ["grid_charge", "battery_export"])


def _solar_health(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    current: datetime,
) -> HealthDomain:
    issues: list[HealthIssue] = []
    for entity_id in SOLAR_REQUIRED_ENTITIES:
        state = states.get(entity_id)
        if state is None:
            issues.append(
                _issue("missing_entity", "Required entity is absent", entity_id)
            )
            continue
        summary = parse_solar_summary(state)
        if summary is None or not any(
            value is not None
            for value in (
                summary.estimate_kwh,
                summary.estimate10_kwh,
                summary.estimate90_kwh,
            )
        ):
            issues.append(
                _issue(
                    "missing_solcast_summary",
                    "Required Solcast summary is missing or has no supported unit",
                    entity_id,
                )
            )
        if current - state.last_updated.astimezone(UTC) > timedelta(
            minutes=config.solcast_forecast_freshness_minutes
        ):
            issues.append(
                _issue(
                    "stale_state",
                    "Solcast forecast exceeds freshness policy",
                    entity_id,
                    warning=True,
                )
            )
    return _domain(issues, ["grid_charge", "battery_export"])


def _weather_health(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    current: datetime,
) -> HealthDomain:
    """Evaluate configured weather context without affecting overall health."""
    issues: list[HealthIssue] = []
    temperature_id = config.weather_temperature_entity_id
    if temperature_id:
        issues.extend(
            _check_numeric_entity(
                states,
                temperature_id,
                current=current,
                freshness_minutes=config.weather_freshness_minutes,
            )
        )
    condition_id = config.weather_condition_entity_id
    if condition_id:
        state = states.get(condition_id)
        if state is None:
            issues.append(
                _issue(
                    "missing_entity",
                    "Configured weather entity is absent",
                    condition_id,
                )
            )
        elif is_missing_state(state.state):
            issues.append(
                _issue("unavailable_state", f"State is {state.state!r}", condition_id)
            )
    return _domain(issues, [])


def _flow_health(
    flow: EnergyFlow,
    config: CollectorConfig,
    *,
    ev_active: bool | None,
    ev_power_w: float | None,
) -> HealthDomain:
    issues: list[HealthIssue] = []
    if flow.sign_convention_status == "unconfirmed":
        issues.append(
            _issue(
                "sign_conventions_unknown",
                "Grid and battery signs must be explicitly configured",
            )
        )
    elif flow.sign_convention_status == "unavailable":
        issues.append(
            _issue("derived_flow_unavailable", "Required raw flow values are missing")
        )
    if (
        flow.balance_residual_w is not None
        and abs(flow.balance_residual_w) > config.balance_tolerance_w
    ):
        issues.append(
            _issue(
                "balance_residual_too_large",
                f"Residual exceeds {config.balance_tolerance_w:g} W tolerance",
            )
        )
    if (
        ev_active is False
        and ev_power_w is not None
        and ev_power_w > config.balance_tolerance_w
    ):
        issues.append(
            _issue(
                "ev_telemetry_inconsistent",
                "EV power is positive while charging-active state is false",
            )
        )
    return _domain(issues, ["derived_flow", "grid_charge", "battery_export"])


def evaluate_data_health(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    *,
    now: datetime | None = None,
    energy_flow: EnergyFlow | None = None,
    ev_active: bool | None = None,
    ev_power_w: float | None = None,
    ev_health: EVTelemetryHealth | None = None,
) -> DataHealth:
    """Evaluate independent domains; overall currently follows telemetry integrity."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    telemetry = _telemetry_health(states, config, current)
    price = _price_health(states, config, current)
    solar = _solar_health(states, config, current)
    weather = _weather_health(states, config, current)
    flow = _flow_health(
        energy_flow
        or EnergyFlow(
            sign_convention_status="unconfirmed",
            sign_convention_confidence="unconfirmed",
        ),
        config,
        ev_active=ev_active,
        ev_power_w=ev_power_w,
    )
    overall = HealthDomain(
        is_healthy=telemetry.is_healthy,
        score=telemetry.score,
        issues=list(telemetry.issues),
        required_for=["display"],
    )
    return DataHealth(
        telemetry=telemetry,
        price=price,
        solar=solar,
        weather=weather,
        flow=flow,
        ev=ev_health or EVTelemetryHealth(),
        overall=overall,
    )


ReadinessAction = Literal["load_profile", "grid_charge", "battery_export"]


def is_ready_for(health: DataHealth, action: ReadinessAction) -> bool:
    """Return readiness for an advisory consumer; this never executes an action."""
    required = {
        "load_profile": (health.telemetry,),
        "grid_charge": (health.telemetry, health.price, health.solar, health.flow),
        "battery_export": (health.telemetry, health.price, health.solar, health.flow),
    }
    return all(domain.is_healthy for domain in required[action])
