"""Add v0.5.1 forecast accuracy rollups and maintenance audit.

Revision ID: 20260813_01
Revises: 20260812_01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from energy_optimizer.timestamps import AwareDateTime

revision = "20260813_01"
down_revision = "20260812_01"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "forecast_accuracy_rollups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rollup_date", sa.Date(), nullable=False),
        sa.Column("forecast_type", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("alignment_version", sa.String(32), nullable=False),
        sa.Column("training_policy", sa.String(32), nullable=False),
        sa.Column("horizon_bucket", sa.String(16), nullable=False),
        sa.Column("day_type", sa.String(16), nullable=False),
        sa.Column("eligible_points", sa.Integer(), nullable=False),
        sa.Column("missing_points", sa.Integer(), nullable=False),
        sa.Column("total_points", sa.Integer(), nullable=False),
        sa.Column("sum_signed_error", sa.Float(), nullable=False),
        sa.Column("sum_absolute_error", sa.Float(), nullable=False),
        sa.Column("sum_squared_error", sa.Float(), nullable=False),
        sa.Column("forecast_energy_kwh", sa.Float(), nullable=False),
        sa.Column("actual_energy_kwh", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "rollup_date",
            "forecast_type",
            "model_version",
            "alignment_version",
            "training_policy",
            "horizon_bucket",
            "day_type",
            name="uq_forecast_accuracy_rollup_dimensions",
        ),
    )
    op.create_index(
        "idx_forecast_accuracy_rollup_date",
        "forecast_accuracy_rollups",
        ["rollup_date"],
    )
    op.create_table(
        "forecast_maintenance_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("boundary_date", sa.Date(), nullable=False),
        sa.Column("started_at_utc", AwareDateTime(), nullable=False),
        sa.Column("finished_at_utc", AwareDateTime()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rows_rolled_up", sa.Integer(), nullable=False),
        sa.Column("scores_deleted", sa.Integer(), nullable=False),
        sa.Column("points_deleted", sa.Integer(), nullable=False),
        sa.Column("runs_deleted", sa.Integer(), nullable=False),
        sa.Column("reserve_runs_deleted", sa.Integer(), nullable=False),
        sa.Column("attempts_deleted", sa.Integer(), nullable=False),
        sa.Column("metadata_json", JSON_TYPE, nullable=False),
        sa.UniqueConstraint(
            "operation", "boundary_date", name="uq_forecast_maintenance_boundary"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_forecast_maintenance_runs_forecast_maintenance_status",
        ),
    )
    op.create_index(
        "idx_forecast_maintenance_started",
        "forecast_maintenance_runs",
        ["started_at_utc"],
    )


def downgrade() -> None:
    """Remove only v0.5.1 aggregate/maintenance data."""
    op.drop_index(
        "idx_forecast_maintenance_started", table_name="forecast_maintenance_runs"
    )
    op.drop_table("forecast_maintenance_runs")
    op.drop_index(
        "idx_forecast_accuracy_rollup_date", table_name="forecast_accuracy_rollups"
    )
    op.drop_table("forecast_accuracy_rollups")
