"""Inventory invariants on synthetic SQLite / explicitly owned PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete, event, func, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_bounded_forecast_scoring import NOW, bounded, old_selection, point, put
from test_bounded_forecast_scoring import repo as repo

from energy_optimizer.db import pending_inventory
from energy_optimizer.db.forecast_scoring import ScoringSelectionBudgetExceeded
from energy_optimizer.db.migrations import alembic_config, current_revision
from energy_optimizer.db.models import (
    ForecastPoint,
    ForecastPointScore,
    ForecastRun,
    ForecastScorePending,
)
from energy_optimizer.forecast_operations import _safe_failure


def inventory(connection):
    return list(
        connection.scalars(
            select(ForecastScorePending.forecast_point_id).order_by(
                ForecastScorePending.forecast_point_id
            )
        )
    )


def assert_matches(repo):
    with Session(repo.engine) as session:
        assert bounded(session) == old_selection(session)


def test_raw_sql_updates_scores_types_and_retention(repo):
    # Unlike the old helper, verify SQLite cascade semantics with FKs enabled.
    if repo.backend == "sqlite":
        with repo.engine.connect() as c:
            c.exec_driver_sql("PRAGMA foreign_keys=ON")
    put(repo, [point(1), point(2), point(3, run_id=2), point(4, 60)])
    with repo.engine.begin() as c:
        assert inventory(c) == [1, 2, 4]
        c.execute(
            update(ForecastPoint)
            .where(ForecastPoint.id == 2)
            .values(id=20, period_end_utc=NOW - timedelta(minutes=10))
        )
        c.execute(
            update(ForecastPoint)
            .where(ForecastPoint.id == 4)
            .values(period_end_utc=NOW - timedelta(minutes=120))
        )
    assert_matches(repo)
    assert repo.score_completed_forecast_points(now=NOW, delay_minutes=0, limit=1) == 1
    with repo.engine.begin() as c:
        assert inventory(c) == [1, 20]
        c.execute(
            update(ForecastPointScore)
            .where(ForecastPointScore.forecast_point_id == 4)
            .values(forecast_point_id=1)
        )
        assert inventory(c) == [4, 20]
        c.execute(
            delete(ForecastPointScore).where(ForecastPointScore.forecast_point_id == 1)
        )
        assert inventory(c) == [1, 4, 20]
        c.execute(
            update(ForecastRun)
            .where(ForecastRun.id == 2)
            .values(forecast_type="baseline_household_load")
        )
        assert inventory(c) == [1, 3, 4, 20]
        c.execute(
            update(ForecastRun).where(ForecastRun.id == 1).values(forecast_type="solar")
        )
        assert inventory(c) == [3]
        c.execute(
            update(ForecastPoint)
            .where(ForecastPoint.id == 20)
            .values(forecast_run_id=2)
        )
        assert inventory(c) == [3, 20]
    assert_matches(repo)
    assert repo.score_completed_forecast_points(now=NOW, delay_minutes=0) == 2
    # Both FK cascade and the repository's explicit score-then-point deletion.
    with repo.engine.begin() as c:
        c.execute(delete(ForecastPoint).where(ForecastPoint.id == 3))
        c.execute(
            delete(ForecastPointScore).where(ForecastPointScore.forecast_point_id == 20)
        )
        assert inventory(c) == [20]
        c.execute(delete(ForecastPoint).where(ForecastPoint.id == 20))
        assert inventory(c) == []


def test_rollback_after_score_trigger_preserves_pending_and_restart(repo):
    put(repo, [point(i) for i in range(1, 8)])
    from energy_optimizer.db.forecast_scoring import ScoringDiagnostics

    diagnostics = ScoringDiagnostics()

    def stop():
        if diagnostics.processed == 3:
            raise TimeoutError("synthetic interruption after dequeues")

    with pytest.raises(TimeoutError):
        repo.score_completed_forecast_points(
            now=NOW, delay_minutes=0, diagnostics=diagnostics, runtime_guard=stop
        )
    repo.engine.dispose()  # New physical connection; no in-memory recovery cursor.
    with repo.engine.connect() as c:
        assert inventory(c) == list(range(1, 8))
        assert c.scalar(select(func.count()).select_from(ForecastPointScore)) == 0
    for expected in (3, 3, 1, 0):
        assert (
            repo.score_completed_forecast_points(now=NOW, delay_minutes=0, limit=3)
            == expected
        )
    with repo.engine.connect() as c:
        assert inventory(c) == []
        assert c.scalar(select(func.count()).select_from(ForecastPointScore)) == 7


def test_empty_derived_schema_fails_instead_of_silently_skipping(repo):
    put(repo, [point(1)])
    with repo.engine.begin() as c:
        pending_inventory.remove_inventory_triggers(c)
        ForecastScorePending.__table__.drop(c)
    with Session(repo.engine) as s, pytest.raises(DBAPIError):
        bounded(s)


def test_backfill_includes_all_unscored_future_and_sparse_ids(repo, monkeypatch):
    put(
        repo,
        [
            point(1),
            point(2),
            point(1_000_000, -500),
            point(2_000_000_000, 60),
            point(5, run_id=2),
        ],
    )
    repo.score_completed_forecast_points(now=NOW, delay_minutes=0, limit=1)
    with repo.engine.begin() as c:
        pending_inventory.remove_inventory_triggers(c)
        c.execute(delete(ForecastScorePending))
    # Fail after first inserted batch and verify transaction rollback, then retry.
    ticks = iter([0, 0, 121])
    monkeypatch.setattr(pending_inventory, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError), repo.engine.begin() as c:
        pending_inventory.backfill_pending_inventory(c)
    with repo.engine.connect() as c:
        assert inventory(c) == []
    monkeypatch.setattr(pending_inventory, "monotonic", lambda: 0)
    with repo.engine.begin() as c:
        assert pending_inventory.backfill_pending_inventory(c) == 3
        pending_inventory.install_inventory_triggers(c)
        assert inventory(c) == [1, 2, 2_000_000_000]
    assert_matches(repo)


@pytest.mark.parametrize("history", [0, 10_000])
def test_one_indexed_selection_query_independent_of_scored_history(repo, history):
    if history:
        put(repo, [point(i) for i in range(1, history + 1)])
        with repo.engine.begin() as c:
            c.execute(
                insert(ForecastPointScore),
                [
                    dict(
                        forecast_point_id=i,
                        scored_at_utc=NOW,
                        actual_available=False,
                        health_eligible=False,
                        metadata_json={},
                    )
                    for i in range(1, history + 1)
                ],
            )
    put(repo, [point(history + i, -i) for i in range(1, 21)])
    queries = []

    def record(_c, _cursor, statement, _params, _context, _many):
        queries.append(statement)

    event.listen(repo.engine, "before_cursor_execute", record)
    try:
        with Session(repo.engine) as s:
            assert bounded(s, limit=5) == list(range(history + 20, history + 15, -1))
    finally:
        event.remove(repo.engine, "before_cursor_execute", record)
    assert len(queries) == 1
    assert "forecast_score_pending" in queries[0]
    assert "forecast_points " not in queries[0]
    assert "forecast_point_scores" not in queries[0]


def test_truncate_rejected_and_schema_qualified_functions(repo):
    if repo.backend != "postgresql":
        pytest.skip("PostgreSQL trigger security / TRUNCATE semantics")
    put(repo, [point(1)])
    repo.score_completed_forecast_points(now=NOW, delay_minutes=0)
    for table in ("forecast_point_scores", "forecast_score_pending"):
        with (
            pytest.raises(DBAPIError, match="invalidate pending"),
            repo.engine.begin() as c,
        ):
            c.exec_driver_sql(f"TRUNCATE {table}")
    with repo.engine.begin() as c:
        c.exec_driver_sql(
            "CREATE TEMP TABLE forecast_score_pending(forecast_point_id int)"
        )
        c.execute(delete(ForecastPointScore))
        assert c.scalar(text("SELECT count(*) FROM public.forecast_score_pending")) == 1
        assert (
            c.scalar(text("SELECT count(*) FROM pg_temp.forecast_score_pending")) == 0
        )
        c.exec_driver_sql("DROP TABLE pg_temp.forecast_score_pending")
        rows = c.execute(
            text(
                "SELECT prosecdef,proconfig FROM pg_proc "
                "WHERE proname LIKE 'score_pending_%_v1'"
            )
        ).all()
        assert rows and all(
            not r[0] and r[1] == ["search_path=pg_catalog"] for r in rows
        )


def test_concurrent_workers_cannot_duplicate_or_lose_scores(repo):
    if repo.backend != "postgresql":
        pytest.skip("PostgreSQL row-lock / snapshot semantics")
    from energy_optimizer.db.engine import DatabaseTransactionError
    from energy_optimizer.db.forecast_scoring import ScoringDiagnostics

    put(repo, [point(i) for i in range(1, 11)])
    selected, release = Event(), Event()
    diagnostics = ScoringDiagnostics()

    def hold():
        if diagnostics.selected and not selected.is_set():
            selected.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            repo.score_completed_forecast_points,
            now=NOW,
            delay_minutes=0,
            diagnostics=diagnostics,
            runtime_guard=hold,
        )
        assert selected.wait(10)
        second = pool.submit(
            repo.score_completed_forecast_points, now=NOW, delay_minutes=0
        )
        release.set()
        assert first.result(timeout=15) == 10
        with suppress(DatabaseTransactionError):
            assert second.result(timeout=15) == 0
        # A stale REPEATABLE READ worker may serialize-fail; next cycle retries.
    assert repo.score_completed_forecast_points(now=NOW, delay_minutes=0) == 0
    with repo.engine.connect() as c:
        assert inventory(c) == []
        assert c.scalar(select(func.count()).select_from(ForecastPointScore)) == 10


def test_selection_timeout_has_distinct_credential_safe_failure_summary():
    assert _safe_failure(ScoringSelectionBudgetExceeded("secret")) == (
        "Forecast scoring selection budget exceeded"
    )
    assert (
        _safe_failure(TimeoutError("secret")) == "Configured forecast runtime exceeded"
    )


def test_sqlite_alembic_ddl_timeout_atomic_and_retry(tmp_path, monkeypatch):
    from energy_optimizer.db.engine import create_database_engine

    url = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    cfg = alembic_config(url)
    command.upgrade(cfg, "20261008_01")
    engine = create_database_engine(url)
    with engine.begin() as c:
        c.execute(
            insert(ForecastRun).values(
                id=1,
                created_at_utc=NOW,
                forecast_type="baseline_household_load",
                source="synthetic",
                horizon_start_utc=NOW,
                horizon_end_utc=NOW + timedelta(days=1),
                model_version="synthetic",
                metadata_json={},
            )
        )
        c.execute(insert(ForecastPoint), [point(1), point(2, 60)])
    ticks = iter([0, 0, 121])
    monkeypatch.setattr(pending_inventory, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        command.upgrade(cfg, "head")
    assert current_revision(engine) == "20261008_01"
    assert "forecast_score_pending" not in inspect(engine).get_table_names()
    with engine.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'score_pending_%'"
                )
            )
            == 0
        )
        assert c.scalar(select(func.count()).select_from(ForecastPoint)) == 2
    monkeypatch.setattr(pending_inventory, "monotonic", lambda: 0)
    command.upgrade(cfg, "head")
    assert current_revision(engine) == "20261024_01"
    with engine.connect() as c:
        assert inventory(c) == [1, 2]
    from alembic import op

    def interrupted_drop(_name):
        raise RuntimeError("synthetic interruption after trigger removal")

    with monkeypatch.context() as patch:
        patch.setattr(op, "drop_table", interrupted_drop)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            command.downgrade(cfg, "20261008_01")
    assert current_revision(engine) == "20261024_01"
    with engine.connect() as c:
        assert inventory(c) == [1, 2]
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'score_pending_%'"
                )
            )
            == 6
        )
    command.downgrade(cfg, "20261008_01")
    assert "forecast_score_pending" not in inspect(engine).get_table_names()
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(ForecastPoint)) == 2
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert inventory(c) == [1, 2]
    engine.dispose()


def test_postgresql_migration_atomic_backfill_lock_timeout_and_retry(repo, monkeypatch):
    if repo.backend != "postgresql":
        pytest.skip("PostgreSQL transactional migration semantics")
    from energy_optimizer.db.engine import create_database_engine

    schema = "scoring_migration_forecast_points_" + uuid4().hex
    # URL/ownership already checked by the shared isolated test fixture.
    with repo.engine.begin() as c:
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    url = repo.engine.url.update_query_dict({"options": f"-csearch_path={schema}"})
    cfg = alembic_config(url.render_as_string(hide_password=False))
    engine = create_database_engine(url.render_as_string(hide_password=False))
    try:
        command.upgrade(cfg, "20261008_01")
        with engine.begin() as c:
            c.execute(
                insert(ForecastRun).values(
                    id=1,
                    created_at_utc=NOW,
                    forecast_type="baseline_household_load",
                    source="synthetic",
                    horizon_start_utc=NOW,
                    horizon_end_utc=NOW + timedelta(days=1),
                    model_version="synthetic",
                    metadata_json={},
                )
            )
            c.execute(insert(ForecastPoint), [point(1), point(2, 60)])
        ticks = iter([0, 0, 121])
        monkeypatch.setattr(pending_inventory, "monotonic", lambda: next(ticks))
        with pytest.raises(TimeoutError):
            command.upgrade(cfg, "head")
        assert current_revision(engine) == "20261008_01"
        assert "forecast_score_pending" not in inspect(engine).get_table_names()
        with engine.connect() as c:
            assert (
                c.scalar(
                    text(
                        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid=p.pronamespace WHERE n.nspname=current_schema() "
                        "AND p.proname LIKE 'score_pending_%_v1'"
                    )
                )
                == 0
            )
        monkeypatch.setattr(pending_inventory, "monotonic", lambda: 0)
        with engine.begin() as blocker:
            blocker.exec_driver_sql("LOCK TABLE forecast_points IN ROW EXCLUSIVE MODE")
            with pytest.raises(DBAPIError) as error:
                command.upgrade(cfg, "head")
            assert error.value.orig.sqlstate == "55P03"
        assert current_revision(engine) == "20261008_01"
        assert "forecast_score_pending" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")
        assert current_revision(engine) == "20261024_01"
        with engine.connect() as c:
            assert inventory(c) == [1, 2]
        with engine.begin() as blocker:
            blocker.exec_driver_sql("LOCK TABLE forecast_points IN ROW EXCLUSIVE MODE")
            with pytest.raises(DBAPIError) as error:
                command.downgrade(cfg, "20261008_01")
            assert error.value.orig.sqlstate == "55P03"
        assert current_revision(engine) == "20261024_01"
        with engine.connect() as c:
            assert inventory(c) == [1, 2]
        command.downgrade(cfg, "20261008_01")
        assert "forecast_score_pending" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            assert inventory(c) == [1, 2]
            c.execute(delete(ForecastPoint).where(ForecastPoint.id == 1))
            assert inventory(c) == [2]
            # Roll back this probe; preserved original forecasts remain unchanged.
    finally:
        engine.dispose()
        with repo.engine.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def test_postgresql_selection_query_interruption_recovers_without_loss(repo):
    if repo.backend != "postgresql":
        pytest.skip("PostgreSQL server-side selection timeout")
    from energy_optimizer.db.engine import DatabaseQueryCanceledError
    from energy_optimizer.db.forecast_scoring import ScoringDiagnostics

    put(repo, [point(1), point(2)])

    def cancel(_c, cursor, statement, parameters, _context, _many):
        if statement.startswith("SELECT forecast_score_pending.forecast_point_id"):
            cursor.execute("SET LOCAL statement_timeout='10ms'")
            return "SELECT pg_sleep(0.1)", ()
        return statement, parameters

    diagnostics = ScoringDiagnostics()
    event.listen(repo.engine, "before_cursor_execute", cancel, retval=True)
    try:
        with pytest.raises(DatabaseQueryCanceledError):
            repo.score_completed_forecast_points(
                now=NOW, delay_minutes=0, diagnostics=diagnostics
            )
    finally:
        event.remove(repo.engine, "before_cursor_execute", cancel)
    assert diagnostics.phase == "pending_selection" and diagnostics.sqlstate == "57014"
    with repo.engine.connect() as c:
        assert inventory(c) == [1, 2]
        assert c.scalar(select(func.count()).select_from(ForecastPointScore)) == 0
    assert repo.score_completed_forecast_points(now=NOW, delay_minutes=0) == 2
