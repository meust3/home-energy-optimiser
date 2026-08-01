"""SQLite persistence and read-only analytical queries."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from energy_optimizer.models import EnergyObservation

SCHEMA_VERSION = 2

DOMAIN_COLUMNS = {
    "telemetry_is_healthy": "INTEGER NOT NULL DEFAULT 0",
    "telemetry_health_score": "INTEGER NOT NULL DEFAULT 0",
    "price_is_healthy": "INTEGER NOT NULL DEFAULT 0",
    "price_health_score": "INTEGER NOT NULL DEFAULT 0",
    "solar_is_healthy": "INTEGER NOT NULL DEFAULT 0",
    "solar_health_score": "INTEGER NOT NULL DEFAULT 0",
    "weather_is_healthy": "INTEGER NOT NULL DEFAULT 1",
    "weather_health_score": "INTEGER NOT NULL DEFAULT 100",
    "health_domains_json": "TEXT",
}


class Historian:
    """Persist observations; duplicate slots use last-write-wins upsert."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    slot_utc TEXT PRIMARY KEY,
                    observed_at_utc TEXT NOT NULL,
                    observed_at_local TEXT NOT NULL,
                    battery_soc_percent REAL,
                    battery_energy_estimate_kwh REAL,
                    battery_power_w REAL,
                    battery_mode TEXT,
                    pv_power_w REAL,
                    house_consumption_w REAL,
                    grid_power_w REAL,
                    work_mode TEXT,
                    amber_import_price_per_kwh REAL,
                    amber_export_price_per_kwh REAL,
                    amber_price_spike INTEGER,
                    amber_import_forecast_json TEXT NOT NULL,
                    amber_export_forecast_json TEXT NOT NULL,
                    solcast_remaining_today_json TEXT,
                    solcast_tomorrow_json TEXT,
                    solcast_next_hour_json TEXT,
                    solcast_this_hour_json TEXT,
                    solcast_today_json TEXT,
                    solcast_power_now_w REAL,
                    temperature_c REAL,
                    weather_condition TEXT,
                    is_healthy INTEGER NOT NULL,
                    health_score INTEGER NOT NULL,
                    health_issues_json TEXT NOT NULL,
                    telemetry_is_healthy INTEGER NOT NULL DEFAULT 0,
                    telemetry_health_score INTEGER NOT NULL DEFAULT 0,
                    price_is_healthy INTEGER NOT NULL DEFAULT 0,
                    price_health_score INTEGER NOT NULL DEFAULT 0,
                    solar_is_healthy INTEGER NOT NULL DEFAULT 0,
                    solar_health_score INTEGER NOT NULL DEFAULT 0,
                    weather_is_healthy INTEGER NOT NULL DEFAULT 1,
                    weather_health_score INTEGER NOT NULL DEFAULT 100,
                    health_domains_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_observations_health_time
                    ON observations(is_healthy, slot_utc);
                """)
            existing_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(observations)")
            }
            added_domain_columns = False
            for name, declaration in DOMAIN_COLUMNS.items():
                if name not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE observations ADD COLUMN {name} {declaration}"
                    )
                    added_domain_columns = True
            if added_domain_columns:
                legacy_marker = self._json(
                    {
                        "migration": "legacy_global_health",
                        "domain_health_unavailable": True,
                    }
                )
                connection.execute(
                    """
                    UPDATE observations SET
                        telemetry_is_healthy=is_healthy,
                        telemetry_health_score=health_score,
                        price_is_healthy=is_healthy,
                        price_health_score=health_score,
                        solar_is_healthy=is_healthy,
                        solar_health_score=health_score,
                        weather_is_healthy=1,
                        weather_health_score=100,
                        health_domains_json=?
                    """,
                    (legacy_marker,),
                )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_observations_telemetry_health_time
                ON observations(telemetry_is_healthy, slot_utc)"""
            )
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM schema_version"
            ).fetchone()
            if row["count"] == 0:
                connection.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,)
                )
            else:
                connection.execute(
                    "UPDATE schema_version SET version=?", (SCHEMA_VERSION,)
                )

    @staticmethod
    def _json(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        elif isinstance(value, list):
            value = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in value
            ]
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    def save(self, observation: EnergyObservation) -> None:
        self.migrate()
        columns = (
            "slot_utc",
            "observed_at_utc",
            "observed_at_local",
            "battery_soc_percent",
            "battery_energy_estimate_kwh",
            "battery_power_w",
            "battery_mode",
            "pv_power_w",
            "house_consumption_w",
            "grid_power_w",
            "work_mode",
            "amber_import_price_per_kwh",
            "amber_export_price_per_kwh",
            "amber_price_spike",
            "amber_import_forecast_json",
            "amber_export_forecast_json",
            "solcast_remaining_today_json",
            "solcast_tomorrow_json",
            "solcast_next_hour_json",
            "solcast_this_hour_json",
            "solcast_today_json",
            "solcast_power_now_w",
            "temperature_c",
            "weather_condition",
            "is_healthy",
            "health_score",
            "health_issues_json",
            "telemetry_is_healthy",
            "telemetry_health_score",
            "price_is_healthy",
            "price_health_score",
            "solar_is_healthy",
            "solar_health_score",
            "weather_is_healthy",
            "weather_health_score",
            "health_domains_json",
        )
        values = (
            observation.slot_utc.isoformat(),
            observation.observed_at_utc.isoformat(),
            observation.observed_at_local.isoformat(),
            observation.battery_soc_percent,
            observation.battery_energy_estimate_kwh,
            observation.battery_power_w,
            observation.battery_mode,
            observation.pv_power_w,
            observation.house_consumption_w,
            observation.grid_power_w,
            observation.work_mode,
            observation.amber_import_price_per_kwh,
            observation.amber_export_price_per_kwh,
            (
                None
                if observation.amber_price_spike is None
                else int(observation.amber_price_spike)
            ),
            self._json(observation.amber_import_forecast),
            self._json(observation.amber_export_forecast),
            self._json(observation.solcast_remaining_today),
            self._json(observation.solcast_tomorrow),
            self._json(observation.solcast_next_hour),
            self._json(observation.solcast_this_hour),
            self._json(observation.solcast_today),
            observation.solcast_power_now_w,
            observation.temperature_c,
            observation.weather_condition,
            int(observation.data_health.is_healthy),
            observation.data_health.health_score,
            self._json(observation.data_health.issues),
            int(observation.data_health.telemetry.is_healthy),
            observation.data_health.telemetry.score,
            int(observation.data_health.price.is_healthy),
            observation.data_health.price.score,
            int(observation.data_health.solar.is_healthy),
            observation.data_health.solar.score,
            int(observation.data_health.weather.is_healthy),
            observation.data_health.weather.score,
            self._json(observation.data_health),
        )
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(
            f"{column}=excluded.{column}" for column in columns if column != "slot_utc"
        )
        sql = (
            f"INSERT INTO observations ({','.join(columns)}) "
            f"VALUES ({placeholders}) ON CONFLICT(slot_utc) "
            f"DO UPDATE SET {updates}"
        )
        with self.connect() as connection:
            connection.execute(sql, values)

    def summary(self, *, days: int | None = None, limit: int = 10) -> dict[str, Any]:
        self.migrate()
        cutoff = None
        if days is not None:
            cutoff = datetime.now(UTC).timestamp() - days * 86400
            cutoff = datetime.fromtimestamp(cutoff, UTC).isoformat()
        where = "WHERE slot_utc >= ?" if cutoff else ""
        params: tuple[Any, ...] = (cutoff,) if cutoff else ()
        with self.connect() as connection:
            counts_sql = (
                "SELECT COUNT(*) total, SUM(is_healthy) healthy, "
                "SUM(telemetry_is_healthy) telemetry_healthy, "
                "SUM(price_is_healthy) price_healthy, "
                "SUM(solar_is_healthy) solar_healthy, "
                "SUM(weather_is_healthy) weather_healthy, "
                "MIN(slot_utc) earliest, MAX(slot_utc) latest "
                f"FROM observations {where}"
            )
            counts = connection.execute(counts_sql, params).fetchone()
            missing_columns = (
                "battery_soc_percent",
                "battery_power_w",
                "pv_power_w",
                "house_consumption_w",
                "grid_power_w",
                "amber_import_price_per_kwh",
                "amber_export_price_per_kwh",
            )
            missing_expressions = ",".join(
                f"SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END) AS {column}"
                for column in missing_columns
            )
            missing = connection.execute(
                f"SELECT {missing_expressions} FROM observations {where}", params
            ).fetchone()
            local_hour = "CAST(substr(observed_at_local, 12, 2) AS INTEGER)"
            condition = "AND" if where else "WHERE"
            hourly_sql = (
                f"SELECT {local_hour} hour, "
                "AVG(house_consumption_w)/1000.0 average_kw, "
                "COUNT(house_consumption_w) samples "
                f"FROM observations {where} {condition} "
                "house_consumption_w IS NOT NULL GROUP BY hour ORDER BY hour"
            )
            by_hour = connection.execute(hourly_sql, params).fetchall()
            recent_sql = (
                "SELECT slot_utc, battery_soc_percent, house_consumption_w, "
                "pv_power_w, grid_power_w, is_healthy, health_score, "
                "telemetry_is_healthy, telemetry_health_score, "
                "price_is_healthy, price_health_score, "
                "solar_is_healthy, solar_health_score, "
                "weather_is_healthy, weather_health_score "
                f"FROM observations {where} ORDER BY slot_utc DESC LIMIT ?"
            )
            recent = connection.execute(recent_sql, (*params, limit)).fetchall()
            profile_sql = (
                "SELECT slot_utc, observed_at_local, house_consumption_w "
                f"FROM observations {where} {condition} "
                "telemetry_is_healthy=1 AND house_consumption_w IS NOT NULL"
            )
            profile_rows = connection.execute(profile_sql, params).fetchall()
        weekday: dict[int, list[float]] = {}
        for row in profile_rows:
            day = datetime.fromisoformat(row["observed_at_local"]).weekday()
            weekday.setdefault(day, []).append(row["house_consumption_w"] / 1000)
        return {
            "database_path": str(self.database_path),
            "total": counts["total"],
            "healthy": counts["healthy"] or 0,
            "unhealthy": counts["total"] - (counts["healthy"] or 0),
            "health_domains": {
                domain: {
                    "healthy": counts[f"{domain}_healthy"] or 0,
                    "unhealthy": counts["total"] - (counts[f"{domain}_healthy"] or 0),
                }
                for domain in ("telemetry", "price", "solar", "weather")
            },
            "earliest": counts["earliest"],
            "latest": counts["latest"],
            "missing": (
                dict(missing) if counts["total"] else {c: 0 for c in missing_columns}
            ),
            "average_house_kw_by_hour": [dict(row) for row in by_hour],
            "average_house_kw_by_weekday": [
                {
                    "day_of_week": day,
                    "average_kw": sum(values) / len(values),
                    "samples": len(values),
                }
                for day, values in sorted(weekday.items())
            ],
            "recent": [dict(row) for row in recent],
        }

    def healthy_load_samples(self, *, days: int | None = None) -> list[sqlite3.Row]:
        self.migrate()
        sql = (
            "SELECT observed_at_local, house_consumption_w FROM observations "
            "WHERE telemetry_is_healthy=1 AND house_consumption_w IS NOT NULL"
        )
        params: tuple[Any, ...] = ()
        if days is not None:
            cutoff = datetime.now(UTC).timestamp() - days * 86400
            sql += " AND slot_utc >= ?"
            params = (datetime.fromtimestamp(cutoff, UTC).isoformat(),)
        with self.connect() as connection:
            return connection.execute(sql, params).fetchall()
