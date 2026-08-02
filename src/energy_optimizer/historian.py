"""SQLite persistence and read-only analytical queries."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from energy_optimizer.history_analysis import (
    calculate_gap_report,
    summarize_health_issues,
)
from energy_optimizer.models import EnergyObservation, ForecastRun

SCHEMA_VERSION = 4

SOLCAST_KWH_COLUMNS = {
    "solcast_remaining_today_kwh_json": "TEXT",
    "solcast_tomorrow_kwh_json": "TEXT",
    "solcast_next_hour_kwh_json": "TEXT",
    "solcast_this_hour_kwh_json": "TEXT",
    "solcast_today_kwh_json": "TEXT",
}

DOMAIN_COLUMNS = {
    "telemetry_is_healthy": "INTEGER NOT NULL DEFAULT 0",
    "telemetry_health_score": "INTEGER NOT NULL DEFAULT 0",
    "price_is_healthy": "INTEGER NOT NULL DEFAULT 0",
    "price_health_score": "INTEGER NOT NULL DEFAULT 0",
    "solar_is_healthy": "INTEGER NOT NULL DEFAULT 0",
    "solar_health_score": "INTEGER NOT NULL DEFAULT 0",
    "weather_is_healthy": "INTEGER NOT NULL DEFAULT 1",
    "weather_health_score": "INTEGER NOT NULL DEFAULT 100",
    "flow_is_healthy": "INTEGER NOT NULL DEFAULT 0",
    "flow_health_score": "INTEGER NOT NULL DEFAULT 0",
    "health_domains_json": "TEXT",
}

DERIVED_COLUMNS = {
    "grid_import_power_w": "REAL",
    "grid_export_power_w": "REAL",
    "battery_charge_power_w": "REAL",
    "battery_discharge_power_w": "REAL",
    "solar_to_house_power_w": "REAL",
    "solar_to_battery_power_w": "REAL",
    "solar_to_grid_power_w": "REAL",
    "battery_to_house_power_w": "REAL",
    "battery_to_grid_power_w": "REAL",
    "grid_to_house_power_w": "REAL",
    "grid_to_battery_power_w": "REAL",
    "balance_residual_w": "REAL",
    "sign_convention_status": "TEXT NOT NULL DEFAULT 'unconfirmed'",
    "sign_convention_confidence": "TEXT NOT NULL DEFAULT 'unconfirmed'",
    "sign_supporting_sample_count": "INTEGER NOT NULL DEFAULT 0",
    "ev_charging_active": "INTEGER",
    "ev_power_w": "REAL",
    "ev_session_id": "TEXT",
    "ev_energy_required_kwh": "REAL",
    "ev_ready_by_local": "TEXT",
    "ev_source": "TEXT NOT NULL DEFAULT 'none'",
    "ev_detection_confidence": "TEXT NOT NULL DEFAULT 'unconfirmed'",
    "baseline_house_consumption_w": "REAL",
    "baseline_training_eligible": "INTEGER NOT NULL DEFAULT 0",
    "baseline_exclusion_reason": "TEXT",
    "event_labels_json": "TEXT NOT NULL DEFAULT '[\"unknown\"]'",
    "event_label_confidence": "TEXT NOT NULL DEFAULT 'unconfirmed'",
    "event_label_evidence_json": "TEXT NOT NULL DEFAULT '{}'",
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
            old_domain_names = set(DOMAIN_COLUMNS) - {
                "flow_is_healthy",
                "flow_health_score",
            }
            missing_old_domain = any(
                name not in existing_columns for name in old_domain_names
            )
            for name, declaration in DOMAIN_COLUMNS.items():
                if name not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE observations ADD COLUMN {name} {declaration}"
                    )
            if missing_old_domain:
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
                        flow_is_healthy=0,
                        flow_health_score=0,
                        health_domains_json=?
                    """,
                    (legacy_marker,),
                )
            for name, declaration in DERIVED_COLUMNS.items():
                if name not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE observations ADD COLUMN {name} {declaration}"
                    )
            for name, declaration in SOLCAST_KWH_COLUMNS.items():
                if name not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE observations ADD COLUMN {name} {declaration}"
                    )
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS forecast_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_utc TEXT NOT NULL,
                    forecast_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    horizon_start_utc TEXT NOT NULL,
                    horizon_end_utc TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forecast_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    forecast_run_id INTEGER NOT NULL,
                    period_start_utc TEXT NOT NULL,
                    period_end_utc TEXT NOT NULL,
                    expected_value REAL NOT NULL,
                    lower_value REAL,
                    upper_value REAL,
                    unit TEXT NOT NULL,
                    actual_value REAL,
                    error_value REAL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(forecast_run_id) REFERENCES forecast_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_forecast_runs_type_created
                    ON forecast_runs(forecast_type, created_at_utc);
                CREATE INDEX IF NOT EXISTS idx_forecast_points_run_period
                    ON forecast_points(forecast_run_id, period_start_utc);
                CREATE INDEX IF NOT EXISTS idx_observations_baseline_training
                    ON observations(baseline_training_eligible, slot_utc);
                """)
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
            *SOLCAST_KWH_COLUMNS.keys(),
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
            "flow_is_healthy",
            "flow_health_score",
            "health_domains_json",
            *DERIVED_COLUMNS.keys(),
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
            self._json(observation.solcast_remaining_today_kwh),
            self._json(observation.solcast_tomorrow_kwh),
            self._json(observation.solcast_next_hour_kwh),
            self._json(observation.solcast_this_hour_kwh),
            self._json(observation.solcast_today_kwh),
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
            int(observation.data_health.flow.is_healthy),
            observation.data_health.flow.score,
            self._json(observation.data_health),
            observation.energy_flow.grid_import_power_w,
            observation.energy_flow.grid_export_power_w,
            observation.energy_flow.battery_charge_power_w,
            observation.energy_flow.battery_discharge_power_w,
            observation.energy_flow.solar_to_house_power_w,
            observation.energy_flow.solar_to_battery_power_w,
            observation.energy_flow.solar_to_grid_power_w,
            observation.energy_flow.battery_to_house_power_w,
            observation.energy_flow.battery_to_grid_power_w,
            observation.energy_flow.grid_to_house_power_w,
            observation.energy_flow.grid_to_battery_power_w,
            observation.energy_flow.balance_residual_w,
            observation.energy_flow.sign_convention_status,
            observation.energy_flow.sign_convention_confidence,
            observation.energy_flow.supporting_sample_count,
            (
                None
                if observation.ev_charging_active is None
                else int(observation.ev_charging_active)
            ),
            observation.ev_power_w,
            observation.ev_session_id,
            observation.ev_energy_required_kwh,
            (
                observation.ev_ready_by_local.isoformat()
                if observation.ev_ready_by_local
                else None
            ),
            observation.ev_source,
            observation.ev_detection_confidence,
            observation.baseline_house_consumption_w,
            int(observation.baseline_training_eligible),
            observation.baseline_exclusion_reason,
            self._json(observation.event_labels),
            observation.event_label_confidence,
            self._json(observation.event_label_evidence),
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
        range_end: datetime | None = None
        if days is not None:
            range_end = datetime.now(UTC)
            cutoff = range_end.timestamp() - days * 86400
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
                "SUM(flow_is_healthy) flow_healthy, "
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
            slot_rows = connection.execute(
                f"SELECT slot_utc FROM observations {where} ORDER BY slot_utc", params
            ).fetchall()
            health_rows = connection.execute(
                "SELECT health_domains_json, health_score AS overall_health_score, "
                "telemetry_health_score, price_health_score, "
                "solar_health_score, weather_health_score, flow_health_score "
                f"FROM observations {where}",
                params,
            ).fetchall()
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
                for domain in ("telemetry", "price", "solar", "weather", "flow")
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
            "gap_report": calculate_gap_report(
                [datetime.fromisoformat(row["slot_utc"]) for row in slot_rows],
                start=datetime.fromisoformat(cutoff) if cutoff else None,
                end=range_end,
            ),
            "health_issue_summary": summarize_health_issues(
                [dict(row) for row in health_rows]
            ),
        }

    def healthy_load_samples(self, *, days: int | None = None) -> list[sqlite3.Row]:
        self.migrate()
        sql = (
            "SELECT observed_at_local, "
            "baseline_house_consumption_w AS house_consumption_w "
            "FROM observations WHERE telemetry_is_healthy=1 "
            "AND baseline_training_eligible=1 "
            "AND baseline_house_consumption_w IS NOT NULL"
        )
        params: tuple[Any, ...] = ()
        if days is not None:
            cutoff = datetime.now(UTC).timestamp() - days * 86400
            sql += " AND slot_utc >= ?"
            params = (datetime.fromtimestamp(cutoff, UTC).isoformat(),)
        with self.connect() as connection:
            return connection.execute(sql, params).fetchall()

    def power_sign_samples(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Return raw stored values needed for non-mutating sign analysis."""
        rows = self.observation_rows(
            start=start,
            end=end,
            columns=(
                "slot_utc",
                "pv_power_w",
                "house_consumption_w",
                "grid_power_w",
                "battery_power_w",
                "battery_mode",
            ),
        )
        return rows

    def observation_rows(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        columns: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Query an inclusive UTC range for analysis or export."""
        self.migrate()
        table_columns = tuple(row["name"] for row in self._table_info())
        allowed_columns = set(table_columns)
        selected = columns or table_columns
        if not selected or any(column not in allowed_columns for column in selected):
            raise ValueError("Unknown or empty observation column selection")
        clauses: list[str] = []
        params: list[str] = []
        for operator, value in ((">=", start), ("<=", end)):
            if value is None:
                continue
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("history query datetimes must be timezone-aware")
            clauses.append(f"slot_utc {operator} ?")
            params.append(value.astimezone(UTC).isoformat())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT {','.join(selected)} FROM observations{where} ORDER BY slot_utc"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def observation_columns(self) -> tuple[str, ...]:
        """Return persisted observation columns in stable schema order."""
        self.migrate()
        return tuple(row["name"] for row in self._table_info())

    def save_forecast_run(self, run: ForecastRun) -> int:
        """Store one immutable forecast run and its points locally."""
        self.migrate()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO forecast_runs (
                    created_at_utc, forecast_type, source, horizon_start_utc,
                    horizon_end_utc, model_version, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.created_at_utc.astimezone(UTC).isoformat(),
                    run.forecast_type,
                    run.source,
                    run.horizon_start_utc.astimezone(UTC).isoformat(),
                    run.horizon_end_utc.astimezone(UTC).isoformat(),
                    run.model_version,
                    self._json(run.metadata),
                ),
            )
            run_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO forecast_points (
                    forecast_run_id, period_start_utc, period_end_utc,
                    expected_value, lower_value, upper_value, unit,
                    actual_value, error_value, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        point.period_start_utc.astimezone(UTC).isoformat(),
                        point.period_end_utc.astimezone(UTC).isoformat(),
                        point.expected_value,
                        point.lower_value,
                        point.upper_value,
                        point.unit,
                        point.actual_value,
                        point.error_value,
                        self._json(point.metadata),
                    )
                    for point in run.points
                ],
            )
        return run_id

    def compare_forecast_run(self, run_id: int) -> dict[str, Any]:
        """Populate actual/error values from observations and return MAE and bias."""
        self.migrate()
        actual_columns = {
            "solar_power": "pv_power_w",
            "household_load": "house_consumption_w",
            "baseline_household_load": "baseline_house_consumption_w",
            "battery_soc": "battery_soc_percent",
            "grid_import": "grid_import_power_w",
            "grid_export": "grid_export_power_w",
            "buy_price": "amber_import_price_per_kwh",
            "sell_price": "amber_export_price_per_kwh",
        }
        with self.connect() as connection:
            run = connection.execute(
                "SELECT forecast_type FROM forecast_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"Forecast run {run_id} does not exist")
            actual_column = actual_columns[run["forecast_type"]]
            points = connection.execute(
                "SELECT id, period_start_utc, period_end_utc, expected_value "
                "FROM forecast_points WHERE forecast_run_id=?",
                (run_id,),
            ).fetchall()
            for point in points:
                actual = connection.execute(
                    f"SELECT AVG({actual_column}) actual FROM observations "
                    "WHERE slot_utc >= ? AND slot_utc < ?",
                    (point["period_start_utc"], point["period_end_utc"]),
                ).fetchone()["actual"]
                error = actual - point["expected_value"] if actual is not None else None
                connection.execute(
                    "UPDATE forecast_points SET actual_value=?, error_value=? "
                    "WHERE id=?",
                    (actual, error, point["id"]),
                )
        return self.forecast_metrics(run_id)

    def forecast_metrics(self, run_id: int) -> dict[str, Any]:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(error_value) sample_count,
                       AVG(ABS(error_value)) mae,
                       AVG(error_value) bias
                FROM forecast_points WHERE forecast_run_id=?
                """,
                (run_id,),
            ).fetchone()
        return {
            "forecast_run_id": run_id,
            "sample_count": row["sample_count"],
            "mae": row["mae"],
            "bias": row["bias"],
        }

    def forecast_comparison_rows(
        self,
        *,
        forecast_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.migrate()
        clauses: list[str] = []
        params: list[Any] = []
        if forecast_type:
            clauses.append("r.forecast_type=?")
            params.append(forecast_type)
        if start:
            clauses.append("p.period_start_utc>=?")
            params.append(start.astimezone(UTC).isoformat())
        if end:
            clauses.append("p.period_end_utc<=?")
            params.append(end.astimezone(UTC).isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT r.id forecast_run_id, r.created_at_utc, r.forecast_type, "
            "r.source, r.model_version, p.period_start_utc, p.period_end_utc, "
            "p.expected_value, p.lower_value, p.upper_value, p.unit, "
            "p.actual_value, p.error_value, p.metadata_json "
            "FROM forecast_runs r JOIN forecast_points p "
            f"ON p.forecast_run_id=r.id {where} "
            "ORDER BY p.period_start_utc"
        )
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def _table_info(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute("PRAGMA table_info(observations)").fetchall()
