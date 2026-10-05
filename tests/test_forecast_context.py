"""Synthetic witnesses for optional context; never reads live HA or household data."""

import copy
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url

from energy_optimizer.collector import (
    Collector,
    align_to_five_minute_slot,
    build_observation,
)
from energy_optimizer.context_collection import collect_and_store_context
from energy_optimizer.context_repository import ContextRepository
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import alembic_config, current_revision
from energy_optimizer.db.models import ContextObservation, WeatherContextSnapshot
from energy_optimizer.forecast_context import (
    ContextMapping,
    ContextSource,
    WeatherCacheSource,
    collect_context,
    content_hash,
    convert_value,
    parse_mapping,
    parse_weather_cache,
)
from energy_optimizer.home_assistant import (
    HomeAssistantClient,
    HomeAssistantResponseError,
    ReadOnlyViolation,
)
from energy_optimizer.home_assistant_app import (
    AppHealth,
    HomeAssistantAppOptions,
    app_environment,
)
from energy_optimizer.models import HomeAssistantState
from energy_optimizer.persistence import open_repository
from energy_optimizer.timestamps import json_safe

T = datetime(2026, 10, 5, 0, tzinfo=UTC)


def source(**updates):
    return ContextSource.model_validate(
        {
            "source_id": "zone_a_temperature",
            "entity_id": "sensor.zone_a_temperature",
            "zone": "zone_a",
            "scope": "indoor",
            "integration": "zha",
            "quantity": "temperature",
            "evidence": "sensor_measured",
            **updates,
        }
    )


def mapping(*sources, cache=True, **updates):
    return ContextMapping(
        version="synthetic-v1",
        effective_from_utc=T - timedelta(days=1),
        sources=sources or (source(),),
        weather_cache=(
            WeatherCacheSource(
                entity_id="sensor.example_hourly_cache",
                weather_entity_id="weather.example",
                provider="example_provider",
                integration="example_integration",
            )
            if cache
            else None
        ),
        **updates,
    )


def state(entity_id="sensor.zone_a_temperature", value="20", **attrs):
    return HomeAssistantState(
        entity_id=entity_id,
        state=value,
        attributes=attrs,
        last_changed=T - timedelta(days=30),
        last_updated=T - timedelta(days=1),
        last_reported=T - timedelta(minutes=3),
    )


def cache_state(*, success=T, value=20, issue=None, count=24, **updates):
    attrs = {
        "cache_success_utc": success.isoformat(),
        "provider_issue_utc": issue,
        "forecast_type": "hourly",
        "provider": "example_provider",
        "integration": "example_integration",
        "weather_entity_id": "weather.example",
        "units": {"temperature": "°C", "humidity": "%", "precipitation": "mm"},
        "forecast": [
            {
                "datetime": (T + timedelta(hours=i + 1)).isoformat(),
                "temperature": value,
                "humidity": 60,
                "precipitation": 0,
            }
            for i in range(count)
        ],
        **updates,
    }
    return state("sensor.example_hourly_cache", "ready", **attrs)


def batch(m, *, receipt=T, slot=None, weather=None, states=None):
    values = states or {"sensor.zone_a_temperature": state(unit_of_measurement="°C")}
    values = dict(values)
    if weather is not None:
        values[weather.entity_id] = weather
    return collect_context(
        values, m, slot=slot or align_to_five_minute_slot(receipt), receipt=receipt
    )


@pytest.mark.parametrize(
    ("raw", "quantity", "unit", "expected"),
    [
        ("32", "temperature", "°F", 0),
        ("0", "temperature", "°C", 0),
        ("0", "humidity", "%", 0),
        (1, "power", "kW", 1000),
        (1000, "energy", "Wh", 1),
        (1, "precipitation", "in", 25.4),
    ],
)
def test_units_and_valid_zero(raw, quantity, unit, expected):
    value, _, conversion, reason = convert_value(raw, quantity, unit)
    assert value == pytest.approx(expected)
    assert reason is None and conversion


@pytest.mark.parametrize(
    ("raw", "quantity", "unit", "reason"),
    [
        ("unknown", "temperature", "°C", "value_unavailable"),
        ("unavailable", "humidity", "%", "value_unavailable"),
        ("nan", "temperature", "°C", "nonfinite_number"),
        ("inf", "temperature", "°C", "nonfinite_number"),
        (True, "temperature", "°C", "nonfinite_number"),
        ("bad", "temperature", "°C", "invalid_number"),
        (101, "humidity", "%", "implausible_value"),
        (20, "humidity", None, "unit_unknown_or_unsupported"),
        (200, "temperature", "°C", "implausible_value"),
    ],
)
def test_missing_or_invalid_never_zero_or_clamped(raw, quantity, unit, reason):
    value, _, _, actual = convert_value(raw, quantity, unit)
    assert value is None and actual == reason


def test_sensor_climate_duplicates_and_evidence_stay_separate():
    sources = (
        source(duplicate_group="zone_a_air"),
        source(
            source_id="climate_temp",
            entity_id="climate.example",
            integration="sensibo",
            attribute="current_temperature",
            source_unit="°C",
            duplicate_group="zone_a_air",
        ),
        source(
            source_id="setpoint",
            entity_id="climate.example",
            integration="sensibo",
            quantity="setpoint",
            attribute="temperature",
            source_unit="°C",
            evidence="commanded_assumed",
        ),
        source(
            source_id="mode",
            entity_id="climate.example",
            integration="sensibo",
            quantity="mode",
            evidence="commanded_assumed",
        ),
        source(
            source_id="activity",
            entity_id="climate.example",
            integration="sensibo",
            quantity="activity",
            attribute="hvac_action",
            evidence="integration_reported",
        ),
        source(
            source_id="meter",
            entity_id="sensor.example_meter",
            integration="meter",
            quantity="power",
            evidence="electrically_measured",
        ),
    )
    m = mapping(*sources, cache=False)
    states = {
        "sensor.zone_a_temperature": state(unit_of_measurement="°C"),
        "climate.example": state(
            "climate.example", "cool", current_temperature=22, temperature=19
        ),
        "sensor.example_meter": state(
            "sensor.example_meter", "600", unit_of_measurement="W"
        ),
    }
    readings = batch(m, states=states).readings
    assert [r.value for r in readings] == [20, 22, 19, "cool", None, 600]
    assert readings[0].source.duplicate_group == readings[1].source.duplicate_group
    assert readings[4].availability == "missing"
    assert readings[3].source.evidence == "commanded_assumed"


@pytest.mark.parametrize(
    "updates",
    [
        {"entity_id": "sensor.vehicle_temperature"},
        {"entity_id": "climate.byd_example"},
        {"quantity": "power"},
        {"quantity": "mode"},
        {"scope": "remote_weather"},
        {"scope": "remote_weather", "evidence": "remote_modelled"},
    ],
)
def test_mislabelled_roles_and_vehicle_are_rejected(updates):
    with pytest.raises(ValueError):
        source(**updates)


def test_mapping_bounds_duplicates_and_timezone():
    with pytest.raises(ValueError):
        mapping(source(), source())
    with pytest.raises(ValueError):
        mapping(
            *[
                source(source_id=f"s{i}", entity_id=f"sensor.t{i}", zone=f"z{i}")
                for i in range(7)
            ]
        )
    with pytest.raises(ValueError):
        ContextMapping(version="v1", effective_from_utc=T.replace(tzinfo=None))
    with pytest.raises(ValueError):
        parse_mapping(" " * 16385)
    m = mapping()
    assert parse_mapping(m.model_dump_json()) == m


def test_unchanged_state_missing_measurement_time_remains_unknown():
    reading = batch(mapping(cache=False)).readings[0]
    assert reading.value == 20
    assert reading.freshness == "unknown"
    assert reading.measurement_time_utc is None
    assert reading.ha_last_changed == T - timedelta(days=30)
    assert reading.ha_report_age_seconds == 180
    malformed = HomeAssistantState(
        entity_id="sensor.example",
        state="20",
        last_reported="broken",
        last_changed=T,
        last_updated=T,
    )
    assert malformed.last_reported is None


def test_measurement_age_and_unit_conflict():
    s = source(measurement_time_attribute="measured_at")
    m = mapping(s, cache=False)
    for age, freshness in [(60, "measurement_recent"), (8000, "measurement_stale")]:
        reading = batch(
            m,
            states={
                s.entity_id: state(
                    unit_of_measurement="°C",
                    measured_at=(T - timedelta(seconds=age)).isoformat(),
                )
            },
        ).readings[0]
        assert reading.freshness == freshness
        assert reading.value == 20  # Preserve stale evidence; never silently replace.
    future = batch(
        m,
        states={
            s.entity_id: state(
                unit_of_measurement="°C",
                measured_at=(T + timedelta(seconds=1)).isoformat(),
            )
        },
    ).readings[0]
    assert future.value is None and future.reason == "measurement_time_in_future"
    conflict = batch(
        mapping(source(source_unit="°C"), cache=False),
        states={s.entity_id: state(unit_of_measurement="°F")},
    ).readings[0]
    assert (
        conflict.value is None
        and conflict.reason == "configured_and_reported_units_disagree"
    )


def test_unavailable_or_restored_source_is_missing():
    m = mapping(cache=False)
    for item in [
        state(value="unavailable", unit_of_measurement="°C"),
        state(restored=True, unit_of_measurement="°C"),
    ]:
        assert batch(m, states={item.entity_id: item}).readings[0].value is None


def test_cache_native_semantics_missing_issue_privacy_and_explicit_truncation():
    m = mapping()
    item = cache_state(count=50, truncated=True, received_entries=60)
    item.attributes["forecast"][0]["private_coordinates"] = "DO_NOT_STORE"
    snap, diag = parse_weather_cache(m.weather_cache, item, T)
    assert snap.provider_issue_utc is None and snap.provider_version is None
    assert diag["upstream_freshness"] == "unknown"
    assert diag["retained_entries"] == 47 and diag["outside_window_entries"] == 3
    assert diag["truncated"] and diag["cache_received_entries"] == 60
    assert "DO_NOT_STORE" not in snap.model_dump_json()
    values = snap.points[0]["values"]
    assert values["temperature"]["semantics"] == "point_at_native_target"
    assert values["precipitation"]["semantics"] == "accumulation_period_unspecified"
    assert values["precipitation"]["period_end_utc"] is None
    assert diag["native_spacing_seconds"] == [3600]


@pytest.mark.parametrize(
    ("updates", "status"),
    [
        ({"forecast": []}, "empty_or_malformed_cache"),
        ({"forecast_type": "daily"}, "invalid_cache_identity_or_time"),
        ({"provider": "wrong"}, "invalid_cache_identity_or_time"),
        (
            {"cache_success_utc": (T + timedelta(hours=1)).isoformat()},
            "invalid_cache_identity_or_time",
        ),
        ({"restored": True}, "pending_setup_or_unavailable"),
        ({"units": {"temperature": {"private": "bad"}}}, "invalid_forecast_unit"),
        (
            {"provider_issue_utc": (T + timedelta(seconds=1)).isoformat()},
            "invalid_provider_issue_time",
        ),
    ],
)
def test_cache_errors_are_explicit(updates, status):
    snap, diag = parse_weather_cache(mapping().weather_cache, cache_state(**updates), T)
    assert snap is None and diag["status"] == status


def test_cache_target_bounds_shapes_and_nonfinite():
    source_cache = mapping().weather_cache
    item = cache_state(count=97)
    assert (
        parse_weather_cache(source_cache, item, T)[1]["status"]
        == "payload_entry_bound_exceeded"
    )
    item = cache_state()
    item.attributes["forecast"][1]["datetime"] = item.attributes["forecast"][0][
        "datetime"
    ]
    assert (
        parse_weather_cache(source_cache, item, T)[1]["status"]
        == "invalid_or_duplicate_target_time"
    )
    item.attributes["forecast"][1]["datetime"] = "no timezone"
    assert parse_weather_cache(source_cache, item, T)[0] is None
    for value, status in [
        (float("nan"), "nonfinite_or_malformed_payload"),
        ({"nested_private": "bad"}, "invalid_forecast_scalar"),
    ]:
        item = cache_state()
        item.attributes["forecast"][0]["temperature"] = value
        assert parse_weather_cache(source_cache, item, T)[1]["status"] == status


def test_stale_cache_is_archived_without_claiming_upstream_freshness():
    item = cache_state(success=T - timedelta(hours=4))
    snap, diag = parse_weather_cache(mapping().weather_cache, item, T)
    assert snap is not None and diag["cache_stale"]
    assert snap.cache_success_utc == T - timedelta(hours=4)
    assert snap.provider_issue_utc is None
    assert diag["upstream_freshness"] == "unknown"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.headers = {}
        self.payload = payload
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        return Response(self.payload)


def test_one_cached_get_optional_malformed_isolated_core_unchanged(
    healthy_states, config, now
):
    payload = [s.model_dump(mode="json") for s in healthy_states.values()]
    payload.append(
        {"entity_id": "sensor.zone_a_temperature", "attributes": {"private": "never"}}
    )
    m = mapping(cache=False)
    enabled = config.model_copy(update={"context_collection_enabled": True})
    session = Session(payload)
    client = HomeAssistantClient(
        "http://example.invalid", "synthetic-secret", session=session
    )
    observation, states = Collector(
        client, enabled, context_mapping=m
    ).collect_with_states(observed_at=now)
    assert observation == build_observation(healthy_states, config, observed_at=now)
    assert len(session.calls) == 1 and session.calls[0].endswith("/api/states")
    assert "sensor.zone_a_temperature" not in states
    with pytest.raises(ReadOnlyViolation):
        client._get_json("/api/services/weather/get_forecasts")
    assert not hasattr(client, "post")
    payload[0].pop("state")
    with pytest.raises(HomeAssistantResponseError):
        client.get_states(healthy_states, optional_entity_ids=m.entity_ids)


@pytest.mark.parametrize(
    "context_states",
    [
        {},
        {"sensor.zone_a_temperature": state(value="bad")},
        {"sensor.zone_a_temperature": state(unit_of_measurement="°C")},
    ],
)
def test_enabled_disabled_context_leaves_baseline_and_forecast_inputs_identical(
    context_states, healthy_states, config, now
):
    class Client:
        def get_states(self, _ids, **_kwargs):
            return {**healthy_states, **context_states}

    m = mapping(cache=False)
    disabled = Collector(Client(), config, context_mapping=m).collect(observed_at=now)
    enabled = Collector(
        Client(),
        config.model_copy(update={"context_collection_enabled": True}),
        context_mapping=m,
    ).collect(observed_at=now)
    assert enabled.model_dump() == disabled.model_dump()
    assert enabled.baseline_training_eligible == disabled.baseline_training_eligible


@pytest.fixture(params=["sqlite", "postgresql"])
def context_db(request, tmp_path):
    admin = None
    schema = None
    if request.param == "sqlite":
        url = f"sqlite+pysqlite:///{(tmp_path / 'context.db').as_posix()}"
    else:
        configured = os.getenv("TEST_POSTGRES_URL")
        if not configured:
            pytest.skip("owned TEST_POSTGRES_URL required")
        parsed = make_url(configured)
        assert parsed.host == "127.0.0.1"
        assert parsed.database == os.environ["F1_F3_OWNED_TEST_DATABASE"]
        admin = create_database_engine(configured)
        schema = f"context_{uuid.uuid4().hex}"
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = parsed.set(query={"options": f"-csearch_path={schema}"}).render_as_string(
            hide_password=False
        )
    command.upgrade(alembic_config(url), "head")
    repository = open_repository(url)
    try:
        yield repository, url
    finally:
        repository.close()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def save_core(repository, healthy_states, config, time_utc):
    observation = build_observation(healthy_states, config, observed_at=time_utc)
    repository.save_observation(observation)
    return observation.slot_utc


def test_roundtrip_retry_dedup_revisions_and_causal_availability(
    context_db, healthy_states, config
):
    repository, _ = context_db
    contexts = ContextRepository(repository)
    m = mapping()
    receipt = T + timedelta(minutes=5)
    slot = save_core(repository, healthy_states, config, receipt)
    first = batch(m, receipt=receipt, slot=slot, weather=cache_state())
    recorded = receipt + timedelta(seconds=2)
    result = contexts.save(first, recorded_at=recorded)
    assert result["inserted"]
    assert contexts.save(first, recorded_at=recorded)["inserted"] is False
    key = content_hash(
        {"source": first.weather.source.model_dump(), "mapping": m.fingerprint}
    )
    assert contexts.context_as_of(receipt) is None
    assert contexts.weather_as_of(key, receipt) is None
    assert (
        contexts.weather_as_of(key, recorded)["received_at_utc"]
        == first.weather.model_dump(mode="json")["received_at_utc"]
    )
    assert (
        contexts.context_as_of(T) is None
    )  # Provider/cache times cannot backdate receipt.
    with repository.transaction() as session:
        original = copy.deepcopy(
            session.get(WeatherContextSnapshot, result["weather_snapshot_id"]).body
        )
    # Repeated reads and repeated successful retrievals are not independent versions.
    for index, item in enumerate(
        [
            cache_state(),
            cache_state(success=T + timedelta(minutes=10)),
            cache_state(success=T + timedelta(minutes=15), value=21),
            cache_state(success=T + timedelta(minutes=20), value=20),
            cache_state(
                success=T + timedelta(minutes=25),
                value=20,
                issue=(T + timedelta(minutes=24)).isoformat(),
            ),
        ],
        start=2,
    ):
        receive = T + timedelta(minutes=index * 5)
        slot = save_core(repository, healthy_states, config, receive)
        contexts.save(
            batch(m, receipt=receive, slot=slot, weather=item), recorded_at=receive
        )
    with repository.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ContextObservation)) == 6
        assert (
            session.scalar(select(func.count()).select_from(WeatherContextSnapshot))
            == 4
        )
        assert (
            session.get(WeatherContextSnapshot, result["weather_snapshot_id"]).body
            == original
        )
        rows = session.scalars(select(ContextObservation)).all()
        assert all("weather" not in row.body for row in rows)
        assert all(row.body["weather_snapshot_id"] for row in rows)
    assert json.loads(json.dumps(contexts.context_as_of(T + timedelta(hours=1))))


def test_additive_migration_preserves_legacy_rows_and_old_columns(
    context_db, healthy_states, config
):
    repository, url = context_db
    command.downgrade(alembic_config(url), "20260927_01")
    assert "context_observations" not in inspect(repository.engine).get_table_names()
    save_core(repository, healthy_states, config, T)
    before = repository.observation_rows()

    def columns():
        return [
            {**column, "type": str(column["type"])}
            for column in inspect(repository.engine).get_columns("observations")
        ]

    old_columns = columns()
    command.upgrade(alembic_config(url), "20261005_01")
    assert current_revision(repository.engine) == "20261005_01"
    assert repository.observation_rows() == before
    assert columns() == old_columns
    assert ContextRepository(repository).context_as_of(T) is None


@pytest.mark.parametrize("where", ["open", "save", "close", "parse"])
def test_optional_failure_diagnostic_no_private_exception_leak(
    where, monkeypatch, caplog
):
    # Alembic env fileConfig disables existing loggers during migration tests.
    monkeypatch.setattr(
        logging.getLogger("energy_optimizer.context_collection"), "disabled", False
    )

    class Broken:
        def close(self):
            if where == "close":
                raise RuntimeError("PRIVATE_CREDENTIAL")

    def factory():
        if where == "open":
            raise RuntimeError("PRIVATE_CREDENTIAL")
        return Broken()

    def save(_self, _batch):
        if where == "save":
            raise RuntimeError("PRIVATE_CREDENTIAL")
        return {"inserted": True}

    monkeypatch.setattr(ContextRepository, "save", save)
    if where == "parse":
        import energy_optimizer.context_collection as module

        def fail(*_args, **_kwargs):
            raise RuntimeError("PRIVATE_RAW_STATE")

        monkeypatch.setattr(module, "collect_context", fail)
    result = collect_and_store_context(
        {}, mapping(), slot=T, receipt=T, repository_factory=factory
    )
    assert result["status"] == ("operating" if where == "close" else "optional_failure")
    assert "PRIVATE" not in caplog.text
    assert "core already saved" in caplog.text


def test_core_commit_survives_missing_optional_tables(tmp_path, healthy_states, config):
    url = f"sqlite+pysqlite:///{(tmp_path / 'old.db').as_posix()}"
    command.upgrade(alembic_config(url), "20260927_01")
    repository = open_repository(url)
    save_core(repository, healthy_states, config, T)
    result = collect_and_store_context(
        {},
        mapping(),
        slot=T,
        receipt=T,
        repository_factory=lambda: open_repository(url),
    )
    assert result["status"] == "optional_failure"
    assert len(repository.observation_rows()) == 1
    assert current_revision(repository.engine) == "20260927_01"  # No startup migration.
    repository.close()


def test_bounded_sqlite_lock_and_core_priority(tmp_path, healthy_states, config):
    url = f"sqlite+pysqlite:///{(tmp_path / 'locked.db').as_posix()}"
    command.upgrade(alembic_config(url), "head")
    core = open_repository(url)
    save_core(core, healthy_states, config, T)
    blocker = core.engine.connect()
    blocker.exec_driver_sql("BEGIN EXCLUSIVE")
    started = time.monotonic()
    bounded = create_database_engine(url, sqlite_timeout_seconds=0.1)
    from energy_optimizer.persistence import ApplicationRepository

    result = collect_and_store_context(
        {},
        mapping(),
        slot=T,
        receipt=T,
        repository_factory=lambda: ApplicationRepository(bounded),
    )
    elapsed = time.monotonic() - started
    blocker.rollback()
    blocker.close()
    assert elapsed < 2 and result["status"] == "optional_failure"
    assert len(core.observation_rows()) == 1
    core.close()


def test_old_app_options_disabled_defaults_and_json_status():
    old = {
        "db_host": "example.invalid",
        "db_name": "synthetic",
        "db_user": "test",
        "db_password": "not-a-real-secret",
    }
    options = HomeAssistantAppOptions.model_validate(old)
    assert (
        options.context_collection_enabled is False
        and options.context_mapping_json == ""
    )
    environment = app_environment(options, supervisor_token="synthetic-token")
    assert environment["CONTEXT_COLLECTION_ENABLED"] == "false"
    health = AppHealth(max_observation_age_seconds=600)
    assert health.response()[1]["context_collection"]["status"] == "disabled"
    health.record_context(
        {
            "status": "operating",
            "last_useful_receipt_utc": T.isoformat(),
            "weather_snapshot_id": "opaque",
            "diagnostic": {"weather": {"first_target_utc": T}},
        }
    )
    json.dumps(health.response()[1])
    health.record_context({"status": "optional_failure"})
    assert health.response()[0] == 200
    assert health.context_collection["last_useful_receipt_utc"] == T.isoformat()
    assert health.context_collection["last_weather_coverage"][
        "first_target_utc"
    ] == json_safe(T)


def test_weather_availability_and_cache_timing_are_preserved_without_issue_inference():
    m = mapping()
    item = cache_state(last_attempt_utc=T.isoformat())
    snapshot, diagnostic = parse_weather_cache(m.weather_cache, item, T)
    assert snapshot.diagnostics["cache_ha_last_changed"] == T - timedelta(days=30)
    assert diagnostic["cache_ha_last_reported"] == T - timedelta(minutes=3)
    assert snapshot.provider_issue_utc is None
    assert diagnostic["cache_availability"] == "available"
    missing = batch(m)
    assert missing.weather_source == m.weather_cache
    assert missing.diagnostic["weather"]["cache_availability"] == "missing"
    unavailable = item.model_copy(update={"state": "unavailable"})
    snap, diagnostic = parse_weather_cache(m.weather_cache, unavailable, T)
    assert snap is None and diagnostic["cache_availability"] == "unavailable"
