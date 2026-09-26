"""Cover pending forecast scoring without scanning full point payloads.

Revision ID: 20260927_01
Revises: 20260905_01

Apply only in a controlled maintenance window. This ordinary transactional index
build can block forecast-point writes. No data is rewritten or deleted.
"""

from alembic import op

revision = "20260927_01"
down_revision = "20260905_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_forecast_points_scoring",
        "forecast_points",
        ["id", "period_end_utc", "forecast_run_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_forecast_points_scoring", table_name="forecast_points")
