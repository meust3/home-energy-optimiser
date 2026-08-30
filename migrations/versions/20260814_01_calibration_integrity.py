"""Add independent-slot calibration evidence to forecast accuracy rollups.

Revision ID: 20260814_01
Revises: 20260813_01
"""

import sqlalchemy as sa
from alembic import op

from energy_optimizer.timestamps import AwareDateTime

revision = "20260814_01"
down_revision = "20260813_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column(
            "unique_target_slots", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "eligible_target_slots", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "date_unique_target_slots", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "date_eligible_target_slots",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "expected_target_slots", sa.Integer(), nullable=False, server_default="288"
        ),
        sa.Column(
            "target_slot_coverage_percent",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("slot_sum_actual_w", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "slot_sum_forecast_w", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "slot_sum_signed_error_w", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "slot_sum_absolute_error_w", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "slot_sum_squared_error_w2", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "cumulative_signed_energy_error_kwh",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cumulative_underforecast_kwh",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "complete_day", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("minimum_target_utc", AwareDateTime()),
        sa.Column("maximum_target_utc", AwareDateTime()),
        sa.Column("calculated_at_utc", AwareDateTime()),
    )
    with op.batch_alter_table("forecast_accuracy_rollups") as batch:
        for column in columns:
            batch.add_column(column)


def downgrade() -> None:
    """Remove only v0.5.2 rollup evidence; forecast detail remains unchanged."""
    names = (
        "calculated_at_utc",
        "maximum_target_utc",
        "minimum_target_utc",
        "complete_day",
        "cumulative_underforecast_kwh",
        "cumulative_signed_energy_error_kwh",
        "slot_sum_squared_error_w2",
        "slot_sum_absolute_error_w",
        "slot_sum_signed_error_w",
        "slot_sum_forecast_w",
        "slot_sum_actual_w",
        "target_slot_coverage_percent",
        "expected_target_slots",
        "date_eligible_target_slots",
        "date_unique_target_slots",
        "eligible_target_slots",
        "unique_target_slots",
    )
    with op.batch_alter_table("forecast_accuracy_rollups") as batch:
        for name in names:
            batch.drop_column(name)
