"""Alembic revision inspection and conservative legacy SQLite adoption."""

from enum import StrEnum
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

ALEMBIC_HEAD = "20260813_01"
LEGACY_SCHEMA_VERSION = 6


class SchemaRevisionStatus(StrEnum):
    """Compatibility between a database revision and this application head."""

    CURRENT = "schema_current"
    OUTDATED = "schema_outdated"
    AHEAD = "schema_ahead"
    UNVERSIONED = "schema_unversioned"


def alembic_config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("script_location", str(Path("migrations")))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def expected_revision() -> str:
    return ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()


def current_revision(engine: Engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def schema_revision_status(
    current: str | None, expected: str | None = None
) -> SchemaRevisionStatus:
    """Classify a revision without assuming an unknown revision is safe to upgrade."""
    wanted = expected or expected_revision()
    if current is None:
        return SchemaRevisionStatus.UNVERSIONED
    if current == wanted:
        return SchemaRevisionStatus.CURRENT

    script = ScriptDirectory.from_config(alembic_config("sqlite://"))
    ordered_revisions = [revision.revision for revision in script.walk_revisions()]
    if current in ordered_revisions and wanted in ordered_revisions:
        if ordered_revisions.index(current) > ordered_revisions.index(wanted):
            return SchemaRevisionStatus.OUTDATED
        return SchemaRevisionStatus.AHEAD

    # A revision unknown to this source may come from newer code or a divergent
    # branch. Treat it as ahead/incompatible instead of suggesting a blind upgrade.
    return SchemaRevisionStatus.AHEAD


def upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
