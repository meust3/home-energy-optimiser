"""Synthetic PostgreSQL round trips for configured EV uncertainty."""

import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text, update
from sqlalchemy.engine import make_url
from test_byd_vehicle import _configure, _vehicle_states

from energy_optimizer.collector import build_observation
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.models import Observation
from energy_optimizer.persistence import open_repository
from energy_optimizer.reprocessing import reprocess_observations


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="local PostgreSQL required"
)
@pytest.mark.parametrize("variant", ["stale", "unknown", "idle", "disabled"])
def test_postgres_baseline_uncertainty_round_trip(healthy_states, config, now, variant):
    url = os.environ["TEST_POSTGRES_URL"]
    parsed = make_url(url)
    assert parsed.host == "127.0.0.1" and parsed.database in {
        "ev_baseline_test",
        "release_test",
    }
    schema = "ev_fix_" + uuid.uuid4().hex
    admin = create_database_engine(url)
    repository = None
    try:
        with admin.begin() as con:
            con.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
        repository = open_repository(scoped.render_as_string(hide_password=False))
        repository.create_schema_for_tests()
        config.grid_power_sign_convention = "positive_export"
        config.battery_power_sign_convention = "positive_discharge"
        config.sign_convention_confidence = "high"
        config.sign_convention_supporting_samples = 175
        if variant != "disabled":
            _configure(config)
            states = _vehicle_states(
                healthy_states,
                now,
                charging=(
                    "unknown"
                    if variant == "unknown"
                    else "on" if variant == "stale" else "off"
                ),
                updated=(
                    now - timedelta(seconds=1006 if variant == "stale" else 0)
                ).isoformat(),
            )
        else:
            states = healthy_states
        observation = build_observation(states, config, observed_at=now)
        repository.save_observation(observation)
        row = repository.latest_observation()
        excluded = variant in {"stale", "unknown"}
        assert row["baseline_training_eligible"] == (not excluded)
        assert row["house_consumption_w"] == row["baseline_house_consumption_w"] == 1800
        assert row["ev_power_w"] is None
        assert row["telemetry_is_healthy"]
        assert len(repository.healthy_load_samples()) == (0 if excluded else 1)
        if excluded:
            assert (
                row["baseline_exclusion_reason"]
                == "configured_ev_status_unknown_without_ac_power"
            )
            # Simulate a previously admitted row; repair only this synthetic schema.
            with repository.transaction() as session:
                session.execute(
                    update(Observation).values(
                        pv_power_w=1000,
                        house_consumption_w=2000,
                        grid_power_w=-1500,
                        battery_power_w=-500,
                        sign_convention_status="unconfirmed",
                        baseline_training_eligible=True,
                        baseline_exclusion_reason=None,
                    )
                )
            reprocess_observations(
                repository, config, apply=True, backup_verified=True, now=now
            )
            repaired = repository.latest_observation()
            assert not repaired["baseline_training_eligible"]
            assert repaired["house_consumption_w"] == 2000
            assert repaired["ev_source"] == row["ev_source"]
            assert repaired["ev_charging_active"] == row["ev_charging_active"]
            assert not repository.healthy_load_samples()
            rerun = reprocess_observations(
                repository,
                config,
                apply=True,
                backup_verified=True,
                now=now + timedelta(minutes=1),
            )
            assert rerun.rows_repairable == rerun.audit_records_added == 0
    finally:
        if repository is not None:
            repository.close()
        with admin.begin() as con:
            con.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
