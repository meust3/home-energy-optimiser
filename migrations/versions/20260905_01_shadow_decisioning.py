"""Add immutable battery shadow decision and outcome audit tables.

Revision ID: 20260905_01
Revises: 20260814_01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from energy_optimizer.timestamps import AwareDateTime

revision = "20260905_01"
down_revision = "20260814_01"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "shadow_decision_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("decision_boundary_utc", AwareDateTime(), nullable=False),
        sa.Column("created_at_utc", AwareDateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "observation_slot_utc",
            AwareDateTime(),
            sa.ForeignKey("observations.slot_utc"),
        ),
        sa.Column(
            "forecast_run_id",
            sa.Integer(),
            sa.ForeignKey("forecast_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "reserve_run_id",
            sa.Integer(),
            sa.ForeignKey("reserve_runs.id"),
            nullable=False,
        ),
        sa.Column("forecast_type", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("alignment_version", sa.String(32), nullable=False),
        sa.Column("training_policy", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("assumption_set_version", sa.String(64), nullable=False),
        sa.Column("shadow_decisioning_enabled", sa.Boolean(), nullable=False),
        sa.Column("non_hold_selection_enabled", sa.Boolean(), nullable=False),
        sa.Column("tradable_calibrated", sa.Boolean(), nullable=False),
        sa.Column("selected_action", sa.String(64)),
        sa.Column("selected_start_utc", AwareDateTime()),
        sa.Column("selected_end_utc", AwareDateTime()),
        sa.Column("selected_power_w", sa.Float()),
        sa.Column("selected_battery_energy_kwh", sa.Float()),
        sa.Column("selected_grid_energy_kwh", sa.Float()),
        sa.Column("expected_gross_value_aud", sa.Float()),
        sa.Column("confidence_rating", sa.String(16)),
        sa.Column("confidence_score", sa.Integer()),
        sa.Column("reason_codes_json", JSON_TYPE, nullable=False),
        sa.Column("explanation_json", JSON_TYPE, nullable=False),
        sa.Column("input_snapshot_json", JSON_TYPE, nullable=False),
        sa.Column("constraint_snapshot_json", JSON_TYPE, nullable=False),
        sa.Column("assumption_snapshot_json", JSON_TYPE, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("price_horizon_end_utc", AwareDateTime()),
        sa.Column("solar_horizon_end_utc", AwareDateTime()),
        sa.Column("no_command_issued", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "decision_boundary_utc",
            "policy_version",
            name="uq_shadow_decision_boundary_policy",
        ),
        sa.CheckConstraint(
            "no_command_issued = true",
            name="ck_shadow_decision_runs_shadow_decision_no_command_true",
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'blocked')",
            name="ck_shadow_decision_runs_shadow_decision_status",
        ),
    )
    op.create_index(
        "idx_shadow_decision_created",
        "shadow_decision_runs",
        ["created_at_utc"],
    )
    op.create_index(
        "idx_shadow_decision_status_boundary",
        "shadow_decision_runs",
        ["status", "decision_boundary_utc"],
    )

    op.create_table(
        "shadow_decision_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "decision_run_id",
            sa.Integer(),
            sa.ForeignKey("shadow_decision_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("candidate_rank", sa.Integer()),
        sa.Column("feasible", sa.Boolean(), nullable=False),
        sa.Column("feasibility_reason", sa.String(128), nullable=False),
        sa.Column("blocking_constraints_json", JSON_TYPE, nullable=False),
        sa.Column("warning_constraints_json", JSON_TYPE, nullable=False),
        sa.Column("start_utc", AwareDateTime()),
        sa.Column("end_utc", AwareDateTime()),
        sa.Column("power_w", sa.Float()),
        sa.Column("battery_energy_delta_kwh", sa.Float()),
        sa.Column("grid_energy_delta_kwh", sa.Float()),
        sa.Column("gross_import_cost_aud", sa.Float()),
        sa.Column("gross_export_revenue_aud", sa.Float()),
        sa.Column("gross_avoided_import_value_aud", sa.Float()),
        sa.Column("opportunity_cost_aud", sa.Float()),
        sa.Column("gross_incremental_value_aud", sa.Float()),
        sa.Column("reserve_before_kwh", sa.Float()),
        sa.Column("reserve_margin_after_kwh", sa.Float()),
        sa.Column("battery_energy_after_kwh", sa.Float()),
        sa.Column("price_coverage_percent", sa.Float()),
        sa.Column("price_horizon_end_utc", AwareDateTime()),
        sa.Column("average_import_price_aud_per_kwh", sa.Float()),
        sa.Column("average_export_price_aud_per_kwh", sa.Float()),
        sa.Column("confidence_rating", sa.String(16), nullable=False),
        sa.Column("confidence_components_json", JSON_TYPE, nullable=False),
        sa.Column("assumptions_json", JSON_TYPE, nullable=False),
        sa.Column("ranking_score", sa.Float()),
        sa.Column("ranking_components_json", JSON_TYPE, nullable=False),
        sa.Column("tie_break_reason", sa.String(128)),
        sa.UniqueConstraint(
            "decision_run_id",
            "action",
            name="uq_shadow_candidate_run_action",
        ),
    )
    op.create_index(
        "idx_shadow_candidate_run_rank",
        "shadow_decision_candidates",
        ["decision_run_id", "candidate_rank"],
    )

    op.create_table(
        "shadow_decision_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "decision_run_id",
            sa.Integer(),
            sa.ForeignKey("shadow_decision_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scoring_version", sa.String(64), nullable=False),
        sa.Column("scored_at_utc", AwareDateTime(), nullable=False),
        sa.Column("window_start_utc", AwareDateTime(), nullable=False),
        sa.Column("window_end_utc", AwareDateTime(), nullable=False),
        sa.Column("actual_coverage_percent", sa.Float(), nullable=False),
        sa.Column("actual_price_coverage_percent", sa.Float(), nullable=False),
        sa.Column("actual_energy_coverage_percent", sa.Float(), nullable=False),
        sa.Column("observed_import_kwh", sa.Float()),
        sa.Column("observed_export_kwh", sa.Float()),
        sa.Column("observed_battery_charge_kwh", sa.Float()),
        sa.Column("observed_battery_discharge_kwh", sa.Float()),
        sa.Column("observed_household_kwh", sa.Float()),
        sa.Column("observed_pv_kwh", sa.Float()),
        sa.Column("observed_variable_energy_value_aud", sa.Float()),
        sa.Column("simulated_selected_value_aud", sa.Float()),
        sa.Column("simulated_hold_value_aud", sa.Float()),
        sa.Column("selected_vs_hold_value_aud", sa.Float()),
        sa.Column("hindsight_best_action", sa.String(64)),
        sa.Column("hindsight_best_value_aud", sa.Float()),
        sa.Column("regret_aud", sa.Float()),
        sa.Column("simulated_min_battery_energy_kwh", sa.Float()),
        sa.Column("simulated_reserve_breach", sa.Boolean()),
        sa.Column("operator_intervention_possible", sa.Boolean(), nullable=False),
        sa.Column("operator_intervention_confidence", sa.String(16), nullable=False),
        sa.Column("operator_intervention_evidence_json", JSON_TYPE, nullable=False),
        sa.Column("counterfactual_confidence", sa.String(16), nullable=False),
        sa.Column("counterfactual_limitations_json", JSON_TYPE, nullable=False),
        sa.UniqueConstraint(
            "decision_run_id", "scoring_version", name="uq_shadow_outcome_run_version"
        ),
    )
    op.create_index(
        "idx_shadow_outcome_scored",
        "shadow_decision_outcomes",
        ["scored_at_utc"],
    )


def downgrade() -> None:
    """Discard only v0.6.0 shadow history; energy/forecast/reserve data remains."""
    op.drop_index("idx_shadow_outcome_scored", table_name="shadow_decision_outcomes")
    op.drop_table("shadow_decision_outcomes")
    op.drop_index(
        "idx_shadow_candidate_run_rank",
        table_name="shadow_decision_candidates",
    )
    op.drop_table("shadow_decision_candidates")
    op.drop_index(
        "idx_shadow_decision_status_boundary",
        table_name="shadow_decision_runs",
    )
    op.drop_index("idx_shadow_decision_created", table_name="shadow_decision_runs")
    op.drop_table("shadow_decision_runs")
