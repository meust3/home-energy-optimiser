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


def test_reserve_forecast_actual_energy_and_tier_error(healthy_states, config, now):
    historian = Historian(config.database_path)
    observation = build_observation(healthy_states, config, observed_at=now)
    historian.save(observation)
    slot = align_to_five_minute_slot(now)
    run = ForecastRun(
        created_at_utc=now - timedelta(hours=1),
        forecast_type="baseline_household_load",
        source="reserve_estimator",
        horizon_start_utc=slot,
        horizon_end_utc=slot + timedelta(minutes=5),
        model_version="hierarchical-demand-v1",
        points=[
            ForecastPoint(
                period_start_utc=slot,
                period_end_utc=slot + timedelta(minutes=5),
                expected_value=1600,
                unit="W",
                metadata={"tier": "tier3_all_days_30m"},
            )
        ],
    )
    run_id = historian.save_forecast_run(run)
    metrics = historian.score_reserve_forecast(run_id)
    assert metrics["actual_household_energy_kwh"] == 0.15
    assert metrics["forecast_household_energy_kwh"] == 0.133
    assert metrics["forecast_error_kwh"] == 0.017
    assert metrics["absolute_percentage_error"] == 0.125
    assert metrics["bias_kwh"] == 0.017
    assert metrics["error_by_tier"]["tier3_all_days_30m"]["slots"] == 1
