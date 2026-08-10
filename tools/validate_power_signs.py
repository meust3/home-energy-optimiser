"""Analyze likely GoodWe power signs from stored observations without modifying data."""

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_timezone_name
from energy_optimizer.persistence import open_repository
from energy_optimizer.power_signs import analyze_power_signs
from energy_optimizer.time_ranges import parse_range_value, resolve_history_range
from energy_optimizer.timestamps import compact_timestamp, json_safe


def _metric(value: object, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value}{suffix}"


def _example_label(example: dict[str, object] | None) -> str:
    if not example:
        return "N/A"
    slot = compact_timestamp(example.get("slot_utc"))
    return f"{slot} ({_metric(example.get('residual_w'), ' W')})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="Inclusive ISO date or datetime")
    parser.add_argument("--end", help="Inclusive ISO date or datetime")
    parser.add_argument("--days", type=int, help="Analyze this many recent days")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()
    timezone_name = load_timezone_name()
    try:
        if args.days is not None:
            start, end = resolve_history_range(
                from_value=args.start,
                to_value=args.end,
                days=args.days,
                timezone_name=timezone_name,
            )
        else:
            start = parse_range_value(args.start, timezone_name) if args.start else None
            end = (
                parse_range_value(args.end, timezone_name, end=True)
                if args.end
                else None
            )
    except ValueError as exc:
        parser.error(str(exc))
    if start and end and end < start:
        parser.error("--end must not be before --start")
    historian = open_repository()
    result = analyze_power_signs(historian.power_sign_samples(start=start, end=end))
    console = Console()
    if args.json:
        console.print_json(data=json_safe(result))
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
        "N",
        "MAE W",
        "Median W",
        "Confidence",
    ):
        table.add_column(heading)
    for hypothesis in result["hypotheses"]:
        table.add_row(
            hypothesis["grid_positive_likely_means"],
            hypothesis["battery_positive_likely_means"],
            str(hypothesis["sample_count"]),
            _metric(hypothesis["mean_absolute_residual_w"]),
            _metric(hypothesis["median_residual_w"]),
            hypothesis["confidence"],
        )
    console.print(table)
    evidence = Table(title="Residual evidence by convention")
    for heading in (
        "Grid +",
        "Battery +",
        "Supporting example",
        "Contradicting example",
    ):
        evidence.add_column(heading)
    for hypothesis in result["hypotheses"]:
        evidence.add_row(
            hypothesis["grid_positive_likely_means"],
            hypothesis["battery_positive_likely_means"],
            _example_label(next(iter(hypothesis["supporting_examples"]), None)),
            _example_label(next(iter(hypothesis["contradicting_examples"]), None)),
        )
    console.print(evidence)
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
    suggestion = result["suggested_configuration"]
    if suggestion:
        console.print("Suggested configuration (review before applying):")
        for name, value in suggestion.items():
            console.print(f"  {name}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
