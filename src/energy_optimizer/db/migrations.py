"""Alembic revision inspection and conservative legacy SQLite adoption."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

ALEMBIC_HEAD = "20260811_01"
LEGACY_SCHEMA_VERSION = 6


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


def upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
