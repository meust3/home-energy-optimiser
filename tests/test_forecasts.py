from datetime import timedelta

from energy_optimizer.collector import align_to_five_minute_slot, build_observation
from energy_optimizer.historian import Historian
from energy_optimizer.models import ForecastPoint, ForecastRun


def test_forecast_storage_and_projected_vs_actual_metrics(healthy_states, config, now):
    historian = Historian(config.database_path)
    first = build_observation(healthy_states, config, observed_at=now)
    second = build_observation(
        healthy_states, config, observed_at=now + timedelta(minutes=5)
    )
    historian.save(first)
    historian.save(second)
    first_slot = align_to_five_minute_slot(now)
    run = ForecastRun(
        created_at_utc=now,
        forecast_type="household_load",
        source="unit-test",
        horizon_start_utc=first_slot,
        horizon_end_utc=first_slot + timedelta(minutes=10),
        model_version="test-v1",
        points=[
            ForecastPoint(
                period_start_utc=first_slot,
                period_end_utc=first_slot + timedelta(minutes=5),
                expected_value=1700,
                unit="W",
            ),
            ForecastPoint(
                period_start_utc=first_slot + timedelta(minutes=5),
                period_end_utc=first_slot + timedelta(minutes=10),
                expected_value=1900,
                unit="W",
            ),
        ],
    )
    run_id = historian.save_forecast_run(run)
    metrics = historian.compare_forecast_run(run_id)
    assert metrics["sample_count"] == 2
    assert metrics["mae"] == 100
    assert metrics["bias"] == 0
    rows = historian.forecast_comparison_rows(forecast_type="household_load")
    assert len(rows) == 2
    assert rows[0]["actual_value"] == 1800
    assert rows[0]["error_value"] == 100
    assert rows[1]["error_value"] == -100


def test_forecast_tables_created_by_migration(config):
    historian = Historian(config.database_path)
    historian.migrate()
    with historian.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"forecast_runs", "forecast_points"} <= tables
