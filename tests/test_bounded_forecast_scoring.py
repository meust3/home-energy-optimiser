"""Synthetic regressions; PostgreSQL requires an explicitly owned local target."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from energy_optimizer.db.engine import DatabaseQueryCanceledError
from energy_optimizer.db.forecast_scoring import (
    ScoringDiagnostics,
    select_pending_ids,
)
from energy_optimizer.db.models import (
    Base,
    ForecastPoint,
    ForecastPointScore,
    ForecastRun,
)
from energy_optimizer.db.repository import DatabaseRepository

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def owned_postgres_url() -> str | None:
    """Accept only the two named disposable test endpoints, before connecting."""
    url = os.environ.get("SCORING_OWNED_TEST_URL")
    expected_target = ("127.0.0.1", 55439, "scoring_fix_test", "scoring_test")
    if not url:
        # The checked-in release workflow owns this disposable service.
        url = os.environ.get("TEST_POSTGRES_URL")
        expected_target = ("127.0.0.1", 5432, "release_test", "release_test")
        if url:
            assert os.environ.get("F1_F3_OWNED_TEST_DATABASE") == "release_test"
    if url:
        parsed = make_url(url)
        # Dialect/query/libpq settings must not redirect a destructive test reset.
        assert parsed.drivername == "postgresql+psycopg"
        assert not parsed.query
        assert not any(
            os.environ.get(key)
            for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")
        )
        assert (
            parsed.host,
            parsed.port,
            parsed.database,
            parsed.username,
        ) == expected_target
    return url


@pytest.fixture(params=["sqlite", "postgresql"])
def repo(request, tmp_path):
    if request.param == "sqlite":
        url = "sqlite:///" + str(tmp_path / "scoring.db")
    else:
        url = owned_postgres_url()
        if not url:
            pytest.skip("Explicit isolated PostgreSQL URL not supplied")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for run_id, kind in [(1, "baseline_household_load"), (2, "solar")]:
            c.execute(
                insert(ForecastRun).values(
                    id=run_id,
                    created_at_utc=NOW - timedelta(days=2),
                    forecast_type=kind,
                    source="synthetic",
                    horizon_start_utc=NOW - timedelta(days=1),
                    horizon_end_utc=NOW + timedelta(days=1),
                    model_version="synthetic",
                    metadata_json={"alignment_version": "full_5m_v1"},
                )
            )
    yield DatabaseRepository(engine)
    engine.dispose()


@pytest.mark.parametrize(
    "url,owner,accepted",
    [
        (
            "postgresql+psycopg://release_test@127.0.0.1:5432/release_test",
            "release_test",
            True,
        ),
        ("postgresql+psycopg://release_test@127.0.0.1:5432/release_test", None, False),
        (
            "postgresql+psycopg://release_test@127.0.0.1:5432/release_test",
            "other",
            False,
        ),
        (
            "postgresql+psycopg://release_test@example.invalid:5432/release_test",
            "release_test",
            False,
        ),
        (
            "postgresql+psycopg://release_test@127.0.0.1:5432/home_energy",
            "release_test",
            False,
        ),
        (
            "postgresql+psycopg://owner@127.0.0.1:5432/release_test",
            "release_test",
            False,
        ),
        (
            "postgresql+psycopg://release_test@127.0.0.1:5433/release_test",
            "release_test",
            False,
        ),
    ],
)
def test_ci_scoring_target_requires_exact_disposable_endpoint(
    monkeypatch, url, owner, accepted
):
    monkeypatch.delenv("SCORING_OWNED_TEST_URL", raising=False)
    monkeypatch.setenv("TEST_POSTGRES_URL", url)
    monkeypatch.delenv("F1_F3_OWNED_TEST_DATABASE", raising=False)
    if owner is not None:
        monkeypatch.setenv("F1_F3_OWNED_TEST_DATABASE", owner)
    if accepted:
        assert owned_postgres_url() == url
    else:
        with pytest.raises(AssertionError):
            owned_postgres_url()


@pytest.mark.parametrize(
    "suffix",
    [
        "?host=example.invalid",
        "?port=55432",
        "?dbname=other_database",
        "?user=other_role",
        "?hostaddr=192.0.2.1",
        "?service=other",
        "?options=-csearch_path=other",
        "?host=example.invalid&port=55432&dbname=other_database&user=other_role",
    ],
)
@pytest.mark.parametrize("source", ["SCORING_OWNED_TEST_URL", "TEST_POSTGRES_URL"])
def test_scoring_target_rejects_query_redirection(monkeypatch, suffix, source):
    monkeypatch.delenv("SCORING_OWNED_TEST_URL", raising=False)
    monkeypatch.delenv("TEST_POSTGRES_URL", raising=False)
    monkeypatch.setenv("F1_F3_OWNED_TEST_DATABASE", "release_test")
    target = (
        "scoring_test@127.0.0.1:55439/scoring_fix_test"
        if source == "SCORING_OWNED_TEST_URL"
        else "release_test@127.0.0.1:5432/release_test"
    )
    monkeypatch.setenv(source, "postgresql+psycopg://" + target + suffix)
    with pytest.raises(AssertionError):
        owned_postgres_url()


@pytest.mark.parametrize(
    "setting", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"]
)
def test_scoring_target_rejects_libpq_redirection(monkeypatch, setting):
    monkeypatch.setenv(
        "SCORING_OWNED_TEST_URL",
        "postgresql+psycopg://scoring_test@127.0.0.1:55439/scoring_fix_test",
    )
    monkeypatch.setenv(setting, "synthetic-override")
    with pytest.raises(AssertionError):
        owned_postgres_url()


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg2"])
def test_scoring_target_rejects_other_drivers(monkeypatch, driver):
    monkeypatch.setenv(
        "SCORING_OWNED_TEST_URL",
        driver + "://scoring_test@127.0.0.1:55439/scoring_fix_test",
    )
    with pytest.raises(AssertionError):
        owned_postgres_url()


def point(id, minutes=-60, run_id=1):
    end = NOW + timedelta(minutes=minutes)
    return dict(
        id=id,
        forecast_run_id=run_id,
        period_start_utc=end - timedelta(minutes=5),
        period_end_utc=end,
        expected_value=1000,
        unit="W",
        metadata_json={},
    )


def put(repo, points):
    with repo.engine.begin() as c:
        c.execute(insert(ForecastPoint), points)


def old_selection(session, cutoff=NOW, limit=2500):
    return list(
        session.scalars(
            select(ForecastPoint.id)
            .join(ForecastRun)
            .outerjoin(ForecastPointScore)
            .where(
                ForecastPoint.period_end_utc <= cutoff,
                ForecastPointScore.forecast_point_id.is_(None),
                ForecastRun.forecast_type == "baseline_household_load",
            )
            .order_by(ForecastPoint.period_end_utc, ForecastPoint.id)
            .limit(limit)
        )
    )


def bounded(session, limit=2500, guard=None, diagnostics=None):
    return select_pending_ids(
        session,
        cutoff=NOW,
        limit=limit,
        runtime_guard=guard,
        diagnostics=diagnostics or ScoringDiagnostics(),
    )


def test_exact_selection_sparse_boundaries_future_types_and_order(repo):
    put(
        repo,
        [
            point(0),
            point(1, 10),
            point(9999, -60),
            point(10000, -120),
            point(10001, -120),
            point(20000, -1, 2),
            point(2_000_000_000, -300),
        ],
    )
    # A persisted missing-actual score is still scored; do not retry it.
    repo.score_completed_forecast_points(now=NOW, delay_minutes=0, limit=1)
    with Session(repo.engine) as s:
        d = ScoringDiagnostics()
        assert bounded(s, diagnostics=d) == old_selection(s) == [10000, 10001, 0, 9999]
        assert d.ranges <= 4  # giant sparse ID gap is skipped by PK seek


@pytest.mark.parametrize("limit", [1, 17, 2500])
def test_global_top_k_across_ranges_and_reconsideration(repo, limit):
    put(
        repo,
        [point(i, -(i % 500) - 1) for i in range(1, 3002)]
        + [point(20000 + i, -600) for i in range(3000)],
    )
    with Session(repo.engine) as s:
        assert bounded(s, limit) == old_selection(s, limit=limit)
    assert (
        repo.score_completed_forecast_points(now=NOW, delay_minutes=0, limit=limit)
        == limit
    )
    with Session(repo.engine) as s:
        assert bounded(s, limit) == old_selection(s, limit=limit)


def test_empty_and_invalid_limit(repo):
    with Session(repo.engine) as s:
        assert bounded(s) == []
        for limit in (0, 2501):
            with pytest.raises(ValueError):
                bounded(s, limit)


def test_guard_during_selection_writes_nothing(repo):
    put(repo, [point(1), point(20000)])
    d = ScoringDiagnostics()

    def guard():
        if d.ranges:
            raise TimeoutError("synthetic selection stop")

    with pytest.raises(TimeoutError):
        repo.score_completed_forecast_points(
            now=NOW, delay_minutes=0, runtime_guard=guard, diagnostics=d
        )
    with Session(repo.engine) as s:
        assert s.scalar(select(func.count()).select_from(ForecastPointScore)) == 0
    assert d.failed and d.phase == "pending_selection"


def test_scoring_rollback_after_flush_and_forecast_immutability(repo):
    put(repo, [point(1), point(2)])
    before = repo.forecast_run(1)
    d = ScoringDiagnostics()

    def guard():
        if d.processed:
            raise TimeoutError("synthetic runtime stop")

    with pytest.raises(TimeoutError):
        repo.score_completed_forecast_points(
            now=NOW, delay_minutes=0, runtime_guard=guard, diagnostics=d
        )
    with Session(repo.engine) as s:
        assert s.scalar(select(func.count()).select_from(ForecastPointScore)) == 0
    assert repo.forecast_run(1) == before
    assert repo.score_completed_forecast_points(now=NOW, delay_minutes=0) == 2


def test_future_point_is_reconsidered_next_call(repo):
    put(repo, [point(1, 20)])
    assert repo.score_completed_forecast_points(now=NOW, delay_minutes=0) == 0
    assert (
        repo.score_completed_forecast_points(
            now=NOW + timedelta(hours=1), delay_minutes=0
        )
        == 1
    )


def test_selection_budget_fails_without_partial_result(repo, monkeypatch):
    from energy_optimizer.db import forecast_scoring as module

    put(repo, [point(1)])
    ticks = iter([0.0, 0.0, 61.0])
    d = ScoringDiagnostics()
    monkeypatch.setattr(module, "monotonic", lambda: next(ticks))
    with Session(repo.engine) as s, pytest.raises(TimeoutError, match="budget"):
        bounded(s, diagnostics=d)


def test_repeatable_snapshot_and_late_insert(repo):
    if repo.backend != "postgresql":
        pytest.skip("PostgreSQL MVCC regression")
    put(repo, [point(1), point(20000)])
    d = ScoringDiagnostics()
    changed = False

    def guard():
        nonlocal changed
        if d.ranges == 1 and not changed:
            changed = True
            put(repo, [point(2, -500), point(20001, -400)])

    with Session(repo.engine) as s:
        s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        assert bounded(s, guard=guard, diagnostics=d) == [1, 20000]
    with Session(repo.engine) as s:
        assert bounded(s) == [2, 20001, 1, 20000]


def test_real_query_timeout_diagnostics_redact_and_rollback(repo):
    if repo.backend != "postgresql":
        pytest.skip("PostgreSQL timeout regression")
    put(repo, [point(1)])
    fired = False

    def delay(conn, cursor, statement, parameters, context, executemany):
        nonlocal fired
        if not fired and statement.startswith(
            "SELECT observations.baseline_house_consumption_w"
        ):
            fired = True
            cursor.execute("SET LOCAL statement_timeout='10ms'")
            return "SELECT pg_sleep(0.1)", ()
        return statement, parameters

    event.listen(repo.engine, "before_cursor_execute", delay, retval=True)
    d = ScoringDiagnostics()
    try:
        with pytest.raises(DatabaseQueryCanceledError):
            repo.score_completed_forecast_points(
                now=NOW, delay_minutes=0, diagnostics=d
            )
    finally:
        event.remove(repo.engine, "before_cursor_execute", delay)
    assert fired and d.sqlstate == "57014" and d.phase == "actual_lookup" and d.failed
    data = json.dumps(d.snapshot())
    assert (
        "pg_sleep" not in data and "scoring_test" not in data and "SELECT" not in data
    )
    with Session(repo.engine) as s:
        assert s.scalar(select(func.count()).select_from(ForecastPointScore)) == 0


def test_diagnostics_do_not_include_exception_text():
    from energy_optimizer.db.forecast_scoring import scoring_trace

    d = ScoringDiagnostics()
    d.enter("payload_fetch")
    with pytest.raises(RuntimeError), scoring_trace(d):
        raise RuntimeError("postgresql+psycopg://secret@host/household secret-payload")
    first = d.snapshot()
    assert first == d.snapshot()
    assert "secret" not in json.dumps(first)


def test_repository_uses_snapshot_and_does_not_skip_late_points(repo):
    if repo.backend != "postgresql":
        pytest.skip("PostgreSQL MVCC regression")
    put(repo, [point(1), point(20000)])
    d = ScoringDiagnostics()
    changed = False

    def guard():
        nonlocal changed
        if d.ranges == 1 and not changed:
            changed = True
            put(repo, [point(2, -500), point(20001, -400)])

    assert (
        repo.score_completed_forecast_points(
            now=NOW, delay_minutes=0, runtime_guard=guard, diagnostics=d
        )
        == 2
    )
    with Session(repo.engine) as session:
        assert set(session.scalars(select(ForecastPointScore.forecast_point_id))) == {
            1,
            20000,
        }
    assert repo.score_completed_forecast_points(now=NOW, delay_minutes=0) == 2
