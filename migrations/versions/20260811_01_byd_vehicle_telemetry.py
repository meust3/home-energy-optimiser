"""Add privacy-minimized read-only vehicle telemetry to observations.

Revision ID: 20260811_01
Revises: 20260810_01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from energy_optimizer.timestamps import AwareDateTime

revision = "20260811_01"
down_revision = "20260810_01"
branch_labels = None
depends_on = None


VEHICLE_COLUMNS = (
    sa.Column("ev_vehicle_soc_percent", sa.Float(), nullable=True),
    sa.Column("ev_vehicle_battery_power_w_raw", sa.Float(), nullable=True),
    sa.Column("ev_plugged_in", sa.Boolean(), nullable=True),
    sa.Column("ev_vehicle_online", sa.Boolean(), nullable=True),
    sa.Column("ev_at_home", sa.Boolean(), nullable=True),
    sa.Column("ev_telemetry_updated_at_utc", AwareDateTime(), nullable=True),
    sa.Column("ev_telemetry_age_seconds", sa.Float(), nullable=True),
    sa.Column("ev_telemetry_fresh", sa.Boolean(), nullable=True),
    sa.Column("ev_vehicle_status", sa.Text(), nullable=True),
)


def upgrade() -> None:
    """Add nullable columns only; existing observations remain unchanged."""
    connection = op.get_bind()
    existing = (
        set()
        if op.get_context().as_sql
        else {
            column["name"] for column in inspect(connection).get_columns("observations")
        }
    )
    for column in VEHICLE_COLUMNS:
        if column.name not in existing:
            op.add_column("observations", column)


def downgrade() -> None:
    """Remove only v0.4.0 vehicle fields; collected EV telemetry is discarded."""
    connection = op.get_bind()
    existing = (
        {column.name for column in VEHICLE_COLUMNS}
        if op.get_context().as_sql
        else {
            column["name"] for column in inspect(connection).get_columns("observations")
        }
    )
    for column in reversed(VEHICLE_COLUMNS):
        if column.name in existing:
            op.drop_column("observations", column.name)
