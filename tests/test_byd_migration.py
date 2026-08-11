from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect, text

from energy_optimizer.db.migrations import alembic_config, current_revision

NEW_COLUMNS = {
    "ev_vehicle_soc_percent",
    "ev_vehicle_battery_power_w_raw",
    "ev_plugged_in",
    "ev_vehicle_online",
    "ev_at_home",
    "ev_telemetry_updated_at_utc",
    "ev_telemetry_age_seconds",
    "ev_telemetry_fresh",
    "ev_vehicle_status",
}


def _url(path):
    return f"sqlite:///{path.as_posix()}"


def test_additive_vehicle_migration_preserves_legacy_observation(tmp_path):
    url = _url(tmp_path / "legacy.db")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE observations ("
                "slot_utc TEXT PRIMARY KEY, house_consumption_w FLOAT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO observations (slot_utc, house_consumption_w) "
                "VALUES (:slot, :power)"
            ),
            {"slot": datetime(2026, 8, 1, tzinfo=UTC).isoformat(), "power": 1800},
        )
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(text("INSERT INTO alembic_version VALUES ('20260810_01')"))
    engine.dispose()

    command.upgrade(alembic_config(url), "20260811_01")
    migrated = create_engine(url)
    columns = {
        column["name"] for column in inspect(migrated).get_columns("observations")
    }
    assert columns >= NEW_COLUMNS
    with migrated.connect() as connection:
        row = connection.execute(text("SELECT * FROM observations")).mappings().one()
        assert row["house_consumption_w"] == 1800
        assert all(row[name] is None for name in NEW_COLUMNS)
        assert connection.scalar(text("SELECT COUNT(*) FROM observations")) == 1
    assert current_revision(migrated) == "20260811_01"
    migrated.dispose()


def test_fresh_sqlite_upgrade_downgrade_reupgrade_is_compatible(tmp_path):
    url = _url(tmp_path / "fresh.db")
    command.upgrade(alembic_config(url), "20260811_01")
    engine = create_engine(url)
    assert _columns(engine) >= NEW_COLUMNS
    assert current_revision(engine) == "20260811_01"
    engine.dispose()

    command.downgrade(alembic_config(url), "20260810_01")
    downgraded = create_engine(url)
    assert _columns(downgraded).isdisjoint(NEW_COLUMNS)
    assert current_revision(downgraded) == "20260810_01"
    downgraded.dispose()

    command.upgrade(alembic_config(url), "20260811_01")
    reupgraded = create_engine(url)
    assert _columns(reupgraded) >= NEW_COLUMNS
    assert current_revision(reupgraded) == "20260811_01"
    reupgraded.dispose()


def test_vehicle_upgrade_downgrade_reupgrade_preserves_legacy_sqlite_data(tmp_path):
    url = _url(tmp_path / "round_trip.db")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE observations ("
                "slot_utc TEXT PRIMARY KEY, house_consumption_w FLOAT, "
                "battery_soc_percent FLOAT, baseline_training_eligible BOOLEAN, "
                "ev_charging_active BOOLEAN, ev_power_w FLOAT, ev_source TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO observations (slot_utc, house_consumption_w, "
                "battery_soc_percent, baseline_training_eligible, "
                "ev_charging_active, ev_power_w, ev_source) "
                "VALUES (:slot, :power, :soc, :eligible, :charging, :ev_power, :source)"
            ),
            {
                "slot": datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
                "power": 1800,
                "soc": 67,
                "eligible": True,
                "charging": False,
                "ev_power": None,
                "source": "none",
            },
        )
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(text("INSERT INTO alembic_version VALUES ('20260810_01')"))
    engine.dispose()

    command.upgrade(alembic_config(url), "20260811_01")
    upgraded = create_engine(url)
    assert current_revision(upgraded) == "20260811_01"
    assert _columns(upgraded) >= NEW_COLUMNS
    with upgraded.begin() as connection:
        connection.execute(
            text(
                "UPDATE observations SET ev_vehicle_soc_percent=54, "
                "ev_plugged_in=1, ev_vehicle_status='plugged_idle'"
            )
        )
    upgraded.dispose()

    command.downgrade(alembic_config(url), "20260810_01")
    downgraded = create_engine(url)
    assert current_revision(downgraded) == "20260810_01"
    assert _columns(downgraded).isdisjoint(NEW_COLUMNS)
    with downgraded.connect() as connection:
        row = connection.execute(text("SELECT * FROM observations")).mappings().one()
        assert dict(row) == {
            "slot_utc": datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
            "house_consumption_w": 1800,
            "battery_soc_percent": 67,
            "baseline_training_eligible": 1,
            "ev_charging_active": 0,
            "ev_power_w": None,
            "ev_source": "none",
        }
        assert connection.scalar(text("SELECT COUNT(*) FROM observations")) == 1
    downgraded.dispose()

    command.upgrade(alembic_config(url), "20260811_01")
    reupgraded = create_engine(url)
    assert current_revision(reupgraded) == "20260811_01"
    assert _columns(reupgraded) >= NEW_COLUMNS
    with reupgraded.connect() as connection:
        row = connection.execute(text("SELECT * FROM observations")).mappings().one()
        assert row["house_consumption_w"] == 1800
        assert row["battery_soc_percent"] == 67
        assert row["baseline_training_eligible"] == 1
        assert row["ev_charging_active"] == 0
        assert row["ev_power_w"] is None
        assert row["ev_source"] == "none"
        assert all(row[name] is None for name in NEW_COLUMNS)
        assert connection.scalar(text("SELECT COUNT(*) FROM observations")) == 1
    reupgraded.dispose()


def test_vehicle_migration_compiles_reversible_postgresql_ddl():
    output = StringIO()
    config = alembic_config(
        "postgresql+psycopg://migration_user:placeholder@example.invalid/home_energy"
    )
    config.output_buffer = output

    command.upgrade(config, "20260810_01:20260811_01", sql=True)
    command.downgrade(config, "20260811_01:20260810_01", sql=True)

    sql = output.getvalue()
    for column in NEW_COLUMNS:
        assert f"ADD COLUMN {column}" in sql
        assert f"DROP COLUMN {column}" in sql
    assert "ev_telemetry_updated_at_utc TIMESTAMP WITH TIME ZONE" in sql
    assert "DROP TABLE observations" not in sql


def test_release_runbooks_require_physical_downgrade_not_stamp():
    paths = (
        Path("README.md"),
        Path("docs/database_migration.md"),
        Path("docs/database_backup_restore.md"),
        Path("docs/byd_vehicle_integration.md"),
        Path("docs/home_assistant_app_installation.md"),
        Path("docs/home_assistant_app_troubleshooting.md"),
        Path("home_energy_optimiser/DOCS.md"),
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "alembic stamp 20260810_01" not in text
    assert "alembic downgrade 20260810_01" in text
    runbook = Path("docs/byd_vehicle_integration.md").read_text(encoding="utf-8")
    assert runbook.index("Build an image from that exact commit") < runbook.index(
        "create and restore-test"
    )


def _columns(engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("observations")}
