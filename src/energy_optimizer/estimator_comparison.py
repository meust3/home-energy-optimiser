"""Offline-only estimator comparison; production Tier 2 remains arithmetic mean."""

from math import sqrt
from statistics import mean, median
from typing import Literal

from pydantic import BaseModel

EstimatorName = Literal[
    "arithmetic_mean", "median", "trimmed_mean_10", "winsorized_mean_10"
]


class EstimatorCase(BaseModel):
    training_values_w: list[float]
    actual_w: float
    horizon_hours: float
    local_hour: int
    day_type: str


class EstimatorMetric(BaseModel):
    sample_count: int
    bias_w: float | None
    mae_w: float | None
    rmse_w: float | None
    coverage: float
    energy_error_kwh: float | None


class EstimatorComparison(BaseModel):
    metrics: dict[EstimatorName, EstimatorMetric]
    same_training_samples: bool = True
    production_estimator_changed: bool = False


def compare_estimators(cases: list[EstimatorCase]) -> EstimatorComparison:
    results = {}
    for name in ("arithmetic_mean", "median", "trimmed_mean_10", "winsorized_mean_10"):
        errors = []
        for case in cases:
            if not case.training_values_w:
                continue
            prediction = estimate(case.training_values_w, name)
            errors.append(prediction - case.actual_w)
        results[name] = EstimatorMetric(
            sample_count=len(errors),
            bias_w=mean(errors) if errors else None,
            mae_w=mean(abs(value) for value in errors) if errors else None,
            rmse_w=sqrt(mean(value * value for value in errors)) if errors else None,
            coverage=(len(errors) / len(cases) * 100 if cases else 0),
            energy_error_kwh=(sum(errors) / 12_000 if errors else None),
        )
    return EstimatorComparison(metrics=results)


def estimate(values: list[float], name: EstimatorName) -> float:
    ordered = sorted(float(value) for value in values)
    if name == "arithmetic_mean":
        return mean(ordered)
    if name == "median":
        return median(ordered)
    trim = int(len(ordered) * 0.10)
    if not trim:
        return mean(ordered)
    if name == "trimmed_mean_10":
        return mean(ordered[trim:-trim])
    winsorized = (
        [ordered[trim]] * trim + ordered[trim:-trim] + [ordered[-trim - 1]] * trim
    )
    return mean(winsorized)
