"""Derived pending-score inventory; explicit offline maintenance migration only."""

from alembic import op
from sqlalchemy import Column, Connection, ForeignKey, Integer

from energy_optimizer.db.pending_inventory import (
    backfill_pending_inventory,
    install_inventory_triggers,
    remove_inventory_triggers,
)
from energy_optimizer.timestamps import AwareDateTime

revision = "20261024_01"
down_revision = "20261008_01"
branch_labels = None
depends_on = None


def _lock_writers(connection: Connection) -> None:
    # sqlite3 legacy transaction mode otherwise autocommits initial DDL.
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SET LOCAL lock_timeout='1s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
        connection.exec_driver_sql(
            "LOCK TABLE forecast_runs,forecast_points,forecast_point_scores "
            "IN SHARE ROW EXCLUSIVE MODE"
        )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Inventory backfill requires a connected explicit migration")
    connection = op.get_bind()
    _lock_writers(connection)
    op.create_table(
        "forecast_score_pending",
        Column(
            "forecast_point_id",
            Integer,
            ForeignKey("forecast_points.id", ondelete="CASCADE", onupdate="CASCADE"),
            primary_key=True,
        ),
        Column("period_end_utc", AwareDateTime(), nullable=False),
    )
    op.create_index(
        "idx_forecast_score_pending_due",
        "forecast_score_pending",
        ["period_end_utc", "forecast_point_id"],
    )
    install_inventory_triggers(connection)
    backfill_pending_inventory(connection)


def downgrade() -> None:
    # Only derived state is removed; forecasts, scores and observations are retained.
    if op.get_context().as_sql:
        raise RuntimeError(
            "Inventory downgrade requires a connected explicit migration"
        )
    connection = op.get_bind()
    _lock_writers(connection)
    remove_inventory_triggers(connection)
    op.drop_table("forecast_score_pending")
