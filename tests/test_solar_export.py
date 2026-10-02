from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command

from energy_optimizer import entity_ids as ids
from energy_optimizer.collector import build_observation
from energy_optimizer.db.migrations import alembic_config
from energy_optimizer.parsing import parse_solar_summary
from energy_optimizer.persistence import open_repository
from energy_optimizer.solar_export import (
    ExportConfig,
    ForecastSlot,
    plan_morning_export,
)
from energy_optimizer.solar_export_replay import (
    replay_report,
    replay_solar_export_snapshot,
)

START = datetime(2026, 9, 30, 20, tzinfo=UTC)  # 06:00 Brisbane


def config(**kwargs):
    return replace(
        ExportConfig(
            maximum_charge_kw=10, maximum_discharge_kw=10, maximum_export_kw=5
        ),
        **kwargs,
    )


def slots(solar=10, price=0.6):
    return [
        ForecastSlot(
            START + timedelta(minutes=30 * i),
            START + timedelta(minutes=30 * (i + 1)),
            0 if i < 4 else solar,
            1,
            0.4,
            price if i < 4 else 0.02,
        )
        for i in range(12)
    ]


def plan(**kwargs):
    values = dict(
        created_at_utc=START,
        initial_energy_kwh=32,
        reserve_kwh=8,
        slots=slots(),
        export_before_utc=START + timedelta(hours=2),
        recharge_deadline_utc=START + timedelta(hours=6),
        calibrated=True,
        config=config(),
    )
    values.update(kwargs)
    return plan_morning_export(**values)


def test_sunny_morning_export_recharges_with_no_additional_imports():
    result = plan()
    assert result["action"] == "EXPORT_BATTERY"
    assert result["export_kwh"] > 9.9
    assert result["expected_incremental_model_value_aud"] > 4
    assert result["projected_recharge_at_utc"] is not None
    assert result["projection"]["minimum_energy_kwh"] >= 8
    assert result["projection"]["grid_import_kwh"] == 0
    assert result["no_command_issued"] and not result["execution_ready"]
    assert all(
        window["end_utc"] <= (START + timedelta(hours=2)).isoformat()
        for window in result["export_windows"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"slots": slots(solar=2)},
        {"slots": slots(price=-0.2)},
        {"reserve_kwh": 32},
        {"config": config(maximum_charge_kw=0.5)},
        {"config": config(degradation_aud_per_battery_kwh=1)},
    ],
)
def test_export_rejected_when_recharge_or_economics_fail(changes):
    result = plan(**changes)
    assert result["action"] == "HOLD"
    assert result["export_kwh"] == 0


def test_household_demand_consumes_solar_before_recharge():
    heavy_load = [replace(slot, household_kw=9) for slot in slots()]
    result = plan(slots=heavy_load)
    assert result["action"] == "HOLD"
    assert result["projection"]["minimum_energy_kwh"] >= 8


def test_uncalibrated_candidate_cannot_become_recommendation():
    result = plan(calibrated=False)
    assert result["export_kwh"] > 0
    assert result["action"] == "HOLD"
    assert result["status"] == "blocked"
    assert "calibration_evidence_insufficient" in result["blockers"]


def test_shared_discharge_power_and_export_limit_include_household():
    result = plan(config=config(maximum_discharge_kw=2, maximum_export_kw=5))
    assert result["export_kwh"] <= 2.0 + 1e-6  # 1 kW house, 1 kW export for 2 h
    assert result["projection"]["grid_import_kwh"] == 0


def test_projection_reconciles_energy_and_never_charges_while_exporting():
    settings = config()
    result = plan(config=settings)
    previous = result["initial_energy_kwh"]
    for point in result["projection"]["points"]:
        expected = previous + point["solar_charge_kwh"] * settings.charge_efficiency
        expected -= (
            point["battery_to_house_kwh"] + point["battery_export_kwh"]
        ) / settings.discharge_efficiency
        assert point["battery_energy_kwh"] == pytest.approx(expected)
        assert 8 <= point["battery_energy_kwh"] <= 40
        assert not (point["solar_charge_kwh"] > 0 and point["battery_export_kwh"] > 0)
        previous = point["battery_energy_kwh"]


def test_export_can_replace_charging_during_early_solar():
    early_solar = [
        replace(slot, solar_p10_kw=2) if i < 4 else slot
        for i, slot in enumerate(slots())
    ]
    result = plan(slots=early_solar)
    assert result["export_kwh"] > 0
    assert result["action"] == "EXPORT_BATTERY"


def test_full_solar_export_limit_leaves_no_room_for_battery_export():
    already_exporting = [
        replace(slot, solar_p10_kw=6) if i < 4 else slot
        for i, slot in enumerate(slots())
    ]
    assert plan(slots=already_exporting, initial_energy_kwh=40)["export_kwh"] == 0


def test_unknown_limits_and_forecast_gap_are_blockers():
    assert "power_limits_unknown" in plan(config=ExportConfig())["blockers"]
    assert "forecast_coverage_incomplete" in plan(slots=slots()[1:])["blockers"]


@pytest.mark.parametrize(
    "changes",
    [
        {"capacity_kwh": float("nan")},
        {"maximum_export_kw": float("inf")},
        {"discharge_efficiency": 0},
        {"minimum_soc_percent": 100},
        {"maximum_charge_kw": -1},
    ],
)
def test_invalid_assumptions_are_rejected(changes):
    with pytest.raises(ValueError):
        config(**changes)


def test_solar_capture_preserves_half_hour_kw_and_only_allowlisted_fields(
    healthy_states,
):
    state = healthy_states[ids.SOLCAST_TODAY]
    state.attributes["detailedForecast"] = [
        {
            "period_start": START.isoformat(),
            "pv_estimate": 4,
            "pv_estimate10": 2,
            "pv_estimate90": 6,
            "unrelated": "private",
        }
    ]
    summary = parse_solar_summary(state)
    interval = summary.intervals[0]
    assert interval.estimate10_kw == 2
    assert interval.period_end_utc - interval.period_start_utc == timedelta(minutes=30)
    assert "private" not in summary.model_dump_json()
    assert not summary.interval_issues


@pytest.mark.parametrize(
    "detail,issue",
    [
        ([{"period_start": "2026-10-01T06:00:00"}], "solar_interval_timestamp_invalid"),
        (
            [{"period_start": START.isoformat(), "pv_estimate": 4}],
            "solar_interval_p10_missing",
        ),
        (
            [{"period_start": START.isoformat(), "pv_estimate": 4, "pv_estimate10": 5}],
            "solar_interval_uncertainty_invalid",
        ),
        ([{}] * 97, "solar_interval_payload_invalid"),
    ],
)
def test_optional_solar_detail_failures_preserve_daily_summary(
    healthy_states, detail, issue
):
    state = healthy_states[ids.SOLCAST_TODAY]
    original = parse_solar_summary(state).estimate_kwh
    state.attributes["detailedForecast"] = detail
    summary = parse_solar_summary(state)
    assert summary.estimate_kwh == original
    assert issue in summary.interval_issues


def test_collected_detail_round_trips_existing_json_storage(
    healthy_states, config, now, tmp_path
):
    healthy_states[ids.SOLCAST_TODAY].attributes["detailedForecast"] = [
        {
            "period_start": now.isoformat(),
            "pv_estimate": 4,
            "pv_estimate10": 2,
            "pv_estimate90": 6,
        }
    ]
    observation = build_observation(healthy_states, config, observed_at=now)
    assert observation.data_health.telemetry.is_healthy
    url = f"sqlite:///{tmp_path / 'intervals.db'}"
    command.upgrade(alembic_config(url), "head")
    repository = open_repository(url)
    try:
        repository.save_observation(observation)
        stored = repository.latest_observation()["solcast_today_kwh_json"]
        assert stored["intervals"][0]["estimate10_kw"] == 2
        assert datetime.fromisoformat(stored["intervals"][0]["period_start_utc"]) == now
    finally:
        repository.close()


def snapshot():
    identity = dict(
        forecast_type="baseline_household_load",
        model_version="test",
        alignment_version="full_5m_v1",
        training_policy="verified_preferred",
    )
    points = slots()
    return dict(
        decision=dict(
            id=1,
            created_at_utc=START,
            forecast_run_id=2,
            reserve_run_id=3,
            input_hash="fixture",
            input_snapshot_json={
                "calibration": dict(
                    identity=identity,
                    identity_matches=True,
                    status="good",
                    independent_evidence_sufficient=True,
                    required_horizons_present=True,
                    rollup_backfill_complete=True,
                )
            },
            constraint_snapshot_json={
                "maximum_discharge_power_w": 10000,
                "maximum_export_power_w": 5000,
            },
            assumption_snapshot_json={
                "items": [{"name": "maximum_grid_charge_power", "value": 10000}]
            },
        ),
        observation=dict(
            observed_at_utc=START,
            health_domains_json={
                key: {"is_healthy": True} for key in ("telemetry", "price", "solar")
            },
            solcast_today_kwh_json={
                "intervals": [
                    {
                        "period_start_utc": p.start_utc,
                        "period_end_utc": p.end_utc,
                        "estimate10_kw": p.solar_p10_kw,
                    }
                    for p in points
                ]
            },
            amber_import_forecast_json=[
                {
                    "start_time": p.start_utc,
                    "end_time": p.end_utc,
                    "per_kwh": p.import_aud_per_kwh,
                }
                for p in points
            ],
            amber_export_forecast_json=[
                {
                    "start_time": p.start_utc,
                    "end_time": p.end_utc,
                    "per_kwh": p.export_aud_per_kwh,
                }
                for p in points
            ],
        ),
        forecast=dict(
            id=2,
            created_at_utc=START,
            forecast_type=identity["forecast_type"],
            model_version="test",
            metadata_json={
                "alignment_version": "full_5m_v1",
                "training_policy": "verified_preferred",
            },
            points=[
                {
                    "period_start_utc": p.start_utc,
                    "period_end_utc": p.end_utc,
                    "expected_value": p.household_kw * 1000,
                    "unit": "W",
                }
                for p in points
            ],
        ),
        reserve=dict(
            id=3,
            evaluation_timestamp_utc=START,
            observation_is_stale=False,
            usable_battery_capacity_kwh=40,
            battery_energy_kwh=32,
            recommended_reserve_kwh=8,
            ev_demand_kwh=0,
        ),
    )


def replay(value):
    from datetime import time

    return replay_solar_export_snapshot(
        value, export_before=time(8), recharge_deadline=time(12)
    )


def test_replay_complete_original_inputs_and_ignore_scored_actuals():
    value = snapshot()
    original = replay(value)
    for point in value["forecast"]["points"]:
        point["actual_value"] = 1e9
    assert replay(value) == original
    assert original["action"] == "EXPORT_BATTERY"


def test_replay_daily_total_cannot_replace_missing_timed_solar():
    value = snapshot()
    value["observation"]["solcast_today_kwh_json"] = {"estimate10_kwh": 100}
    result = replay(value)
    assert "timed_solar_forecast_missing" in result["blockers"]
    assert result["export_kwh"] is None


def test_replay_future_forecast_and_wrong_link_are_blocked():
    value = snapshot()
    value["forecast"]["created_at_utc"] = START + timedelta(seconds=1)
    value["reserve"]["id"] = 99
    result = replay(value)
    assert "future_input_rejected" in result["blockers"]
    assert "linked_identity_mismatch" in result["blockers"]


def test_replay_health_missing_p10_ev_and_stale_inputs_block():
    value = snapshot()
    value["observation"]["observed_at_utc"] = START - timedelta(minutes=11)
    value["observation"]["health_domains_json"]["solar"] = {}
    value["reserve"]["ev_demand_kwh"] = 5
    value["observation"]["solcast_today_kwh_json"]["intervals"][0][
        "estimate10_kw"
    ] = None
    result = replay(value)
    for reason in (
        "observation_stale_or_future",
        "solar_health_unverified",
        "ev_required_energy_timing_unknown",
        "forecast_value_missing_or_invalid",
    ):
        assert reason in result["blockers"]


def test_replay_partial_initial_slot_uses_only_persisted_reserve_prefix():
    value = snapshot()
    first = value["forecast"]["points"][0]
    first["period_start_utc"] = START + timedelta(minutes=5)
    assert "forecast_gap_or_overlap" in replay(value)["blockers"]
    value["reserve"]["demand_forecast_json"] = {
        "slot_decisions": [
            {
                "period_start_local": START,
                "period_end_local": START + timedelta(minutes=5),
                "estimated_power_kw": 1,
            }
        ]
    }
    assert replay(value)["action"] == "EXPORT_BATTERY"


def test_replay_report_bounds_snapshot_count():
    with pytest.raises(ValueError):
        replay_report([])
