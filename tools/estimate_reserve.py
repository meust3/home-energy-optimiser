"""Estimate an advisory battery reserve from live or historical current state."""

import argparse
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_config, load_database_path, load_reserve_config
from energy_optimizer.historian import Historian
from energy_optimizer.home_assistant import HomeAssistantClient
from energy_optimizer.reserve import (
    estimate_battery_reserve,
    estimate_live_battery_reserve,
    store_reserve_forecast,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument(
        "--source",
        choices=("live", "history"),
        default="live",
        help="Current-state source (default: live GET-only collection)",
    )
    parser.add_argument(
        "--save-observation",
        action="store_true",
        help="Save a live observation; off by default",
    )
    parser.add_argument(
        "--as-of",
        type=_aware_datetime,
        help="Timezone-aware instant for deterministic history replay",
    )
    parser.add_argument(
        "--score-run",
        type=int,
        help="Score a completed reserve forecast run against stored actuals",
    )
    args = parser.parse_args()
    if args.score_run is not None:
        result = Historian(load_database_path()).score_reserve_forecast(args.score_run)
        console = Console()
        if args.json:
            console.print_json(data=result)
        else:
            console.print(Panel(str(result), title="Reserve forecast scoring"))
        return 0
    if args.source != "live" and args.save_observation:
        parser.error("--save-observation is only valid with --source live")
    if args.source != "history" and args.as_of is not None:
        parser.error("--as-of is only valid with --source history")
    if args.source == "live":
        config = load_config()
        historian = Historian(config.database_path)
        with HomeAssistantClient(
            config.ha_url,
            config.ha_token,
            timeout_seconds=config.request_timeout_seconds,
        ) as client:
            estimate = estimate_live_battery_reserve(
                historian,
                config,
                client,
                save_observation=args.save_observation,
            )
    else:
        config = load_reserve_config()
        historian = Historian(config.database_path)
        estimate = estimate_battery_reserve(
            historian,
            config,
            source="history",
            as_of=args.as_of,
        )
    store_reserve_forecast(historian, estimate)
    console = Console()
    if args.json:
        console.print_json(data=estimate.model_dump(mode="json"))
        return 0
    table = Table(title="Advisory battery reserve estimate")
    table.add_column("Measure")
    table.add_column("Value", justify="right")
    for label, value in (
        ("Current-state source", estimate.current_state_source),
        ("Observation timestamp", estimate.observation_timestamp.isoformat()),
        ("Observation age", _format_age(estimate.observation_age_seconds)),
        ("Battery SOC used", _unit(estimate.battery_soc_percent, "%")),
        (
            "Usable capacity assumption",
            _unit(estimate.usable_battery_capacity_kwh, "kWh"),
        ),
        ("Calculated battery energy", _unit(estimate.battery_energy_kwh, "kWh")),
        ("Forecast horizon", f"{estimate.forecast_horizon_hours:.2f} hours"),
        ("Average forecast load", _unit(estimate.average_forecast_load_kw, "kW")),
        ("Expected household demand", estimate.expected_house_demand_kwh),
        ("Expected EV demand", estimate.expected_ev_demand_kwh),
        ("Technical minimum", estimate.technical_reserve_kwh),
        ("Emergency reserve", estimate.emergency_reserve_kwh),
        ("Forecast uncertainty", estimate.uncertainty_buffer_kwh),
        ("Gross reserve requirement", estimate.gross_reserve_requirement_kwh),
        ("Capacity-capped reserve", estimate.capacity_capped_reserve_kwh),
        ("Unmet reserve requirement", estimate.unmet_reserve_requirement_kwh),
        ("Current reserve shortfall", estimate.current_reserve_shortfall_kwh),
        ("Recommended reserve", estimate.recommended_reserve_kwh),
        ("Potentially tradable", estimate.potentially_tradable_kwh),
    ):
        table.add_row(label, _display(value))
    console.print(table)
    if estimate.current_state_source == "history" and estimate.observation_is_stale:
        console.print(
            f"[bold yellow]WARNING: {estimate.observation_warning}[/bold yellow]"
        )
    diagnostics = estimate.demand_forecast.diagnostics
    diagnostic_table = Table(title="Demand-history qualification")
    diagnostic_table.add_column("Diagnostic")
    diagnostic_table.add_column("Value", justify="right")
    for label, value in (
        ("Historical observations examined", diagnostics.total_observations_examined),
        ("Eligible baseline observations", diagnostics.eligible_baseline_observations),
        (
            "Minimum samples per weekday/slot",
            diagnostics.minimum_samples_per_weekday_slot,
        ),
        (
            "Forecast slots qualified from history",
            diagnostics.historical_slots_qualified,
        ),
        (
            "Slots with some but insufficient history",
            diagnostics.slots_with_insufficient_matching_history,
        ),
        ("Slots with no matching history", diagnostics.slots_with_no_matching_history),
        (
            "Same partial-day samples excluded",
            diagnostics.same_partial_day_samples_excluded,
        ),
        ("Future samples excluded", diagnostics.future_samples_excluded),
    ):
        diagnostic_table.add_row(label, str(value))
    for reason, count in diagnostics.ineligible_observations_by_reason.items():
        diagnostic_table.add_row(f"Ineligible: {reason}", str(count))
    console.print(diagnostic_table)
    console.print(diagnostics.matching_rule)
    console.print(diagnostics.legacy_row_policy)

    tier_table = Table(title="Hierarchical demand forecast")
    tier_table.add_column("Tier")
    tier_table.add_column("Available samples", justify="right")
    tier_table.add_column("Forecast slots", justify="right")
    tier_table.add_column("Energy kWh", justify="right")
    tier_table.add_column("Variability", justify="right")
    tier_table.add_column("Avg age days", justify="right")
    for tier, contribution in diagnostics.tier_contributions.items():
        tier_table.add_row(
            tier,
            str(diagnostics.samples_available_by_tier.get(tier, 0)),
            str(contribution.slot_count),
            f"{contribution.energy_kwh:.3f}",
            (
                "N/A"
                if contribution.average_variability is None
                else f"{contribution.average_variability:.3f}"
            ),
            (
                "N/A"
                if contribution.average_sample_age_days is None
                else f"{contribution.average_sample_age_days:.1f}"
            ),
        )
    console.print(tier_table)
    console.print(f"Configured fallback share: {diagnostics.fallback_share:.1%}")
    console.print(
        f"History: {diagnostics.history_duration_days:.0f} calendar days, "
        f"{diagnostics.complete_daily_periods} complete days, "
        f"{diagnostics.complete_overnight_periods} complete overnights"
    )
    console.print(
        f"Shares: exact {diagnostics.exact_history_share:.1%}, grouped "
        f"{diagnostics.grouped_history_share:.1%}, recent band "
        f"{diagnostics.recent_band_share:.1%}, fallback "
        f"{diagnostics.configured_fallback_share:.1%}, weak estimates "
        f"{diagnostics.weak_estimate_share:.1%}"
    )
    if diagnostics.ev_contamination_risk:
        console.print(f"[yellow]{diagnostics.ev_contamination_risk}[/yellow]")

    fallback_table = Table(title="Configured fallback assumptions")
    fallback_table.add_column("Local-time band")
    fallback_table.add_column("Configured kW", justify="right")
    fallback_table.add_column("Slots", justify="right")
    fallback_table.add_column("Energy kWh", justify="right")
    for band, contribution in estimate.demand_forecast.fallback_contributions.items():
        fallback_table.add_row(
            band.replace("_", " "),
            f"{contribution.configured_power_kw:.3f}",
            str(contribution.slot_count),
            f"{contribution.energy_kwh:.3f}",
        )
    console.print(fallback_table)
    console.print(
        "Fallback values are configured conservative assumptions; they were not "
        "learned from household history."
    )
    console.print(
        Panel(
            f"Type: {estimate.next_opportunity.opportunity_type}\n"
            f"Start: {estimate.next_opportunity.expected_start_local.isoformat()}\n"
            f"End: {estimate.next_opportunity.expected_end_local.isoformat()}\n"
            f"Confidence: {estimate.next_opportunity.confidence}",
            title="Next replenishment opportunity",
        )
    )
    confidence_table = Table(title="Confidence components")
    confidence_table.add_column("Component")
    confidence_table.add_column("Rating")
    confidence_table.add_column("Score", justify="right")
    confidence_table.add_column("Ceilings")
    for label, component in (
        ("Data availability", estimate.data_availability_confidence),
        ("Household demand", estimate.household_demand_confidence),
        ("Opportunity", estimate.opportunity_forecast_confidence),
        ("Overall reserve", estimate.overall_reserve_confidence),
    ):
        confidence_table.add_row(
            label,
            component.rating,
            str(component.score),
            ", ".join(component.ceilings) or "none",
        )
    console.print(confidence_table)
    console.print(f"Stored forecast run: {estimate.forecast_run_id}")
    console.print(f"Ready for manual review: {estimate.ready_for_manual_review}")
    console.print(estimate.reasoning)
    console.print("Strictly read-only advisory output. No command was issued.")
    return 0


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--as-of must be an ISO 8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--as-of must include a UTC offset")
    return parsed


def _format_age(seconds: float) -> str:
    minutes = seconds / 60
    return f"{minutes:.1f} minutes"


def _unit(value: float | None, unit: str) -> str:
    return "missing" if value is None else f"{value:.3f} {unit}"


def _display(value: object) -> str:
    if value is None:
        return "missing"
    if isinstance(value, float):
        return f"{value:.3f} kWh"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
