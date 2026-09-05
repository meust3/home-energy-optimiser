from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from energy_optimizer.collector import build_observation
from energy_optimizer.dashboard_api import DashboardQueryError, DashboardService
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import alembic_config, current_revision
from energy_optimizer.db.models import ForecastPoint as DBForecastPoint
from energy_optimizer.db.models import ForecastPointScore, ReserveRun
from energy_optimizer.forecast_operations import (
    ForecastCoordinator,
    ForecastOperationsConfig,
)
from energy_optimizer.forecast_rollups import forecast_rollup_backfill_status
from energy_optimizer.home_assistant_app import AppHealth
from energy_optimizer.models import ForecastPoint, ForecastRun
from energy_optimizer.persistence import open_repository
from energy_optimizer.shadow_decisioning import (
    ASSUMPTION_SET_VERSION,
    POLICY_VERSION,
    BatteryAction,
    CalibrationGate,
    ShadowDecisionConfig,
    evaluate_shadow_decision,
    integrate_price_intervals,
    score_shadow_outcome,
)
from energy_optimizer.shadow_replay import replay_persisted_shadow_decision
from energy_optimizer.solar_diagnostics import calculate_solar_diagnostics

BOUNDARY = datetime(2026, 8, 20, 2, 30, tzinfo=UTC)


def _collector(**overrides):
    values = {
        "timezone": "Australia/Brisbane",
        "usable_battery_capacity_kwh": 40.0,
        "battery_charge_efficiency": 0.95,
        "reserve_max_charge_power_w": 9_999.0,
        "battery_soc_freshness_minutes": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _gate(**overrides) -> CalibrationGate:
    values = {
        "identity": {
            "forecast_type": "baseline_household_load",
            "model_version": "household-demand-hierarchy-v1-cohort-v1",
            "alignment_version": "full_5m_v1",
            "training_policy": "verified_preferred",
        },
        "identity_matches": True,
        "status": "acceptable",
        "independent_evidence_sufficient": True,
        "required_horizons_present": True,
        "quality_blocks": (),
        "rollup_backfill_complete": True,
    }
    values.update(overrides)
    return CalibrationGate(**values)


def _interval(start: datetime, price: float, minutes: int = 30) -> dict:
    return {
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(minutes=minutes)).isoformat(),
        "duration": minutes,
        "per_kwh": price,
    }


def _observation(**overrides) -> dict:
    values = {
        "slot_utc": BOUNDARY,
        "observed_at_utc": BOUNDARY - timedelta(seconds=5),
        "battery_soc_percent": 80.0,
        "battery_energy_estimate_kwh": 32.0,
        "telemetry_is_healthy": True,
        "sign_convention_status": "confirmed",
        "health_domains_json": {},
        "amber_import_forecast_json": [
            _interval(BOUNDARY, 0.40),
            _interval(BOUNDARY + timedelta(minutes=30), 0.10),
        ],
        "amber_export_forecast_json": [
            _interval(BOUNDARY, 0.80),
            _interval(BOUNDARY + timedelta(minutes=30), 0.10),
        ],
        "solcast_next_hour_kwh_json": {
            "estimate10_kwh": 0.2,
            "estimate_kwh": 0.4,
            "estimate90_kwh": 0.8,
        },
    }
    values.update(overrides)
    return values


def _forecast(*, run_id: int = 1) -> dict:
    points = []
    for offset in range(0, 90, 5):
        start = BOUNDARY + timedelta(minutes=offset)
        points.append(
            {
                "period_start_utc": start,
                "period_end_utc": start + timedelta(minutes=5),
                "expected_value": 1_000.0,
            }
        )
    return {
        "id": run_id,
        "forecast_type": "baseline_household_load",
        "model_version": "household-demand-hierarchy-v1-cohort-v1",
        "horizon_end_utc": BOUNDARY + timedelta(minutes=90),
        "metadata_json": {
            "alignment_version": "full_5m_v1",
            "training_policy": "verified_preferred",
        },
        "points": points,
    }


def _reserve(*, run_id: int = 1, forecast_id: int = 1, reserve: float = 12.0):
    return {
        "id": run_id,
        "forecast_run_id": forecast_id,
        "recommended_reserve_kwh": reserve,
    }


def _config(**overrides) -> ShadowDecisionConfig:
    values = {
        "enabled": True,
        "allow_non_hold_recommendations": True,
        "decision_interval_minutes": 30,
        "minimum_expected_value_aud": 0.25,
        "maximum_export_power_w": 5_000,
        "maximum_discharge_power_w": 5_000,
        "import_limit_w": 5_000,
    }
    values.update(overrides)
    return ShadowDecisionConfig(**values)


def _evaluate(**overrides):
    values = {
        "decision_boundary_utc": BOUNDARY,
        "created_at_utc": BOUNDARY,
        "observation": _observation(),
        "forecast_run": _forecast(),
        "reserve_run": _reserve(),
        "calibration": _gate(),
        "collector_config": _collector(),
        "config": _config(),
    }
    values.update(overrides)
    return evaluate_shadow_decision(**values)


def test_policy_is_deterministic_complete_and_advisory_only():
    first = _evaluate()
    second = _evaluate()

    assert first.input_hash == second.input_hash
    assert first.policy_version == POLICY_VERSION
    assert first.assumption_set_version == ASSUMPTION_SET_VERSION
    assert first.selected_action == BatteryAction.EXPORT_BATTERY
    assert first.no_command_issued is True
    assert first.explanation["optimality_claimed"] is False
    assert first.explanation["no_command_issued"] is True
    assert {candidate.action for candidate in first.candidates} == {
        "HOLD",
        "CHARGE_BATTERY_FROM_GRID",
        "PRESERVE_BATTERY",
        "DISCHARGE_FOR_SELF_CONSUMPTION",
        "EXPORT_BATTERY",
        "DEFER_EXPORT",
        "CHARGE_EV_NOW",
        "DEFER_EV",
        "PRESERVE_EV_ENERGY_REQUIREMENT",
    }
    ev = [item for item in first.candidates if "EV" in item.action]
    assert ev and all(not item.feasible for item in ev)
    assert all(item.gross_incremental_value_aud is None for item in ev)
    assert all(
        {"name", "value", "unit", "source", "classification"} <= set(item)
        for item in first.assumption_snapshot["items"]
    )


@pytest.mark.parametrize(
    ("calibration", "reason"),
    [
        (_gate(status="insufficient_evidence"), "calibration_evidence_insufficient"),
        (_gate(identity_matches=False), "calibration_evidence_insufficient"),
        (_gate(required_horizons_present=False), "calibration_evidence_insufficient"),
        (_gate(quality_blocks=("truncated",)), "calibration_evidence_insufficient"),
        (_gate(rollup_backfill_complete=False), "calibration_rollup_incomplete"),
    ],
)
def test_exact_calibration_gate_forces_hold(calibration, reason):
    result = _evaluate(calibration=calibration)
    assert result.selected_action == "HOLD"
    assert reason in result.reason_codes
    assert result.tradable_calibrated is False


def test_non_hold_kill_switch_and_value_threshold_force_hold():
    disabled = _evaluate(config=_config(allow_non_hold_recommendations=False))
    expensive = _evaluate(config=_config(minimum_expected_value_aud=100.0))
    assert disabled.selected_action == "HOLD"
    assert "non_hold_selection_disabled" in disabled.reason_codes
    assert expensive.selected_action == "HOLD"
    assert "minimum_expected_value_not_met" in expensive.reason_codes


@pytest.mark.parametrize(
    "observation",
    [
        None,
        _observation(observed_at_utc=BOUNDARY - timedelta(minutes=11)),
        _observation(battery_soc_percent=None, battery_energy_estimate_kwh=None),
        _observation(telemetry_is_healthy=False),
    ],
)
def test_missing_stale_or_unhealthy_current_state_is_blocked(observation):
    result = _evaluate(observation=observation)
    assert result.status == "blocked"
    assert result.selected_action is None


def test_unknown_signs_and_constraints_block_non_hold_without_inventing_values():
    signs = _evaluate(observation=_observation(sign_convention_status="unconfirmed"))
    limits = _evaluate(
        config=_config(
            maximum_export_power_w=0,
            maximum_discharge_power_w=0,
            import_limit_w=0,
        )
    )
    assert signs.selected_action == "HOLD"
    assert all(
        "directional_flow_signs_unconfirmed" in item.blocking_constraints
        for item in signs.candidates
        if item.action
        not in {"HOLD", "CHARGE_EV_NOW", "DEFER_EV", "PRESERVE_EV_ENERGY_REQUIREMENT"}
    )
    constrained = {item.action: item for item in limits.candidates}
    assert not constrained["CHARGE_BATTERY_FROM_GRID"].feasible
    assert not constrained["EXPORT_BATTERY"].feasible
    assert constrained["CHARGE_BATTERY_FROM_GRID"].gross_incremental_value_aud is None


def test_reserve_is_never_crossed_and_window_uses_remaining_boundary_time():
    result = _evaluate(
        created_at_utc=BOUNDARY + timedelta(minutes=10),
        observation=_observation(
            observed_at_utc=BOUNDARY + timedelta(minutes=9),
            battery_energy_estimate_kwh=12.0,
            battery_soc_percent=30.0,
        ),
    )
    export = next(item for item in result.candidates if item.action == "EXPORT_BATTERY")
    assert result.selected_candidate.end_utc == BOUNDARY + timedelta(minutes=30)
    assert result.selected_candidate.start_utc == BOUNDARY + timedelta(minutes=10)
    assert not export.feasible
    assert "battery_energy_above_reserve_insufficient" in export.blocking_constraints


def test_duration_weighted_amber_prices_handle_negative_and_one_second_boundary():
    start = BOUNDARY
    prices = [
        _interval(start, -0.10, 15),
        {
            **_interval(start + timedelta(minutes=15, seconds=1), 0.30, 15),
            "end_time": (start + timedelta(minutes=30)).isoformat(),
        },
    ]
    coverage = integrate_price_intervals(
        prices, start=start, end=start + timedelta(minutes=30)
    )
    assert coverage.complete
    assert coverage.weighted_average_aud_per_kwh == pytest.approx(0.10, abs=0.001)


def test_real_price_gap_is_exposed_and_forces_hold():
    observation = _observation(
        amber_import_forecast_json=[_interval(BOUNDARY, 0.20, 10)]
    )
    result = _evaluate(observation=observation)
    assert result.selected_action == "HOLD"
    assert "price_window_incomplete" in result.reason_codes
    assert result.input_snapshot["import_price_coverage"]["coverage_percent"] < 100


def test_cheap_import_high_export_and_later_export_candidates_are_economic():
    cheap = _observation(
        amber_import_forecast_json=[
            _interval(BOUNDARY, -0.10),
            _interval(BOUNDARY + timedelta(minutes=30), 0.50),
        ],
        amber_export_forecast_json=[
            _interval(BOUNDARY, 0.05),
            _interval(BOUNDARY + timedelta(minutes=30), 0.10),
        ],
    )
    cheap_result = _evaluate(observation=cheap)
    cheap_candidates = {item.action: item for item in cheap_result.candidates}
    assert cheap_candidates["CHARGE_BATTERY_FROM_GRID"].feasible
    assert cheap_candidates["CHARGE_BATTERY_FROM_GRID"].gross_import_cost_aud < 0
    assert cheap_candidates["CHARGE_BATTERY_FROM_GRID"].power_w <= 5_000

    later = _observation(
        amber_export_forecast_json=[
            _interval(BOUNDARY, 0.10),
            _interval(BOUNDARY + timedelta(minutes=30), 0.80),
        ]
    )
    later_result = _evaluate(observation=later)
    later_candidate = next(
        item for item in later_result.candidates if item.action == "DEFER_EXPORT"
    )
    assert later_candidate.feasible
    assert later_candidate.gross_incremental_value_aud > 0


def test_export_cap_headroom_and_negative_export_prices_are_respected():
    capped = _evaluate(config=_config(maximum_export_power_w=2_000))
    export = next(item for item in capped.candidates if item.action == "EXPORT_BATTERY")
    assert export.power_w == 2_000
    assert abs(export.grid_energy_delta_kwh) == pytest.approx(1.0)

    nearly_full = _evaluate(
        observation=_observation(
            battery_energy_estimate_kwh=39.9, battery_soc_percent=99.75
        )
    )
    charge = next(
        item
        for item in nearly_full.candidates
        if item.action == "CHARGE_BATTERY_FROM_GRID"
    )
    assert charge.battery_energy_delta_kwh == pytest.approx(0.1)

    negative = _observation(
        amber_export_forecast_json=[
            _interval(BOUNDARY, -0.20),
            _interval(BOUNDARY + timedelta(minutes=30), -0.30),
        ]
    )
    negative_result = _evaluate(observation=negative)
    negative_export = next(
        item for item in negative_result.candidates if item.action == "EXPORT_BATTERY"
    )
    assert negative_export.gross_export_revenue_aud < 0
    assert negative_export.gross_incremental_value_aud < 0


@pytest.mark.parametrize(
    ("updates", "expected_reason"),
    [
        ({"forecast_run": None}, "forecast_missing"),
        ({"reserve_run": None}, "reserve_missing"),
        (
            {
                "observation": _observation(
                    solcast_next_hour_kwh_json=None,
                    solcast_remaining_today_kwh_json=None,
                )
            },
            "solar_constraint_context_uncertain",
        ),
    ],
)
def test_missing_forecast_reserve_or_solcast_falls_back_to_hold(
    updates, expected_reason
):
    result = _evaluate(**updates)
    assert result.selected_action == "HOLD"
    assert expected_reason in result.reason_codes


def test_entity_specific_stale_soc_blocks_even_with_fresh_observation():
    observation = _observation(
        health_domains_json={
            "telemetry": {
                "entity_freshness": {"battery_state_of_charge": "source_update_stale"}
            }
        }
    )
    result = _evaluate(observation=observation)
    assert result.status == "blocked"
    assert "battery_soc_stale" in result.reason_codes


def test_outcome_scoring_reports_coverage_regret_reserve_and_intervention():
    result = _evaluate()
    candidates = []
    for candidate_id, candidate in enumerate(result.candidates, 1):
        candidates.append({"id": candidate_id, **candidate.as_record()})
    observations = []
    for offset in range(0, 30, 5):
        observations.append(
            {
                "slot_utc": BOUNDARY + timedelta(minutes=offset),
                "battery_energy_estimate_kwh": 11.5 if offset == 25 else 30.0,
                "grid_import_power_w": 0.0,
                "grid_export_power_w": 2_000.0,
                "battery_charge_power_w": 0.0,
                "battery_discharge_power_w": 2_000.0,
                "house_consumption_w": 1_000.0,
                "pv_power_w": 500.0,
                "amber_import_price_per_kwh": 0.20,
                "amber_export_price_per_kwh": 0.80,
            }
        )
    outcome = score_shadow_outcome(
        decision_run={
            "id": 9,
            "selected_action": result.selected_action,
            "selected_start_utc": BOUNDARY,
            "selected_end_utc": BOUNDARY + timedelta(minutes=30),
            "constraint_snapshot_json": {"recommended_reserve_kwh": 12.0},
        },
        candidates=candidates,
        observations=observations,
        scored_at_utc=BOUNDARY + timedelta(hours=1),
    )
    assert outcome["actual_coverage_percent"] == 100
    assert outcome["simulated_reserve_breach"] is True
    assert outcome["operator_intervention_possible"] is True
    assert outcome["counterfactual_confidence"] == "low"
    assert outcome["hindsight_best_action"] is not None
    assert outcome["regret_aud"] is not None
    assert (
        "simulated_counterfactual_not_a_physical_measurement"
        in outcome["counterfactual_limitations_json"]
    )


def test_backfill_planner_ignores_legacy_identity_and_exposes_progress():
    target = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)

    class Repository:
        def forecast_rollup_candidate_targets_read_only(self, **_kwargs):
            return [target], False

        def forecast_rollup_rows_read_only(self, **_kwargs):
            return [
                {
                    "rollup_date": date(2026, 8, 19),
                    "forecast_type": "baseline_household_load",
                    "model_version": "legacy",
                    "alignment_version": "legacy",
                    "training_policy": "legacy_all_eligible",
                    "horizon_bucket": "0-3h",
                    "calculated_at_utc": BOUNDARY,
                }
            ], False

    status = forecast_rollup_backfill_status(
        Repository(),
        forecast_type="baseline_household_load",
        model_version="current",
        alignment_version_name="full_5m_v1",
        training_policy="verified_preferred",
        window_start=date(2026, 8, 18),
        window_end=date(2026, 8, 20),
        timezone_name="Australia/Brisbane",
    )
    assert status["rollup_backfill_status"] == "in_progress"
    assert status["eligible_dates"] == 1
    assert status["completed_dates"] == 0
    assert status["remaining_dates"] == 1
    assert status["remaining_local_dates"] == [date(2026, 8, 19)]
    assert status["current_identity_complete"] is False


@pytest.mark.parametrize(
    ("forecast", "expected"),
    [
        (
            {"estimate10_kwh": 1.0, "estimate_kwh": 2.0, "estimate90_kwh": 3.0},
            (1.0, 2.0, 3.0),
        ),
        (
            {"estimate10": 1.0, "estimate": 2.0, "estimate90": 3.0},
            (1.0, 2.0, 3.0),
        ),
        (
            {
                "estimate10": 1_000,
                "estimate": 2_000,
                "estimate90": 3_000,
                "source_unit": "Wh",
            },
            (1.0, 2.0, 3.0),
        ),
    ],
)
def test_solcast_diagnostics_support_normalized_and_legacy_keys(forecast, expected):
    local = datetime(2026, 8, 20, 12, tzinfo=UTC)
    rows = [
        {
            "observed_at_local": local + timedelta(minutes=5 * index),
            "pv_power_w": 2_000.0,
            "telemetry_is_healthy": True,
            "solcast_today_kwh_json": forecast,
        }
        for index in range(288)
    ]
    result = calculate_solar_diagnostics(rows)[0]
    assert (
        result["solcast_p10_kwh"],
        result["solcast_p50_kwh"],
        result["solcast_p90_kwh"],
    ) == expected


def _reserve_values(forecast_id: int) -> dict:
    return {
        "forecast_run_id": forecast_id,
        "evaluation_timestamp_utc": BOUNDARY,
        "observation_timestamp_utc": BOUNDARY,
        "observation_source": "history",
        "observation_age_seconds": 0,
        "observation_is_stale": False,
        "battery_soc_percent": 80,
        "battery_energy_kwh": 32,
        "usable_battery_capacity_kwh": 40,
        "forecast_start_utc": BOUNDARY,
        "forecast_end_utc": BOUNDARY + timedelta(hours=1),
        "forecast_horizon_minutes": 60,
        "forecast_horizon_hours": 1,
        "household_demand_kwh": 1,
        "ev_demand_kwh": 0,
        "technical_reserve_kwh": 8,
        "emergency_reserve_kwh": 4,
        "uncertainty_buffer_kwh": 0,
        "gross_reserve_requirement_kwh": 12,
        "capacity_capped_reserve_kwh": 12,
        "unmet_reserve_requirement_kwh": 0,
        "current_reserve_shortfall_kwh": 0,
        "recommended_reserve_kwh": 12,
        "potentially_tradable_kwh": 20,
        "confidence": "medium",
        "confidence_score": 60,
        "ready_for_manual_review": True,
        "opportunity_state": "none",
        "first_candidate_json": {},
        "effective_boundary_json": None,
        "skipped_candidate_count": 0,
        "expected_replenishment_kwh": None,
        "command_issued": False,
        "model_version": "reserve-v1",
        "reasons_json": {},
        "confidence_json": {},
        "health_json": {},
        "operational_context_json": {},
        "demand_forecast_json": {},
        "estimate_json": {},
    }


def _persist_dependencies(repository) -> tuple[int, int]:
    forecast_id = repository.save_forecast_run(
        ForecastRun(
            created_at_utc=BOUNDARY,
            forecast_type="baseline_household_load",
            source="scheduled_forecast_operations",
            horizon_start_utc=BOUNDARY,
            horizon_end_utc=BOUNDARY + timedelta(hours=1),
            model_version="household-demand-hierarchy-v1-cohort-v1",
            metadata={
                "alignment_version": "full_5m_v1",
                "training_policy": "verified_preferred",
            },
            points=[
                ForecastPoint(
                    period_start_utc=BOUNDARY,
                    period_end_utc=BOUNDARY + timedelta(minutes=5),
                    expected_value=1_000,
                    unit="W",
                )
            ],
        )
    )
    with repository.transaction() as session:
        reserve_id = session.execute(
            insert(ReserveRun)
            .values(**_reserve_values(forecast_id))
            .returning(ReserveRun.id)
        ).scalar_one()
    return forecast_id, int(reserve_id)


def test_shadow_persistence_is_atomic_idempotent_and_no_command_constrained(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'shadow.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    forecast_id, reserve_id = _persist_dependencies(repository)
    result = _evaluate(
        observation=_observation(slot_utc=None),
        forecast_run=_forecast(run_id=forecast_id),
        reserve_run=_reserve(run_id=reserve_id, forecast_id=forecast_id),
    )
    run_id = repository.save_shadow_decision(
        result,
        forecast_run_id=forecast_id,
        reserve_run_id=reserve_id,
        shadow_enabled=True,
        non_hold_enabled=True,
    )
    assert run_id is not None
    assert (
        repository.save_shadow_decision(
            result,
            forecast_run_id=forecast_id,
            reserve_run_id=reserve_id,
            shadow_enabled=True,
            non_hold_enabled=True,
        )
        is None
    )
    detail = repository.shadow_decision_detail_read_only(run_id)
    assert detail["no_command_issued"] is True
    assert len(detail["candidates"]) == len(result.candidates)
    ev = next(
        item for item in detail["candidates"] if item["action"] == "CHARGE_EV_NOW"
    )
    assert ev["gross_incremental_value_aud"] is None
    assert ev["price_coverage_percent"] is None
    assert repository.table_counts().shadow_decision_runs == 1
    with pytest.raises(IntegrityError), repository.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE shadow_decision_runs SET no_command_issued=false WHERE id=:id"
            ),
            {"id": run_id},
        )
    repository.close()


def test_outcome_rows_are_idempotent_per_version_and_append_for_new_version(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'outcomes.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    forecast_id, reserve_id = _persist_dependencies(repository)
    result = _evaluate(
        observation=_observation(slot_utc=None),
        forecast_run=_forecast(run_id=forecast_id),
        reserve_run=_reserve(run_id=reserve_id, forecast_id=forecast_id),
    )
    run_id = repository.save_shadow_decision(
        result,
        forecast_run_id=forecast_id,
        reserve_run_id=reserve_id,
        shadow_enabled=True,
        non_hold_enabled=True,
    )
    detail = repository.shadow_decision_detail_read_only(run_id)
    rows = [
        {
            "slot_utc": BOUNDARY + timedelta(minutes=offset),
            "battery_energy_estimate_kwh": 30,
            "grid_import_power_w": 0,
            "grid_export_power_w": 1_000,
            "battery_charge_power_w": 0,
            "battery_discharge_power_w": 1_000,
            "house_consumption_w": 1_000,
            "pv_power_w": 500,
            "amber_import_price_per_kwh": 0.20,
            "amber_export_price_per_kwh": 0.80,
        }
        for offset in range(0, 30, 5)
    ]
    original_hash = detail["input_hash"]
    outcome = score_shadow_outcome(
        decision_run=detail,
        candidates=detail["candidates"],
        observations=rows,
        scored_at_utc=BOUNDARY + timedelta(hours=1),
    )
    assert repository.save_shadow_outcome(outcome) is not None
    assert repository.save_shadow_outcome(outcome) is None
    revised = {**outcome, "scoring_version": "battery-shadow-outcome-v2-test"}
    assert repository.save_shadow_outcome(revised) is not None
    assert len(repository.shadow_outcome_rows_read_only(limit=10)) == 2
    assert (
        repository.shadow_decision_detail_read_only(run_id)["input_hash"]
        == original_hash
    )
    repository.close()


def test_v060_sqlite_migration_downgrade_reupgrade_preserves_preexisting_data(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, "20260814_01")
    engine = open_repository(url)
    forecast_id, _ = _persist_dependencies(engine)
    command.upgrade(config, "head")
    assert current_revision(engine.engine) == "20260905_01"
    assert "shadow_decision_runs" in inspect(engine.engine).get_table_names()
    command.downgrade(config, "20260814_01")
    assert current_revision(engine.engine) == "20260814_01"
    assert "shadow_decision_runs" not in inspect(engine.engine).get_table_names()
    assert engine.forecast_run(forecast_id) is not None
    command.upgrade(config, "head")
    assert current_revision(engine.engine) == "20260905_01"
    assert engine.forecast_run(forecast_id) is not None
    engine.close()


def test_v060_migration_compiles_reversible_postgresql_ddl():
    from io import StringIO

    output = StringIO()
    config = alembic_config(
        "postgresql+psycopg://migration:placeholder@example.invalid/home_energy"
    )
    config.output_buffer = output
    command.upgrade(config, "20260814_01:20260905_01", sql=True)
    command.downgrade(config, "20260905_01:20260814_01", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE shadow_decision_runs" in sql
    assert "CREATE TABLE shadow_decision_candidates" in sql
    assert "CREATE TABLE shadow_decision_outcomes" in sql
    assert "DROP TABLE shadow_decision_runs" in sql


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for PostgreSQL 17 compatibility",
)
def test_v060_postgresql_populated_migration_round_trip():
    configured = os.environ["TEST_POSTGRES_URL"]
    schema = f"v060_migration_{uuid.uuid4().hex}"
    admin_engine = create_database_engine(configured)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    parsed = make_url(configured)
    query = dict(parsed.query)
    current_options = query.get("options", "").strip()
    query["options"] = " ".join(
        item for item in (current_options, f"-csearch_path={schema}") if item
    )
    isolated_url = parsed.set(query=query).render_as_string(hide_password=False)
    repository = None
    try:
        migration = alembic_config(isolated_url)
        command.upgrade(migration, "20260814_01")
        repository = open_repository(isolated_url)
        forecast_id, reserve_id = _persist_dependencies(repository)
        command.upgrade(migration, "20260905_01")
        with Session(repository.engine) as session, session.begin():
            point_id = session.scalar(
                select(DBForecastPoint.id).where(
                    DBForecastPoint.forecast_run_id == forecast_id
                )
            )
            session.add(
                ForecastPointScore(
                    forecast_point_id=point_id,
                    scored_at_utc=BOUNDARY + timedelta(minutes=10),
                    actual_value=1_100,
                    absolute_error=100,
                    signed_error=100,
                    squared_error=10_000,
                    actual_available=True,
                    health_eligible=True,
                    missing_reason=None,
                    metadata_json={},
                )
            )
        targets, truncated = repository.forecast_rollup_candidate_targets_read_only(
            forecast_type="baseline_household_load",
            model_version="household-demand-hierarchy-v1-cohort-v1",
            alignment_version="full_5m_v1",
            training_policy="verified_preferred",
            after=BOUNDARY - timedelta(minutes=5),
            before=BOUNDARY + timedelta(minutes=10),
        )
        assert targets == [BOUNDARY]
        assert truncated is False
        result = _evaluate(
            observation=_observation(slot_utc=None),
            forecast_run=_forecast(run_id=forecast_id),
            reserve_run=_reserve(run_id=reserve_id, forecast_id=forecast_id),
        )
        decision_id = repository.save_shadow_decision(
            result,
            forecast_run_id=forecast_id,
            reserve_run_id=reserve_id,
            shadow_enabled=True,
            non_hold_enabled=True,
        )
        assert decision_id is not None
        assert repository.table_counts().shadow_decision_candidates == 9
        command.downgrade(migration, "20260814_01")
        assert current_revision(repository.engine) == "20260814_01"
        assert repository.forecast_run(forecast_id) is not None
        command.upgrade(migration, "20260905_01")
        assert current_revision(repository.engine) == "20260905_01"
        assert repository.forecast_run(forecast_id) is not None
        assert repository.table_counts().shadow_decision_runs == 0
    finally:
        if repository is not None:
            repository.close()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_coordinator_persists_shadow_after_reserve_in_same_boundary(
    tmp_path, healthy_states, config
):
    url = f"sqlite+pysqlite:///{(tmp_path / 'coordinator.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    created = datetime(2026, 8, 1, 2, 8, tzinfo=UTC)
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=created)
    )
    repository.close()
    health = AppHealth(900)
    coordinator = ForecastCoordinator(
        repository_factory=lambda: open_repository(url),
        collector_config=config,
        operations_config=ForecastOperationsConfig(
            enabled=True, reserve_snapshot_enabled=True
        ),
        shadow_config=ShadowDecisionConfig(enabled=True),
        health=health,
        clock=lambda: created,
    )

    assert coordinator.run_boundary(BOUNDARY.replace(month=8, day=1, minute=0))
    assert not coordinator.run_boundary(BOUNDARY.replace(month=8, day=1, minute=0))
    repository = open_repository(url)
    try:
        rows = repository.shadow_decision_rows_read_only(limit=5)
        assert len(rows) == 1
        detail = repository.shadow_decision_detail_read_only(rows[0]["id"])
        assert detail["forecast_run_id"] is not None
        assert detail["reserve_run_id"] is not None
        assert len(detail["candidates"]) == 9
        assert detail["selected_action"] == "HOLD"
        assert detail["no_command_issued"] is True
        attempt = repository.forecast_operations_status_read_only()["last_attempt"]
        assert attempt["status"] == "success"
        assert attempt["metadata_json"]["shadow_decision_run_id"] == detail["id"]
        before_replay = repository.table_counts()
        replay = replay_persisted_shadow_decision(repository, detail["id"])
        assert replay["synthetic_replay"] is True
        assert replay["database_write_performed"] is False
        assert replay["selected_action"] == detail["selected_action"]
        assert repository.table_counts() == before_replay
    finally:
        repository.close()
    assert health.shadow_decisioning == "healthy"


def test_disabled_shadow_creates_no_run_and_leaves_forecast_reserve_working(
    tmp_path, healthy_states, config
):
    url = f"sqlite+pysqlite:///{(tmp_path / 'disabled.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    created = datetime(2026, 8, 1, 2, 8, tzinfo=UTC)
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=created)
    )
    repository.close()
    health = AppHealth(900)
    coordinator = ForecastCoordinator(
        repository_factory=lambda: open_repository(url),
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=True),
        health=health,
        clock=lambda: created,
    )
    assert coordinator.run_boundary(created.replace(minute=0))
    repository = open_repository(url)
    counts = repository.table_counts()
    repository.close()
    assert counts.forecast_runs == 1
    assert counts.reserve_runs == 1
    assert counts.shadow_decision_runs == 0
    assert health.collector == "healthy"


def test_shadow_runtime_timeout_isolated_from_forecast_and_collector(
    monkeypatch, tmp_path, healthy_states, config
):
    url = f"sqlite+pysqlite:///{(tmp_path / 'shadow-timeout.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    created = datetime(2026, 8, 1, 2, 8, tzinfo=UTC)
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=created)
    )
    repository.close()
    elapsed = {"value": 0.0}
    original = evaluate_shadow_decision

    def slow_evaluate(**kwargs):
        result = original(**kwargs)
        elapsed["value"] = 61.0
        return result

    monkeypatch.setattr(
        "energy_optimizer.forecast_operations.evaluate_shadow_decision",
        slow_evaluate,
    )
    health = AppHealth(900)
    coordinator = ForecastCoordinator(
        repository_factory=lambda: open_repository(url),
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=True),
        shadow_config=ShadowDecisionConfig(enabled=True, max_runtime_seconds=60),
        health=health,
        clock=lambda: created,
        monotonic=lambda: elapsed["value"],
    )
    assert coordinator.run_boundary(created.replace(minute=0))
    repository = open_repository(url)
    counts = repository.table_counts()
    attempt = repository.forecast_operations_status_read_only()["last_attempt"]
    repository.close()
    assert counts.forecast_runs == 1
    assert counts.reserve_runs == 1
    assert counts.shadow_decision_runs == 0
    assert attempt["status"] == "success"
    assert health.collector == "healthy"
    assert health.shadow_decisioning == "warning"


def test_dashboard_shadow_empty_state_limits_and_forecast_mode_are_read_only(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'dashboard.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    forecast_id, reserve_id = _persist_dependencies(repository)
    result = _evaluate(
        observation=_observation(slot_utc=None),
        forecast_run=_forecast(run_id=forecast_id),
        reserve_run=_reserve(run_id=reserve_id, forecast_id=forecast_id),
    )
    decision_id = repository.save_shadow_decision(
        result,
        forecast_run_id=forecast_id,
        reserve_run_id=reserve_id,
        shadow_enabled=True,
        non_hold_enabled=True,
    )
    before = repository.table_counts()
    repository.close()
    health = AppHealth(900)
    health.demand_training_policy = "verified_preferred"
    service = DashboardService(url, health)

    latest = service.latest_shadow_decision()
    history = service.shadow_decisions(limit=1)
    detail = service.shadow_decision(decision_id)
    outcomes = service.shadow_outcomes(limit=1)
    live = service.forecast_comparison_card(mode="live", now=BOUNDARY)
    complete = service.forecast_comparison_card(
        mode="latest_complete", now=BOUNDARY + timedelta(days=2)
    )
    assert latest.available and latest.decision["id"] == decision_id
    assert len(history.decisions) == 1
    assert detail.available and len(detail.decision["candidates"]) == 9
    assert outcomes.empty
    assert live.run_id == forecast_id
    assert len(live.points) == 1
    assert live.points[0].actual_w is None
    assert complete.empty_state["code"] == "no_complete_forecast"
    with pytest.raises(DashboardQueryError):
        service.forecast_comparison_card(mode="invented")
    repository = open_repository(url)
    assert repository.table_counts() == before
    repository.close()


def test_forecast_card_selects_latest_identity_not_best_performance(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'forecast-card.db').as_posix()}"
    repository = open_repository(url)
    repository.create_schema_for_tests()
    current = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)

    def save_run(start: datetime, actual: float | None) -> int:
        run_id = repository.save_forecast_run(
            ForecastRun(
                created_at_utc=start - timedelta(minutes=5),
                forecast_type="baseline_household_load",
                source="scheduled_forecast_operations",
                horizon_start_utc=start,
                horizon_end_utc=start + timedelta(hours=24),
                model_version="household-demand-hierarchy-v1-cohort-v1",
                metadata={
                    "alignment_version": "full_5m_v1",
                    "training_policy": "verified_preferred",
                },
                points=[
                    ForecastPoint(
                        period_start_utc=start + timedelta(minutes=5 * index),
                        period_end_utc=start + timedelta(minutes=5 * (index + 1)),
                        expected_value=1_000,
                        lower_value=800,
                        upper_value=1_200,
                        unit="W",
                    )
                    for index in range(288)
                ],
            )
        )
        if actual is not None:
            with Session(repository.engine) as session, session.begin():
                point_ids = list(
                    session.scalars(
                        select(DBForecastPoint.id).where(
                            DBForecastPoint.forecast_run_id == run_id
                        )
                    )
                )
                error = actual - 1_000
                session.execute(
                    insert(ForecastPointScore),
                    [
                        {
                            "forecast_point_id": point_id,
                            "scored_at_utc": current,
                            "actual_value": actual,
                            "absolute_error": abs(error),
                            "signed_error": error,
                            "squared_error": error**2,
                            "actual_available": True,
                            "health_eligible": True,
                            "missing_reason": None,
                            "metadata_json": {},
                        }
                        for point_id in point_ids
                    ],
                )
        return run_id

    older_better = save_run(current - timedelta(days=3), 1_100)
    newer_worse = save_run(current - timedelta(days=2), 3_000)
    live_run = save_run(current - timedelta(hours=1), None)
    before = repository.table_counts()
    repository.close()
    health = AppHealth(900)
    health.demand_training_policy = "verified_preferred"
    service = DashboardService(url, health)

    live = service.forecast_comparison_card(mode="live", now=current)
    complete = service.forecast_comparison_card(mode="latest_complete", now=current)
    assert live.run_id == live_run
    assert len(live.points) == 288
    assert all(point.actual_w is None for point in live.points)
    assert all(point.actual_missing_reason for point in live.points)
    assert complete.run_id == newer_worse
    assert complete.run_id != older_better
    assert len(complete.points) == 288
    assert complete.coverage["matured_actual_coverage_percent"] == 100
    assert complete.metrics["forecast_energy_kwh"] == pytest.approx(24)
    assert complete.metrics["actual_energy_kwh"] == pytest.approx(72)
    assert complete.metrics["signed_energy_error_kwh"] == pytest.approx(48)
    assert complete.metrics["mae_w"] == pytest.approx(2_000)
    assert complete.metrics["bias_w"] == pytest.approx(2_000)
    assert complete.metrics["wape_percent"] == pytest.approx(200 / 3)
    assert complete.identity["alignment_version"] == "full_5m_v1"
    assert complete.points[0].lower_w == 800
    assert complete.points[0].upper_w == 1_200
    repository = open_repository(url)
    assert repository.table_counts() == before
    repository.close()
