"""Estimate an advisory battery reserve from local history only."""

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_reserve_config
from energy_optimizer.historian import Historian
from energy_optimizer.reserve import estimate_battery_reserve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()
    config = load_reserve_config()
    estimate = estimate_battery_reserve(Historian(config.database_path), config)
    console = Console()
    if args.json:
        console.print_json(data=estimate.model_dump(mode="json"))
        return 0
    table = Table(title="Advisory battery reserve estimate")
    table.add_column("Measure")
    table.add_column("kWh", justify="right")
    for label, value in (
        ("Current battery", estimate.battery_energy_kwh),
        ("Expected household demand", estimate.expected_house_demand_kwh),
        ("Expected EV demand", estimate.expected_ev_demand_kwh),
        ("Technical minimum", estimate.technical_reserve_kwh),
        ("Emergency reserve", estimate.emergency_reserve_kwh),
        ("Forecast uncertainty", estimate.uncertainty_buffer_kwh),
        ("Recommended reserve", estimate.recommended_reserve_kwh),
        ("Potentially tradable", estimate.potentially_tradable_kwh),
    ):
        table.add_row(label, "missing" if value is None else f"{value:.3f}")
    console.print(table)
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


if __name__ == "__main__":
    raise SystemExit(main())
