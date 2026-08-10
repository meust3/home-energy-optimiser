"""Baseline the complete schema version 6 plus migration progress.

Revision ID: 20260810_01
"""

from alembic import op
from sqlalchemy import inspect

from energy_optimizer.db.models import Base

revision = "20260810_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create a fresh schema; an existing v6 SQLite database must be stamped."""
    connection = op.get_bind()
    if op.get_context().as_sql:
        for table in Base.metadata.sorted_tables:
            table.create(connection, checkfirst=False)
        return
    existing = set(inspect(connection).get_table_names())
    application_tables = set(Base.metadata.tables)
    if existing & application_tables:
        missing = application_tables - existing
        if missing == {"migration_progress"}:
            Base.metadata.tables["migration_progress"].create(connection)
            return
        if missing:
            raise RuntimeError(
                "Existing application schema detected. Run tools/adopt_database.py "
                "after validating that it is schema version 6."
            )
        return
    Base.metadata.create_all(connection)


def downgrade() -> None:
    """Downgrade is intentionally non-destructive; restore a verified backup."""
    raise RuntimeError("Baseline downgrade is destructive; restore a database backup")
