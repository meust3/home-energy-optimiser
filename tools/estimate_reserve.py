"""Estimate an advisory battery reserve from live or historical current state."""

import argparse
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_config, load_reserve_config
from energy_optimizer.historian import Historian
from energy_optimizer.home_assistant import HomeAssistantClient
from energy_optimizer.reserve import (
    estimate_battery_reserve,
    estimate_live_battery_reserve,
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
    args = parser.parse_args()
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
        ("Expected household demand", estimate.expected_house_demand_kwh),
        ("Expected EV demand", estimate.expected_ev_demand_kwh),
        ("Technical minimum", estimate.technical_reserve_kwh),
        ("Emergency reserve", estimate.emergency_reserve_kwh),
        ("Forecast uncertainty", estimate.uncertainty_buffer_kwh),
        ("Recommended reserve", estimate.recommended_reserve_kwh),
        ("Potentially tradable", estimate.potentially_tradable_kwh),
    ):
        table.add_row(label, _display(value))
    console.print(table)
    if estimate.current_state_source == "history" and estimate.observation_is_stale:
        console.print(
            f"[bold yellow]WARNING: {estimate.observation_warning}[/bold yellow]"
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
    console.print(
        f"Confidence: {estimate.confidence} ({estimate.confidence_score}/100)"
    )
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
