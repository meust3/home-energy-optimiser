"""Dry-run or apply auditable historical derived-field reprocessing."""

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_reprocessing_config
from energy_optimizer.historian import Historian
from energy_optimizer.reprocessing import reprocess_observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply derived updates")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_reprocessing_config()
    report = reprocess_observations(
        Historian(config.database_path), config, apply=args.apply
    )
    console = Console()
    if args.json:
        console.print_json(data=report.model_dump(mode="json"))
        return 0
    if args.apply:
        console.print(
            Panel(
                "Applied derived-field updates only. Raw telemetry was not changed.",
                title="Historical reprocessing applied",
            )
        )
    else:
        console.print(
            Panel(
                "Dry run only; the database was not modified. Before --apply, copy "
                "data/energy_history.db to a timestamped backup file.",
                title="Historical reprocessing dry run",
            )
        )
    table = Table()
    table.add_column("Measure")
    table.add_column("Value", justify="right")
    for label, value in (
        ("Rows examined", report.rows_examined),
        ("Eligible for derivation", report.rows_eligible_for_reprocessing),
        ("Would become baseline eligible", report.rows_becoming_baseline_eligible),
        ("Remaining ineligible", report.rows_remaining_ineligible),
        ("Residual samples", report.residual_sample_count),
        ("Mean absolute residual W", report.mean_absolute_residual_w),
        ("Median absolute residual W", report.median_absolute_residual_w),
        ("Maximum absolute residual W", report.maximum_absolute_residual_w),
        ("Rows exceeding tolerance", report.rows_exceeding_tolerance),
        ("Audit records added", report.audit_records_added),
    ):
        table.add_row(label, "N/A" if value is None else str(value))
    for reason, count in report.exclusion_reasons.items():
        table.add_row(f"Excluded: {reason}", str(count))
    console.print(table)
    console.print("No Home Assistant or hardware command was issued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
