"""Domain-specific data health and action-readiness evaluation."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from energy_optimizer import entity_ids as ids
from energy_optimizer.models import (
    CollectorConfig,
    DataHealth,
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
        if parse_solar_summary(state) is None:
            issues.append(
                _issue(
                    "missing_solcast_summary",
                    "Required Solcast summary is missing",
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


def evaluate_data_health(
    states: dict[str, HomeAssistantState],
    config: CollectorConfig,
    *,
    now: datetime | None = None,
) -> DataHealth:
    """Evaluate independent domains; overall currently follows telemetry integrity."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    telemetry = _telemetry_health(states, config, current)
    price = _price_health(states, config, current)
    solar = _solar_health(states, config, current)
    weather = _domain([], [])
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
        overall=overall,
    )


ReadinessAction = Literal["load_profile", "grid_charge", "battery_export"]


def is_ready_for(health: DataHealth, action: ReadinessAction) -> bool:
    """Return readiness for an advisory consumer; this never executes an action."""
    required = {
        "load_profile": (health.telemetry,),
        "grid_charge": (health.telemetry, health.price, health.solar),
        "battery_export": (health.telemetry, health.price, health.solar),
    }
    return all(domain.is_healthy for domain in required[action])
