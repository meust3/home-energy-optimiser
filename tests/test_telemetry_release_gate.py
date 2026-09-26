from datetime import timedelta

import pytest
from psycopg.errors import LockNotAvailable, QueryCanceled, SerializationFailure
from sqlalchemy.exc import OperationalError

from energy_optimizer import entity_ids as ids
from energy_optimizer.collector import build_observation
from energy_optimizer.db.engine import (
    DatabaseConnectionError,
    DatabaseLockTimeoutError,
    DatabaseQueryCanceledError,
    DatabaseTransactionError,
    translate_database_error,
)
from energy_optimizer.health import evaluate_data_health
from energy_optimizer.models import HomeAssistantState


def report(healthy_states, config, now, *, age=0, receipt_age=0, value=None):
    config.goodwe_soc_timestamp_enabled = True
    healthy_states[ids.GOODWE_BATTERY_SOC].last_updated = now - timedelta(hours=4)
    healthy_states[ids.GOODWE_TIMESTAMP] = HomeAssistantState(
        entity_id=ids.GOODWE_TIMESTAMP,
        state=(
            value if value is not None else (now - timedelta(seconds=age)).isoformat()
        ),
        last_changed=now - timedelta(seconds=receipt_age),
        last_updated=now - timedelta(seconds=receipt_age),
    )


def test_unchanged_soc_uses_runtime_frame_and_persists_evidence(
    healthy_states, config, now
):
    report(healthy_states, config, now)
    observation = build_observation(healthy_states, config, observed_at=now)
    domain = observation.data_health.telemetry
    assert domain.entity_freshness[ids.GOODWE_BATTERY_SOC] == "available_but_unchanged"
    assert not any(i.code == "source_update_stale" for i in domain.issues)
    evidence = domain.model_dump(mode="json")["entity_freshness_evidence"][
        ids.GOODWE_BATTERY_SOC
    ]
    assert evidence["reason"] == "runtime_frame_fresh"
    assert evidence["device_age_seconds"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"age": 601},
        {"receipt_age": 601},
        {"age": -61},
        {"receipt_age": -61},
        {"value": "unavailable"},
        {"value": "unknown"},
        {"value": "not-a-time"},
    ],
)
def test_runtime_clock_failures_remain_blocked(healthy_states, config, now, kwargs):
    report(healthy_states, config, now, **kwargs)
    health = evaluate_data_health(healthy_states, config, now=now)
    assert (
        health.telemetry.entity_freshness[ids.GOODWE_BATTERY_SOC]
        == "source_update_stale"
    )
    assert any(i.code == "source_update_stale" for i in health.telemetry.issues)


def test_missing_runtime_clock_does_not_use_grace(healthy_states, config, now):
    config.goodwe_soc_timestamp_enabled = True
    health = evaluate_data_health(healthy_states, config, now=now)
    assert (
        health.telemetry.entity_freshness[ids.GOODWE_BATTERY_SOC]
        == "source_update_stale"
    )


@pytest.mark.parametrize("value", ["unavailable", "unknown", "bad", "101"])
def test_fresh_clock_cannot_validate_bad_soc(healthy_states, config, now, value):
    report(healthy_states, config, now)
    healthy_states[ids.GOODWE_BATTERY_SOC].state = value
    assert not evaluate_data_health(
        healthy_states, config, now=now
    ).telemetry.is_healthy


def test_naive_inverter_clock_uses_installation_timezone(healthy_states, config, now):
    from zoneinfo import ZoneInfo

    report(
        healthy_states,
        config,
        now,
        value=now.astimezone(ZoneInfo(config.timezone))
        .replace(tzinfo=None)
        .isoformat(),
    )
    assert (
        evaluate_data_health(
            healthy_states, config, now=now
        ).telemetry.entity_freshness[ids.GOODWE_BATTERY_SOC]
        == "available_but_unchanged"
    )


def test_pv_input_limit_is_separate_from_ac_power(healthy_states, config, now):
    healthy_states[ids.GOODWE_PV_POWER].state = "15884"
    assert evaluate_data_health(healthy_states, config, now=now).telemetry.is_healthy
    healthy_states[ids.GOODWE_PV_POWER].state = "20001"
    assert not evaluate_data_health(
        healthy_states, config, now=now
    ).telemetry.is_healthy
    healthy_states[ids.GOODWE_PV_POWER].state = "15884"
    healthy_states[ids.GOODWE_GRID_POWER].state = "15884"
    assert not evaluate_data_health(
        healthy_states, config, now=now
    ).telemetry.is_healthy


@pytest.mark.parametrize(
    "original,expected",
    [
        (QueryCanceled("statement canceled"), DatabaseQueryCanceledError),
        (LockNotAvailable("lock wait"), DatabaseLockTimeoutError),
        (SerializationFailure("serialization"), DatabaseTransactionError),
        (OSError("connection failed"), DatabaseConnectionError),
    ],
)
def test_database_sqlstate_classification(original, expected):
    translated = translate_database_error(OperationalError("SELECT 1", {}, original))
    assert type(translated) is expected


def test_runtime_evidence_roundtrips_through_repository(healthy_states, config, now):
    from energy_optimizer.db.engine import create_database_engine
    from energy_optimizer.db.repository import DatabaseRepository

    report(healthy_states, config, now)
    repository = DatabaseRepository(create_database_engine("sqlite:///:memory:"))
    repository.create_schema_for_tests()
    try:
        repository.save_observation(
            build_observation(healthy_states, config, observed_at=now)
        )
        evidence = repository.latest_observation()["health_domains_json"]["telemetry"][
            "entity_freshness_evidence"
        ]
        assert evidence[ids.GOODWE_BATTERY_SOC]["reason"] == "runtime_frame_fresh"
    finally:
        repository.engine.dispose()


def test_app_options_export_separate_limits_and_opt_in_clock():
    from energy_optimizer.home_assistant_app import (
        HomeAssistantAppOptions,
        app_environment,
    )

    options = HomeAssistantAppOptions(db_host="test.invalid", db_password="test-only")
    assert options.goodwe_soc_timestamp_enabled is False
    options.goodwe_soc_timestamp_enabled = True
    options.maximum_plausible_pv_power_w = 19500
    environment = app_environment(options, supervisor_token="test-only")
    assert environment["MAXIMUM_PLAUSIBLE_PV_POWER_W"] == "19500"
    assert environment["GOODWE_SOC_TIMESTAMP_ENABLED"] == "true"
