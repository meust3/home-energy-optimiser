"""Add forecast operations, separate scoring, and full reserve audit tables.

Revision ID: 20260812_01
Revises: 20260811_01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from energy_optimizer.timestamps import AwareDateTime

revision = "20260812_01"
down_revision = "20260811_01"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "forecast_point_scores",
        sa.Column(
            "forecast_point_id",
            sa.Integer(),
            sa.ForeignKey("forecast_points.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scored_at_utc", AwareDateTime(), nullable=False),
        sa.Column("actual_value", sa.Float()),
        sa.Column("absolute_error", sa.Float()),
        sa.Column("signed_error", sa.Float()),
        sa.Column("squared_error", sa.Float()),
        sa.Column("actual_available", sa.Boolean(), nullable=False),
        sa.Column("health_eligible", sa.Boolean(), nullable=False),
        sa.Column("missing_reason", sa.Text()),
        sa.Column("metadata_json", JSON_TYPE, nullable=False),
    )
    op.create_index(
        "idx_forecast_scores_scored_at",
        "forecast_point_scores",
        ["scored_at_utc"],
    )

    op.create_table(
        "reserve_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "forecast_run_id",
            sa.Integer(),
            sa.ForeignKey("forecast_runs.id"),
            nullable=False,
        ),
        sa.Column("evaluation_timestamp_utc", AwareDateTime(), nullable=False),
        sa.Column("observation_timestamp_utc", AwareDateTime(), nullable=False),
        sa.Column("observation_source", sa.String(16), nullable=False),
        sa.Column("observation_age_seconds", sa.Float(), nullable=False),
        sa.Column("observation_is_stale", sa.Boolean(), nullable=False),
        sa.Column("battery_soc_percent", sa.Float()),
        sa.Column("battery_energy_kwh", sa.Float()),
        sa.Column("usable_battery_capacity_kwh", sa.Float(), nullable=False),
        sa.Column("forecast_start_utc", AwareDateTime(), nullable=False),
        sa.Column("forecast_end_utc", AwareDateTime(), nullable=False),
        sa.Column("forecast_horizon_minutes", sa.Float(), nullable=False),
        sa.Column("forecast_horizon_hours", sa.Float(), nullable=False),
        sa.Column("household_demand_kwh", sa.Float(), nullable=False),
        sa.Column("ev_demand_kwh", sa.Float(), nullable=False),
        sa.Column("technical_reserve_kwh", sa.Float(), nullable=False),
        sa.Column("emergency_reserve_kwh", sa.Float(), nullable=False),
        sa.Column("uncertainty_buffer_kwh", sa.Float(), nullable=False),
        sa.Column("gross_reserve_requirement_kwh", sa.Float(), nullable=False),
        sa.Column("capacity_capped_reserve_kwh", sa.Float(), nullable=False),
        sa.Column("unmet_reserve_requirement_kwh", sa.Float(), nullable=False),
        sa.Column("current_reserve_shortfall_kwh", sa.Float(), nullable=False),
        sa.Column("recommended_reserve_kwh", sa.Float(), nullable=False),
        sa.Column("potentially_tradable_kwh", sa.Float()),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("ready_for_manual_review", sa.Boolean(), nullable=False),
        sa.Column("opportunity_state", sa.String(40), nullable=False),
        sa.Column("first_candidate_json", JSON_TYPE, nullable=False),
        sa.Column("effective_boundary_json", JSON_TYPE),
        sa.Column("skipped_candidate_count", sa.Integer(), nullable=False),
        sa.Column("expected_replenishment_kwh", sa.Float()),
        sa.Column("command_issued", sa.Boolean(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("reasons_json", JSON_TYPE, nullable=False),
        sa.Column("confidence_json", JSON_TYPE, nullable=False),
        sa.Column("health_json", JSON_TYPE, nullable=False),
        sa.Column("operational_context_json", JSON_TYPE, nullable=False),
        sa.Column("demand_forecast_json", JSON_TYPE, nullable=False),
        sa.Column("estimate_json", JSON_TYPE, nullable=False),
        sa.CheckConstraint(
            "command_issued = false", name="ck_reserve_runs_reserve_command_false"
        ),
    )
    op.create_index(
        "idx_reserve_runs_evaluation", "reserve_runs", ["evaluation_timestamp_utc"]
    )
    op.create_index("idx_reserve_runs_forecast", "reserve_runs", ["forecast_run_id"])

    op.create_table(
        "reserve_opportunity_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "reserve_run_id",
            sa.Integer(),
            sa.ForeignKey("reserve_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("opportunity_json", JSON_TYPE, nullable=False),
        sa.Column("analysis_json", JSON_TYPE, nullable=False),
        sa.UniqueConstraint(
            "reserve_run_id",
            "sequence_number",
            name="uq_reserve_opportunity_sequence",
        ),
    )
    op.create_index(
        "idx_reserve_opportunities_run",
        "reserve_opportunity_evaluations",
        ["reserve_run_id"],
    )

    op.create_table(
        "forecast_operation_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("scheduled_for_utc", AwareDateTime(), nullable=False),
        sa.Column("started_at_utc", AwareDateTime(), nullable=False),
        sa.Column("finished_at_utc", AwareDateTime()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("forecast_run_id", sa.Integer(), sa.ForeignKey("forecast_runs.id")),
        sa.Column("reserve_run_id", sa.Integer(), sa.ForeignKey("reserve_runs.id")),
        sa.Column("forecast_point_count", sa.Integer(), nullable=False),
        sa.Column("failure_summary", sa.String(500)),
        sa.Column("metadata_json", JSON_TYPE, nullable=False),
        sa.UniqueConstraint(
            "operation", "scheduled_for_utc", name="uq_forecast_attempt_boundary"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped')",
            name="ck_forecast_operation_attempts_forecast_attempt_status",
        ),
    )
    op.create_index(
        "idx_forecast_attempts_started",
        "forecast_operation_attempts",
        ["started_at_utc"],
    )
    op.create_index(
        "idx_forecast_attempts_status",
        "forecast_operation_attempts",
        ["status", "scheduled_for_utc"],
    )


def downgrade() -> None:
    """Remove only v0.5.0 operations/audit data; observations are untouched."""
    op.drop_index(
        "idx_forecast_attempts_status", table_name="forecast_operation_attempts"
    )
    op.drop_index(
        "idx_forecast_attempts_started", table_name="forecast_operation_attempts"
    )
    op.drop_table("forecast_operation_attempts")
    op.drop_index(
        "idx_reserve_opportunities_run", table_name="reserve_opportunity_evaluations"
    )
    op.drop_table("reserve_opportunity_evaluations")
    op.drop_index("idx_reserve_runs_forecast", table_name="reserve_runs")
    op.drop_index("idx_reserve_runs_evaluation", table_name="reserve_runs")
    op.drop_table("reserve_runs")
    op.drop_index("idx_forecast_scores_scored_at", table_name="forecast_point_scores")
    op.drop_table("forecast_point_scores")
