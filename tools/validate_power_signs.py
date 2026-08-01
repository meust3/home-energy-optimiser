"""Analyze likely GoodWe power signs from stored observations without modifying data."""

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_database_path, load_timezone_name
from energy_optimizer.historian import Historian
from energy_optimizer.power_signs import analyze_power_signs
from energy_optimizer.time_ranges import parse_range_value


def _metric(value: object, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="Inclusive ISO date or datetime")
    parser.add_argument("--end", help="Inclusive ISO date or datetime")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()
    timezone_name = load_timezone_name()
    try:
        start = parse_range_value(args.start, timezone_name) if args.start else None
        end = parse_range_value(args.end, timezone_name, end=True) if args.end else None
    except ValueError as exc:
        parser.error(str(exc))
    if start and end and end < start:
        parser.error("--end must not be before --start")
    historian = Historian(load_database_path())
    result = analyze_power_signs(historian.power_sign_samples(start=start, end=end))
    console = Console()
    if args.json:
        console.print_json(data=result)
        return 0
    console.print(
        Panel(
            f"Complete samples: {result['sample_count']}\n"
            f"Excluded incomplete samples: {result['excluded_incomplete_samples']}\n"
            f"Confidence: [bold]{result['confidence']}[/bold]\n"
            f"Best-vs-second improvement: "
            f"{_metric(result['best_vs_second_improvement_percent'], '%')}\n\n"
            f"{result['disclaimer']}",
            title="GoodWe power-sign analysis",
            border_style="yellow",
        )
    )
    table = Table(title="Energy-balance hypotheses")
    for heading in (
        "Grid + means",
        "Battery + means",
        "Samples",
        "MAE W",
        "RMSE W",
        "Bias W",
    ):
        table.add_column(heading)
    for hypothesis in result["hypotheses"]:
        table.add_row(
            hypothesis["grid_positive_likely_means"],
            hypothesis["battery_positive_likely_means"],
            str(hypothesis["sample_count"]),
            _metric(hypothesis["mean_absolute_residual_w"]),
            _metric(hypothesis["root_mean_square_residual_w"]),
            _metric(hypothesis["mean_signed_residual_w"]),
        )
    console.print(table)
    mode_table = Table(title="Battery-mode evidence")
    for heading in ("Mode", "Samples", "Average W", "Positive", "Negative", "Zero"):
        mode_table.add_column(heading)
    for row in result["battery_mode_evidence"]:
        mode_table.add_row(
            row["battery_mode"],
            str(row["sample_count"]),
            str(row["average_battery_power_w"]),
            str(row["positive_samples"]),
            str(row["negative_samples"]),
            str(row["zero_samples"]),
        )
    console.print(mode_table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
