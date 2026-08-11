import os
import uuid

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import make_url

from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.migrations import alembic_config
from tools.check_database import check_database


@pytest.fixture(params=("sqlite", "postgresql"))
def revision_database_url(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite+pysqlite:///{(tmp_path / 'readiness.db').as_posix()}"
        return

    configured = os.getenv("TEST_POSTGRES_URL")
    if not configured:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL compatibility")
    schema = f"check_database_{uuid.uuid4().hex}"
    admin_engine = create_database_engine(configured)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    parsed = make_url(configured)
    query = dict(parsed.query)
    existing_options = query.get("options", "").strip()
    query["options"] = " ".join(
        value for value in (existing_options, f"-csearch_path={schema}") if value
    )
    isolated_url = parsed.set(query=query).render_as_string(hide_password=False)
    try:
        yield isolated_url
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_v041_schema_reports_clean_migration_required_failure(revision_database_url):
    command.upgrade(alembic_config(revision_database_url), "20260811_01")

    report = check_database(revision_database_url, application_readiness=True)

    assert report["connectivity"] is True
    assert report["current_revision"] == "20260811_01"
    assert report["expected_revision"] == "20260812_01"
    assert report["schema_status"] == "schema_outdated"
    assert report["migration_required"] is True
    assert report["summary"] == "FAIL"
    assert "Alembic upgrade is required" in report["reason"]
    assert "error" not in report
    assert "forecast_point_scores" not in report["table_counts"]
    assert set(report["table_counts"]) >= {
        "observations",
        "forecast_runs",
        "forecast_points",
        "observation_derivations",
        "ev_session_annotations",
        "ev_session_annotation_rows",
    }
    assert "application_readiness" not in report


def test_v050_schema_reports_healthy(revision_database_url):
    command.upgrade(alembic_config(revision_database_url), "head")

    report = check_database(revision_database_url, application_readiness=True)

    assert report["current_revision"] == "20260812_01"
    assert report["schema_status"] == "schema_current"
    assert report["migration_required"] is False
    assert report["summary"] == "PASS"
    assert "reason" not in report
    assert report["table_counts"]["forecast_point_scores"] == 0
    assert all(
        capability["status"] == "PASS"
        for capability in report["application_readiness"].values()
    )


def test_missing_v050_table_is_reported_without_querying_it(revision_database_url):
    command.upgrade(alembic_config(revision_database_url), "head")
    engine = create_database_engine(revision_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE forecast_point_scores"))
    engine.dispose()

    report = check_database(revision_database_url, application_readiness=True)

    assert report["current_revision"] == "20260812_01"
    assert report["schema_status"] == "table_missing_unexpectedly"
    assert report["migration_required"] is False
    assert report["missing_tables"] == ["forecast_point_scores"]
    assert report["summary"] == "FAIL"
    assert "required tables are missing" in report["reason"]
    assert "error" not in report
    assert "forecast_point_scores" not in report["table_counts"]


def test_unversioned_schema_is_distinguished(revision_database_url):
    engine = create_database_engine(revision_database_url)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE observations (slot_utc TEXT PRIMARY KEY)")
        )
    engine.dispose()

    report = check_database(revision_database_url)

    assert report["current_revision"] is None
    assert report["schema_status"] == "schema_unversioned"
    assert report["migration_required"] is True
    assert report["summary"] == "FAIL"
    assert report["table_counts"] == {"observations": 0}
    assert "error" not in report


def test_unknown_newer_revision_is_distinguished_as_ahead(revision_database_url):
    command.upgrade(alembic_config(revision_database_url), "head")
    engine = create_database_engine(revision_database_url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='20260813_01'"))
    engine.dispose()

    report = check_database(revision_database_url)

    assert report["current_revision"] == "20260813_01"
    assert report["schema_status"] == "schema_ahead"
    assert report["migration_required"] is False
    assert report["summary"] == "FAIL"
    assert "ahead of or unknown" in report["reason"]
    assert "error" not in report
