"""Immutable arbitrage evidence; manual migration only, no historical reconstruction."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from energy_optimizer.timestamps import AwareDateTime

revision = "20261008_01"
down_revision = "20261005_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "arbitrage_input_captures",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("origin", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("captured_at_utc", AwareDateTime(), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column(
            "body", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
    )
    op.create_index(
        "idx_arbitrage_capture_asof",
        "arbitrage_input_captures",
        ["kind", "captured_at_utc"],
    )
    op.create_table(
        "arbitrage_commit_witnesses",
        sa.Column(
            "capture_id",
            sa.String(64),
            sa.ForeignKey("arbitrage_input_captures.id"),
            primary_key=True,
        ),
        sa.Column("confirmed_at_utc", AwareDateTime(), nullable=False),
    )


def downgrade():
    # Destructive evidence deletion is never an automatic recovery path.
    op.drop_table("arbitrage_commit_witnesses")
    op.drop_table("arbitrage_input_captures")
