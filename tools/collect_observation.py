"""Collect exactly one read-only Home Assistant observation."""

import argparse

from rich.console import Console
from rich.table import Table

from energy_optimizer.collector import Collector
from energy_optimizer.config import load_config
from energy_optimizer.historian import Historian
from energy_optimizer.home_assistant import HomeAssistantClient
from energy_optimizer.models import HealthDomain


def _health_label(domain: HealthDomain) -> str:
    status = "healthy" if domain.is_healthy else "unhealthy"
    return f"{domain.score}/100 ({status})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--no-save", action="store_true", help="Do not write SQLite")
    args = parser.parse_args()
    config = load_config()
    with HomeAssistantClient(
        config.ha_url,
        config.ha_token,
        timeout_seconds=config.request_timeout_seconds,
    ) as client:
        observation = Collector(client, config).collect()
    if not args.no_save:
        Historian(config.database_path).save(observation)
    console = Console()
    if args.json:
        console.print_json(
            data={
                **observation.model_dump(mode="json"),
                "saved": not args.no_save,
                "command_issued": False,
            }
        )
    else:
        table = Table(title="Home Energy Observation")
        table.add_column("Field")
        table.add_column("Value")
        for label, value in (
            ("UTC slot", observation.slot_utc.isoformat()),
            ("Battery SOC", observation.battery_soc_percent),
            ("Battery energy (estimate)", observation.battery_energy_estimate_kwh),
            ("House consumption (W)", observation.house_consumption_w),
            ("PV power (W)", observation.pv_power_w),
            ("Grid power (W, raw sign)", observation.grid_power_w),
            (
                "Telemetry health",
                _health_label(observation.data_health.telemetry),
            ),
            (
                "Price health",
                _health_label(observation.data_health.price),
            ),
            (
                "Solar health",
                _health_label(observation.data_health.solar),
            ),
            (
                "Weather health",
                _health_label(observation.data_health.weather),
            ),
            (
                "Overall health",
                _health_label(observation.data_health.overall),
            ),
            ("Saved", not args.no_save),
        ):
            table.add_row(label, "missing" if value is None else str(value))
        console.print(table)
        console.print("Read-only collection complete. No command was issued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
