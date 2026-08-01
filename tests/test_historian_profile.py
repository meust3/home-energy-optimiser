import sqlite3
from datetime import timedelta

from energy_optimizer import entity_ids as ids
from energy_optimizer.collector import align_to_five_minute_slot, build_observation
from energy_optimizer.historian import Historian
from energy_optimizer.load_profile import estimate_load_profile


def test_schema_insert_upsert_null_and_queries(healthy_states, config, now):
    historian = Historian(config.database_path)
    observation = build_observation(healthy_states, config, observed_at=now)
    observation.temperature_c = None
    historian.save(observation)
    observation.house_consumption_w = 2000
    historian.save(observation)
    with historian.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(observations)")
        }
        row = connection.execute("SELECT * FROM observations").fetchone()
    assert "health_issues_json" in columns
    assert row["temperature_c"] is None
    assert row["house_consumption_w"] == 2000
    assert historian.summary()["total"] == 1
    assert historian.summary()["average_house_kw_by_hour"][0]["average_kw"] == 2


def test_load_profile_history_and_fallback():
    rows = [
        {
            "observed_at_local": f"2026-08-{day:02d}T12:00:00+10:00",
            "house_consumption_w": value,
        }
        for day, value in ((7, 1000), (14, 3000))
    ]
    points = estimate_load_profile(rows, minimum_samples=2, fallback_kw=2.5)
    friday_noon = next(p for p in points if p.day_of_week == 4 and p.slot_index == 144)
    monday_noon = next(p for p in points if p.day_of_week == 0 and p.slot_index == 144)
    assert friday_noon.source == "history"
    assert friday_noon.estimated_power_kw == 2
    assert monday_noon.source == "fallback"
    assert monday_noon.estimated_power_kw == 2.5


def test_load_query_uses_telemetry_not_price_health(healthy_states, config, now):
    historian = Historian(config.database_path)
    healthy_states.pop(ids.AMBER_IMPORT_FORECAST)
    price_unhealthy = build_observation(healthy_states, config, observed_at=now)
    historian.save(price_unhealthy)
    telemetry_unhealthy = build_observation(
        healthy_states, config, observed_at=now + timedelta(minutes=5)
    )
    telemetry_unhealthy.data_health.telemetry.is_healthy = False
    telemetry_unhealthy.data_health.overall.is_healthy = False
    historian.save(telemetry_unhealthy)
    assert len(historian.healthy_load_samples()) == 1


def test_migrates_existing_schema_without_deleting_rows(config):
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(config.database_path) as connection:
        connection.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (1);
            CREATE TABLE observations (
                slot_utc TEXT PRIMARY KEY, observed_at_utc TEXT NOT NULL,
                observed_at_local TEXT NOT NULL, battery_soc_percent REAL,
                battery_energy_estimate_kwh REAL, battery_power_w REAL,
                battery_mode TEXT, pv_power_w REAL, house_consumption_w REAL,
                grid_power_w REAL, work_mode TEXT,
                amber_import_price_per_kwh REAL,
                amber_export_price_per_kwh REAL, amber_price_spike INTEGER,
                amber_import_forecast_json TEXT NOT NULL,
                amber_export_forecast_json TEXT NOT NULL,
                solcast_remaining_today_json TEXT, solcast_tomorrow_json TEXT,
                solcast_next_hour_json TEXT, solcast_this_hour_json TEXT,
                solcast_today_json TEXT, solcast_power_now_w REAL,
                temperature_c REAL, weather_condition TEXT,
                is_healthy INTEGER NOT NULL, health_score INTEGER NOT NULL,
                health_issues_json TEXT NOT NULL
            );
            INSERT INTO observations (
                slot_utc, observed_at_utc, observed_at_local,
                amber_import_forecast_json, amber_export_forecast_json,
                is_healthy, health_score, health_issues_json
            ) VALUES (
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00',
                '2026-01-01T10:00:01+10:00', '[]', '[]', 1, 65, '[]'
            );
            """)
    historian = Historian(config.database_path)
    historian.migrate()
    with historian.connect() as connection:
        row = connection.execute("SELECT * FROM observations").fetchone()
        version = connection.execute("SELECT version FROM schema_version").fetchone()
    assert row["slot_utc"] == "2026-01-01T00:00:00+00:00"
    assert row["telemetry_is_healthy"] == 1
    assert row["telemetry_health_score"] == 65
    assert "legacy_global_health" in row["health_domains_json"]
    assert version["version"] == 2


def test_observation_rows_select_inclusive_range(healthy_states, config, now):
    historian = Historian(config.database_path)
    for offset in (0, 5, 10):
        historian.save(
            build_observation(
                healthy_states, config, observed_at=now + timedelta(minutes=offset)
            )
        )
    rows = historian.observation_rows(
        start=align_to_five_minute_slot(now + timedelta(minutes=5)),
        end=align_to_five_minute_slot(now + timedelta(minutes=10)),
        columns=("slot_utc", "house_consumption_w"),
    )
    assert len(rows) == 2
    assert list(rows[0]) == ["slot_utc", "house_consumption_w"]
