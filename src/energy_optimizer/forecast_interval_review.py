"""Offline held-out residual review; never supplies operational forecast bounds."""

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from math import isfinite
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from energy_optimizer.forecast_calibration import (
    HORIZON_BUCKETS,
    CalibrationIdentity,
    current_calibration_identity,
)
from energy_optimizer.timestamps import aware_datetime


def _quantile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    first = int(position)
    last = min(first + 1, len(ordered) - 1)
    return ordered[first] + (ordered[last] - ordered[first]) * (position - first)


def review_forecast_intervals(
    rows: list[dict[str, Any]],
    *,
    training_end: datetime,
    timezone_name: str = "Australia/Brisbane",
    identity: CalibrationIdentity | None = None,
    minimum_training_dates: int = 28,
    minimum_holdout_dates: int = 7,
    minimum_group_samples: int = 100,
) -> dict[str, Any]:
    """Fit P10/P90 residual candidates before an explicit chronological cutoff.

    Within each horizon, select the latest pre-target prediction for each physical
    slot. Overlapping runs cannot inflate samples. Every group is evaluated on
    later independent local dates. Bounds remain an offline candidate even if the
    empirical coverage check passes; operational admission is a separate gate.
    """
    if not isinstance(rows, list):
        raise ValueError("Interval review input must be a list of exported rows")
    if len(rows) > 100_000:
        raise ValueError("Interval review is limited to 100000 exported rows")
    cutoff = aware_datetime(training_end).astimezone(UTC)
    zone = ZoneInfo(timezone_name)
    if cutoff.astimezone(zone).time() != time.min:
        raise ValueError("Training cutoff must be local midnight")
    if min(minimum_training_dates, minimum_holdout_dates, minimum_group_samples) < 1:
        raise ValueError("Evidence minimums must be positive")
    selected_identity = identity or current_calibration_identity()
    selected: dict[tuple[datetime, str], dict[str, Any]] = {}
    rejected = 0
    for raw in rows:
        metadata = raw.get("run_metadata_json") or {}
        if (
            raw.get("source") != "scheduled_forecast_operations"
            or raw.get("forecast_type") != selected_identity.forecast_type
            or raw.get("model_version") != selected_identity.model_version
            or metadata.get("alignment_version") != selected_identity.alignment_version
            or metadata.get("training_policy") != selected_identity.training_policy
            or not raw.get("health_eligible")
            or not raw.get("actual_available")
        ):
            rejected += 1
            continue
        target = aware_datetime(raw["period_start_utc"]).astimezone(UTC)
        end = aware_datetime(raw["period_end_utc"]).astimezone(UTC)
        created = aware_datetime(raw["created_at_utc"]).astimezone(UTC)
        scored = aware_datetime(raw["scored_at_utc"]).astimezone(UTC)
        lead = (target - created).total_seconds() / 3600
        horizon = next((name for a, b, name in HORIZON_BUCKETS if a <= lead < b), None)
        actual = float(raw["actual_value"])
        expected = float(raw["expected_value"])
        if (
            horizon is None
            or end - target != timedelta(minutes=5)
            or scored < end
            or not isfinite(actual)
            or not isfinite(expected)
            or actual < 0
            or expected < 0
        ):
            rejected += 1
            continue
        # No label known after training_end can enter the fit.
        training = end <= cutoff and scored <= cutoff
        if not training and target < cutoff:
            rejected += 1
            continue
        key = target, horizon
        candidate = {
            "target": target,
            "created": created,
            "actual": actual,
            "expected": expected,
            "training": training,
            "horizon": horizon,
            "date": target.astimezone(zone).date(),
            "hour": target.astimezone(zone).hour,
        }
        previous = selected.get(key)
        if previous is None or created > previous["created"]:
            selected[key] = candidate
        elif created == previous["created"] and (
            actual != previous["actual"] or expected != previous["expected"]
        ):
            raise ValueError("Conflicting predictions for an identical target/creation")
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in selected.values():
        groups[row["horizon"], row["hour"] // 6].append(row)
    output = []
    for (horizon, band), samples in sorted(groups.items()):
        train = [r for r in samples if r["training"]]
        test = [r for r in samples if not r["training"]]
        train_dates = len({r["date"] for r in train})
        test_dates = len({r["date"] for r in test})
        sufficient = (
            train_dates >= minimum_training_dates
            and test_dates >= minimum_holdout_dates
            and len(train) >= minimum_group_samples
            and len(test) >= minimum_group_samples
        )
        item = {
            "horizon": horizon,
            "local_hour_band": [band * 6, (band + 1) * 6],
            "training_dates": train_dates,
            "holdout_dates": test_dates,
            "training_slots": len(train),
            "holdout_slots": len(test),
            "status": "insufficient_independent_evidence",
            "residual_p10_w": None,
            "residual_p90_w": None,
            "holdout_coverage_percent": None,
        }
        if sufficient:
            residuals = [r["actual"] - r["expected"] for r in train]
            lower, upper = _quantile(residuals, 0.1), _quantile(residuals, 0.9)
            contained = sum(
                max(0, r["expected"] + lower)
                <= r["actual"]
                <= max(0, r["expected"] + upper)
                for r in test
            )
            coverage = contained / len(test) * 100
            baseline = median(r["actual"] for r in train)
            item.update(
                residual_p10_w=lower,
                residual_p90_w=upper,
                holdout_coverage_percent=coverage,
                holdout_model_mae_w=sum(abs(r["actual"] - r["expected"]) for r in test)
                / len(test),
                holdout_training_band_median_mae_w=sum(
                    abs(r["actual"] - baseline) for r in test
                )
                / len(test),
                status=(
                    "coverage_candidate_pass"
                    if 75 <= coverage <= 85
                    else "coverage_candidate_failed"
                ),
            )
        output.append(item)
    return {
        "method_version": "offline-residual-interval-review-v1",
        "identity": selected_identity.model_dump(),
        "training_end_utc": cutoff,
        "nominal_coverage_percent": 80,
        "coverage_tolerance_percent": 5,
        "minimum_training_dates": minimum_training_dates,
        "minimum_holdout_dates": minimum_holdout_dates,
        "minimum_group_samples": minimum_group_samples,
        "raw_rows": len(rows),
        "rejected_rows": rejected,
        "independent_target_horizon_slots": len(selected),
        "groups": output,
        "operational_bounds_enabled": False,
        "database_write_performed": False,
        "training_provenance_warning": (
            "EV-unverified history retains contamination risk; a coverage pass "
            "does not validate reserve or daily-energy safety."
        ),
    }
