"""Audited repair of derived fields for invalid negative household demand."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update

from energy_optimizer.data_validation import (
    INVALID_ACTUAL_NEGATIVE_HOUSEHOLD_DEMAND,
    INVALID_NEGATIVE_HOUSEHOLD_DEMAND,
    MATERIAL_NEGATIVE_HOUSEHOLD_DEMAND_W,
)
from energy_optimizer.db.models import (
    ForecastAccuracyRollup,
    ForecastPoint,
    ForecastPointScore,
    ForecastRun,
    Observation,
    ObservationDerivation,
)

MODEL_VERSION = "negative-household-demand-validation-v1"


def reclassify_invalid_household_demand(
    repository: Any,
    *,
    apply: bool = False,
    backup_verified: bool = False,
    timezone_name: str = "Australia/Brisbane",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dry-run by default; applying requires an explicit verified-backup claim."""
    if apply and not backup_verified:
        raise ValueError("--apply requires --backup-verified")
    threshold = MATERIAL_NEGATIVE_HOUSEHOLD_DEMAND_W
    with repository.transaction() as session:
        observations = list(
            session.scalars(
                select(Observation)
                .where(Observation.house_consumption_w < threshold)
                .order_by(Observation.slot_utc)
            )
        )
        slots = [row.slot_utc for row in observations]
        affected_score_ids = (
            list(
                session.scalars(
                    select(ForecastPointScore.forecast_point_id)
                    .join(
                        ForecastPoint,
                        ForecastPoint.id == ForecastPointScore.forecast_point_id,
                    )
                    .join(
                        ForecastRun,
                        ForecastRun.id == ForecastPoint.forecast_run_id,
                    )
                    .where(
                        ForecastPoint.period_start_utc.in_(slots),
                        ForecastRun.forecast_type == "baseline_household_load",
                    )
                )
            )
            if slots
            else []
        )
    report = {
        "mode": "apply" if apply else "dry_run",
        "threshold_w": threshold,
        "affected_observations": len(observations),
        "affected_scores": len(affected_score_ids),
        "raw_household_demand_preserved": True,
    }
    if not apply or not observations:
        return report
    changed = 0
    audit_at = (now or datetime.now(UTC)).astimezone(UTC)
    dates = {
        row.slot_utc.astimezone(ZoneInfo(timezone_name)).date() for row in observations
    }
    with repository.transaction() as session:
        apply_rows = list(
            session.scalars(
                select(Observation)
                .where(Observation.slot_utc.in_(slots))
                .order_by(Observation.slot_utc)
            )
        )
        for row in apply_rows:
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "slot": row.slot_utc.astimezone(UTC).isoformat(),
                        "raw": row.house_consumption_w,
                        "rule": threshold,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            exists = session.scalar(
                select(ObservationDerivation.id).where(
                    ObservationDerivation.slot_utc == row.slot_utc,
                    ObservationDerivation.model_version == MODEL_VERSION,
                    ObservationDerivation.input_fingerprint == fingerprint,
                )
            )
            if exists is None:
                session.add(
                    ObservationDerivation(
                        slot_utc=row.slot_utc,
                        derived_at_utc=audit_at,
                        model_version=MODEL_VERSION,
                        input_fingerprint=fingerprint,
                        conventions_json={"material_negative_threshold_w": threshold},
                        previous_derived_json={
                            "baseline_house_consumption_w": (
                                row.baseline_house_consumption_w
                            ),
                            "baseline_training_eligible": (
                                row.baseline_training_eligible
                            ),
                            "baseline_exclusion_reason": row.baseline_exclusion_reason,
                            "telemetry_is_healthy": row.telemetry_is_healthy,
                            "is_healthy": row.is_healthy,
                        },
                        result_derived_json={
                            "baseline_house_consumption_w": None,
                            "baseline_training_eligible": False,
                            "baseline_exclusion_reason": (
                                INVALID_NEGATIVE_HOUSEHOLD_DEMAND
                            ),
                            "telemetry_is_healthy": False,
                            "is_healthy": False,
                        },
                        originally_legacy=bool(row.originally_legacy),
                    )
                )
            if (
                row.baseline_exclusion_reason != INVALID_NEGATIVE_HOUSEHOLD_DEMAND
                or row.baseline_house_consumption_w is not None
                or row.baseline_training_eligible
                or row.telemetry_is_healthy
                or row.is_healthy
            ):
                row.baseline_house_consumption_w = None
                row.baseline_training_eligible = False
                row.baseline_exclusion_reason = INVALID_NEGATIVE_HOUSEHOLD_DEMAND
                row.telemetry_is_healthy = False
                row.is_healthy = False
                row.reprocessed_at_utc = audit_at
                row.derivation_model_version = MODEL_VERSION
                changed += 1
        if affected_score_ids:
            session.execute(
                update(ForecastPointScore)
                .where(ForecastPointScore.forecast_point_id.in_(affected_score_ids))
                .values(
                    health_eligible=False,
                    absolute_error=None,
                    signed_error=None,
                    squared_error=None,
                    missing_reason=INVALID_ACTUAL_NEGATIVE_HOUSEHOLD_DEMAND,
                )
            )
        if dates:
            session.execute(
                delete(ForecastAccuracyRollup).where(
                    ForecastAccuracyRollup.rollup_date.in_(dates)
                )
            )
    return {
        **report,
        "changed_observations": changed,
        "invalidated_rollup_dates": sorted(d.isoformat() for d in dates),
    }
