from datetime import timedelta

from energy_optimizer.collector import build_observation
from energy_optimizer.historian import Historian
from energy_optimizer.reprocessing import reprocess_observations


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
    report = reprocess_observations(historian, config, apply=True, now=now)
    raw_after = historian.power_sign_samples()[0]
    row = historian.latest_observation()
    assert report.rows_becoming_baseline_eligible == 1
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
    first = reprocess_observations(historian, config, apply=True, now=now)
    second = reprocess_observations(
        historian, config, apply=True, now=now + timedelta(minutes=1)
    )
    with historian.connect() as connection:
        audits = connection.execute(
            "SELECT COUNT(*) FROM observation_derivations"
        ).fetchone()[0]
    assert first.audit_records_added == 1
    assert second.audit_records_added == 0
    assert audits == 1


def test_invalid_residual_remains_ineligible(healthy_states, config, now):
    historian = _legacy_database(healthy_states, config, now)
    with historian.connect() as connection:
        connection.execute(
            "UPDATE observations SET pv_power_w=0, grid_power_w=0, "
            "battery_power_w=0, house_consumption_w=1000"
        )
    report = reprocess_observations(historian, config, apply=True, now=now)
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
    reprocess_observations(historian, config, apply=True, now=now)
    row = historian.latest_observation()
    assert row["baseline_training_eligible"] == 0
    assert row["baseline_exclusion_reason"] == "ev_active_power_unknown"
