"""Synthetic runtime priority and causal-version witnesses."""

import time
from datetime import timedelta

from sqlalchemy import func, select, text
from test_forecast_context import (
    T,
    batch,
    cache_state,
    mapping,
    save_core,
)
from test_forecast_context import context_db as context_db

from energy_optimizer.context_collection import collect_and_store_context
from energy_optimizer.context_repository import ContextRepository
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.models import WeatherContextSnapshot


def test_not_effective_mapping_does_not_open_database():
    m = mapping().model_copy(update={"effective_from_utc": T + timedelta(days=1)})

    def forbidden():
        raise AssertionError("must not open database")

    result = collect_and_store_context(
        {}, m, slot=T, receipt=T, repository_factory=forbidden
    )
    assert result == {"status": "mapping_not_effective"}


def test_content_reversion_without_new_cache_stamp_keeps_distinct_receipts(
    context_db, healthy_states, config
):
    repository, _ = context_db
    m = mapping()
    context = ContextRepository(repository)
    for i, value in enumerate([20, 21, 20]):
        receive = T + timedelta(minutes=5 * i)
        slot = save_core(repository, healthy_states, config, receive)
        context.save(
            batch(m, receipt=receive, slot=slot, weather=cache_state(value=value)),
            recorded_at=receive,
        )
    with repository.transaction() as session:
        assert (
            session.scalar(select(func.count()).select_from(WeatherContextSnapshot))
            == 3
        )


def test_actual_forecast_output_unchanged_after_context_save(
    context_db, healthy_states, config
):
    from energy_optimizer.demand_forecast import forecast_household_demand

    repository, _ = context_db
    origin = T + timedelta(days=1)
    slot = save_core(repository, healthy_states, config, T)

    def forecast():
        rows = repository.reserve_history_rows_read_only(days=30, now=origin)
        return forecast_household_demand(
            rows,
            start_local=origin,
            end_local=origin + timedelta(hours=24),
            minimum_samples=1,
            fallback_kw=2,
            training_policy="verified_preferred",
        ).model_dump(mode="json")

    before = forecast()
    ContextRepository(repository).save(
        batch(mapping(), slot=slot, weather=cache_state()), recorded_at=T
    )
    assert forecast() == before


def test_collector_main_saves_core_before_context_and_failure_cannot_stop_cycle(
    monkeypatch, healthy_states, config
):
    from tools import run_collector

    events = []
    cfg = config.model_copy(
        update={
            "context_collection_enabled": True,
            "context_mapping_json": mapping().model_dump_json(),
        }
    )

    class Store:
        def save(self, _observation):
            events.append("core_commit")
            return "saved"

        def close(self):
            events.append("close_core")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get_states(self, _ids, **_kwargs):
            events.append("one_get")
            return healthy_states

    def optional(*_args, **_kwargs):
        assert events[-1] == "core_commit"
        events.append("optional_failure")
        return {"status": "optional_failure"}

    def one_cycle(collect, *, on_success, **_kwargs):
        observation = collect()
        on_success(observation)

    monkeypatch.setattr(run_collector, "load_config", lambda: cfg)
    monkeypatch.setattr(run_collector, "ObservationStore", Store)
    monkeypatch.setattr(run_collector, "HomeAssistantClient", Client)
    monkeypatch.setattr(run_collector, "collect_and_store_context", optional)
    monkeypatch.setattr(run_collector, "run", one_cycle)
    assert run_collector.main(on_success=lambda _o: events.append("success")) == 0
    assert events == [
        "one_get",
        "core_commit",
        "optional_failure",
        "success",
        "close_core",
    ]


def test_context_database_lock_wait_is_bounded(context_db, healthy_states, config):
    repository, url = context_db
    from energy_optimizer.persistence import ApplicationRepository

    save_core(repository, healthy_states, config, T)
    blocker = repository.engine.connect()
    if repository.backend == "postgresql":
        blocker.begin()
        blocker.execute(
            text("LOCK TABLE context_observations IN ACCESS EXCLUSIVE MODE")
        )
    else:
        blocker.exec_driver_sql("BEGIN EXCLUSIVE")
    engine = create_database_engine(
        url,
        connect_timeout_seconds=1,
        statement_timeout_ms=100,
        sqlite_timeout_seconds=0.1,
    )
    started = time.monotonic()
    try:
        result = collect_and_store_context(
            {},
            mapping(),
            slot=T,
            receipt=T,
            repository_factory=lambda: ApplicationRepository(engine),
        )
    finally:
        blocker.rollback()
        blocker.close()
    assert time.monotonic() - started < 3
    assert result["status"] == "optional_failure"
    assert len(repository.observation_rows()) == 1


def test_runtime_repository_timeouts_on_both_backends(context_db):
    from energy_optimizer.context_collection import open_bounded_context_repository

    _repository, url = context_db
    bounded = open_bounded_context_repository(url)
    try:
        with bounded.engine.connect() as connection:
            if bounded.backend == "postgresql":
                assert connection.scalar(text("SHOW statement_timeout")) == "500ms"
                assert connection.scalar(text("SHOW lock_timeout")) == "500ms"
            else:
                assert connection.scalar(text("PRAGMA busy_timeout")) == 500
    finally:
        bounded.close()
