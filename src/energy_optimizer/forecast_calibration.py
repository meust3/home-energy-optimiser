"""Calibration metrics for genuine out-of-sample operational forecasts."""

from collections import defaultdict
from datetime import UTC, datetime
from math import sqrt
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from energy_optimizer.forecast_alignment import (
    FULL_FIVE_MINUTE_ALIGNMENT,
    LEGACY_ALIGNMENT,
    alignment_version,
)
from energy_optimizer.timestamps import aware_datetime

CalibrationStatus = Literal[
    "insufficient_data", "poor", "degraded", "acceptable", "good"
]
HORIZON_BUCKETS = ((0, 3, "0-3h"), (3, 6, "3-6h"), (6, 12, "6-12h"), (12, 24, "12-24h"))
BASELINE_REFERENCE = {
    "label": "Pre-v0.5.1 / legacy baseline",
    "bias_w": 767.0,
    "mae_w": 956.0,
    "forecast_energy_kwh": 46.9,
    "actual_energy_kwh": 27.8,
}
CURRENT_FORECAST_TYPE = "baseline_household_load"
CURRENT_FORECAST_MODEL_VERSION = "household-demand-hierarchy-v1-cohort-v1"
CURRENT_TRAINING_POLICY = "verified_preferred"


class CalibrationIdentity(BaseModel):
    """Exact forecast generation whose scores form one calibration cohort."""

    model_config = ConfigDict(frozen=True)

    forecast_type: str
    model_version: str
    alignment_version: str
    training_policy: str


class CalibrationMetric(BaseModel):
    total_points: int = 0
    eligible_points: int = 0
    coverage: float = 0
    bias_w: float | None = None
    absolute_bias_w: float | None = None
    mae_w: float | None = None
    rmse_w: float | None = None


class CompleteRunEnergyMetric(BaseModel):
    forecast_run_id: int
    forecast_energy_kwh: float
    actual_energy_kwh: float
    energy_bias_kwh: float
    energy_error_percent: float | None


class ForecastCalibrationReport(BaseModel):
    status: CalibrationStatus
    status_reason: str
    sample_period_start: datetime | None = None
    sample_period_end: datetime | None = None
    eligible_run_count: int = 0
    eligible_point_count: int = 0
    complete_run_count: int = 0
    metrics: CalibrationMetric
    metrics_by_horizon: dict[str, CalibrationMetric]
    metrics_by_local_hour: dict[str, CalibrationMetric]
    complete_run_energy: list[CompleteRunEnergyMetric] = Field(default_factory=list)
    current_identity: CalibrationIdentity
    alignment_version: str = FULL_FIVE_MINUTE_ALIGNMENT
    training_policies: list[str] = Field(default_factory=list)
    model_versions: list[str] = Field(default_factory=list)
    baseline_reference: dict[str, Any] = Field(
        default_factory=lambda: dict(BASELINE_REFERENCE)
    )
    legacy_baseline_metrics: CalibrationMetric = Field(
        default_factory=CalibrationMetric
    )
    legacy_baseline_run_count: int = 0


def calculate_forecast_calibration(
    rows: list[dict[str, Any]],
    *,
    timezone_name: str = "Australia/Brisbane",
    current_identity: CalibrationIdentity | None = None,
) -> ForecastCalibrationReport:
    """Evaluate exactly one current cohort and retain legacy comparison metrics."""
    identity = current_identity or CalibrationIdentity(
        forecast_type=CURRENT_FORECAST_TYPE,
        model_version=CURRENT_FORECAST_MODEL_VERSION,
        alignment_version=FULL_FIVE_MINUTE_ALIGNMENT,
        training_policy=CURRENT_TRAINING_POLICY,
    )
    eligible_rows = []
    legacy_rows = []
    policies: set[str] = set()
    models: set[str] = set()
    for row in rows:
        metadata = row.get("run_metadata_json") or {}
        if row.get("source") != "scheduled_forecast_operations":
            continue
        if alignment_version(metadata) == LEGACY_ALIGNMENT:
            legacy_rows.append(row)
        if not _matches_identity(row, metadata, identity):
            continue
        eligible_rows.append(row)
        policies.add(str(metadata.get("training_policy", "unknown")))
        models.add(str(row.get("model_version", "unknown")))

    overall = _metric(eligible_rows)
    legacy_metric = _metric(legacy_rows)
    by_horizon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_hour: dict[str, list[dict[str, Any]]] = defaultdict(list)
    timezone = ZoneInfo(timezone_name)
    runs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        hours = (
            aware_datetime(row["period_start_utc"])
            - aware_datetime(row["created_at_utc"])
        ).total_seconds() / 3600
        by_horizon[_horizon_bucket(hours)].append(row)
        local_hour = aware_datetime(row["period_start_utc"]).astimezone(timezone).hour
        by_hour[f"{local_hour:02d}:00"].append(row)
        runs[int(row["forecast_run_id"])].append(row)

    complete_energy = []
    for run_id, run_rows in runs.items():
        scored = [row for row in run_rows if _eligible(row)]
        if len(run_rows) != 288 or len(scored) != 288:
            continue
        forecast = sum(float(row["expected_value"]) for row in scored) / 12_000
        actual = sum(float(row["actual_value"]) for row in scored) / 12_000
        bias = forecast - actual
        complete_energy.append(
            CompleteRunEnergyMetric(
                forecast_run_id=run_id,
                forecast_energy_kwh=forecast,
                actual_energy_kwh=actual,
                energy_bias_kwh=bias,
                energy_error_percent=(bias / actual * 100 if actual else None),
            )
        )

    status, reason = _status(
        overall, complete_run_count=len(complete_energy), run_count=len(runs)
    )
    starts = [
        aware_datetime(row["period_start_utc"]).astimezone(UTC) for row in eligible_rows
    ]
    ends = [
        aware_datetime(row["period_end_utc"]).astimezone(UTC) for row in eligible_rows
    ]
    return ForecastCalibrationReport(
        status=status,
        status_reason=reason,
        sample_period_start=min(starts) if starts else None,
        sample_period_end=max(ends) if ends else None,
        eligible_run_count=len(runs),
        eligible_point_count=overall.eligible_points,
        complete_run_count=len(complete_energy),
        metrics=overall,
        metrics_by_horizon={
            name: _metric(by_horizon[name]) for _, _, name in HORIZON_BUCKETS
        },
        metrics_by_local_hour={
            name: _metric(group) for name, group in sorted(by_hour.items())
        },
        complete_run_energy=complete_energy,
        current_identity=identity,
        alignment_version=identity.alignment_version,
        training_policies=sorted(policies),
        model_versions=sorted(models),
        legacy_baseline_metrics=legacy_metric,
        legacy_baseline_run_count=len(
            {int(row["forecast_run_id"]) for row in legacy_rows}
        ),
    )


def _matches_identity(
    row: dict[str, Any], metadata: dict[str, Any], identity: CalibrationIdentity
) -> bool:
    return (
        row.get("forecast_type") == identity.forecast_type
        and row.get("model_version") == identity.model_version
        and metadata.get("alignment_version") == identity.alignment_version
        and metadata.get("training_policy") == identity.training_policy
    )


def _eligible(row: dict[str, Any]) -> bool:
    return (
        bool(row.get("actual_available") and row.get("health_eligible"))
        and row.get("actual_value") is not None
    )


def _metric(rows: list[dict[str, Any]]) -> CalibrationMetric:
    usable = [row for row in rows if _eligible(row)]
    # Stored signed_error is actual - forecast. Calibration bias is forecast - actual.
    errors = [
        float(row["expected_value"]) - float(row["actual_value"]) for row in usable
    ]
    bias = sum(errors) / len(errors) if errors else None
    return CalibrationMetric(
        total_points=len(rows),
        eligible_points=len(errors),
        coverage=(len(errors) / len(rows) * 100 if rows else 0),
        bias_w=bias,
        absolute_bias_w=abs(bias) if bias is not None else None,
        mae_w=(sum(abs(error) for error in errors) / len(errors) if errors else None),
        rmse_w=(
            sqrt(sum(error * error for error in errors) / len(errors))
            if errors
            else None
        ),
    )


def _horizon_bucket(hours: float) -> str:
    for lower, upper, name in HORIZON_BUCKETS:
        if lower <= hours < upper:
            return name
    return "24h+"


def _status(
    metric: CalibrationMetric, *, complete_run_count: int, run_count: int
) -> tuple[CalibrationStatus, str]:
    if complete_run_count < 1 or run_count < 2 or metric.coverage < 80:
        return (
            "insufficient_data",
            "At least one complete 24-hour run, two independent runs, and 80% "
            "coverage are required.",
        )
    absolute_bias = metric.absolute_bias_w or 0
    mae = metric.mae_w or 0
    if absolute_bias <= 200 and mae <= 600:
        return "good", "Project heuristic: absolute bias <= 200 W and MAE <= 600 W."
    if absolute_bias <= 300 and mae <= 750:
        return "acceptable", "Project target: absolute bias <= 300 W and MAE <= 750 W."
    if absolute_bias <= 600 and mae <= 900:
        return "degraded", "Calibration exceeds the acceptable project target."
    return "poor", "Calibration materially exceeds the project bias or MAE target."
