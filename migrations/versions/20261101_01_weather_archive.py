"""Optional immutable weather receipts, content versions and durable call budget.

Explicit offline/reviewed migration only; this file activates no collection.
"""

from alembic import op
from sqlalchemy import MetaData, select

from energy_optimizer.weather.schema import register_weather_tables

revision = "20261101_01"
down_revision = "20261024_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = register_weather_tables(MetaData())
    for table in tables.values():
        table.create(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    # Refuse to silently discard captured history or quota reservations.
    tables = register_weather_tables(MetaData())
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        names = ", ".join(
            connection.dialect.identifier_preparer.format_table(t)
            for t in tables.values()
        )
        # Hold all six locks through checks, drops and revision update. NOWAIT
        # refuses active readers/writers before any destructive DDL can run.
        connection.exec_driver_sql(
            f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    elif connection.dialect.name == "sqlite":
        # Acquire the single-writer reservation before reading emptiness. The
        # zero-row update upgrades an already-open deferred transaction safely.
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.exec_driver_sql(
                "UPDATE alembic_version SET version_num = version_num WHERE 0"
            )
    else:
        raise RuntimeError("Weather rollback requires PostgreSQL or SQLite")

    if any(
        connection.execute(select(1).select_from(t).limit(1)).first() is not None
        for t in tables.values()
    ):
        raise RuntimeError("Weather archive is not empty; preserve it before downgrade")
    for table in reversed(tuple(tables.values())):
        table.drop(connection, checkfirst=False)
