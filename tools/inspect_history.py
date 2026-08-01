"""Inspect locally stored home-energy history."""

import argparse
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from energy_optimizer.config import load_database_path
from energy_optimizer.historian import Historian


def _value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _table(
    console: Console,
    title: str,
    rows: list[dict[str, object]],
    *,
    max_rows: int | None = None,
) -> None:
    if not rows:
        console.print(Panel("No data", title=title, border_style="dim"))
        return
    table = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold cyan")
    for key in rows[0]:
        table.add_column(key.replace("_", " ").title())
    for row in rows[:max_rows]:
        table.add_row(*(_value(row.get(key)) for key in rows[0]))
    console.print(table)


def _render_gap(console: Console, report: dict[str, Any]) -> None:
    body = (
        f"Range: {report['range_start'] or 'N/A'} -> "
        f"{report['range_end'] or 'N/A'}\n"
        f"Expected: {report['expected_slots']:,}   "
        f"Collected: {report['collected_slots']:,}   "
        f"Missing: {report['missing_slots']:,}\n"
        f"Coverage: {report['coverage_percent']:.2f}%   "
        f"Longest gap: {report['longest_gap_slots']} slots "
        f"({report['longest_gap_minutes']} minutes)"
    )
    if report["longest_gap_start"]:
        body += (
            f"\nLongest gap range: {report['longest_gap_start']} -> "
            f"{report['longest_gap_end']}"
        )
    console.print(Panel(body, title="Collection coverage", border_style="blue"))


def _render_issue_summary(console: Console, summary: dict[str, Any]) -> None:
    rows = []
    for domain, details in summary.items():
        common = details["most_common_issues"]
        common_label = "N/A"
        if common:
            first = common[0]
            common_label = f"{first['code']} ({first['count']})"
        rows.append(
            {
                "domain": domain,
                "average_score": details["average_score"],
                "warnings": details["warning_count"],
                "errors": details["error_count"],
                "most_common": common_label,
            }
        )
    _table(console, "Health issue summary", rows)
    common_rows = [
        {"domain": domain, **issue}
        for domain, details in summary.items()
        for issue in details["most_common_issues"]
    ]
    _table(console, "Most common health issues", common_rows, max_rows=20)


def _health_cell(row: dict[str, Any], prefix: str) -> str:
    status = "OK" if row[f"{prefix}_is_healthy"] else "BAD"
    return f"{status} {row[f'{prefix}_health_score']}"


def _recent_rows(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    return [
        {
            "slot_utc": row["slot_utc"],
            "soc_%": row["battery_soc_percent"],
            "house_kw": (
                row["house_consumption_w"] / 1000
                if row["house_consumption_w"] is not None
                else None
            ),
            "pv_kw": (
                row["pv_power_w"] / 1000 if row["pv_power_w"] is not None else None
            ),
            "grid_kw_raw": (
                row["grid_power_w"] / 1000 if row["grid_power_w"] is not None else None
            ),
            "telemetry": _health_cell(row, "telemetry"),
            "price": _health_cell(row, "price"),
            "solar": _health_cell(row, "solar"),
            "weather": _health_cell(row, "weather"),
            "overall": (
                f"{'OK' if row['is_healthy'] else 'BAD'} {row['health_score']}"
            ),
        }
        for row in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="Only include this many recent days")
    parser.add_argument("--limit", type=int, default=10, help="Recent row limit")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()
    if args.days is not None and args.days <= 0:
        parser.error("--days must be positive")
    if args.limit <= 0:
        parser.error("--limit must be positive")
    summary = Historian(load_database_path()).summary(days=args.days, limit=args.limit)
    console = Console()
    if args.json:
        console.print_json(data=summary)
        return 0
    console.print(
        Panel(
            f"[bold]{summary['database_path']}[/bold]\n"
            f"{summary['total']:,} observations | "
            f"{summary['healthy']:,} healthy | {summary['unhealthy']:,} unhealthy",
            title="Home Energy History",
            border_style="green",
        )
    )
    _render_gap(console, summary["gap_report"])
    _table(
        console,
        "Health by domain",
        [
            {"domain": domain, **counts}
            for domain, counts in summary["health_domains"].items()
        ],
    )
    _render_issue_summary(console, summary["health_issue_summary"])
    _table(
        console,
        "Missing values",
        [{"field": key, "count": value} for key, value in summary["missing"].items()],
    )
    _table(
        console,
        "Average house consumption by hour",
        summary["average_house_kw_by_hour"],
    )
    _table(
        console,
        "Average house consumption by weekday",
        [
            {
                **row,
                "day_of_week": (
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                )[row["day_of_week"]],
            }
            for row in summary["average_house_kw_by_weekday"]
        ],
    )
    _table(console, "Recent observations", _recent_rows(summary["recent"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
