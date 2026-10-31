import hashlib
import json
import subprocess
import sys
from datetime import timedelta, timezone

import pytest
from test_sems_backfill import prepared  # noqa: F401

from energy_optimizer.db.sems_context import apply_context_plan
from energy_optimizer.ev_annotation import STATE_COLUMNS
from energy_optimizer.frozen_training import (
    freeze_training_population,
    load_frozen_training_population,
    replay_demand_population,
)
from energy_optimizer.sems_backfill import prepare_backfill


def test_frozen_population_survives_later_sems_apply_and_reverse(
    prepared,  # noqa: F811
):  # noqa: F811
    repo, snapshot, ledger, later = prepared
    decision_at = later - timedelta(days=2, hours=1)
    assert decision_at.isoformat() < ledger["sessions"][0]["context_known_at_utc"]
    original = repo.observation_rows()
    frozen = freeze_training_population(
        original, captured_at=decision_at, source_id="synthetic-original-population"
    )
    digest = hashlib.sha256(frozen).hexdigest()
    before = load_frozen_training_population(
        frozen, expected_sha256=digest, decision_at=decision_at
    )
    plan = prepare_backfill(snapshot, ledger)
    assert apply_context_plan(repo, plan, now=later) == "applied"
    assert len(repo.healthy_load_samples()) == 1
    assert (
        load_frozen_training_population(
            frozen, expected_sha256=digest, decision_at=decision_at
        )
        == before
    )
    assert len(before) == 3
    assert apply_context_plan(repo, plan, now=later, reverse=True) == "reversed"
    assert (
        load_frozen_training_population(
            frozen, expected_sha256=digest, decision_at=decision_at
        )
        == before
    )
    rows = repo.observation_rows()
    repo.apply_ev_annotation(
        rows=rows,
        start=rows[0]["slot_utc"],
        end=rows[-1]["slot_utc"] + timedelta(minutes=5),
        session_id="later-manual-annotation",
        note="synthetic later evidence",
        now=later + timedelta(hours=1),
        state_columns=STATE_COLUMNS,
    )
    assert len(repo.healthy_load_samples()) == 0
    assert (
        load_frozen_training_population(
            frozen, expected_sha256=digest, decision_at=decision_at
        )
        == before
    )


def test_population_captured_later_is_not_historical_evidence(prepared):  # noqa: F811
    repo, _, _, later = prepared
    frozen = freeze_training_population(
        repo.observation_rows(), captured_at=later, source_id="late-copy"
    )
    with pytest.raises(ValueError, match="after the decision"):
        load_frozen_training_population(
            frozen,
            expected_sha256=hashlib.sha256(frozen).hexdigest(),
            decision_at=later - timedelta(days=1),
        )


def test_changed_population_and_caller_mutation_cannot_change_sealed_rows(
    prepared,  # noqa: F811
):  # noqa: F811
    repo, _, _, later = prepared
    frozen = freeze_training_population(
        repo.observation_rows(), captured_at=later, source_id="original"
    )
    digest = hashlib.sha256(frozen).hexdigest()
    rows = load_frozen_training_population(
        frozen, expected_sha256=digest, decision_at=later
    )
    rows[0]["baseline_training_eligible"] = False
    assert (
        load_frozen_training_population(
            frozen, expected_sha256=digest, decision_at=later
        )[0]["baseline_training_eligible"]
        is True
    )
    changed = json.loads(frozen)
    changed["observations"][0]["baseline_training_eligible"] = False
    with pytest.raises(ValueError, match="checksum"):
        load_frozen_training_population(
            json.dumps(changed).encode(), expected_sha256=digest, decision_at=later
        )


def test_forecast_uses_only_sealed_population(prepared):  # noqa: F811
    repo, snapshot, ledger, later = prepared
    boundary = later - timedelta(days=2, hours=1)
    frozen = freeze_training_population(
        repo.observation_rows(), captured_at=boundary, source_id="synthetic-original"
    )
    options = dict(
        expected_sha256=hashlib.sha256(frozen).hexdigest(),
        decision_at=boundary,
        start_local=boundary,
        end_local=boundary + timedelta(hours=1),
        minimum_samples=1,
        fallback_kw=0.8,
    )
    before = replay_demand_population(frozen, **options)
    assert (
        apply_context_plan(repo, prepare_backfill(snapshot, ledger), now=later)
        == "applied"
    )
    assert replay_demand_population(frozen, **options) == before
    assert before["forecast"]["history_sample_count"] == 3
    assert before["knowledge_time_policy"] == "immutable_original_population"
    assert before["no_command_issued"] is True


@pytest.mark.parametrize("fault", ["duplicate", "future", "naive", "missing", "nan"])
def test_incomplete_or_inconsistent_population_is_refused(
    prepared,  # noqa: F811
    fault,
):  # noqa: F811
    repo, _, _, later = prepared
    rows = repo.observation_rows()
    if fault == "duplicate":
        rows.append(rows[0])
    elif fault == "future":
        rows[0]["observed_at_utc"] = later + timedelta(days=1)
    elif fault == "naive":
        rows[0]["observed_at_local"] = later.replace(tzinfo=None)
    elif fault == "missing":
        del rows[0]["baseline_training_eligible"]
    else:
        rows[0]["baseline_house_consumption_w"] = float("nan")
    with pytest.raises(ValueError):
        freeze_training_population(rows, captured_at=later, source_id="invalid")


def test_cli_refuses_changed_population_and_existing_output(
    prepared,  # noqa: F811
    tmp_path,
):  # noqa: F811
    repo, _, _, later = prepared
    frozen = freeze_training_population(
        repo.observation_rows(), captured_at=later, source_id="synthetic-cli"
    )
    source = tmp_path / "population.json"
    source.write_bytes(frozen)
    output = tmp_path / "replay.json"
    command = [
        sys.executable,
        "-m",
        "tools.replay_demand_population",
        str(source),
        "--expected-sha256",
        hashlib.sha256(frozen).hexdigest(),
        "--decision-at",
        later.isoformat(),
        "--start",
        later.isoformat(),
        "--end",
        (later + timedelta(hours=1)).isoformat(),
        "--minimum-samples",
        "1",
        "--fallback-kw",
        "0.8",
        "--output",
        str(output),
    ]
    assert subprocess.run(command, capture_output=True, timeout=20).returncode == 0
    saved = output.read_bytes()
    assert subprocess.run(command, capture_output=True, timeout=20).returncode == 2
    assert output.read_bytes() == saved
    output.unlink()
    source.write_bytes(frozen + b" ")
    assert subprocess.run(command, capture_output=True, timeout=20).returncode == 2
    assert not output.exists()


def test_utc_metadata_and_unknown_demand_are_preserved(prepared):  # noqa: F811
    repo, _, _, later = prepared
    rows = repo.observation_rows()
    rows[0]["baseline_house_consumption_w"] = None
    captured = later.astimezone(timezone(timedelta(hours=10)))
    frozen = freeze_training_population(
        rows, captured_at=captured, source_id="synthetic"
    )
    payload = json.loads(frozen)
    assert payload["captured_at_utc"] == later.isoformat()
    assert payload["observations"][0]["baseline_house_consumption_w"] is None
    result = replay_demand_population(
        frozen,
        expected_sha256=hashlib.sha256(frozen).hexdigest(),
        decision_at=captured,
        start_local=captured,
        end_local=captured + timedelta(hours=1),
        minimum_samples=1,
        fallback_kw=0.8,
    )
    assert result["decision_at_utc"] == later.isoformat()
    assert result["provenance_verified"] is False
