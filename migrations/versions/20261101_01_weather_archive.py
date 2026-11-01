"""Optional immutable weather receipts, content versions and durable call budget.

Explicit offline/reviewed migration only; this file activates no collection.
"""

from alembic import op
from sqlalchemy import MetaData

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
    from sqlalchemy import func, select

    if any(
        connection.scalar(select(func.count()).select_from(t)) for t in tables.values()
    ):
        raise RuntimeError("Weather archive is not empty; preserve it before downgrade")
    for table in reversed(tuple(tables.values())):
        table.drop(connection, checkfirst=False)
