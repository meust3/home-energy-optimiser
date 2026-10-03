"""Synthetic producer and persistence witnesses for both disposable backends."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from test_shadow_decisioning import (
    BOUNDARY,
    _config,
    _evaluate,
    _observation,
    _persist_dependencies,
)
from test_shadow_evidence import _linked

from energy_optimizer.collector import build_observation
from energy_optimizer.dashboard_api import DashboardService
from energy_optimizer.forecast_operations import (
    ForecastCoordinator,
    ForecastOperationsConfig,
)
from energy_optimizer.home_assistant_app import AppHealth
from energy_optimizer.persistence import open_repository
from energy_optimizer.shadow_decisioning import (
    CALCULATION_VERSION,
    score_shadow_outcome,
)
from energy_optimizer.shadow_replay import replay_persisted_shadow_decision


@pytest.fixture(params=["sqlite", "postgresql"])
def isolated_evidence_repository(request, tmp_path):
    admin = None
    schema = None
    if request.param == "sqlite":
        url = f"sqlite+pysqlite:///{(tmp_path / 'final-evidence.db').as_posix()}"
    else:
        configured = os.getenv("TEST_POSTGRES_URL")
        if not configured:
            pytest.skip("owned TEST_POSTGRES_URL required for final evidence parity")
        parsed = make_url(configured)
        # This extra witness deliberately requires the final-validation owner guard.
        assert parsed.host == "127.0.0.1"
        assert parsed.database == os.environ["F1_F3_OWNED_TEST_DATABASE"]
        admin = open_repository(configured)
        schema = f"f1_f3_{uuid.uuid4().hex}"
        with admin.engine.begin() as connection:
            assert (
                connection.scalar(text("SELECT current_database()")) == parsed.database
            )
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        query = dict(parsed.query)
        query["options"] = f"-csearch_path={schema}"
        url = parsed.set(query=query).render_as_string(hide_password=False)
    repository = open_repository(url)
    repository.create_schema_for_tests()
    try:
        yield repository, url
    finally:
        repository.close()
        if admin is not None:
            with admin.engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.close()


def _canonical(result_or_row):
    if isinstance(result_or_row, dict):
        row = result_or_row
        value = {
            "policy_version": row["policy_version"],
            "decision_boundary_utc": row["decision_boundary_utc"].isoformat(),
            "input": row["input_snapshot_json"],
            "constraints": row["constraint_snapshot_json"],
            "assumptions": row["assumption_snapshot_json"],
        }
    else:
        result = result_or_row
        value = {
            "policy_version": result.policy_version,
            "decision_boundary_utc": result.decision_boundary_utc.isoformat(),
            "input": result.input_snapshot,
            "constraints": result.constraint_snapshot,
            "assumptions": result.assumption_snapshot,
        }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def test_marker_hash_signed_null_api_and_legacy_dedup(isolated_evidence_repository):
    repository, url = isolated_evidence_repository
    forecast_id, reserve_id = _persist_dependencies(repository)
    start, forecast, reserve = _linked()
    forecast["id"] = forecast_id
    reserve.update(id=reserve_id, forecast_run_id=forecast_id)
    arguments = dict(
        created_at_utc=start,
        observation=_observation(slot_utc=None, battery_energy_estimate_kwh=25.6),
        forecast_run=forecast,
        reserve_run=reserve,
        config=_config(allow_non_hold_recommendations=False),
    )
    result = _evaluate(**arguments)
    assert _canonical(result) == result.input_hash
    for mutate in ("marker", "source", "energy"):
        snapshot = copy.deepcopy(result.input_snapshot)
        if mutate == "marker":
            snapshot["calculation_version"] = "changed"
        elif mutate == "source":
            snapshot["action_window_demand_evidence"]["reserve_run_id"] += 1
        else:
            snapshot["action_window_demand_evidence"]["segments"][0][
                "energy_kwh"
            ] += 0.001
        assert _canonical(replace(result, input_snapshot=snapshot)) != result.input_hash
    run_id = repository.save_shadow_decision(
        result,
        forecast_run_id=forecast_id,
        reserve_run_id=reserve_id,
        shadow_enabled=True,
        non_hold_enabled=False,
    )
    detail = repository.shadow_decision_detail_read_only(run_id)
    assert _canonical(detail) == detail["input_hash"] == result.input_hash
    assert detail["input_snapshot_json"]["calculation_version"] == CALCULATION_VERSION
    evidence = detail["input_snapshot_json"]["action_window_demand_evidence"]
    assert evidence == result.input_snapshot["action_window_demand_evidence"]
    json.dumps(evidence, allow_nan=False)
    hold = next(c for c in detail["candidates"] if c["action"] == "HOLD")
    assert hold["reserve_margin_after_kwh"] == pytest.approx(-14.4)
    assert hold["ranking_components_json"]["reserve_gate_passed"] is False
    assert detail["no_command_issued"] is True
    assert (
        DashboardService(url, AppHealth(900)).shadow_decision(run_id).decision == detail
    )
    outcome = score_shadow_outcome(
        decision_run=detail,
        candidates=detail["candidates"],
        observations=[],
        scored_at_utc=BOUNDARY + timedelta(hours=1),
    )
    repository.save_shadow_outcome(outcome)
    persisted_outcome = repository.shadow_outcome_rows_read_only(limit=1)[0]
    for name in [
        "simulated_selected_value_aud",
        "simulated_hold_value_aud",
        "selected_vs_hold_value_aud",
        "hindsight_best_action",
        "regret_aud",
        "simulated_min_battery_energy_kwh",
        "simulated_reserve_breach",
    ]:
        assert persisted_outcome[name] is None
    # Construct a synthetic older row before insertion, without mutating persisted data.
    older = _evaluate(
        **{
            **arguments,
            "decision_boundary_utc": BOUNDARY - timedelta(minutes=30),
            "created_at_utc": start - timedelta(minutes=30),
        }
    )
    legacy_input = copy.deepcopy(older.input_snapshot)
    legacy_input.pop("calculation_version")
    legacy_input.pop("action_window_demand_evidence")
    legacy_hold = copy.deepcopy(older.selected_candidate)
    legacy_hold.reserve_margin_after_kwh = 0
    legacy_hold.ranking_components["reserve_gate_passed"] = True
    older = replace(
        older,
        input_snapshot=legacy_input,
        selected_candidate=legacy_hold,
        candidates=tuple(
            legacy_hold if c.action == "HOLD" else c for c in older.candidates
        ),
    )
    older = replace(older, input_hash=_canonical(older))
    older_id = repository.save_shadow_decision(
        older,
        forecast_run_id=forecast_id,
        reserve_run_id=reserve_id,
        shadow_enabled=True,
        non_hold_enabled=False,
    )
    original = repository.shadow_decision_detail_read_only(older_id)
    assert _canonical(original) == original["input_hash"] == older.input_hash
    retry = _evaluate(
        **{
            **arguments,
            "decision_boundary_utc": older.decision_boundary_utc,
            "created_at_utc": older.created_at_utc,
        }
    )
    assert (
        repository.save_shadow_decision(
            retry,
            forecast_run_id=forecast_id,
            reserve_run_id=reserve_id,
            shadow_enabled=True,
            non_hold_enabled=False,
        )
        is None
    )
    assert repository.shadow_decision_detail_read_only(older_id) == original
    assert "calculation_version" not in original["input_snapshot_json"]
    unknown_reserve = {**reserve, "recommended_reserve_kwh": None}
    unknown = _evaluate(
        **{
            **arguments,
            "decision_boundary_utc": BOUNDARY + timedelta(minutes=30),
            "created_at_utc": BOUNDARY + timedelta(minutes=30),
            "reserve_run": unknown_reserve,
        }
    )
    unknown_id = repository.save_shadow_decision(
        unknown,
        forecast_run_id=forecast_id,
        reserve_run_id=reserve_id,
        shadow_enabled=True,
        non_hold_enabled=False,
    )
    unknown_detail = repository.shadow_decision_detail_read_only(unknown_id)
    unknown_hold = next(
        c for c in unknown_detail["candidates"] if c["action"] == "HOLD"
    )
    assert unknown_hold["reserve_margin_after_kwh"] is None
    assert unknown_hold["ranking_components_json"]["reserve_gate_passed"] is None


def test_producer_shapes_hash_and_read_only_replay(
    isolated_evidence_repository, healthy_states, config
):
    repository, url = isolated_evidence_repository
    created = BOUNDARY.replace(day=1, minute=10, second=20)
    repository.save_observation(
        build_observation(healthy_states, config, observed_at=created)
    )
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
    row = repository.shadow_decision_rows_read_only(limit=1)[0]
    detail = repository.shadow_decision_detail_read_only(row["id"])
    assert _canonical(detail) == detail["input_hash"]
    evidence = detail["input_snapshot_json"]["action_window_demand_evidence"]
    assert evidence["complete"], evidence["reason"]
    assert evidence["segments"][0]["source"] == "reserve_partial"
    assert evidence["segments"][0]["seconds"] == 280
    assert evidence["segments"][1]["point_id"] is not None
    before = repository.table_counts()
    replay = replay_persisted_shadow_decision(repository, row["id"])
    assert (
        replay["source_calculation_version"]
        == replay["replay_calculation_version"]
        == CALCULATION_VERSION
    )
    assert (
        replay["calculation_semantics_match"] and not replay["database_write_performed"]
    )
    assert repository.table_counts() == before

    # A read-only legacy view demonstrates diagnostic version separation, not a rewrite.
    class LegacyView:
        def shadow_decision_detail_read_only(self, _):
            legacy = copy.deepcopy(detail)
            legacy["input_snapshot_json"].pop("calculation_version")
            return legacy

        def __getattr__(self, name):
            return getattr(repository, name)

    legacy_replay = replay_persisted_shadow_decision(LegacyView(), row["id"])
    assert legacy_replay["source_calculation_version"] == "legacy"
    assert not legacy_replay["calculation_semantics_match"]
    assert repository.table_counts() == before
