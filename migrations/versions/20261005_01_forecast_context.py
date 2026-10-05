"""Add optional context batches and immutable received weather snapshots.

Local candidate only. Manual approved migration required before release;
never applied automatically by collection or App startup.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from energy_optimizer.timestamps import AwareDateTime

revision = "20261005_01"
down_revision = "20260927_01"
branch_labels = None
depends_on = None


def upgrade():
    body_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "context_observations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "slot_utc",
            AwareDateTime(),
            sa.ForeignKey("observations.slot_utc"),
            nullable=False,
        ),
        sa.Column("received_at_utc", AwareDateTime(), nullable=False),
        sa.Column("recorded_at_utc", AwareDateTime(), nullable=False),
        sa.Column("mapping_hash", sa.String(64), nullable=False),
        sa.Column("body", body_type, nullable=False),
    )
    op.create_index(
        "ix_context_observations_recorded_at_utc",
        "context_observations",
        ["recorded_at_utc"],
    )
    op.create_table(
        "weather_context_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("semantic_hash", sa.String(64), nullable=False),
        sa.Column("received_at_utc", AwareDateTime(), nullable=False),
        sa.Column("recorded_at_utc", AwareDateTime(), nullable=False),
        sa.Column("body", body_type, nullable=False),
    )
    op.create_index(
        "idx_weather_context_asof",
        "weather_context_snapshots",
        ["source_key", "recorded_at_utc"],
    )


def downgrade():
    # Deliberate manual destructive downgrade only, never an application fallback.
    op.drop_table("context_observations")
    op.drop_table("weather_context_snapshots")
