"""Inspect raw and derived energy flows without modifying stored observations."""

import argparse
from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_sign_settings
from energy_optimizer.persistence import open_repository
from energy_optimizer.timestamps import compact_timestamp, json_safe, terminal_value

FLOW_COLUMNS = (
    "slot_utc",
    "pv_power_w",
    "house_consumption_w",
    "grid_power_w",
    "battery_power_w",
    "grid_import_power_w",
    "grid_export_power_w",
    "battery_charge_power_w",
    "battery_discharge_power_w",
    "balance_residual_w",
    "sign_convention_status",
    "event_labels_json",
    "ev_charging_active",
    "ev_power_w",
    "baseline_house_consumption_w",
    "baseline_training_eligible",
    "baseline_exclusion_reason",
)


def _slot_label(value: object) -> str:
    return compact_timestamp(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="Inspect this many recent days")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.days is not None and args.days <= 0:
        parser.error("--days must be positive")
    if args.limit <= 0:
        parser.error("--limit must be positive")
    start = datetime.now(UTC) - timedelta(days=args.days) if args.days else None
    rows = open_repository().observation_rows(start=start, columns=FLOW_COLUMNS)
    rows = rows[-args.limit :]
    console = Console()
    if args.json:
        console.print_json(
            data=json_safe({"configured_signs": load_sign_settings(), "rows": rows})
        )
        return 0
    settings = load_sign_settings()
    console.print(
        Panel(
            f"Grid sign: {settings['grid_power_sign']}\n"
            f"Battery sign: {settings['battery_power_sign']}\n"
            f"Confidence: {settings['confidence']} "
            f"({settings['supporting_samples']} supporting samples)\n"
            f"Balance tolerance: {settings['balance_tolerance_w']} W",
            title="Configured energy-flow conventions",
        )
    )
    table = Table(title="Raw and derived energy flows")
    for heading in (
        "UTC",
        "PV raw",
        "House raw",
        "Grid raw",
        "Batt raw",
        "Import",
        "Export",
        "Charge",
        "Discharge",
        "Residual",
        "Signs",
        "EV W",
        "Baseline",
        "Eligible",
        "Labels",
    ):
        table.add_column(heading)
    for row in reversed(rows):
        table.add_row(
            _slot_label(row["slot_utc"]),
            _value(row["pv_power_w"]),
            _value(row["house_consumption_w"]),
            _value(row["grid_power_w"]),
            _value(row["battery_power_w"]),
            _value(row["grid_import_power_w"]),
            _value(row["grid_export_power_w"]),
            _value(row["battery_charge_power_w"]),
            _value(row["battery_discharge_power_w"]),
            _value(row["balance_residual_w"]),
            row["sign_convention_status"],
            _value(row["ev_power_w"]),
            _value(row["baseline_house_consumption_w"]),
            "yes" if row["baseline_training_eligible"] else "no",
            terminal_value(row["event_labels_json"]),
        )
    console.print(table)
    console.print("Read-only inspection complete. Stored values were not modified.")
    return 0


def _value(value: object) -> str:
    return (
        "N/A"
        if value is None
        else str(round(value, 1) if isinstance(value, float) else value)
    )


if __name__ == "__main__":
    raise SystemExit(main())
