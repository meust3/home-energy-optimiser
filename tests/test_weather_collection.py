from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse
from types import SimpleNamespace

import pytest
import requests
from alembic import command
from sqlalchemy import Engine, event, func, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

import energy_optimizer.weather.collection as collection_module
import energy_optimizer.weather.repository as repository_module
from energy_optimizer.dashboard_api import DashboardService
from energy_optimizer.dashboard_web import IngressAccessPolicy, make_handler
from energy_optimizer.db.migrations import alembic_config
from energy_optimizer.db.models import WEATHER_TABLES
from energy_optimizer.forecast_operations import (
    ForecastCoordinator,
    ForecastOperationsConfig,
)
from energy_optimizer.home_assistant_app import (
    AppHealth,
    HomeAssistantAppOptions,
    app_environment,
)
from energy_optimizer.persistence import open_repository
from energy_optimizer.weather.client import (
    ENDPOINT,
    OneCallClient,
    PageResponse,
    WeatherFetchError,
)
from energy_optimizer.weather.collection import WeatherCollector
from energy_optimizer.weather.config import WeatherCollectionConfig
from energy_optimizer.weather.deadline import (
    DeadlinePool,
    DeadlineReader,
    DeadlineSocket,
    deadline_adapter,
)
from energy_optimizer.weather.pagination import page_metadata
from energy_optimizer.weather.providers import parse_onecall4
from energy_optimizer.weather.receipt import sanitized_payload
from energy_optimizer.weather.repository import (
    ATTEMPTS,
    CYCLES,
    PAYLOADS,
    TARGETS,
    VERSIONS,
    WeatherRepository,
)
from energy_optimizer.weather.spool import WeatherSpool

NOW = datetime(2026, 8, 1, 2, 30, 20, tzinfo=UTC)
KEY = "a" * 32
CONFIG = WeatherCollectionConfig(
    enabled=True, provider_cap_confirmed=True, api_key=KEY, latitude=0, longitude=0
)


@pytest.fixture(autouse=True)
def no_live_weather(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "No live provider requests permitted in implementation tests"
        )

    monkeypatch.setattr(requests.Session, "request", forbidden)


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    url = f"sqlite:///{tmp_path / 'weather.db'}"
    admin = None
    schema = None
    if request.param == "postgresql":
        supplied = os.getenv("WEATHER_TEST_POSTGRES_URL")
        if not supplied:
            pytest.skip("isolated WEATHER_TEST_POSTGRES_URL not configured")
        parsed = make_url(supplied)
        assert (
            parsed.host in {"127.0.0.1", "localhost"}
            and parsed.database == "weather_test"
        )
        admin = open_repository(supplied)
        schema = "weather_" + uuid.uuid4().hex
        with admin.engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = parsed.set(query={"options": f"-csearch_path={schema}"}).render_as_string(
            hide_password=False
        )
    repository = open_repository(url)
    for table in WEATHER_TABLES.values():
        table.create(repository.engine)

    def factory():
        return open_repository(url)

    yield SimpleNamespace(
        repository=repository,
        archive=WeatherRepository(repository),
        factory=factory,
        spool=WeatherSpool(tmp_path / "delivery"),
    )
    repository.close()
    if admin is not None:
        assert schema.startswith("weather_") and len(schema) == 40
        with admin.engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.close()


class Client:
    def __init__(self, factory, *, status=200, temperature=25, omit=None, fail=False):
        self.factory, self.status, self.temperature = factory, status, temperature
        self.omit, self.fail, self.calls, self.now = omit, fail, [], NOW

    def fetch(self, **kwargs):
        repository = self.factory()
        with repository.transaction() as db:
            assert db.scalar(select(func.count()).select_from(ATTEMPTS)) > len(
                self.calls
            )
        repository.close()
        self.calls.append(kwargs["start_epoch"])
        if self.fail:
            raise WeatherFetchError(f"private details must be withheld {KEY}")
        records = [
            {
                "dt": kwargs["start_epoch"] + n * 900,
                "temp": self.temperature,
                "clouds": 40,
                "weather": [{"id": 802}],
            }
            for n in range(50)
        ]
        records = [row for row in records if row["dt"] != self.omit]
        body = {
            "lat": 0,
            "lon": 0,
            "data": records,
            "next": ENDPOINT.replace("https://", "http://")
            + f"?start={records[-1]['dt']+1}&appid={KEY}",
        }
        return PageResponse(
            self.status,
            self.now + timedelta(milliseconds=100),
            json.dumps(body).encode(),
        )


def collector(store, client, config=CONFIG):
    states = []
    service = WeatherCollector(
        config=config,
        spool=store.spool,
        repository_factory=store.factory,
        on_status=states.append,
        client=client,
        clock=lambda: client.now + timedelta(milliseconds=100),
    )
    return service, states


def step(service, client, now):
    client.now = now
    return service.step(now, collector_idle=True)


def finish(service, client, now=NOW):
    for n in range(5):
        result = step(service, client, now + timedelta(seconds=n))
        if result["status"] != "COLLECTING":
            return result
    raise AssertionError("cycle did not terminate within page bound")


def test_disabled_does_not_open_database_or_network():
    def forbidden():
        raise AssertionError("disabled feature performed I/O")

    service = WeatherCollector(
        config=WeatherCollectionConfig(),
        repository_factory=forbidden,
        on_status=lambda _: None,
        client=SimpleNamespace(fetch=forbidden),
    )
    assert service.step(NOW, collector_idle=True)["status"] == "disabled"
    assert KEY not in repr(CONFIG)


def test_transport_is_fixed_https_bounded_and_does_not_follow_redirects():
    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def mount(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(
                status_code=302,
                iter_content=lambda **_: iter([b"{}"]),
                close=lambda: None,
            )

    result = OneCallClient(session_factory=Session, clock=lambda: NOW).fetch(
        key=KEY, latitude=0, longitude=0, start_epoch=int(NOW.timestamp())
    )
    assert result.status == 302 and len(calls) == 1
    url, options = calls[0]
    assert url == ENDPOINT and options["allow_redirects"] is False
    assert options["timeout"] == (5, 10) and options["params"]["units"] == "metric"
    assert "raw=" not in repr(result)


def test_transport_exception_does_not_echo_request_credentials():
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def mount(self, *args):
            pass

        def get(self, *args, **kwargs):
            raise requests.Timeout("secret " + KEY)

    with pytest.raises(WeatherFetchError) as error:
        OneCallClient(session_factory=Session).fetch(
            key=KEY, latitude=0, longitude=0, start_epoch=0
        )
    assert KEY not in str(error.value)


def test_full_cycle_records_before_get_and_preserves_versions(store):
    client = Client(store.factory)
    service, _ = collector(store, client)
    first = finish(service, client)
    assert first["status"] == "COMPLETE" and first["target_timestamps"] == 192
    assert len(client.calls) == 4
    original = store.archive.cycle(
        cycle_id=first["cycle_id"], as_of=NOW + timedelta(minutes=1)
    )
    assert len(original["targets"]) == 192
    assert original["targets"][0]["body"]["temperature"]["value"] == 25
    client.temperature = 26
    second = finish(service, client, NOW + timedelta(minutes=10))
    assert second["status"] == "COMPLETE" and second["cycle_id"] != first["cycle_id"]
    assert (
        store.archive.cycle(cycle_id=first["cycle_id"], as_of=NOW + timedelta(hours=1))[
            "targets"
        ][0]["body"]["temperature"]["value"]
        == 25
    )
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 8
        assert db.scalar(select(func.count()).select_from(VERSIONS)) == 400
        for payload in db.execute(select(PAYLOADS.c.body)).scalars():
            assert KEY.encode() not in payload


def test_identical_content_reused_but_every_receipt_is_kept(store):
    client = Client(store.factory)
    service, _ = collector(store, client)
    finish(service, client)
    finish(service, client, NOW + timedelta(minutes=10))
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 8
        assert db.scalar(select(func.count()).select_from(VERSIONS)) == 200
        assert db.scalar(select(func.count()).select_from(TARGETS)) == 400


def test_celsius_parser_upgrade_preserves_every_legacy_record(store, monkeypatch):
    def legacy_parser(*args, **kwargs):
        capture = parse_onecall4(*args, **kwargs)
        return replace(
            capture,
            parser_version="weather-v1",
            points=tuple(
                replace(p, unit="\u00c2\u00b0C") if p.unit == "\u00b0C" else p
                for p in capture.points
            ),
        )

    monkeypatch.setattr(collection_module, "parse_onecall4", legacy_parser)
    monkeypatch.setattr(repository_module, "PARSER_VERSION", "weather-v1")
    client = Client(store.factory)
    service, _ = collector(store, client)
    first = finish(service, client)
    with store.repository.transaction() as db:
        original = {
            table.name: [dict(r) for r in db.execute(select(table)).mappings()]
            for table in WEATHER_TABLES.values()
        }
    monkeypatch.setattr(collection_module, "parse_onecall4", parse_onecall4)
    monkeypatch.setattr(repository_module, "PARSER_VERSION", "weather-v2")
    second = finish(service, client, NOW + timedelta(minutes=10))
    assert first["status"] == second["status"] == "COMPLETE"
    with store.repository.transaction() as db:
        for table in WEATHER_TABLES.values():
            current = [dict(r) for r in db.execute(select(table)).mappings()]
            assert all(row in current for row in original[table.name])
        assert db.scalar(select(func.count()).select_from(PAYLOADS)) == 4
        assert db.scalar(select(func.count()).select_from(VERSIONS)) == 400
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 8
        for attempt, version in db.execute(
            select(ATTEMPTS.c.parser_version, VERSIONS.c.body).select_from(
                TARGETS.join(ATTEMPTS).join(VERSIONS)
            )
        ):
            assert version["temperature"]["unit"] == (
                "\u00c2\u00b0C" if attempt == "weather-v1" else "\u00b0C"
            )
    old = store.archive.cycle(
        cycle_id=first["cycle_id"], as_of=NOW + timedelta(hours=1)
    )
    new = store.archive.cycle(
        cycle_id=second["cycle_id"], as_of=NOW + timedelta(hours=1)
    )
    assert old["targets"][0]["body"]["temperature"]["unit"] == "\u00c2\u00b0C"
    assert new["targets"][0]["body"]["temperature"]["unit"] == "\u00b0C"


def test_pending_v1_receipt_uses_actual_v2_parser_without_another_request(
    store, monkeypatch
):
    monkeypatch.setattr(repository_module, "PARSER_VERSION", "weather-v1")
    claim = store.archive.claim_page(config=CONFIG, now=NOW)
    store.spool.prepare()
    client = Client(store.factory)
    service, _ = collector(store, client)
    page = service._fetch(claim)
    store.spool.save(page)
    monkeypatch.setattr(repository_module, "PARSER_VERSION", "weather-v2")
    restarted, _ = collector(store, client)
    assert step(restarted, client, NOW + timedelta(seconds=1))["status"] == "COLLECTING"
    assert len(client.calls) == 1
    with store.repository.transaction() as db:
        attempt = db.execute(select(ATTEMPTS)).mappings().one()
        assert attempt["parser_version"] == "weather-v2"
        assert attempt["requested_at"] == claim["requested_at"]
        for row in db.execute(select(VERSIONS)).mappings():
            assert row["body"]["temperature"]["unit"] == "\u00b0C"
            canonical = json.dumps(
                {
                    "scope": CONFIG.scope,
                    "target": row["target_at"].isoformat(),
                    "values": row["body"],
                    "parser": attempt["parser_version"],
                },
                sort_keys=True,
                allow_nan=False,
            )
            assert hashlib.sha256(canonical.encode()).hexdigest() == row["sha256"]
        before = dict(attempt)
    # A duplicate delivery cannot reinterpret a completed attempt again.
    store.archive.finish_page(
        claim,
        now=NOW + timedelta(minutes=1),
        config=CONFIG,
        raw=page.receipt.body,
        http_status=200,
        capture=replace(
            parse_onecall4(
                page.receipt.body,
                product="onecall4_15min",
                site_ref="home",
                requested_at=NOW,
                received_at=page.finished_at,
                requested_units="metric",
            ),
            parser_version="unexpected-replay-version",
        ),
    )
    with store.repository.transaction() as db:
        assert dict(db.execute(select(ATTEMPTS)).mappings().one()) == before


def test_worker_restart_resumes_only_next_committed_page(store):
    client = Client(store.factory)
    service, _ = collector(store, client)
    assert step(service, client, NOW)["status"] == "COLLECTING"
    start = client.calls[0]
    restarted, _ = collector(store, client)
    result = finish(restarted, client, NOW + timedelta(seconds=1))
    assert result["status"] == "COMPLETE"
    assert client.calls == [start + n * 50 * 900 for n in range(4)]


def test_next_ten_minute_slot_is_not_skipped_for_small_wake_jitter(store):
    client = Client(store.factory)
    service, _ = collector(store, client)
    result = finish(service, client, NOW + timedelta(milliseconds=100))
    assert result["status"] == "COMPLETE"
    assert step(service, client, NOW + timedelta(minutes=5))["status"] == "NOT_DUE"
    result = step(service, client, NOW + timedelta(minutes=10))
    assert result["status"] == "COLLECTING"
    assert len(client.calls) == 5


def test_unknown_request_not_retried_after_restart(store):
    claim = store.archive.claim_page(CONFIG, NOW)
    client = Client(store.factory)
    service, _ = collector(store, client)
    assert (
        step(service, client, NOW + timedelta(seconds=5))["status"] == "PAGE_IN_FLIGHT"
    )
    assert (
        step(service, client, NOW + timedelta(seconds=121))["error_code"]
        == "INTERRUPTED_REQUEST"
    )
    assert client.calls == []
    with store.repository.transaction() as db:
        assert (
            db.scalar(select(ATTEMPTS.c.status).where(ATTEMPTS.c.id == claim["id"]))
            == "UNKNOWN"
        )


@pytest.mark.parametrize("status", [401, 403, 429])
def test_provider_rejection_blocks_route_without_affecting_collector(store, status):
    client = Client(store.factory, status=status)
    service, states = collector(store, client)
    assert step(service, client, NOW)["error_code"] == f"HTTP_{status}"
    service, _ = collector(store, client)
    assert (
        step(service, client, NOW + timedelta(minutes=10))["status"]
        == "PROVIDER_BLOCKED"
    )
    assert len(client.calls) == 1
    health = AppHealth(900)
    health.record_weather(states[-1])
    assert health.response(now=health._started_at_utc)[0] == 200


def test_gap_is_partial_and_missing_values_not_invented(store):
    epoch = int(NOW.timestamp()) // 900 * 900
    client = Client(store.factory, omit=epoch + 4 * 900)
    service, _ = collector(store, client)
    result = finish(service, client)
    assert result["status"] == "PARTIAL" and result["target_timestamps"] == 191


def test_transport_unknown_retains_reservation_and_hides_secret(store, caplog):
    client = Client(store.factory, fail=True)
    service, _ = collector(store, client)
    assert step(service, client, NOW)["error_code"] == "TRANSPORT_OUTCOME_UNKNOWN"
    assert step(service, client, NOW + timedelta(seconds=5))["status"] == "NOT_DUE"
    assert len(client.calls) == 1 and KEY not in caplog.text
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 1
        assert db.scalar(select(ATTEMPTS.c.received_at)) is None


def test_archive_retry_reuses_buffer_without_another_provider_request(
    store, monkeypatch
):
    client = Client(store.factory)
    service, _ = collector(store, client)
    original = WeatherRepository.finish_page
    attempts = []

    def once(self, *args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("synthetic write interruption")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(WeatherRepository, "finish_page", once)
    assert step(service, client, NOW)["status"] == "archive_unavailable"
    assert step(service, client, NOW + timedelta(seconds=1))["status"] == "COLLECTING"
    assert len(client.calls) == 1


def _seed_budget(store, used):
    claim = store.archive.claim_page(CONFIG, NOW - timedelta(hours=1))
    with store.repository.transaction() as db:
        db.execute(
            ATTEMPTS.update()
            .where(ATTEMPTS.c.id == claim["id"])
            .values(status="UNKNOWN")
        )
        db.execute(
            CYCLES.update()
            .where(CYCLES.c.id == claim["cycle_id"])
            .values(status="PARTIAL")
        )
        if used > 1:
            db.execute(
                insert(ATTEMPTS),
                [
                    dict(
                        id=str(uuid.uuid4()),
                        account_ref=CONFIG.account_ref,
                        cycle_id=claim["cycle_id"],
                        page_number=n + 2,
                        request_start_epoch=0,
                        requested_at=NOW - timedelta(hours=1),
                        status="UNKNOWN",
                        model_identity="UNKNOWN",
                        native_resolution="UNKNOWN",
                        parser_version="test",
                    )
                    for n in range(used - 1)
                ],
            )


def test_quota_900_stops_before_network_and_survives_restart(store):
    _seed_budget(store, 900)
    client = Client(store.factory)
    service, _ = collector(store, client)
    result = step(service, client, NOW)
    assert result["status"] == "QUOTA_STOP" and client.calls == []
    assert result["remaining_attempts"] == 0


def test_concurrent_claim_is_single_reservation(store):
    def claim(_):
        repository = store.factory()
        try:
            return WeatherRepository(repository).claim_page(CONFIG, NOW)["status"]
        except RuntimeError:
            return "BUSY"
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(claim, range(12)))
    assert statuses.count("RESERVED") == 1
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 1


def test_asof_reads_do_not_borrow_later_receipts_or_completion(store):
    client = Client(store.factory)
    service, _ = collector(store, client)
    result = finish(service, client)
    earlier = store.archive.cycle(cycle_id=result["cycle_id"], as_of=NOW)
    assert earlier["status"] == "INCOMPLETE_AS_OF" and earlier["targets"] == []
    assert store.archive.history(as_of=NOW)[0]["completed_at"] is None


def test_ingress_queries_read_only_and_exclude_location_key_payload(store):
    client = Client(store.factory)
    service, _ = collector(store, client)
    result = finish(service, client)
    health = AppHealth(900)
    dashboard = DashboardService(
        "test", health, repository_factory=lambda _: store.factory()
    )
    payload = dashboard.weather_archive(
        cycle_id=result["cycle_id"], as_of=NOW + timedelta(seconds=20)
    ).model_dump_json()
    assert KEY not in payload
    assert (
        "latitude" not in payload
        and "longitude" not in payload
        and '"body": "' not in payload
    )

    class Socket:
        def __init__(self, request):
            self.input, self.output = io.BytesIO(request), b""

        def makefile(self, *args):
            return self.input

        def sendall(self, value):
            self.output += value

    handler = make_handler(
        health=health, service=dashboard, access_policy=IngressAccessPolicy()
    )
    for method, path, status in [
        ("GET", "/api/v1/weather", 200),
        ("POST", "/api/v1/weather", 405),
        ("GET", "/api/v1/weather?latitude=0", 400),
        ("GET", "/weather", 200),
    ]:
        socket = Socket(f"{method} {path} HTTP/1.0\r\n\r\n".encode())
        handler(socket, ("127.0.0.1", 1), SimpleNamespace())
        assert f" {status} ".encode() in socket.output.split(b"\r\n")[0]


def test_app_defaults_and_secrets_not_exported_to_environment():
    options = HomeAssistantAppOptions(
        db_host="test.invalid",
        db_password="test",
        weather_openweather_api_key=KEY,
        weather_latitude=0,
        weather_longitude=0,
    )
    assert options.weather_collection_enabled is False
    assert options.weather_provider_cap_confirmed is False
    assert options.weather_provider_daily_cap == 1000
    assert KEY not in repr(options)
    assert KEY not in json.dumps(
        app_environment(options, supervisor_token="test-supervisor")
    )
    with pytest.raises(ValueError):
        HomeAssistantAppOptions(
            db_host="test.invalid", db_password="test", weather_provider_daily_cap=2000
        )


def test_weather_coordinator_runs_without_demand_forecasts(config):
    now = [NOW - timedelta(seconds=21)]
    health = AppHealth(900)
    health.last_successful_collection_utc = NOW - timedelta(seconds=20)
    calls = []

    class Weather:
        enabled = True
        active = False

        def step(self, when, collector_idle):
            if not collector_idle:
                return {"status": "deferred_to_collector"}
            calls.append((when, collector_idle))
            self.active = len(calls) < 4

    class Stop:
        def is_set(self):
            return False

        def wait(self, delay):
            if len(calls) == 4:
                return True
            now[0] += timedelta(seconds=delay)
            return False

    def forbidden():
        raise AssertionError("disabled demand forecaster opened database")

    coordinator = ForecastCoordinator(
        repository_factory=forbidden,
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=False),
        health=health,
        clock=lambda: now[0],
        weather=Weather(),
    )
    coordinator.run(Stop())
    assert len(calls) == 4 and all(idle for _, idle in calls)
    assert health.forecast_scheduler == "disabled"


@pytest.mark.parametrize("stop_after_core", [False, True])
def test_coordinator_prioritizes_core_and_honors_stop(
    config, monkeypatch, stop_after_core
):
    now = [NOW - timedelta(seconds=21)]
    events = []
    stopped = [False]
    health = AppHealth(900)
    health.last_successful_collection_utc = NOW - timedelta(seconds=20)

    class Weather:
        enabled = True
        active = False

        def step(self, when, collector_idle):
            assert collector_idle
            events.append("weather")
            stopped[0] = True

    class Stop:
        def is_set(self):
            return stopped[0]

        def wait(self, delay):
            now[0] += timedelta(seconds=delay)
            return stopped[0]

    coordinator = ForecastCoordinator(
        repository_factory=lambda: SimpleNamespace(
            recover_stale_forecast_operations=lambda **_: None, close=lambda: None
        ),
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=True),
        health=health,
        clock=lambda: now[0],
        weather=Weather(),
    )

    def core(boundary):
        events.append("core")
        stopped[0] = stop_after_core

    monkeypatch.setattr(coordinator, "run_boundary", core)
    coordinator.run(Stop())
    assert events == (["core"] if stop_after_core else ["core", "weather"])


@pytest.mark.parametrize(
    "hint",
    [
        "https://example.invalid/data/4.0/onecall/timeline/15min?start=START",
        ENDPOINT + "?start=START&units=imperial",
        ENDPOINT + "?start=START&lat=10",
        ENDPOINT + "?start=START&start=START",
        ENDPOINT + "?start=START&appid=other",
        ENDPOINT + "?start=START&unexpected=1",
    ],
)
def test_pagination_rejects_changed_destination_or_request_semantics(hint):
    start = int(NOW.timestamp()) // 900 * 900
    raw = json.dumps(
        {"data": [{"dt": start}], "next": hint.replace("START", str(start + 900))}
    ).encode()
    with pytest.raises(ValueError):
        page_metadata(
            raw,
            endpoint=ENDPOINT,
            page_start=start,
            horizon_end=start + 172800,
            latitude=0,
            longitude=0,
            key=KEY,
        )


def test_weather_defers_near_collector_boundaries():
    health = AppHealth(900)
    boundary = NOW.replace(minute=30, second=0)
    health.last_successful_collection_utc = boundary
    assert not health.weather_collection_allowed(boundary + timedelta(seconds=19))
    assert health.weather_collection_allowed(boundary + timedelta(seconds=20))
    assert not health.weather_collection_allowed(boundary + timedelta(seconds=210))


def test_migration_empty_roundtrip_and_nonempty_downgrade_refused(tmp_path):
    url = f"sqlite:///{tmp_path/'migration.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "20261024_01")
    repository = open_repository(url)
    assert (
        "weather_collection_cycles" not in inspect(repository.engine).get_table_names()
    )
    repository.close()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "20261024_01")
    command.upgrade(cfg, "head")
    repository = open_repository(url)
    WeatherRepository(repository).claim_page(CONFIG, NOW)
    with pytest.raises(RuntimeError, match="not empty"):
        command.downgrade(cfg, "20261024_01")
    assert "weather_collection_cycles" in inspect(repository.engine).get_table_names()
    repository.close()


def test_postgresql_migration_roundtrip_uses_only_owned_loopback_database():
    supplied = os.getenv("WEATHER_TEST_POSTGRES_URL")
    if not supplied:
        pytest.skip("isolated WEATHER_TEST_POSTGRES_URL not configured")
    parsed = make_url(supplied)
    assert (
        parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "weather_test"
    )
    admin = open_repository(supplied)
    schema = "weather_migration_" + uuid.uuid4().hex
    with admin.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = parsed.set(
        query={"options": f"-csearch_path={schema} -clock_timeout=250ms"}
    ).render_as_string(hide_password=False)
    cfg = alembic_config(url)
    try:
        command.upgrade(cfg, "20261024_01")
        command.upgrade(cfg, "head")
        repository = open_repository(url)
        statements = []

        def capture(connection, cursor, statement, parameters, context, many):
            if any(
                t.name.upper() in statement.upper() for t in WEATHER_TABLES.values()
            ):
                statements.append(statement.strip().upper())

        event.listen(Engine, "before_cursor_execute", capture)
        try:
            with repository.engine.begin() as writer:
                writer.exec_driver_sql(
                    "LOCK TABLE weather_collection_cycles IN ROW EXCLUSIVE MODE"
                )
                with pytest.raises(DBAPIError) as error:
                    command.downgrade(cfg, "20261024_01")
                assert error.value.orig.sqlstate == "55P03"
            assert any("ACCESS EXCLUSIVE MODE NOWAIT" in q for q in statements)
            assert not any(q.startswith(("SELECT", "DROP TABLE")) for q in statements)
            assert set(t.name for t in WEATHER_TABLES.values()) <= set(
                inspect(repository.engine).get_table_names()
            )
        finally:
            event.remove(Engine, "before_cursor_execute", capture)
            repository.close()
        command.downgrade(cfg, "20261024_01")
        command.upgrade(cfg, "head")
        repository = open_repository(url)
        try:
            WeatherRepository(repository).claim_page(CONFIG, NOW)
            with pytest.raises(RuntimeError, match="not empty"):
                command.downgrade(cfg, "20261024_01")
            assert (
                len(
                    set(WEATHER_TABLES[key].name for key in WEATHER_TABLES)
                    & set(inspect(repository.engine).get_table_names())
                )
                == 6
            )
        finally:
            repository.close()
    finally:
        assert schema.startswith("weather_migration_") and len(schema) == 50
        with admin.engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.close()


def test_durable_receipt_survives_database_failure_and_process_restart(
    store, monkeypatch
):
    client = Client(store.factory)
    service, _ = collector(store, client)
    original = WeatherRepository.finish_page

    def unavailable(*args, **kwargs):
        raise OSError("synthetic archive failure")

    monkeypatch.setattr(WeatherRepository, "finish_page", unavailable)
    assert step(service, client, NOW)["status"] == "archive_unavailable"
    saved = list(store.spool.directory.glob("*.json"))
    assert len(saved) == 1 and KEY.encode() not in saved[0].read_bytes()
    pending = store.spool.load()
    original_hash = pending.receipt.original_sha256
    assert pending.receipt.credential_redacted
    assert KEY.encode() not in pending.receipt.body
    monkeypatch.setattr(WeatherRepository, "finish_page", original)
    restarted, _ = collector(store, client)
    result = step(restarted, client, NOW + timedelta(seconds=2))
    assert result["status"] == "COLLECTING" and len(client.calls) == 1
    assert not list(store.spool.directory.glob("*.json"))
    with store.repository.transaction() as db:
        assert db.scalar(select(ATTEMPTS.c.payload_sha256)) == original_hash
    assert finish(restarted, client, NOW + timedelta(seconds=3))["status"] == "COMPLETE"
    assert len(client.calls) == 4


def test_commit_before_spool_ack_replays_without_duplicate_receipt(store, monkeypatch):
    client = Client(store.factory)
    service, _ = collector(store, client)
    original = store.spool.acknowledge
    monkeypatch.setattr(
        store.spool,
        "acknowledge",
        lambda _: (_ for _ in ()).throw(OSError("synthetic ack failure")),
    )
    assert step(service, client, NOW)["status"] == "archive_unavailable"
    monkeypatch.setattr(store.spool, "acknowledge", original)
    restarted, _ = collector(store, client)
    assert step(restarted, client, NOW + timedelta(seconds=1))["status"] == "COLLECTING"
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 1
        assert db.scalar(select(func.count()).select_from(TARGETS)) == 50
    assert len(client.calls) == 1


def test_broken_spool_blocks_new_reservations_and_requests(store):
    store.spool.prepare()
    (store.spool.directory / "incomplete.tmp").write_bytes(b"incomplete receipt")
    client = Client(store.factory)
    service, _ = collector(store, client)
    assert step(service, client, NOW)["status"] == "archive_unavailable"
    assert client.calls == []
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 0


def test_key_rotation_cannot_reset_account_budget(store):
    _seed_budget(store, 899)
    client = Client(store.factory)
    changed = replace(CONFIG, api_key="b" * 32, latitude=1)
    service, _ = collector(store, client, changed)
    assert step(service, client, NOW)["status"] == "QUOTA_STOP"
    assert client.calls == []
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 899


def test_late_provider_rejection_still_blocks_account(store):
    claim = store.archive.claim_page(CONFIG, NOW)
    assert (
        store.archive.claim_page(CONFIG, NOW + timedelta(seconds=121))["status"]
        == "PARTIAL"
    )
    store.archive.finish_page(
        claim,
        now=NOW + timedelta(seconds=122),
        config=CONFIG,
        raw=b'{"error":"limited"}',
        http_status=429,
        error_code="HTTP_429",
    )
    assert (
        store.archive.claim_page(CONFIG, NOW + timedelta(minutes=10))["status"]
        == "PROVIDER_BLOCKED"
    )


def test_historical_query_excludes_current_operational_health(store):
    client = Client(store.factory)
    service, _ = collector(store, client)
    result = finish(service, client)
    health = AppHealth(900)
    health.record_weather(
        {
            "status": "COMPLETE",
            "received_at_utc": NOW + timedelta(days=1),
            "cycle_id": "future",
        }
    )
    dashboard = DashboardService(
        "test", health, repository_factory=lambda _: store.factory()
    )
    payload = dashboard.weather_archive(
        cycle_id=result["cycle_id"], as_of=NOW
    ).model_dump(mode="json")
    assert payload["collection"] == {"status": "historical_query"}
    assert payload["selected"]["targets"] == []
    assert payload["selected"]["status"] == "INCOMPLETE_AS_OF"


def test_streaming_deadline_interrupts_slow_drip_before_full_chunk():
    ticks = [0.0]
    calls = []

    class Socket:
        def settimeout(self, timeout):
            calls.append(timeout)

        def recv_into(self, buffer):
            ticks[0] += 2
            buffer[0] = 120
            return 1

    reader = io.BufferedReader(DeadlineReader(Socket(), 20, clock=lambda: ticks[0]))
    with pytest.raises(TimeoutError, match="WEATHER_RESPONSE_DEADLINE"):
        reader.read(65536)
    assert ticks[0] == 20 and len(calls) == 10 and calls[-1] == 2
    adapter = deadline_adapter(20)
    pool = adapter.poolmanager.connection_from_url(ENDPOINT)
    assert isinstance(pool, DeadlinePool) and pool._new_conn().deadline == 20
    assert adapter.max_retries.total == 0
    adapter.close()


def test_decoded_json_escape_cannot_hide_echoed_key():
    raw = ('{"echo":"' + "".join(f"\\u{ord(c):04x}" for c in KEY) + '"}').encode()
    stored, redacted = sanitized_payload(raw, KEY)
    assert redacted and KEY not in json.loads(stored)["echo"]


def test_restart_scheduler_inspects_committed_page_without_waiting_ten_minutes(
    config, store
):
    client = Client(store.factory)
    service, _ = collector(store, client)
    assert step(service, client, NOW)["status"] == "COLLECTING"
    restarted, _ = collector(store, client)
    now = [NOW + timedelta(seconds=1)]
    health = AppHealth(900)
    health.last_successful_collection_utc = NOW - timedelta(seconds=20)

    class Stop:
        def is_set(self):
            return len(client.calls) >= 2

        def wait(self, delay):
            now[0] += timedelta(seconds=delay)
            client.now = now[0]
            return self.is_set()

    coordinator = ForecastCoordinator(
        repository_factory=store.factory,
        collector_config=config,
        operations_config=ForecastOperationsConfig(enabled=False),
        health=health,
        clock=lambda: now[0],
        weather=restarted,
    )
    coordinator.run(Stop())
    assert len(client.calls) == 2 and now[0] < NOW + timedelta(seconds=5)


def test_deep_json_retained_without_losing_request_reservation(store):
    class DeepClient(Client):
        def fetch(self, **kwargs):
            self.calls.append(kwargs["start_epoch"])
            escaped_key = "".join(f"\\u{ord(c):04x}" for c in KEY)
            raw = (
                '{"next":"https://api.openweathermap.org/?appid='
                + escaped_key
                + '","nested":'
                + "[" * 1500
                + "0"
                + "]" * 1500
                + "}"
            ).encode()
            return PageResponse(200, self.now + timedelta(milliseconds=100), raw)

    client = DeepClient(store.factory)
    service, _ = collector(store, client)
    result = step(service, client, NOW)
    assert result["status"] == "PARTIAL"
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 1
        raw = db.scalar(select(PAYLOADS.c.body))
        assert b"[REDACTED]" in raw and KEY.encode() not in raw
    assert len(client.calls) == 1


def test_deadline_response_retains_socket_after_connection_close():
    receiving, sending = socket.socketpair()
    try:
        sending.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        wrapped = DeadlineSocket(receiving, time.monotonic() + 5)
        response = HTTPResponse(wrapped)
        response.begin()
        wrapped.close()
        assert response.read() == b"{}"
        response.close()
    finally:
        receiving.close()
        sending.close()


def test_final_five_page_cycle_uses_exactly_remaining_budget(store):
    _seed_budget(store, 895)

    class FortyPointClient(Client):
        def fetch(self, **kwargs):
            response = super().fetch(**kwargs)
            body = json.loads(response.raw)
            body["data"] = body["data"][:40]
            body["next"] = ENDPOINT + f"?start={body['data'][-1]['dt']+1}&appid={KEY}"
            return replace(response, raw=json.dumps(body).encode())

    client = FortyPointClient(store.factory)
    service, _ = collector(store, client)
    assert finish(service, client)["status"] == "COMPLETE"
    assert len(client.calls) == 5
    with store.repository.transaction() as db:
        assert db.scalar(select(func.count()).select_from(ATTEMPTS)) == 900
    assert step(service, client, NOW + timedelta(minutes=10))["status"] == "QUOTA_STOP"
    assert len(client.calls) == 5


def test_sanitizing_unicode_payload_cannot_inflate_spool_beyond_wire_limit():
    raw = json.dumps(
        {"next": ENDPOINT + f"?appid={KEY}", "text": "☁" * 100000}, ensure_ascii=False
    ).encode()
    safe, changed = sanitized_payload(raw, KEY)
    assert changed and len(safe) <= len(raw)
    assert json.loads(safe)["text"] == "☁" * 100000
