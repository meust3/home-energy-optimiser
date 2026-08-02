import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from energy_optimizer.collector import build_observation
from energy_optimizer.demand_forecast import forecast_household_demand
from energy_optimizer.historian import Historian
from energy_optimizer.home_assistant import HomeAssistantClient
from energy_optimizer.opportunity_window import find_next_opportunity
from energy_optimizer.reserve import (
    estimate_battery_reserve,
    estimate_live_battery_reserve,
    store_reserve_forecast,
)


def _rows(start, *, days=21, power_w=1200):
    rows = []
    for day in range(days):
        date = start - timedelta(days=day)
        for slot in range(288):
            rows.append(
                {
                    "observed_at_local": date.replace(
                        hour=slot // 12,
                        minute=(slot % 12) * 5,
                        second=0,
                        microsecond=0,
                    ).isoformat(),
                    "house_consumption_w": power_w,
                }
            )
    return rows


class _History:
    def __init__(self, observation, rows):
        self.observation = observation
        self.rows = rows

    def observation_as_of_read_only(self, as_of=None):
        return self.observation

    def reserve_history_rows_read_only(self, *, days, now, as_of=None):
        return self.rows


def _stored_observation(healthy_states, config, now):
    observation = build_observation(healthy_states, config, observed_at=now)
    historian = Historian(config.database_path)
    historian.save(observation)
    return historian.latest_observation()


def test_insufficient_history_uses_fallback(now):
    local = now.astimezone().replace(hour=18)
    result = forecast_household_demand(
        [],
        start_local=local,
        end_local=local + timedelta(hours=12),
        minimum_samples=3,
        fallback_kw=2.0,
    )
    assert result.expected_energy_kwh == 24
    assert result.confidence == "low"
    assert result.fallback_slot_count == 145


def test_overnight_and_daytime_demand(now):
    local = now.astimezone().replace(hour=18, minute=0)
    rows = _rows(local, power_w=1000)
    overnight = forecast_household_demand(
        rows,
        start_local=local,
        end_local=local + timedelta(hours=12),
        minimum_samples=1,
        fallback_kw=2,
    )
    daytime = forecast_household_demand(
        rows,
        start_local=local.replace(hour=10),
        end_local=local.replace(hour=14),
        minimum_samples=1,
        fallback_kw=2,
    )
    assert overnight.expected_energy_kwh == 12
    assert daytime.expected_energy_kwh == 4


def test_weekend_demand_uses_weekend_profile(now):
    saturday = now.astimezone().replace(hour=8, minute=0) + timedelta(days=1)
    rows = _rows(saturday, power_w=2000)
    result = forecast_household_demand(
        rows,
        start_local=saturday,
        end_local=saturday + timedelta(hours=2),
        minimum_samples=1,
        fallback_kw=1,
    )
    assert result.expected_energy_kwh == 4


def test_solar_opportunity():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime(2026, 8, 2, 9, tzinfo=ZoneInfo("Australia/Brisbane"))
    result = find_next_opportunity(
        {
            "solcast_remaining_today_kwh_json": json.dumps({"estimate_kwh": 8}),
            "pv_power_w": 3000,
            "house_consumption_w": 1000,
        },
        now_local=now,
        cheap_import_price_per_kwh=0.15,
        solar_surplus_threshold_kwh=1,
        max_horizon_hours=24,
    )
    assert result.opportunity_type == "solar"
    assert result.expected_start_local == now


def test_cheap_grid_opportunity():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime(2026, 8, 2, 18, tzinfo=ZoneInfo("Australia/Brisbane"))
    start = now + timedelta(hours=2)
    end = start + timedelta(minutes=30)
    result = find_next_opportunity(
        {
            "amber_import_forecast_json": json.dumps(
                [
                    {
                        "start_time": start.isoformat(),
                        "end_time": end.isoformat(),
                        "per_kwh": 0.10,
                    }
                ]
            )
        },
        now_local=now,
        cheap_import_price_per_kwh=0.15,
        solar_surplus_threshold_kwh=1,
        max_horizon_hours=24,
    )
    assert result.opportunity_type == "cheap_grid"
    assert result.expected_start_local == start


def test_missing_forecasts_require_overnight_reserve():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime(2026, 8, 2, 18, tzinfo=ZoneInfo("Australia/Brisbane"))
    result = find_next_opportunity(
        {},
        now_local=now,
        cheap_import_price_per_kwh=0.15,
        solar_surplus_threshold_kwh=1,
        max_horizon_hours=12,
    )
    assert result.opportunity_type == "overnight_reserve"
    assert result.confidence == "low"


@pytest.mark.parametrize("soc,has_tradable", [(10, False), (95, True)])
def test_low_and_high_soc(healthy_states, config, now, soc, has_tradable):
    healthy_states[
        "sensor.outside_back_goodwe_inverter_battery_state_of_charge"
    ].state = str(soc)
    observation = _stored_observation(healthy_states, config, now)
    result = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    assert (result.potentially_tradable_kwh > 0) is has_tradable


def test_tradable_energy_never_negative(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    observation["battery_energy_estimate_kwh"] = 1
    observation["solcast_remaining_today_kwh_json"] = None
    observation["solcast_tomorrow_kwh_json"] = None
    result = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    assert result.potentially_tradable_kwh == 0


def test_known_and_missing_ev_requirement(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    missing = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    observation["ev_energy_required_kwh"] = 7.5
    known = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    assert missing.expected_ev_demand_kwh == 0
    assert known.expected_ev_demand_kwh == 7.5
    assert known.recommended_reserve_kwh >= missing.recommended_reserve_kwh


def test_missing_health_context_reduces_confidence(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    rows = _rows(now.astimezone(), days=21)
    complete = estimate_battery_reserve(
        _History(observation.copy(), rows), config, now=now.astimezone()
    )
    observation["solar_is_healthy"] = 0
    observation["price_is_healthy"] = 0
    observation["weather_is_healthy"] = 0
    incomplete = estimate_battery_reserve(
        _History(observation, rows), config, now=now.astimezone()
    )
    assert incomplete.confidence_score < complete.confidence_score


@pytest.mark.parametrize("domain", ["solar", "price", "weather"])
def test_missing_optional_context_is_disclosed_in_confidence(
    healthy_states, config, now, domain
):
    observation = _stored_observation(healthy_states, config, now)
    observation[f"{domain}_is_healthy"] = 0
    result = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    assert result.health[domain]["is_healthy"] is False
    assert {"solar": "Solcast", "price": "Amber", "weather": "weather"}[
        domain
    ] in result.reasoning


def test_high_confidence_requires_sufficient_history(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    result = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    assert result.confidence != "high"


def test_sufficient_history_can_reach_high_confidence(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    observation["solcast_remaining_today_kwh_json"] = None
    rows = _rows(now.astimezone(), days=21)
    result = estimate_battery_reserve(
        _History(observation, rows), config, now=now.astimezone()
    )
    assert result.demand_forecast.confidence == "high"
    assert result.confidence == "high"


def test_json_output_and_manual_readiness(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    result = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    payload = json.loads(result.model_dump_json())
    assert payload["ready_for_manual_review"] is True
    assert payload["command_issued"] is False
    assert "ready_for_execution" not in payload
    assert payload["operational_context"]["battery_mode"] == "Normal"
    assert payload["operational_context"]["amber_import_price_per_kwh"] == 0.21


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _GetOnlySession:
    def __init__(self, payload):
        self.headers = {}
        self.payload = payload
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(("GET", url, timeout))
        return _Response(self.payload)


def test_live_soc_overrides_stored_soc_without_saving(healthy_states, config, now):
    healthy_states[
        "sensor.outside_back_goodwe_inverter_battery_state_of_charge"
    ].state = "58"
    historian = Historian(config.database_path)
    historian.save(build_observation(healthy_states, config, observed_at=now))
    with historian.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    healthy_states[
        "sensor.outside_back_goodwe_inverter_battery_state_of_charge"
    ].state = "92"
    session = _GetOnlySession(
        [state.model_dump(mode="json") for state in healthy_states.values()]
    )
    client = HomeAssistantClient("http://ha", "secret", session=session)
    result = estimate_live_battery_reserve(
        historian,
        config,
        client,
        save_observation=False,
        now=now + timedelta(minutes=5),
    )

    with historian.connect() as connection:
        after = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        stored_soc = connection.execute(
            "SELECT battery_soc_percent FROM observations"
        ).fetchone()[0]
    assert result.current_state_source == "live"
    assert result.battery_soc_percent == 92
    assert result.usable_battery_capacity_kwh == 40
    assert result.battery_energy_kwh == 36.8
    assert before == after == 1
    assert stored_soc == 58
    assert len(session.calls) == 1
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1].endswith("/api/states")


def test_stale_history_observation_is_explicit(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    current = now + timedelta(minutes=11)
    result = estimate_battery_reserve(
        _History(observation, []),
        config,
        now=current,
        source="history",
    )
    assert result.current_state_source == "history"
    assert result.observation_timestamp == now.astimezone()
    assert result.observation_age_seconds == 660
    assert result.observation_is_stale
    assert "older than 10 minutes" in result.observation_warning


def test_history_as_of_selects_prior_observation(healthy_states, config, now):
    historian = Historian(config.database_path)
    healthy_states[
        "sensor.outside_back_goodwe_inverter_battery_state_of_charge"
    ].state = "58"
    historian.save(build_observation(healthy_states, config, observed_at=now))
    healthy_states[
        "sensor.outside_back_goodwe_inverter_battery_state_of_charge"
    ].state = "92"
    historian.save(
        build_observation(
            healthy_states, config, observed_at=now + timedelta(minutes=5)
        )
    )
    as_of = now + timedelta(minutes=2)
    result = estimate_battery_reserve(historian, config, source="history", as_of=as_of)
    assert result.battery_soc_percent == 58
    assert result.observation_age_seconds == 120


FALLBACK_POWERS = {
    "overnight": 2.0,
    "morning": 2.5,
    "daytime": 2.0,
    "evening": 3.0,
    "late_evening": 2.5,
}


@pytest.mark.parametrize(
    "hour,band,power",
    [
        (1, "overnight", 2.0),
        (7, "morning", 2.5),
        (12, "daytime", 2.0),
        (19, "evening", 3.0),
        (23, "late_evening", 2.5),
    ],
)
def test_each_configured_fallback_band(now, hour, band, power):
    start = now.astimezone().replace(hour=hour, minute=0, second=0, microsecond=0)
    result = forecast_household_demand(
        [],
        start_local=start,
        end_local=start + timedelta(hours=1),
        minimum_samples=3,
        fallback_kw=2,
        fallback_mode="banded",
        fallback_band_powers_kw=FALLBACK_POWERS,
    )
    assert result.expected_energy_kwh == power
    assert result.fallback_contributions[band].energy_kwh == power


def test_fallback_horizon_spans_multiple_bands(now):
    start = now.astimezone().replace(hour=5, minute=0, second=0, microsecond=0)
    result = forecast_household_demand(
        [],
        start_local=start,
        end_local=start + timedelta(hours=18),
        minimum_samples=3,
        fallback_kw=2,
        fallback_mode="banded",
        fallback_band_powers_kw=FALLBACK_POWERS,
    )
    assert result.fallback_contributions["overnight"].energy_kwh == 2
    assert result.fallback_contributions["morning"].energy_kwh == 7.5
    assert result.fallback_contributions["daytime"].energy_kwh == 16
    assert result.fallback_contributions["evening"].energy_kwh == 15
    assert result.fallback_contributions["late_evening"].energy_kwh == 2.5


def test_partial_history_uses_history_then_fallback(now):
    start = now.astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    rows = [
        {
            "observed_at_local": (start - timedelta(days=7)).isoformat(),
            "house_consumption_w": 1000,
        }
    ]
    result = forecast_household_demand(
        rows,
        start_local=start,
        end_local=start + timedelta(minutes=10),
        minimum_samples=1,
        fallback_kw=2,
    )
    assert result.historical_slot_count == 1
    assert result.fallback_slot_count == 1
    assert result.expected_energy_kwh == 0.25


def test_minimum_sample_threshold_is_reported(now):
    start = now.astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    row = {
        "observed_at_local": (start - timedelta(days=7)).isoformat(),
        "house_consumption_w": 1000,
    }
    result = forecast_household_demand(
        [row],
        start_local=start,
        end_local=start + timedelta(minutes=5),
        minimum_samples=2,
        fallback_kw=2,
    )
    assert result.historical_slot_count == 0
    assert result.diagnostics.slots_with_insufficient_matching_history == 1
    assert result.diagnostics.minimum_samples_per_weekday_slot == 2


def test_legacy_and_ineligible_rows_are_explained(now):
    start = now.astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    base = {"observed_at_local": start.isoformat()}
    rows = [
        {
            **base,
            "telemetry_is_healthy": 0,
            "baseline_training_eligible": 1,
            "baseline_house_consumption_w": 1000,
        },
        {
            **base,
            "telemetry_is_healthy": 1,
            "baseline_training_eligible": 0,
            "baseline_exclusion_reason": "ev_active_power_unknown",
            "baseline_house_consumption_w": 1000,
        },
        {
            **base,
            "telemetry_is_healthy": 1,
            "baseline_training_eligible": 0,
            "baseline_exclusion_reason": None,
            "baseline_house_consumption_w": None,
        },
    ]
    result = forecast_household_demand(
        rows,
        start_local=start,
        end_local=start + timedelta(minutes=5),
        minimum_samples=1,
        fallback_kw=2,
    )
    reasons = result.diagnostics.ineligible_observations_by_reason
    assert reasons == {
        "ev_active_power_unknown": 1,
        "legacy_or_unclassified": 1,
        "telemetry_unhealthy": 1,
    }
    assert result.diagnostics.eligible_baseline_observations == 0


def test_forecast_iteration_is_dst_safe():
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 8, 0, 0, tzinfo=zone)
    end = datetime(2026, 3, 8, 4, 0, tzinfo=zone)
    result = forecast_household_demand(
        [],
        start_local=start,
        end_local=end,
        minimum_samples=1,
        fallback_kw=1,
    )
    assert result.expected_energy_kwh == 3
    assert result.fallback_slot_count == 36


def _forecast_for_tier(rows, start, **overrides):
    options = {
        "minimum_samples": 3,
        "fallback_kw": 2,
        "tier2_minimum_samples": 3,
        "tier3_minimum_samples": 3,
        "tier4_minimum_samples": 3,
        "tier4_lookback_days": 7,
        "weekend_days": {5, 6},
    }
    options.update(overrides)
    return forecast_household_demand(
        rows,
        start_local=start,
        end_local=start + timedelta(minutes=5),
        **options,
    )


def test_exact_weekday_slot_tier(now):
    start = now.astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    rows = [
        {
            "observed_at_local": (start - timedelta(days=7 * week)).isoformat(),
            "house_consumption_w": 1000,
        }
        for week in (1, 2, 3)
    ]
    result = _forecast_for_tier(rows, start)
    assert result.slot_decisions[0].tier == "tier1_exact"


def test_weekday_weekend_bucket_tier():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 8, 12, 0, tzinfo=zone)  # Saturday
    rows = [
        {
            "observed_at_local": (start - timedelta(days=7))
            .replace(minute=minute)
            .isoformat(),
            "house_consumption_w": 1200,
        }
        for minute in (5, 10, 15)
    ]
    result = _forecast_for_tier(rows, start)
    assert result.slot_decisions[0].tier == "tier2_day_type_30m"


def test_all_days_bucket_tier():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 12, 0, tzinfo=zone)  # Monday
    rows = [
        {
            "observed_at_local": datetime(
                2026, 8, day, 12, minute, tzinfo=zone
            ).isoformat(),
            "house_consumption_w": 1300,
        }
        for day, minute in ((8, 5), (8, 10), (9, 15))
    ]
    result = _forecast_for_tier(rows, start)
    assert result.slot_decisions[0].tier == "tier3_all_days_30m"


def test_recent_time_band_tier():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 12, 0, tzinfo=zone)
    rows = [
        {
            "observed_at_local": (start - timedelta(days=day))
            .replace(hour=14, minute=day * 5)
            .isoformat(),
            "house_consumption_w": value,
        }
        for day, value in ((1, 1000), (2, 1200), (3, 5000))
    ]
    result = _forecast_for_tier(rows, start)
    assert result.slot_decisions[0].tier == "tier4_recent_band"
    assert result.slot_decisions[0].estimated_power_kw == 1.2


def test_hierarchical_fallback_tier(now):
    start = now.astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    result = _forecast_for_tier([], start)
    assert result.slot_decisions[0].tier == "tier5_fallback"
    assert result.diagnostics.fallback_share == 1


def test_mixed_tier_forecast_horizon():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 12, 0, tzinfo=zone)
    rows = [
        {
            "observed_at_local": (start - timedelta(days=7 * week)).isoformat(),
            "house_consumption_w": 1000,
        }
        for week in (1, 2, 3)
    ]
    result = forecast_household_demand(
        rows,
        start_local=start,
        end_local=start + timedelta(minutes=10),
        minimum_samples=3,
        fallback_kw=2,
        tier2_minimum_samples=99,
        tier3_minimum_samples=99,
        tier4_minimum_samples=99,
    )
    assert [slot.tier for slot in result.slot_decisions] == [
        "tier1_exact",
        "tier5_fallback",
    ]


def test_confidence_decreases_for_weaker_tiers(now):
    start = now.astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    exact_rows = _rows(start, days=22, power_w=1000)
    exact = _forecast_for_tier(exact_rows, start)
    fallback = _forecast_for_tier([], start)
    assert exact.confidence == "high"
    assert fallback.confidence == "low"


def test_one_partial_day_cannot_produce_medium_confidence():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 2, 18, tzinfo=zone)
    rows = [
        {
            "observed_at_local": (
                start - timedelta(days=1, minutes=offset)
            ).isoformat(),
            "house_consumption_w": 1200,
        }
        for offset in range(0, 12 * 5, 5)
    ]
    result = _forecast_for_tier(rows, start, tier4_minimum_samples=1)
    assert result.diagnostics.complete_daily_periods == 0
    assert result.confidence == "low"
    assert any(
        "fewer_than_2_complete_days" in item for item in result.confidence_ceilings
    )


def test_zero_exact_matches_cannot_be_high():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 12, tzinfo=zone)
    rows = [
        {
            "observed_at_local": (start - timedelta(days=day))
            .replace(minute=5)
            .isoformat(),
            "house_consumption_w": 1200,
        }
        for day in range(1, 9)
    ]
    result = _forecast_for_tier(rows, start)
    assert result.diagnostics.exact_history_share == 0
    assert result.confidence != "high"


def test_majority_tier_three_is_capped_at_medium():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 12, tzinfo=zone)
    result = _forecast_for_tier(
        _rows(start, days=9),
        start,
        minimum_samples=999,
        tier2_minimum_samples=999,
        tier3_minimum_samples=3,
    )
    assert result.slot_decisions[0].tier == "tier3_all_days_30m"
    assert result.diagnostics.weak_estimate_share == 1
    assert result.confidence != "high"


def test_multiple_complete_days_are_reported():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 12, tzinfo=zone)
    result = _forecast_for_tier(_rows(start, days=9), start)
    assert result.diagnostics.complete_daily_periods == 8
    assert result.diagnostics.complete_overnight_periods == 8


def test_same_partial_day_and_future_samples_are_not_used():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 12, tzinfo=zone)
    rows = [
        {
            "observed_at_local": (start - timedelta(hours=1)).isoformat(),
            "house_consumption_w": 9000,
        },
        {
            "observed_at_local": (start + timedelta(minutes=5)).isoformat(),
            "house_consumption_w": 9000,
        },
    ]
    result = _forecast_for_tier(rows, start, tier4_minimum_samples=1)
    assert result.slot_decisions[0].tier == "tier5_fallback"
    assert result.diagnostics.same_partial_day_samples_excluded == 1
    assert result.diagnostics.future_samples_excluded == 1


def test_reserve_forecast_is_stored_for_later_scoring(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    observation["solcast_remaining_today_kwh_json"] = None
    estimate = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    historian = Historian(config.database_path)
    run_id = store_reserve_forecast(historian, estimate)
    with historian.connect() as connection:
        run = connection.execute(
            "SELECT source, model_version FROM forecast_runs WHERE id=?", (run_id,)
        ).fetchone()
        point_count = connection.execute(
            "SELECT COUNT(*) FROM forecast_points WHERE forecast_run_id=?", (run_id,)
        ).fetchone()[0]
    assert run["source"] == "reserve_estimator"
    assert run["model_version"] == "hierarchical-demand-v1"
    assert point_count == len(estimate.demand_forecast.slot_decisions)


def test_gross_requirement_reports_capacity_overflow(healthy_states, config, now):
    observation = _stored_observation(healthy_states, config, now)
    observation["solcast_remaining_today_kwh_json"] = None
    observation["solcast_tomorrow_kwh_json"] = None
    observation["amber_import_forecast_json"] = None
    config.reserve_fallback_mode = "flat"
    config.conservative_fallback_household_load_kw = 10
    result = estimate_battery_reserve(
        _History(observation, []), config, now=now.astimezone()
    )
    assert result.gross_reserve_requirement_kwh > config.usable_battery_capacity_kwh
    assert result.capacity_capped_reserve_kwh == config.usable_battery_capacity_kwh
    assert result.unmet_reserve_requirement_kwh > 0


def test_brisbane_local_slot_matching():
    zone = ZoneInfo("Australia/Brisbane")
    start = datetime(2026, 8, 10, 7, 0, tzinfo=zone)
    rows = [
        {
            "observed_at_local": (start - timedelta(days=7 * week)).isoformat(),
            "house_consumption_w": 1500,
        }
        for week in (1, 2, 3)
    ]
    result = _forecast_for_tier(rows, start)
    assert result.slot_decisions[0].period_start_local.utcoffset() == timedelta(
        hours=10
    )
    assert result.slot_decisions[0].tier == "tier1_exact"
