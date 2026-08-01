"""Inspect locally stored home-energy history."""

import argparse

from rich.console import Console
from rich.table import Table

from energy_optimizer.config import load_database_path
from energy_optimizer.historian import Historian


def _table(console: Console, title: str, rows: list[dict[str, object]]) -> None:
    table = Table(title=title)
    if not rows:
        console.print(f"{title}: no data")
        return
    for key in rows[0]:
        table.add_column(key)
    for row in rows:
        table.add_row(*(str(row.get(key, "")) for key in rows[0]))
    console.print(table)


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
    database_path = load_database_path()
    summary = Historian(database_path).summary(days=args.days, limit=args.limit)
    console = Console()
    if args.json:
        console.print_json(data=summary)
        return 0
    console.print(f"Database: {summary['database_path']}")
    console.print(
        f"Observations: {summary['total']} total; {summary['healthy']} healthy; "
        f"{summary['unhealthy']} unhealthy"
    )
    _table(
        console,
        "Health by domain",
        [
            {"domain": domain, **counts}
            for domain, counts in summary["health_domains"].items()
        ],
    )
    console.print(
        f"Range: {summary['earliest'] or 'none'} to {summary['latest'] or 'none'}"
    )
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
        summary["average_house_kw_by_weekday"],
    )
    _table(console, "Recent observations", summary["recent"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
