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
        f"Coverage: {report['coverage_percent']:.2f}%\n"
        f"First missing: {_period_label(report['first_missing_period'])}\n"
        f"Last missing:  {_period_label(report['last_missing_period'])}\n"
        f"Longest gap:   {_period_label(report['longest_missing_period'])}"
    )
    console.print(Panel(body, title="Collection coverage", border_style="blue"))


def _period_label(period: dict[str, Any] | None) -> str:
    if not period:
        return "none"
    return (
        f"{period['start'][:16]} -> {period['end'][:16]} "
        f"({period['slots']} slots / {period['minutes']} min)"
    )


def _render_health_summary(
    console: Console,
    counts: dict[str, Any],
    summary: dict[str, Any],
    *,
    details: bool,
) -> None:
    rows = []
    for domain, domain_details in summary.items():
        common = domain_details["most_common_issues"]
        common_label = "N/A"
        if common:
            first = common[0]
            common_label = f"{first['code']} ({first['count']})"
        rows.append(
            {
                "domain": domain,
                "ok": counts[domain]["healthy"],
                "bad": counts[domain]["unhealthy"],
                "warn": domain_details["warning_count"],
                "err": domain_details["error_count"],
                "avg": domain_details["average_score"],
                "top_issue": common_label,
            }
        )
    _table(console, "Health by domain", rows)
    if details:
        common_rows = [
            {"domain": domain, **issue}
            for domain, domain_details in summary.items()
            for issue in domain_details["most_common_issues"]
        ]
        _table(console, "Most common health issues", common_rows, max_rows=20)


def _recent_rows(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    return [
        {
            "utc": row["slot_utc"][5:16].replace("T", " "),
            "soc": row["battery_soc_percent"],
            "house": (
                row["house_consumption_w"] / 1000
                if row["house_consumption_w"] is not None
                else None
            ),
            "pv": (row["pv_power_w"] / 1000 if row["pv_power_w"] is not None else None),
            "grid_raw": (
                row["grid_power_w"] / 1000 if row["grid_power_w"] is not None else None
            ),
            "overall": (
                f"{'OK' if row['is_healthy'] else 'BAD'} {row['health_score']}"
            ),
        }
        for row in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="Only include this many recent days")
    parser.add_argument("--limit", type=int, default=5, help="Recent row limit")
    parser.add_argument(
        "--details", action="store_true", help="Show secondary analytical tables"
    )
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
    domain_counts = {
        **summary["health_domains"],
        "overall": {
            "healthy": summary["healthy"],
            "unhealthy": summary["unhealthy"],
        },
    }
    _render_health_summary(
        console,
        domain_counts,
        summary["health_issue_summary"],
        details=args.details,
    )
    _table(console, "Recent observations", _recent_rows(summary["recent"]))
    if args.details:
        _table(
            console,
            "Missing values",
            [
                {"field": key, "count": value}
                for key, value in summary["missing"].items()
            ],
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
