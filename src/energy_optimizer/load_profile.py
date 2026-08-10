"""Simple, explainable weekday/five-minute household load profile."""

from collections import defaultdict
from typing import Any

from energy_optimizer.models import LoadProfilePoint
from energy_optimizer.timestamps import aware_datetime


def estimate_load_profile(
    rows: list[Any], *, minimum_samples: int = 3, fallback_kw: float = 2.0
) -> list[LoadProfilePoint]:
    grouped: dict[tuple[int, int], list[float]] = defaultdict(list)
    for row in rows:
        local = aware_datetime(row["observed_at_local"])
        slot = local.hour * 12 + local.minute // 5
        grouped[(local.weekday(), slot)].append(row["house_consumption_w"] / 1000)
    points: list[LoadProfilePoint] = []
    for day in range(7):
        for slot in range(288):
            samples = grouped[(day, slot)]
            if len(samples) >= minimum_samples:
                estimate = sum(samples) / len(samples)
                source = "history"
                explanation = f"Mean of {len(samples)} healthy observations"
            else:
                estimate = fallback_kw
                source = "fallback"
                explanation = (
                    f"Conservative fallback; {len(samples)}/{minimum_samples} "
                    "required samples"
                )
            points.append(
                LoadProfilePoint(
                    day_of_week=day,
                    slot_index=slot,
                    estimated_power_kw=estimate,
                    sample_count=len(samples),
                    source=source,
                    explanation=explanation,
                )
            )
    return points
