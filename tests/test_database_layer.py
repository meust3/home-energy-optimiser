from datetime import UTC, timedelta

import pytest
from sqlalchemy import create_engine, delete, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from energy_optimizer.collector import build_observation
from energy_optimizer.db.models import Base, Observation
from energy_optimizer.db.redaction import display_database_url, redact_database_urls
from energy_optimizer.db.repository import DatabaseRepository, DuplicateResult
from energy_optimizer.db.transfer import transfer, validate
from energy_optimizer.historian import Historian
from energy_optimizer.persistence import open_repository


def test_database_url_display_and_exception_redaction_hide_password():
    value = "postgresql+psycopg://energy_dev:s3cr%40t@nas:5432/home_energy_dev"
    display = display_database_url(value)
    assert "energy_dev" in display
    assert "nas" in display
    assert "home_energy_dev" in display
    assert "s3cr" not in display
    redacted = redact_database_urls(f"failed at {value}")
    assert "s3cr" not in redacted
    assert "***" in redacted


def test_invalid_url_error_cannot_echo_password():
    with pytest.raises(ValueError, match="credentials redacted") as error:
        display_database_url("not-a-database-url-containing-secret")
    assert "secret" not in str(error.value)


def test_models_compile_for_postgresql_with_jsonb_and_timestamptz():
    sql = str(CreateTable(Observation.__table__).compile(dialect=postgresql.dialect()))
    assert "JSONB" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert Observation.__table__.primary_key.columns.keys() == ["slot_utc"]


def test_sqlite_repository_upserts_and_preserves_json_and_nulls(
    healthy_states, config, now
):
    engine = create_engine(f"sqlite:///{config.database_path}")
    repository = DatabaseRepository(engine)
    repository.create_schema_for_tests()
    observation = build_observation(healthy_states, config, observed_at=now)
    assert repository.save_observation(observation) == DuplicateResult.INSERTED
    assert repository.save_observation(observation) == DuplicateResult.UPDATED
    rows = repository.observation_rows()
    assert len(rows) == 1
    assert rows[0]["slot_utc"].replace(tzinfo=UTC) == observation.slot_utc
    assert rows[0]["slot_utc"].tzinfo is not None
    assert rows[0]["observed_at_utc"].tzinfo is not None
    assert (
        rows[0]["observed_at_local"].utcoffset()
        == observation.observed_at_local.utcoffset()
    )
    assert rows[0]["temperature_c"] is None
    assert isinstance(rows[0]["amber_import_forecast_json"], list)
    assert repository.duplicate_slot_count() == 0
    engine.dispose()


def test_foreign_keys_and_business_uniqueness_present():
    point_fks = list(Base.metadata.tables["forecast_points"].foreign_keys)
    assert {str(item.column) for item in point_fks} == {"forecast_runs.id"}
    derivation = Base.metadata.tables["observation_derivations"]
    unique_names = {constraint.name for constraint in derivation.constraints}
    assert "uq_derivation_business_key" in unique_names


def test_transfer_is_dry_run_first_idempotent_and_validated(
    healthy_states, config, now, tmp_path
):
    source_path = tmp_path / "source.db"
    source_historian = Historian(source_path)
    source_historian.save(build_observation(healthy_states, config, observed_at=now))
    source = create_engine(f"sqlite:///{source_path}")
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    DatabaseRepository(target).create_schema_for_tests()

    dry_run = transfer(
        source,
        target,
        source_id="a" * 64,
        batch_size=1,
        apply=False,
        resume=False,
    )
    assert dry_run["summary"] == "PASS"
    assert DatabaseRepository(target).table_counts().observations == 0

    applied = transfer(
        source,
        target,
        source_id="a" * 64,
        batch_size=1,
        apply=True,
        resume=False,
    )
    assert applied["summary"] == "PASS"
    assert validate(source, target)["summary"] == "PASS"

    repeated = transfer(
        source,
        target,
        source_id="a" * 64,
        batch_size=1,
        apply=True,
        resume=True,
    )
    assert repeated["summary"] == "PASS", repeated
    assert DatabaseRepository(target).table_counts().observations == 1
    source.dispose()
    target.dispose()


def test_source_preserved_validation_allows_extra_later_observation(
    healthy_states, config, now, tmp_path
):
    source_path = tmp_path / "source-subset.db"
    Historian(source_path).save(
        build_observation(healthy_states, config, observed_at=now)
    )
    source = create_engine(f"sqlite:///{source_path}")
    target = create_engine(f"sqlite:///{tmp_path / 'target-superset.db'}")
    repository = DatabaseRepository(target)
    repository.create_schema_for_tests()
    transfer(
        source, target, source_id="b" * 64, batch_size=10, apply=True, resume=False
    )
    repository.save_observation(
        build_observation(
            healthy_states, config, observed_at=now + timedelta(minutes=5)
        )
    )

    assert validate(source, target, validation_mode="exact")["summary"] == "FAIL"
    preserved = validate(source, target, validation_mode="source-preserved")
    assert preserved["summary"] == "PASS"
    assert preserved["observation_preservation"]["extra_target_rows"] == 1
    assert (
        preserved["observation_preservation"]["source_subset_raw_hash_status"] == "PASS"
    )
    source.dispose()
    target.dispose()


def test_source_preserved_validation_rejects_changed_or_missing_source_row(
    healthy_states, config, now, tmp_path
):
    source_path = tmp_path / "source-conflict.db"
    Historian(source_path).save(
        build_observation(healthy_states, config, observed_at=now)
    )
    source = create_engine(f"sqlite:///{source_path}")
    target = create_engine(f"sqlite:///{tmp_path / 'target-conflict.db'}")
    DatabaseRepository(target).create_schema_for_tests()
    transfer(
        source, target, source_id="c" * 64, batch_size=10, apply=True, resume=False
    )
    observations = Base.metadata.tables["observations"]
    with target.begin() as connection:
        connection.execute(update(observations).values(pv_power_w=999999))
    conflict = validate(source, target, validation_mode="source-preserved")
    assert conflict["summary"] == "FAIL"
    assert (
        conflict["table_preservation"]["observations"]["conflicting_source_rows"] == 1
    )
    with target.begin() as connection:
        connection.execute(delete(observations))
    missing = validate(source, target, validation_mode="source-preserved")
    assert missing["summary"] == "FAIL"
    assert missing["table_preservation"]["observations"]["missing_source_rows"] == 1
    source.dispose()
    target.dispose()


def test_postgresql_database_url_never_falls_back_to_sqlite(monkeypatch, tmp_path):
    fallback = tmp_path / "must-not-exist.db"
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://energy_dev:secret@127.0.0.1:1/home_energy_dev",
    )
    monkeypatch.setenv("DATABASE_PATH", str(fallback))
    repository = open_repository()
    try:
        assert repository.backend == "postgresql"
        assert repository.database_name == "home_energy_dev"
        assert "secret" not in repository.target_display
        assert not fallback.exists()
    finally:
        repository.close()
