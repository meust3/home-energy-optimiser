import os
from datetime import timedelta

import pytest
from sqlalchemy import update

from energy_optimizer.collector import build_observation
from energy_optimizer.db.models import Observation
from energy_optimizer.historian import Historian
from energy_optimizer.persistence import open_repository
from energy_optimizer.reprocessing import reprocess_observations

APPLY = {"apply": True, "backup_verified": True}


def _legacy_database(healthy_states, config, now):
    config.grid_power_sign_convention = "positive_export"
    config.battery_power_sign_convention = "positive_discharge"
    config.sign_convention_confidence = "high"
    config.sign_convention_supporting_samples = 175
    historian = Historian(config.database_path)
    historian.save(build_observation(healthy_states, config, observed_at=now))
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET pv_power_w=1000, house_consumption_w=2000, "
            "grid_power_w=-1500, battery_power_w=-500, "
            "sign_convention_status='unconfirmed', grid_import_power_w=NULL, "
            "baseline_house_consumption_w=NULL, baseline_training_eligible=0, "
            "baseline_exclusion_reason=NULL"
        )
    return historian


def test_reprocessing_dry_run_makes_no_database_changes(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    before = historian.latest_observation()
    report = reprocess_observations(historian, config, apply=False, now=now)
    after = historian.latest_observation()
    assert report.applied is False
    assert report.rows_becoming_baseline_eligible == 1
    assert after == before


def test_apply_reprocesses_legacy_and_preserves_raw(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    raw_before = historian.power_sign_samples()[0]
    report = reprocess_observations(historian, config, **APPLY, now=now)
    raw_after = historian.power_sign_samples()[0]
    row = historian.latest_observation()
    assert report.rows_becoming_baseline_eligible == 1
    assert report.rows_repairable == 1
    assert raw_after == raw_before
    assert row["grid_import_power_w"] == 1500
    assert row["battery_charge_power_w"] == 500
    assert row["balance_residual_w"] == 0
    assert row["baseline_house_consumption_w"] == 2000
    assert row["baseline_training_eligible"] == 1
    assert row["originally_legacy"] == 1
    assert row["derivation_model_version"] == "energy-flow-v1"


def test_reprocessing_rerun_is_repeatable(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    first = reprocess_observations(historian, config, **APPLY, now=now)
    second = reprocess_observations(
        historian, config, **APPLY, now=now + timedelta(minutes=1)
    )
    with historian.connect() as connection:
        audits = connection.execute(
            "SELECT COUNT(*) FROM observation_derivations"
        ).fetchone()[0]
    assert first.audit_records_added == 1
    assert second.audit_records_added == 0
    assert second.rows_repairable == 0
    assert second.rows_unchanged == 1
    assert audits == 1


def test_invalid_residual_remains_ineligible(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET pv_power_w=0, grid_power_w=0, "
            "battery_power_w=0, house_consumption_w=1000"
        )
    report = reprocess_observations(historian, config, **APPLY, now=now)
    row = historian.latest_observation()
    assert report.rows_exceeding_tolerance == 1
    assert row["baseline_training_eligible"] == 0
    assert row["baseline_exclusion_reason"] == "balance_residual_outside_tolerance"


def test_known_ev_active_without_power_remains_ineligible(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET ev_charging_active=1, ev_power_w=NULL"
        )
    reprocess_observations(historian, config, **APPLY, now=now)
    row = historian.latest_observation()
    assert row["baseline_training_eligible"] == 0
    assert row["baseline_exclusion_reason"] == "ev_active_power_unknown"


def test_apply_requires_restore_tested_backup(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    with pytest.raises(ValueError, match="restore-tested"):
        reprocess_observations(historian, config, apply=True, now=now)


def test_confirmed_rows_are_protected_without_explicit_override(
    healthy_states, config, now
):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET sign_convention_status='confirmed', "
            "grid_import_power_w=999, grid_export_power_w=0, "
            "battery_charge_power_w=999, battery_discharge_power_w=0"
        )
    report = reprocess_observations(historian, config, **APPLY, now=now)
    row = historian.latest_observation()
    assert report.rows_repairable == 0
    assert report.rows_unchanged == 1
    assert row["grid_import_power_w"] == 999
    assert row["battery_charge_power_w"] == 999


def test_confirmed_row_override_is_separate_and_audited(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET sign_convention_status='confirmed', "
            "grid_import_power_w=999, grid_export_power_w=0, "
            "battery_charge_power_w=999, battery_discharge_power_w=0"
        )
    report = reprocess_observations(
        historian, config, **APPLY, override_confirmed=True, now=now
    )
    row = historian.latest_observation()
    assert report.rows_repairable == 1
    assert report.audit_records_added == 1
    assert row["grid_import_power_w"] == 1500
    assert row["battery_charge_power_w"] == 500


def test_reprocessing_preserves_byd_ev_and_manual_annotation_fields(
    healthy_states, config, now
):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET ev_source='manual_annotation', "
            "ev_session_id='manual-keep', ev_charging_active=1, ev_power_w=NULL, "
            "pv_power_w=0, "
            "ev_detection_confidence='confirmed_manual', "
            "ev_vehicle_soc_percent=63, ev_vehicle_battery_power_w_raw=-21, "
            "ev_plugged_in=1, ev_vehicle_online=1, ev_at_home=1, "
            "ev_telemetry_fresh=1, ev_vehicle_status='charging', "
            "baseline_house_consumption_w=1234, baseline_training_eligible=0, "
            "baseline_exclusion_reason='known_ev_session_without_ev_power', "
            "event_labels_json='[\"ev_charging_confirmed\"]'"
        )
    before = historian.latest_observation()
    reprocess_observations(historian, config, **APPLY, now=now)
    after = historian.latest_observation()
    for name in (
        "ev_source",
        "ev_session_id",
        "ev_charging_active",
        "ev_power_w",
        "ev_detection_confidence",
        "ev_vehicle_soc_percent",
        "ev_vehicle_battery_power_w_raw",
        "ev_plugged_in",
        "ev_vehicle_online",
        "ev_at_home",
        "ev_telemetry_fresh",
        "ev_vehicle_status",
        "event_labels_json",
        "baseline_house_consumption_w",
        "baseline_training_eligible",
        "baseline_exclusion_reason",
    ):
        assert after[name] == before[name]


def test_reprocessing_preserves_byd_classification_and_vehicle_fields(
    healthy_states, config, now
):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET ev_source='byd_vehicle_cloud', "
            "ev_charging_active=1, ev_power_w=NULL, ev_vehicle_soc_percent=63, "
            "ev_plugged_in=1, ev_vehicle_online=1, ev_at_home=1, "
            "ev_telemetry_fresh=1, ev_vehicle_status='charging', "
            "event_labels_json='[\"ev_charging_confirmed\"]'"
        )
    before = historian.latest_observation()
    reprocess_observations(historian, config, **APPLY, now=now)
    after = historian.latest_observation()
    for name in (
        "ev_source",
        "ev_charging_active",
        "ev_power_w",
        "ev_vehicle_soc_percent",
        "ev_plugged_in",
        "ev_vehicle_online",
        "ev_at_home",
        "ev_telemetry_fresh",
        "ev_vehicle_status",
        "event_labels_json",
    ):
        assert after[name] == before[name]
    assert after["baseline_training_eligible"] == 0
    assert after["baseline_exclusion_reason"] == "known_ev_session_without_ac_power"


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for PostgreSQL integration",
)
def test_postgresql_reprocessing_matches_sqlite_behavior(healthy_states, config, now):
    config.grid_power_sign_convention = "positive_export"
    config.battery_power_sign_convention = "positive_discharge"
    config.sign_convention_confidence = "high"
    config.sign_convention_supporting_samples = 175
    repository = open_repository(os.environ["TEST_POSTGRES_URL"])
    try:
        repository.create_schema_for_tests()
        repository.save_observation(
            build_observation(healthy_states, config, observed_at=now)
        )
        with repository.transaction() as session:
            session.execute(
                update(Observation).values(
                    pv_power_w=1000,
                    house_consumption_w=2000,
                    grid_power_w=-1500,
                    battery_power_w=-500,
                    sign_convention_status="unconfirmed",
                    grid_import_power_w=None,
                    grid_export_power_w=None,
                    battery_charge_power_w=None,
                    battery_discharge_power_w=None,
                )
            )
        report = reprocess_observations(repository, config, **APPLY, now=now)
        row = repository.latest_observation()
        assert report.rows_repairable == 1
        assert row["grid_import_power_w"] == 1500
        assert row["battery_charge_power_w"] == 500
        assert row["balance_residual_w"] == 0
        rerun = reprocess_observations(
            repository, config, **APPLY, now=now + timedelta(minutes=1)
        )
        assert rerun.rows_repairable == 0
        assert rerun.audit_records_added == 0
    finally:
        repository.close()
