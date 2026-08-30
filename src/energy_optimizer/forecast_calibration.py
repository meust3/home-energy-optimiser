"""Calibration metrics for genuine out-of-sample operational forecasts.

Raw prediction metrics deliberately remain separate from calibration evidence.
For evidence, overlapping predictions for the same target slot and horizon bucket
are averaged first, so one physical outcome cannot masquerade as many samples.
"""

from collections import defaultdict
from datetime import UTC, date, datetime
from math import ceil, sqrt
from statistics import median
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
    "insufficient_data", "provisional", "poor", "degraded", "acceptable", "good"
]
HORIZON_BUCKETS = ((0, 3, "0-3h"), (3, 6, "3-6h"), (6, 12, "6-12h"), (12, 24, "12-24h"))
HORIZON_NAMES = tuple(item[2] for item in HORIZON_BUCKETS)
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
    wape_percent: float | None = None
    forecast_energy_kwh: float | None = None
    actual_energy_kwh: float | None = None
    signed_energy_error_kwh: float | None = None


class CompleteRunEnergyMetric(BaseModel):
    forecast_run_id: int
    forecast_energy_kwh: float
    actual_energy_kwh: float
    energy_bias_kwh: float
    energy_error_percent: float | None


class IndependentDayMetric(BaseModel):
    local_date: date
    day_type: str
    eligible_target_slots: int
    expected_target_slots: int
    coverage_percent: float
    complete: bool
    cumulative_signed_energy_error_kwh: float
    cumulative_underforecast_kwh: float


class ForecastCalibrationReport(BaseModel):
    status: CalibrationStatus
    status_reason: str
    sample_period_start: datetime | None = None
    sample_period_end: datetime | None = None
    requested_period_start: datetime | None = None
    requested_period_end: datetime | None = None
    actual_period_start: datetime | None = None
    actual_period_end: datetime | None = None
    truncated: bool = False
    eligible_run_count: int = 0
    eligible_point_count: int = 0
    complete_run_count: int = 0
    raw_prediction_row_count: int = 0
    eligible_score_row_count: int = 0
    independent_target_horizon_slot_count: int = 0
    unique_actual_target_slot_count: int = 0
    eligible_actual_target_slot_count: int = 0
    distinct_local_date_count: int = 0
    rollup_row_count: int = 0
    calculated_rollup_row_count: int = 0
    expected_rollup_row_count: int = 0
    rollup_completeness_percent: float = 0
    complete_date_count: int = 0
    complete_weekday_count: int = 0
    complete_weekend_count: int = 0
    required_complete_dates: int = 7
    required_complete_day_coverage_percent: float = 95
    independent_evidence_sufficient: bool = False
    required_horizons_present: bool = False
    quality_blocks: list[str] = Field(default_factory=list)
    metrics: CalibrationMetric
    raw_row_metrics: CalibrationMetric = Field(default_factory=CalibrationMetric)
    metrics_by_horizon: dict[str, CalibrationMetric]
    metrics_by_local_hour: dict[str, CalibrationMetric]
    independent_days: list[IndependentDayMetric] = Field(default_factory=list)
    median_cumulative_underforecast_kwh: float | None = None
    p90_cumulative_underforecast_kwh: float | None = None
    p95_cumulative_underforecast_kwh: float | None = None
    cumulative_underforecast_kwh: float | None = None
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


def current_calibration_identity() -> CalibrationIdentity:
    return CalibrationIdentity(
        forecast_type=CURRENT_FORECAST_TYPE,
        model_version=CURRENT_FORECAST_MODEL_VERSION,
        alignment_version=FULL_FIVE_MINUTE_ALIGNMENT,
        training_policy=CURRENT_TRAINING_POLICY,
    )


def calculate_forecast_calibration(
    rows: list[dict[str, Any]],
    *,
    timezone_name: str = "Australia/Brisbane",
    current_identity: CalibrationIdentity | None = None,
    minimum_complete_dates: int = 7,
    complete_day_coverage_percent: float = 95,
    minimum_weekday_dates: int = 5,
    minimum_weekend_dates: int = 1,
    requested_start: datetime | None = None,
    requested_end: datetime | None = None,
    truncated: bool = False,
) -> ForecastCalibrationReport:
    identity = current_identity or current_calibration_identity()
    eligible_rows: list[dict[str, Any]] = []
    legacy_rows: list[dict[str, Any]] = []
    policies: set[str] = set()
    models: set[str] = set()
    for row in rows:
        metadata = row.get("run_metadata_json") or {}
        if row.get("source") != "scheduled_forecast_operations":
            continue
        if alignment_version(metadata) == LEGACY_ALIGNMENT:
            legacy_rows.append(row)
        if _matches_identity(row, metadata, identity):
            eligible_rows.append(row)
            policies.add(str(metadata.get("training_policy", "unknown")))
            models.add(str(row.get("model_version", "unknown")))

    timezone = ZoneInfo(timezone_name)
    raw = _metric(eligible_rows)
    run_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        run_groups[int(row["forecast_run_id"])].append(row)
    complete_energy: list[CompleteRunEnergyMetric] = []
    for run_id, run_rows in run_groups.items():
        usable = [row for row in run_rows if _eligible(row)]
        if len(run_rows) != 288 or len(usable) != 288:
            continue
        forecast_energy = sum(float(row["expected_value"]) for row in usable) / 12_000
        actual_energy = sum(float(row["actual_value"]) for row in usable) / 12_000
        energy_bias = forecast_energy - actual_energy
        complete_energy.append(
            CompleteRunEnergyMetric(
                forecast_run_id=run_id,
                forecast_energy_kwh=forecast_energy,
                actual_energy_kwh=actual_energy,
                energy_bias_kwh=energy_bias,
                energy_error_percent=(
                    energy_bias / actual_energy * 100 if actual_energy else None
                ),
            )
        )
    slot_rows = _slot_weighted_rows(eligible_rows, timezone)
    overall = _metric(slot_rows)
    by_horizon = {
        name: _metric([r for r in slot_rows if r["horizon_bucket"] == name])
        for name in HORIZON_NAMES
    }
    by_hour: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in slot_rows:
        local = aware_datetime(row["period_start_utc"]).astimezone(timezone)
        by_hour[f"{local.hour:02d}:00"].append(row)

    expected = 288 * len(HORIZON_NAMES)
    horizon_threshold = ceil(288 * complete_day_coverage_percent / 100)
    day_groups: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in slot_rows:
        day_groups[row["local_date"]].append(row)
    days: list[IndependentDayMetric] = []
    for local_date, group in sorted(day_groups.items()):
        usable = [r for r in group if _eligible(r)]
        horizon_signed_kwh = [
            sum(
                (float(r["actual_value"]) - float(r["expected_value"])) / 12_000
                for r in usable
                if r["horizon_bucket"] == name
            )
            for name in HORIZON_NAMES
        ]
        signed_kwh = sum(horizon_signed_kwh) / len(HORIZON_NAMES)
        coverage = len(usable) / expected * 100
        complete = all(
            sum(r["horizon_bucket"] == name and _eligible(r) for r in group)
            >= horizon_threshold
            for name in HORIZON_NAMES
        )
        days.append(
            IndependentDayMetric(
                local_date=local_date,
                day_type="weekend" if local_date.weekday() >= 5 else "weekday",
                eligible_target_slots=len(usable),
                expected_target_slots=expected,
                coverage_percent=coverage,
                complete=complete,
                cumulative_signed_energy_error_kwh=signed_kwh,
                cumulative_underforecast_kwh=max(signed_kwh, 0),
            )
        )
    complete_days = [d for d in days if d.complete]
    weekdays = sum(d.day_type == "weekday" for d in complete_days)
    weekends = sum(d.day_type == "weekend" for d in complete_days)
    horizons_present = all(
        sum(
            1
            for d in complete_days
            if any(
                r["local_date"] == d.local_date
                and r["horizon_bucket"] == name
                and _eligible(r)
                for r in slot_rows
            )
        )
        >= minimum_complete_dates
        for name in HORIZON_NAMES
    )
    independent = (
        len(complete_days) >= minimum_complete_dates
        and weekdays >= minimum_weekday_dates
        and weekends >= minimum_weekend_dates
        and horizons_present
    )
    blocks = []
    if truncated:
        blocks.append("calibration_query_truncated")
    if len(complete_days) < minimum_complete_dates:
        blocks.append("insufficient_complete_dates")
    if weekdays < minimum_weekday_dates:
        blocks.append("insufficient_weekday_dates")
    if weekends < minimum_weekend_dates:
        blocks.append("insufficient_weekend_dates")
    if not horizons_present:
        blocks.append("required_horizons_missing")
    status, reason = _status(
        overall, evidence=independent and not blocks, has_evidence=bool(complete_days)
    )
    under = [d.cumulative_underforecast_kwh for d in complete_days]
    targets = {
        aware_datetime(row["period_start_utc"]).astimezone(UTC) for row in slot_rows
    }
    eligible_targets = {
        aware_datetime(row["period_start_utc"]).astimezone(UTC)
        for row in slot_rows
        if _eligible(row)
    }
    date_horizon_groups = {
        (row["local_date"], row["horizon_bucket"]) for row in slot_rows
    }
    expected_rollups = len(days) * len(HORIZON_NAMES)
    starts = [
        aware_datetime(r["period_start_utc"]).astimezone(UTC) for r in eligible_rows
    ]
    ends = [aware_datetime(r["period_end_utc"]).astimezone(UTC) for r in eligible_rows]
    return ForecastCalibrationReport(
        status=status,
        status_reason=reason,
        sample_period_start=min(starts) if starts else None,
        sample_period_end=max(ends) if ends else None,
        requested_period_start=requested_start,
        requested_period_end=requested_end,
        actual_period_start=min(starts) if starts else None,
        actual_period_end=max(ends) if ends else None,
        truncated=truncated,
        eligible_run_count=len({int(r["forecast_run_id"]) for r in eligible_rows}),
        eligible_point_count=overall.eligible_points,
        complete_run_count=len(complete_energy),
        raw_prediction_row_count=raw.total_points,
        eligible_score_row_count=raw.eligible_points,
        independent_target_horizon_slot_count=overall.total_points,
        unique_actual_target_slot_count=len(targets),
        eligible_actual_target_slot_count=len(eligible_targets),
        distinct_local_date_count=len(days),
        rollup_row_count=len(date_horizon_groups),
        calculated_rollup_row_count=len(date_horizon_groups),
        expected_rollup_row_count=expected_rollups,
        rollup_completeness_percent=(
            len(date_horizon_groups) / expected_rollups * 100 if expected_rollups else 0
        ),
        complete_date_count=len(complete_days),
        complete_weekday_count=weekdays,
        complete_weekend_count=weekends,
        required_complete_dates=minimum_complete_dates,
        required_complete_day_coverage_percent=complete_day_coverage_percent,
        independent_evidence_sufficient=independent,
        required_horizons_present=horizons_present,
        quality_blocks=blocks,
        metrics=overall,
        raw_row_metrics=raw,
        metrics_by_horizon=by_horizon,
        metrics_by_local_hour={k: _metric(v) for k, v in sorted(by_hour.items())},
        independent_days=days,
        complete_run_energy=complete_energy,
        median_cumulative_underforecast_kwh=median(under) if under else None,
        p90_cumulative_underforecast_kwh=_percentile(under, 0.90),
        p95_cumulative_underforecast_kwh=_percentile(under, 0.95),
        cumulative_underforecast_kwh=sum(under) if under else None,
        current_identity=identity,
        alignment_version=identity.alignment_version,
        training_policies=sorted(policies),
        model_versions=sorted(models),
        legacy_baseline_metrics=_metric(legacy_rows),
        legacy_baseline_run_count=len({int(r["forecast_run_id"]) for r in legacy_rows}),
    )


def calculate_forecast_calibration_from_rollups(
    rows: list[dict[str, Any]],
    *,
    current_identity: CalibrationIdentity | None = None,
    minimum_complete_dates: int = 7,
    complete_day_coverage_percent: float = 95,
    minimum_weekday_dates: int = 5,
    minimum_weekend_dates: int = 1,
    requested_start: datetime | None = None,
    requested_end: datetime | None = None,
    truncated: bool = False,
) -> ForecastCalibrationReport:
    """Build the dashboard report from durable aggregates, never capped detail."""
    identity = current_identity or current_calibration_identity()
    cohort = [
        r
        for r in rows
        if r.get("forecast_type") == identity.forecast_type
        and r.get("model_version") == identity.model_version
        and r.get("alignment_version") == identity.alignment_version
        and r.get("training_policy") == identity.training_policy
    ]
    by_horizon = {
        name: _rollup_metric([r for r in cohort if r.get("horizon_bucket") == name])
        for name in HORIZON_NAMES
    }
    dates: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in cohort:
        dates[row["rollup_date"]].append(row)
    day_metrics = []
    unique_actual_targets = 0
    eligible_actual_targets = 0
    for day, group in sorted(dates.items()):
        horizons = {r["horizon_bucket"] for r in group if bool(r.get("complete_day"))}
        eligible = sum(int(r.get("eligible_target_slots") or 0) for r in group)
        expected = 288 * len(HORIZON_NAMES)
        complete = set(HORIZON_NAMES).issubset(horizons)
        signed_by_horizon = [
            sum(
                float(r.get("cumulative_signed_energy_error_kwh") or 0)
                for r in group
                if r.get("horizon_bucket") == name
            )
            for name in HORIZON_NAMES
        ]
        signed = sum(signed_by_horizon) / len(HORIZON_NAMES)
        unique_actual_targets += max(
            (int(r.get("date_unique_target_slots") or 0) for r in group),
            default=0,
        )
        eligible_actual_targets += max(
            (int(r.get("date_eligible_target_slots") or 0) for r in group),
            default=0,
        )
        day_metrics.append(
            IndependentDayMetric(
                local_date=day,
                day_type="weekend" if day.weekday() >= 5 else "weekday",
                eligible_target_slots=eligible,
                expected_target_slots=expected,
                coverage_percent=eligible / expected * 100 if expected else 0,
                complete=complete,
                cumulative_signed_energy_error_kwh=signed,
                cumulative_underforecast_kwh=max(signed, 0),
            )
        )
    complete_days = [d for d in day_metrics if d.complete]
    weekdays = sum(d.day_type == "weekday" for d in complete_days)
    weekends = sum(d.day_type == "weekend" for d in complete_days)
    horizons_present = all(
        sum(
            bool(r.get("complete_day"))
            for r in cohort
            if r.get("horizon_bucket") == name
        )
        >= minimum_complete_dates
        for name in HORIZON_NAMES
    )
    independent = (
        len(complete_days) >= minimum_complete_dates
        and weekdays >= minimum_weekday_dates
        and weekends >= minimum_weekend_dates
        and horizons_present
    )
    blocks = []
    if truncated:
        blocks.append("calibration_rollup_query_truncated")
    if len(complete_days) < minimum_complete_dates:
        blocks.append("insufficient_complete_dates")
    if weekdays < minimum_weekday_dates:
        blocks.append("insufficient_weekday_dates")
    if weekends < minimum_weekend_dates:
        blocks.append("insufficient_weekend_dates")
    if not horizons_present:
        blocks.append("required_horizons_missing")
    expected_rollups = len(dates) * len(HORIZON_NAMES)
    calculated_rollups = sum(r.get("calculated_at_utc") is not None for r in cohort)
    if calculated_rollups < expected_rollups:
        blocks.append("rollup_backfill_incomplete")
    metric = _rollup_metric(cohort)
    status, reason = _status(
        metric, evidence=independent and not blocks, has_evidence=bool(complete_days)
    )
    under = [d.cumulative_underforecast_kwh for d in complete_days]
    mins = [
        aware_datetime(r["minimum_target_utc"]).astimezone(UTC)
        for r in cohort
        if r.get("minimum_target_utc")
    ]
    maxs = [
        aware_datetime(r["maximum_target_utc"]).astimezone(UTC)
        for r in cohort
        if r.get("maximum_target_utc")
    ]
    return ForecastCalibrationReport(
        status=status,
        status_reason=reason,
        sample_period_start=min(mins) if mins else None,
        sample_period_end=max(maxs) if maxs else None,
        requested_period_start=requested_start,
        requested_period_end=requested_end,
        actual_period_start=min(mins) if mins else None,
        actual_period_end=max(maxs) if maxs else None,
        truncated=truncated,
        eligible_point_count=metric.eligible_points,
        raw_prediction_row_count=sum(int(r.get("total_points") or 0) for r in cohort),
        eligible_score_row_count=sum(
            int(r.get("eligible_points") or 0) for r in cohort
        ),
        independent_target_horizon_slot_count=metric.total_points,
        unique_actual_target_slot_count=unique_actual_targets,
        eligible_actual_target_slot_count=eligible_actual_targets,
        distinct_local_date_count=len(day_metrics),
        rollup_row_count=len(cohort),
        calculated_rollup_row_count=calculated_rollups,
        expected_rollup_row_count=expected_rollups,
        rollup_completeness_percent=(
            calculated_rollups / expected_rollups * 100 if expected_rollups else 0
        ),
        complete_date_count=len(complete_days),
        complete_weekday_count=weekdays,
        complete_weekend_count=weekends,
        required_complete_dates=minimum_complete_dates,
        required_complete_day_coverage_percent=complete_day_coverage_percent,
        independent_evidence_sufficient=independent,
        required_horizons_present=horizons_present,
        quality_blocks=blocks,
        metrics=metric,
        raw_row_metrics=_rollup_metric(cohort, raw=True),
        metrics_by_horizon=by_horizon,
        metrics_by_local_hour={},
        independent_days=day_metrics,
        median_cumulative_underforecast_kwh=median(under) if under else None,
        p90_cumulative_underforecast_kwh=_percentile(under, 0.90),
        p95_cumulative_underforecast_kwh=_percentile(under, 0.95),
        cumulative_underforecast_kwh=sum(under) if under else None,
        current_identity=identity,
        alignment_version=identity.alignment_version,
        training_policies=sorted({str(r.get("training_policy")) for r in cohort}),
        model_versions=sorted({str(r.get("model_version")) for r in cohort}),
    )


def _rollup_metric(
    rows: list[dict[str, Any]], *, raw: bool = False
) -> CalibrationMetric:
    if raw:
        total = sum(int(r.get("total_points") or 0) for r in rows)
        eligible = sum(int(r.get("eligible_points") or 0) for r in rows)
        signed = sum(float(r.get("sum_signed_error") or 0) for r in rows)
        absolute = sum(float(r.get("sum_absolute_error") or 0) for r in rows)
        squared = sum(float(r.get("sum_squared_error") or 0) for r in rows)
        actual_energy = sum(float(r.get("actual_energy_kwh") or 0) for r in rows)
        forecast_energy = sum(float(r.get("forecast_energy_kwh") or 0) for r in rows)
    else:
        total = sum(int(r.get("unique_target_slots") or 0) for r in rows)
        eligible = sum(int(r.get("eligible_target_slots") or 0) for r in rows)
        signed = sum(float(r.get("slot_sum_signed_error_w") or 0) for r in rows)
        absolute = sum(float(r.get("slot_sum_absolute_error_w") or 0) for r in rows)
        squared = sum(float(r.get("slot_sum_squared_error_w2") or 0) for r in rows)
        actual_energy = (
            sum(float(r.get("slot_sum_actual_w") or 0) for r in rows) / 12_000
        )
        forecast_energy = (
            sum(float(r.get("slot_sum_forecast_w") or 0) for r in rows) / 12_000
        )
    # Stored signed error is actual minus forecast; reported bias reverses it.
    bias = -signed / eligible if eligible else None
    actual_w_sum = actual_energy * 12_000
    return CalibrationMetric(
        total_points=total,
        eligible_points=eligible,
        coverage=eligible / total * 100 if total else 0,
        bias_w=bias,
        absolute_bias_w=abs(bias) if bias is not None else None,
        mae_w=absolute / eligible if eligible else None,
        rmse_w=sqrt(squared / eligible) if eligible else None,
        wape_percent=absolute / actual_w_sum * 100 if actual_w_sum > 0 else None,
        forecast_energy_kwh=forecast_energy if eligible else None,
        actual_energy_kwh=actual_energy if eligible else None,
        signed_energy_error_kwh=actual_energy - forecast_energy if eligible else None,
    )


def _slot_weighted_rows(
    rows: list[dict[str, Any]], timezone: ZoneInfo
) -> list[dict[str, Any]]:
    groups: dict[tuple[datetime, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        target = aware_datetime(row["period_start_utc"]).astimezone(UTC)
        horizon = _horizon_bucket(
            (target - aware_datetime(row["created_at_utc"])).total_seconds() / 3600
        )
        if horizon in HORIZON_NAMES:
            groups[(target, horizon)].append(row)
    result = []
    for (target, horizon), group in sorted(groups.items()):
        usable = [r for r in group if _eligible(r)]
        base = dict(group[0])
        base["horizon_bucket"] = horizon
        base["local_date"] = target.astimezone(timezone).date()
        if usable:
            base["expected_value"] = sum(
                float(r["expected_value"]) for r in usable
            ) / len(usable)
            base["actual_value"] = sum(float(r["actual_value"]) for r in usable) / len(
                usable
            )
            base["actual_available"] = True
            base["health_eligible"] = True
        else:
            base["actual_available"] = False
            base["health_eligible"] = False
            base["actual_value"] = None
        result.append(base)
    return result


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
    usable = [r for r in rows if _eligible(r)]
    errors = [float(r["expected_value"]) - float(r["actual_value"]) for r in usable]
    actual_sum = sum(abs(float(r["actual_value"])) for r in usable)
    forecast_energy = sum(float(r["expected_value"]) / 12_000 for r in usable)
    actual_energy = sum(float(r["actual_value"]) / 12_000 for r in usable)
    bias = sum(errors) / len(errors) if errors else None
    return CalibrationMetric(
        total_points=len(rows),
        eligible_points=len(errors),
        coverage=len(errors) / len(rows) * 100 if rows else 0,
        bias_w=bias,
        absolute_bias_w=abs(bias) if bias is not None else None,
        mae_w=sum(abs(e) for e in errors) / len(errors) if errors else None,
        rmse_w=sqrt(sum(e * e for e in errors) / len(errors)) if errors else None,
        wape_percent=(
            sum(abs(e) for e in errors) / actual_sum * 100 if actual_sum > 0 else None
        ),
        forecast_energy_kwh=forecast_energy if errors else None,
        actual_energy_kwh=actual_energy if errors else None,
        signed_energy_error_kwh=actual_energy - forecast_energy if errors else None,
    )


def _horizon_bucket(hours: float) -> str:
    for lower, upper, name in HORIZON_BUCKETS:
        if lower <= hours < upper:
            return name
    return "24h+"


def _status(
    metric: CalibrationMetric, *, evidence: bool, has_evidence: bool
) -> tuple[CalibrationStatus, str]:
    if not has_evidence:
        return (
            "insufficient_data",
            "No eligible exact-identity calibration evidence is available.",
        )
    if not evidence:
        return (
            "provisional",
            "Metrics are provisional until seven substantially complete independent "
            "local dates, weekday/weekend coverage, and every required horizon "
            "are present.",
        )
    absolute_bias = metric.absolute_bias_w or 0
    mae = metric.mae_w or 0
    if absolute_bias <= 200 and mae <= 600:
        return (
            "good",
            "Independent-day heuristic: absolute bias <= 200 W and MAE <= 600 W.",
        )
    if absolute_bias <= 300 and mae <= 750:
        return (
            "acceptable",
            "Independent-day project target: absolute bias <= 300 W and MAE <= 750 W.",
        )
    if absolute_bias <= 600 and mae <= 900:
        return (
            "degraded",
            "Independent calibration exceeds the acceptable project target.",
        )
    return (
        "poor",
        "Independent calibration materially exceeds the project bias or MAE target.",
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
