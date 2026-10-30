from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text, update
from test_bounded_forecast_scoring import owned_postgres_url

from energy_optimizer.collector import build_observation
from energy_optimizer.db.models import (
    EVSessionAnnotation,
    EVSessionAnnotationRow,
    Observation,
)
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.db.sems_context import apply_context_plan
from energy_optimizer.sems_backfill import guard, prepare_backfill


@pytest.fixture(params=["sqlite", "postgresql"])
def prepared(request, tmp_path, healthy_states, config, now):
    schema = None
    if request.param == "postgresql":
        url = owned_postgres_url()
        if not url:
            pytest.skip("Requires exclusively owned disposable SEMS PostgreSQL")
        engine = create_engine(url)
        schema = "sems_test_" + uuid4().hex
        with engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'context.db'}")
    repo = DatabaseRepository(engine)
    repo.create_schema_for_tests()
    for i in range(3):
        repo.save(
            build_observation(
                healthy_states, config, observed_at=now + timedelta(minutes=5 * i)
            )
        )
    snapshot = {
        "snapshot_at_utc": (now + timedelta(days=2)).isoformat(),
        "observations": [guard(r) for r in repo.observation_rows()],
        "previously_annotated_slots": [],
    }
    ledger = {
        "observed_at_utc": (now + timedelta(days=1)).isoformat(),
        "sessions": [
            {
                "session_evidence_id": "synthetic-session",
                "qualification": "session_window_context_only",
                "start_utc": now.isoformat(),
                "end_utc": (now + timedelta(minutes=10)).isoformat(),
                "context_known_at_utc": (now + timedelta(days=1)).isoformat(),
            }
        ],
    }
    yield repo, snapshot, ledger, now + timedelta(days=3)
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    repo.engine.dispose()


def test_boundaries_use_actual_instant_half_open_and_preserve_source(prepared):
    repo, snapshot, ledger, _ = prepared
    before = repo.observation_rows()
    plan = prepare_backfill(snapshot, ledger)
    assert [e["disposition"] for e in plan["entries"]] == [
        "exclude_session_window",
        "exclude_session_window",
        "boundary_context_only",
    ]
    assert repo.observation_rows() == before


def test_apply_idempotent_reverse_and_raw_byte_equivalence(prepared):
    repo, snapshot, ledger, now = prepared
    plan = prepare_backfill(snapshot, ledger)
    original = repo.observation_rows()
    assert apply_context_plan(repo, plan, now=now) == "applied"
    assert apply_context_plan(repo, plan, now=now) == "already_applied"
    changed = repo.observation_rows()
    for old, new in zip(original, changed, strict=True):
        for field in old:
            if field not in ("baseline_training_eligible", "baseline_exclusion_reason"):
                assert old[field] == new[field]
    assert apply_context_plan(repo, plan, now=now, reverse=True) == "reversed"
    assert repo.observation_rows() == original
    assert apply_context_plan(repo, plan, now=now, reverse=True) == "already_reversed"
    with pytest.raises(ValueError, match="fresh snapshot"):
        apply_context_plan(repo, plan, now=now)


@pytest.mark.parametrize(
    "field,value,disposition",
    [
        ("ev_power_w", 0.0, "preserve_direct_power"),
        ("ev_session_id", "manual", "preserve_existing_annotation"),
        ("baseline_training_eligible", False, "preserve_existing_exclusion"),
        ("telemetry_is_healthy", False, "not_effective_training_row"),
    ],
)
def test_precedence(prepared, field, value, disposition):
    _, snapshot, ledger, _ = prepared
    snapshot["observations"][0][field] = value
    assert (
        prepare_backfill(snapshot, ledger)["entries"][0]["disposition"] == disposition
    )


def test_audit_history_protected_even_without_current_session_id(prepared):
    _, snapshot, ledger, _ = prepared
    snapshot["previously_annotated_slots"] = [snapshot["observations"][0]["slot_utc"]]
    assert (
        prepare_backfill(snapshot, ledger)["entries"][0]["disposition"]
        == "preserve_existing_annotation"
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_conflict_aborts_whole_transaction(prepared, reverse):
    repo, snapshot, ledger, now = prepared
    plan = prepare_backfill(snapshot, ledger)
    if reverse:
        apply_context_plan(repo, plan, now=now)
    with repo.transaction() as session:
        session.execute(
            update(Observation)
            .where(Observation.slot_utc == repo.observation_rows()[1]["slot_utc"])
            .values(house_consumption_w=9999)
        )
    before = repo.observation_rows()
    with pytest.raises(ValueError, match="changed since review"):
        apply_context_plan(repo, plan, now=now, reverse=reverse)
    assert repo.observation_rows() == before
    with repo.transaction() as session:
        assert len(session.execute(select(EVSessionAnnotation)).all()) == (
            1 if reverse else 0
        )


def test_later_annotation_blocks_rollback_even_if_values_match(prepared):
    repo, snapshot, ledger, now = prepared
    plan = prepare_backfill(snapshot, ledger)
    apply_context_plan(repo, plan, now=now)
    with repo.transaction() as session:
        old = session.execute(select(EVSessionAnnotation)).scalar_one()
        later = EVSessionAnnotation(
            annotation_timestamp_utc=now,
            range_start_utc=old.range_start_utc,
            range_end_utc=old.range_end_utc,
            affected_row_count=1,
            session_id="other",
            note="",
            previous_eligibility_json={},
            new_eligibility_json={},
            annotation_source="manual_annotation",
            action="apply",
        )
        session.add(later)
        session.flush()
        session.add(
            EVSessionAnnotationRow(
                annotation_id=later.id,
                slot_utc=old.range_start_utc,
                previous_state_json={},
            )
        )
    with pytest.raises(ValueError, match="Conflicting annotation"):
        apply_context_plan(repo, plan, now=now, reverse=True)


def test_plan_tampering_and_duplicate_slots_rejected(prepared):
    repo, snapshot, ledger, now = prepared
    plan = prepare_backfill(snapshot, ledger)
    plan["entries"][0]["after"]["baseline_training_eligible"] = True
    with pytest.raises(ValueError, match="digest"):
        apply_context_plan(repo, plan, now=now)
    snapshot["observations"].append(deepcopy(snapshot["observations"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_backfill(snapshot, ledger)
