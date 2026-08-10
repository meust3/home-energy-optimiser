from datetime import UTC, datetime, timedelta, timezone

from energy_optimizer.demand_forecast import forecast_household_demand
from energy_optimizer.load_profile import estimate_load_profile
from energy_optimizer.timestamps import compact_timestamp, json_safe, terminal_value
from tools.inspect_energy_flows import _slot_label
from tools.inspect_history import _period_label, _recent_rows


def test_datetime_baseline_rows_are_eligible_and_leakage_safe():
    start = datetime(2026, 8, 10, 18, 0, tzinfo=timezone(timedelta(hours=10)))
    rows = [
        {
            "slot_utc": datetime(2026, 8, 3, 8, 0, tzinfo=UTC),
            "observed_at_local": datetime(2026, 8, 3, 18, 0, tzinfo=start.tzinfo),
            "telemetry_is_healthy": True,
            "baseline_training_eligible": True,
            "baseline_house_consumption_w": 2000.0,
            "baseline_exclusion_reason": None,
            "ev_power_w": None,
            "ev_source": "none",
        },
        {
            "slot_utc": start.astimezone(UTC),
            "observed_at_local": start,
            "telemetry_is_healthy": True,
            "baseline_training_eligible": True,
            "baseline_house_consumption_w": 9000.0,
            "baseline_exclusion_reason": None,
            "ev_power_w": None,
            "ev_source": "none",
        },
    ]
    result = forecast_household_demand(
        rows,
        start_local=start,
        end_local=start + timedelta(minutes=5),
        minimum_samples=1,
        fallback_kw=3.0,
    )
    assert result.diagnostics.eligible_baseline_observations == 1
    assert result.diagnostics.future_samples_excluded == 1
    assert result.expected_energy_kwh == 0.167


def test_load_profile_and_display_accept_aware_datetimes():
    local = datetime(2026, 8, 3, 18, 5, tzinfo=timezone(timedelta(hours=10)))
    profile = estimate_load_profile(
        [{"observed_at_local": local, "house_consumption_w": 1500.0}],
        minimum_samples=1,
    )
    point = profile[local.weekday() * 288 + local.hour * 12 + local.minute // 5]
    assert point.source == "history"
    assert compact_timestamp(local) == "08-03 18:05"
    assert json_safe({"timestamp": local}) == {"timestamp": local.isoformat()}


def test_inspection_cli_formatters_accept_datetime_repository_rows():
    slot = datetime(2026, 8, 3, 8, 5, tzinfo=UTC)
    row = {
        "slot_utc": slot,
        "battery_soc_percent": 50.0,
        "house_consumption_w": 1500.0,
        "pv_power_w": 500.0,
        "grid_power_w": 1000.0,
        "amber_import_price_per_kwh": 0.25,
        "amber_export_price_per_kwh": 0.10,
        "is_healthy": True,
        "health_score": 100,
        "telemetry_is_healthy": True,
        "price_is_healthy": True,
        "solar_is_healthy": True,
    }
    assert _recent_rows([row])[0]["utc"] == "08-03 08:05"
    assert _slot_label(slot) == "08-03 08:05"
    assert "08-03 08:05" in _period_label(
        {"start": slot, "end": slot, "slots": 1, "minutes": 5}
    )


def test_1959_datetime_baseline_rows_remain_eligible():
    start = datetime(2026, 8, 10, 18, 0, tzinfo=timezone(timedelta(hours=10)))
    rows = []
    for index in range(1959):
        local = start - timedelta(days=7, minutes=5 * index)
        rows.append(
            {
                "slot_utc": local.astimezone(UTC),
                "observed_at_local": local,
                "telemetry_is_healthy": True,
                "baseline_training_eligible": True,
                "baseline_house_consumption_w": 2000.0,
                "baseline_exclusion_reason": None,
                "ev_power_w": None,
                "ev_source": "none",
            }
        )
    result = forecast_household_demand(
        rows,
        start_local=start,
        end_local=start + timedelta(minutes=5),
        minimum_samples=1,
        fallback_kw=3.0,
    )
    assert result.diagnostics.eligible_baseline_observations == 1959
    assert result.diagnostics.ineligible_observations_by_reason == {}


def test_terminal_json_formatting_handles_native_and_legacy_values():
    assert terminal_value(["unknown", "load"]) == '["unknown", "load"]'
    assert terminal_value('["unknown", "load"]') == '["unknown", "load"]'
    assert terminal_value({"source": "manual"}) == '{"source": "manual"}'
    assert terminal_value(None) == "N/A"
