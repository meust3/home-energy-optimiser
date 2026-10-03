"""Synthetic local regression cases; no retained household records or credentials."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from test_shadow_decisioning import (
    BOUNDARY,
    _config,
    _evaluate,
    _forecast,
    _interval,
    _observation,
    _persist_dependencies,
    _reserve,
)

from energy_optimizer.collector import build_observation
from energy_optimizer.forecast_operations import (
    ForecastCoordinator,
    ForecastOperationsConfig,
)
from energy_optimizer.home_assistant_app import AppHealth
from energy_optimizer.persistence import open_repository
from energy_optimizer.shadow_decisioning import (
    CALCULATION_VERSION,
    POLICY_VERSION,
    _action_window_demand,
    _hash_snapshot,
    integrate_price_intervals,
)
from energy_optimizer.shadow_replay import replay_persisted_shadow_decision


def _linked():
    evaluation = BOUNDARY + timedelta(seconds=20)
    aligned = BOUNDARY + timedelta(minutes=5)
    forecast = _forecast()
    forecast.update(created_at_utc=evaluation, horizon_start_utc=aligned)
    forecast["points"] = forecast["points"][1:]
    for index, point in enumerate(forecast["points"]):
        point.update(id=index + 10, unit="W")
    reserve = _reserve(reserve=40)
    reserve.update(
        model_version="reserve-estimator-v1",
        evaluation_timestamp_utc=evaluation,
        observation_timestamp_utc=BOUNDARY,
        demand_forecast_json={
            "start_local": evaluation.isoformat(),
            "diagnostics": {"training_policy": "verified_preferred"},
            "slot_decisions": [
                {
                    "period_start_local": evaluation.isoformat(),
                    "period_end_local": aligned.isoformat(),
                    "expected_energy_kwh": 0.130174,
                },
                {
                    "period_start_local": aligned.isoformat(),
                    "period_end_local": (aligned + timedelta(minutes=5)).isoformat(),
                    # Deliberately different: operational data must own this span.
                    "expected_energy_kwh": 20,
                },
            ],
        },
        operational_context_json={
            "linked_forecast_reconciliation": {
                "semantics": "reserve_starts_at_evaluation_with_partial_boundaries",
                "evaluation_time_utc": evaluation.isoformat(),
                "history_as_of_utc": evaluation.isoformat(),
                "linked_forecast_start_utc": aligned.isoformat(),
            }
        },
    )
    return evaluation, forecast, reserve


def _demand(forecast, reserve, start, end=None):
    return _action_window_demand(
        forecast,
        reserve,
        start=start,
        end=end or BOUNDARY + timedelta(minutes=30),
    )


def test_partial_join_uses_operational_owner_and_freezes_compact_provenance():
    start, forecast, reserve = _linked()
    before = copy.deepcopy((forecast, reserve))
    energy, evidence = _demand(forecast, reserve, start)
    assert energy == pytest.approx(0.130174 + 25 / 60)
    assert evidence["complete"]
    assert evidence["covered_seconds"] == 1780
    assert len(evidence["segments"]) == 6
    assert evidence["segments"][0]["source"] == "reserve_partial"
    assert [p["point_id"] for p in evidence["segments"][1:]] == list(range(10, 15))
    assert evidence["partial_compatibility"]["history_as_of_utc"] == start.isoformat()
    assert evidence["forecast_run_id"] == forecast["id"]
    assert evidence["reserve_run_id"] == reserve["id"]
    assert len(json.dumps(evidence, allow_nan=False)) < 3000
    assert (forecast, reserve) == before
    result = _evaluate(
        created_at_utc=start,
        forecast_run=forecast,
        reserve_run=reserve,
        config=_config(allow_non_hold_recommendations=False),
    )
    assert result.input_snapshot["calculation_version"] == CALCULATION_VERSION
    assert result.input_snapshot["demand_energy_action_window_kwh"] == energy
    assert result.input_snapshot[
        "household_deficit_action_window_kwh"
    ] == pytest.approx(energy - 0.2 * 1780 / 3600)
    assert result.selected_action == "HOLD" and result.no_command_issued
    assert result.policy_version == POLICY_VERSION


@pytest.mark.parametrize(
    "offset,end_minutes,expected",
    [
        (0, 30, 0.5),
        (20, 12, 0.130174 + 7 / 60),
        (120, 30, 0.130174 * 180 / 280 + 25 / 60),
        (20, 3, 0.130174 * 160 / 280),
        (900, 30, 0.25),
    ],
)
def test_exact_aligned_clipped_and_late_windows(offset, end_minutes, expected):
    evaluation, forecast, reserve = _linked()
    start = BOUNDARY + timedelta(seconds=offset)
    if offset == 0:
        forecast = _forecast()
        reserve = _reserve()
    energy, evidence = _demand(
        forecast, reserve, start, BOUNDARY + timedelta(minutes=end_minutes)
    )
    assert energy == pytest.approx(expected)
    assert evidence["complete"]
    assert evidence["covered_seconds"] == (end_minutes * 60 - offset)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing_slots", "reserve_partial_slots_missing"),
        ("bad_slot", "reserve_partial_interval_invalid"),
        ("bad_energy", "reserve_partial_energy_invalid"),
        ("wrong_link", "reserve_forecast_link_missing_or_mismatched"),
        ("wrong_model", "reserve_demand_identity_incompatible"),
        ("wrong_policy", "reserve_demand_identity_incompatible"),
        ("wrong_alignment", "reserve_demand_identity_incompatible"),
        ("wrong_target", "operational_demand_target_incompatible"),
        ("missing_identity", "reserve_demand_identity_missing"),
        ("missing_reconciliation", "reserve_reconciliation_missing"),
        ("future_asof", "reserve_partial_provenance_incompatible"),
        ("future_observation", "reserve_partial_provenance_incompatible"),
        ("future_forecast", "forecast_created_after_action_start"),
        ("wrong_evaluation", "reserve_partial_provenance_incompatible"),
        ("wrong_aligned_start", "reserve_partial_provenance_incompatible"),
    ],
)
def test_partial_evidence_fails_closed_with_specific_reason(mutation, reason):
    start, forecast, reserve = _linked()
    demand = reserve["demand_forecast_json"]
    reconciliation = reserve["operational_context_json"][
        "linked_forecast_reconciliation"
    ]
    if mutation == "missing_slots":
        demand["slot_decisions"] = []
    elif mutation == "bad_slot":
        demand["slot_decisions"][0]["period_end_local"] = "bad"
    elif mutation == "bad_energy":
        demand["slot_decisions"][0]["expected_energy_kwh"] = float("inf")
    elif mutation == "wrong_link":
        reserve["forecast_run_id"] = 2
    elif mutation == "wrong_model":
        reserve["model_version"] = "unverified-model"
    elif mutation == "wrong_policy":
        demand["diagnostics"]["training_policy"] = "verified_only"
    elif mutation == "wrong_alignment":
        forecast["metadata_json"]["alignment_version"] = "partial"
    elif mutation == "wrong_target":
        forecast["forecast_type"] = "total_household_plus_ev"
    elif mutation == "missing_identity":
        demand.pop("diagnostics")
    elif mutation == "missing_reconciliation":
        reserve["operational_context_json"] = {}
    elif mutation == "future_asof":
        reconciliation["history_as_of_utc"] = (start + timedelta(seconds=1)).isoformat()
    elif mutation == "future_observation":
        reserve["observation_timestamp_utc"] = start + timedelta(seconds=1)
    elif mutation == "future_forecast":
        forecast["created_at_utc"] = start + timedelta(seconds=1)
    elif mutation == "wrong_evaluation":
        reserve["evaluation_timestamp_utc"] = start - timedelta(seconds=1)
    else:
        reconciliation["linked_forecast_start_utc"] = start.isoformat()
    result = _evaluate(created_at_utc=start, forecast_run=forecast, reserve_run=reserve)
    assert result.input_snapshot["demand_energy_action_window_kwh"] is None
    assert result.input_snapshot["household_deficit_action_window_kwh"] is None
    assert result.input_snapshot["action_window_demand_evidence"]["reason"] == reason


@pytest.mark.parametrize("source", ["reserve", "operational"])
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), -1])
def test_demand_nonfinite_or_missing_energy_stays_missing(source, invalid):
    start, forecast, reserve = _linked()
    if source == "reserve":
        reserve["demand_forecast_json"]["slot_decisions"][0][
            "expected_energy_kwh"
        ] = invalid
    else:
        forecast["points"][0]["expected_value"] = invalid
    energy, evidence = _demand(forecast, reserve, start)
    assert energy is None and not evidence["complete"]
    assert evidence["reason"].endswith("energy_invalid")


@pytest.mark.parametrize("source", ["reserve", "operational"])
@pytest.mark.parametrize("problem", ["gap", "overlap"])
def test_demand_gaps_and_overlaps_never_sum_to_full_coverage(source, problem):
    start, forecast, reserve = _linked()
    if source == "reserve":
        slots = reserve["demand_forecast_json"]["slot_decisions"]
        if problem == "overlap":
            slots.insert(0, copy.deepcopy(slots[0]))
        else:
            slots[0]["period_end_local"] = (BOUNDARY + timedelta(minutes=4)).isoformat()
    elif problem == "overlap":
        forecast["points"].insert(0, copy.deepcopy(forecast["points"][0]))
    else:
        # Reserve has this interval but must never fill an operational later gap.
        forecast["points"].pop(0)
    energy, evidence = _demand(forecast, reserve, start)
    assert energy is None
    assert evidence["reason"] == f"demand_{problem}"


def test_metadata_bound_rejects_excessively_fragmented_evidence():
    start, forecast, reserve = _linked()
    forecast["points"] = [
        {
            "period_start_utc": BOUNDARY + timedelta(minutes=5, seconds=i),
            "period_end_utc": BOUNDARY + timedelta(minutes=5, seconds=i + 1),
            "expected_value": 1000,
        }
        for i in range(1500)
    ]
    energy, evidence = _demand(forecast, reserve, start)
    assert energy is None and evidence["reason"] == "demand_segment_limit_exceeded"
    assert len(json.dumps(evidence)) < 1500


@pytest.mark.parametrize(
    "battery,reserve,margin,available,gate",
    [
        (25.6, 40, -14.4, 0, False),
        (40, 40, 0, 0, True),
        (32, 12, 20, 20, True),
        (32, None, None, None, None),
        (None, 12, None, None, None),
    ],
)
def test_signed_hold_margin_separate_from_available_energy(
    battery, reserve, margin, available, gate
):
    result = _evaluate(
        observation=_observation(
            battery_energy_estimate_kwh=battery, battery_soc_percent=None
        ),
        reserve_run=_reserve(reserve=reserve),
        config=_config(allow_non_hold_recommendations=False),
    )
    hold = next(c for c in result.candidates if c.action == "HOLD")
    preserve = next(c for c in result.candidates if c.action == "PRESERVE_BATTERY")
    assert hold.feasible
    assert (
        hold.reserve_margin_after_kwh == pytest.approx(margin)
        if margin is not None
        else hold.reserve_margin_after_kwh is None
    )
    assert preserve.reserve_margin_after_kwh == hold.reserve_margin_after_kwh
    assert result.constraint_snapshot["energy_above_reserve_kwh"] == available
    assert hold.ranking_components["reserve_gate_passed"] is gate
    # Missing SOC makes the run blocked, without inventing a selected HOLD.
    assert result.selected_action is None and result.status == "blocked"


def test_below_reserve_hold_still_selected_and_unknown_limits_still_block_actions():
    result = _evaluate(
        observation=_observation(battery_energy_estimate_kwh=25.6),
        reserve_run=_reserve(reserve=40),
        config=_config(
            allow_non_hold_recommendations=False,
            maximum_export_power_w=0,
            maximum_discharge_power_w=0,
            import_limit_w=0,
        ),
    )
    assert result.selected_action == "HOLD"
    assert result.selected_candidate.reserve_margin_after_kwh == pytest.approx(-14.4)
    assert not result.selected_candidate.ranking_components["reserve_gate_passed"]
    for candidate in result.candidates:
        if candidate.action in {
            "EXPORT_BATTERY",
            "DISCHARGE_FOR_SELF_CONSUMPTION",
            "CHARGE_BATTERY_FROM_GRID",
        }:
            assert not candidate.feasible
    assert result.no_command_issued


@pytest.mark.parametrize("gap", [0, 1, 2, 4])
def test_price_tolerance_per_internal_boundary(gap):
    rows = [
        _interval(BOUNDARY, -0.1, 15),
        {
            **_interval(BOUNDARY + timedelta(minutes=15, seconds=gap), 0.3, 15),
            "end_time": (BOUNDARY + timedelta(minutes=30)).isoformat(),
        },
    ]
    coverage = integrate_price_intervals(
        rows, start=BOUNDARY, end=BOUNDARY + timedelta(minutes=30)
    )
    assert coverage.complete is (gap <= 1)
    assert coverage.represented_seconds == 1800 - gap
    assert coverage.tolerated_boundary_seconds == (gap if gap <= 1 else 0)
    assert coverage.uncovered_seconds == (gap if gap > 1 else 0)
    assert coverage.weighted_average_aud_per_kwh == pytest.approx(
        (-90 + (900 - gap) * 0.3) / (1800 - gap)
    )


@pytest.mark.parametrize("edge", ["leading", "trailing"])
@pytest.mark.parametrize("gap", [1, 0.001])
def test_endpoint_gaps_have_no_adjacent_boundary_allowance(edge, gap):
    left = BOUNDARY + timedelta(seconds=gap if edge == "leading" else 0)
    right = BOUNDARY + timedelta(minutes=30, seconds=-gap if edge == "trailing" else 0)
    coverage = integrate_price_intervals(
        [{"start_time": left, "end_time": right, "per_kwh": 0}],
        start=BOUNDARY,
        end=BOUNDARY + timedelta(minutes=30),
    )
    assert not coverage.complete and coverage.tolerated_boundary_seconds == 0
    assert coverage.weighted_average_aud_per_kwh == 0


def test_individual_offsets_cannot_subsidize_a_two_second_gap():
    rows = [
        {
            "start_time": BOUNDARY + timedelta(seconds=s),
            "end_time": BOUNDARY + timedelta(seconds=e),
            "per_kwh": 0,
        }
        for s, e in [(0, 600), (601, 1200), (1201, 1800)]
    ]
    coverage = integrate_price_intervals(
        rows, start=BOUNDARY, end=BOUNDARY + timedelta(minutes=30)
    )
    assert coverage.complete and coverage.tolerated_boundary_seconds == 2
    rows[1]["start_time"] += timedelta(seconds=1)
    initial = integrate_price_intervals(
        rows, start=BOUNDARY, end=BOUNDARY + timedelta(minutes=30)
    )
    rows.extend([_interval(BOUNDARY - timedelta(hours=1), 99), copy.deepcopy(rows[0])])
    repeated = integrate_price_intervals(
        rows, start=BOUNDARY, end=BOUNDARY + timedelta(minutes=30)
    )
    assert not initial.complete and initial == repeated
    assert initial.uncovered_seconds == 2


@pytest.mark.parametrize("price", [None, float("nan"), float("inf"), -float("inf")])
def test_invalid_prices_never_count_as_coverage(price):
    coverage = integrate_price_intervals(
        [_interval(BOUNDARY, price)],
        start=BOUNDARY,
        end=BOUNDARY + timedelta(minutes=30),
    )
    assert not coverage.complete and coverage.weighted_average_aud_per_kwh is None


def test_conflicting_duplicates_follow_sorted_first_without_favorable_price_selection():
    low, high = _interval(BOUNDARY, -0.2), _interval(BOUNDARY, 99)
    first = integrate_price_intervals(
        [low, high], start=BOUNDARY, end=BOUNDARY + timedelta(minutes=30)
    )
    reversed_first = integrate_price_intervals(
        [high, low], start=BOUNDARY, end=BOUNDARY + timedelta(minutes=30)
    )
    assert first.complete and first.represented_seconds == 1800
    assert first.weighted_average_aud_per_kwh == -0.2
    assert reversed_first.weighted_average_aud_per_kwh == 99
    # The known stable source-order limitation is retained, not a price optimizer.


def test_existing_json_serialization_and_dedup_preserve_historical_semantics(tmp_path):
    repository = open_repository(
        f"sqlite+pysqlite:///{(tmp_path / 'evidence.db').as_posix()}"
    )
    try:
        repository.create_schema_for_tests()
        forecast_id, reserve_id = _persist_dependencies(repository)
        start, forecast, reserve = _linked()
        forecast["id"] = forecast_id
        reserve.update(id=reserve_id, forecast_run_id=forecast_id)
        result = _evaluate(
            created_at_utc=start,
            observation=_observation(slot_utc=None),
            forecast_run=forecast,
            reserve_run=reserve,
        )
        legacy_input = copy.deepcopy(result.input_snapshot)
        legacy_input.pop("calculation_version")
        legacy_input.pop("action_window_demand_evidence")
        legacy_input["demand_energy_action_window_kwh"] = None
        legacy_input["household_deficit_action_window_kwh"] = None
        legacy_hash = _hash_snapshot(
            {
                "policy_version": POLICY_VERSION,
                "decision_boundary_utc": result.decision_boundary_utc.isoformat(),
                "input": legacy_input,
                "constraints": result.constraint_snapshot,
                "assumptions": result.assumption_snapshot,
            }
        )
        result = replace(result, input_snapshot=legacy_input, input_hash=legacy_hash)
        legacy_id = repository.save_shadow_decision(
            result,
            forecast_run_id=forecast_id,
            reserve_run_id=reserve_id,
            shadow_enabled=True,
            non_hold_enabled=False,
        )
        legacy_before = repository.shadow_decision_detail_read_only(legacy_id)
        corrected = _evaluate(
            created_at_utc=start,
            observation=_observation(slot_utc=None),
            forecast_run=forecast,
            reserve_run=reserve,
        )
        assert (
            repository.save_shadow_decision(
                corrected,
                forecast_run_id=forecast_id,
                reserve_run_id=reserve_id,
                shadow_enabled=True,
                non_hold_enabled=False,
            )
            is None
        )
        assert repository.shadow_decision_detail_read_only(legacy_id) == legacy_before
        future = _evaluate(
            decision_boundary_utc=BOUNDARY + timedelta(minutes=30),
            created_at_utc=BOUNDARY + timedelta(minutes=30),
            observation=_observation(slot_utc=None),
            forecast_run=forecast,
            reserve_run=reserve,
        )
        future_id = repository.save_shadow_decision(
            future,
            forecast_run_id=forecast_id,
            reserve_run_id=reserve_id,
            shadow_enabled=True,
            non_hold_enabled=False,
        )
        detail = repository.shadow_decision_detail_read_only(future_id)
        assert (
            detail["input_snapshot_json"]["calculation_version"] == CALCULATION_VERSION
        )
        assert (
            detail["input_snapshot_json"]["action_window_demand_evidence"]
            == future.input_snapshot["action_window_demand_evidence"]
        )
        assert detail["no_command_issued"]
        assert legacy_before["input_hash"] == legacy_hash
    finally:
        repository.close()


def test_real_coordinator_snapshot_shape_supplies_compatible_partial_demand(
    tmp_path, healthy_states, config
):
    url = f"sqlite+pysqlite:///{(tmp_path / 'partial_cycle.db').as_posix()}"
    created = BOUNDARY.replace(day=1, minute=10, second=20)
    repository = open_repository(url)
    repository.create_schema_for_tests()
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=created)
    )
    repository.close()
    coordinator = ForecastCoordinator(
        repository_factory=lambda: open_repository(url),
        collector_config=config,
        operations_config=ForecastOperationsConfig(
            enabled=True, reserve_snapshot_enabled=True
        ),
        shadow_config=_config(allow_non_hold_recommendations=False),
        health=AppHealth(900),
        clock=lambda: created,
    )
    assert coordinator.run_boundary(created.replace(minute=0, second=0))
    repository = open_repository(url)
    try:
        run = repository.shadow_decision_rows_read_only(limit=1)[0]
        detail = repository.shadow_decision_detail_read_only(run["id"])
        evidence = detail["input_snapshot_json"]["action_window_demand_evidence"]
        assert evidence["complete"], evidence["reason"]
        assert evidence["segments"][0]["source"] == "reserve_partial"
        assert evidence["segments"][0]["seconds"] == 280
        assert evidence["segments"][1]["point_id"] is not None
        assert detail["selected_action"] == "HOLD" and detail["no_command_issued"]
        replay = replay_persisted_shadow_decision(repository, run["id"])
        assert replay["source_calculation_version"] == CALCULATION_VERSION
        assert replay["replay_calculation_version"] == CALCULATION_VERSION
        assert replay["calculation_semantics_match"]
        assert not replay["database_write_performed"]
    finally:
        repository.close()


def test_empty_late_window_does_not_invent_demand():
    start, forecast, reserve = _linked()
    energy, evidence = _demand(forecast, reserve, start + timedelta(hours=1))
    assert energy is None and evidence["reason"] == "empty_action_window"


def test_wrong_point_link_and_units_remain_unavailable():
    start, forecast, reserve = _linked()
    forecast["points"][0]["forecast_run_id"] = 99
    assert (
        _demand(forecast, reserve, start)[1]["reason"]
        == "operational_point_link_mismatched"
    )
    forecast["points"][0].pop("forecast_run_id")
    forecast["points"][0]["unit"] = "kWh"
    assert (
        _demand(forecast, reserve, start)[1]["reason"] == "operational_energy_invalid"
    )


@pytest.mark.parametrize("field", ["demand_forecast_json", "operational_context_json"])
def test_malformed_partial_json_stays_unavailable(field):
    start, forecast, reserve = _linked()
    reserve[field] = "{malformed"
    assert _demand(forecast, reserve, start)[0] is None


def test_partial_consumed_window_failure_is_located():
    start, forecast, reserve = _linked()
    forecast["points"].pop(1)
    energy, evidence = _demand(forecast, reserve, start)
    assert energy is None
    assert evidence["covered_seconds"] == 580
    assert evidence["problem_window"] == {
        "start_utc": (BOUNDARY + timedelta(minutes=10)).isoformat(),
        "end_utc": (BOUNDARY + timedelta(minutes=15)).isoformat(),
    }


def test_operational_header_cannot_hide_pre_alignment_overlap():
    start, forecast, reserve = _linked()
    forecast["points"].insert(
        0,
        {
            "period_start_utc": BOUNDARY,
            "period_end_utc": BOUNDARY + timedelta(minutes=5),
            "expected_value": 2000,
        },
    )
    energy, evidence = _demand(forecast, reserve, start)
    assert energy is None and evidence["reason"] == "operational_alignment_inconsistent"
