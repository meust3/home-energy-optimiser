"""Read-only historical EV candidate detection for explicit human review."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field

from energy_optimizer.timestamps import aware_datetime
from energy_optimizer.training_provenance import verified_telemetry_boundary


class HistoricalEVCandidateConfig(BaseModel):
    minimum_house_load_w: float = Field(default=5000, gt=0)
    minimum_duration_minutes: int = Field(default=60, gt=0)
    maximum_internal_gap_minutes: int = Field(default=10, ge=5)
    minimum_session_energy_kwh: float = Field(default=5, gt=0)
    plateau_variability_threshold: float = Field(default=0.15, gt=0, le=1)


class HistoricalEVCandidate(BaseModel):
    candidate_id: str
    start_utc: datetime
    end_utc: datetime
    duration_minutes: float = Field(gt=0)
    observed_slot_count: int = Field(gt=0)
    estimated_energy_kwh: float = Field(gt=0)
    median_house_power_w: float = Field(gt=0)
    max_house_power_w: float = Field(gt=0)
    variability: float = Field(ge=0)
    median_grid_power_w: float | None = None
    median_battery_power_w: float | None = None
    median_pv_power_w: float | None = None
    supporting_evidence: list[str]
    contradictory_evidence: list[str]
    false_positive_risks: list[str]
    candidate_score: int = Field(ge=0, le=100)
    status: Literal["unreviewed"] = "unreviewed"


def detect_historical_ev_candidates(
    rows: list[Any], *, config: HistoricalEVCandidateConfig
) -> list[HistoricalEVCandidate]:
    """Surface stable pre-authoritative high-load sessions without changing data."""
    normalized = [dict(row) for row in rows]
    boundary = verified_telemetry_boundary(normalized)
    eligible = []
    for row in normalized:
        slot_value = row.get("slot_utc")
        power = row.get("baseline_house_consumption_w")
        if slot_value is None or power is None:
            continue
        slot = aware_datetime(slot_value).astimezone(UTC)
        if boundary is not None and slot >= boundary:
            continue
        if not bool(row.get("telemetry_is_healthy", True)) or not bool(
            row.get("baseline_training_eligible", True)
        ):
            continue
        if float(power) < config.minimum_house_load_w:
            continue
        eligible.append((slot, row))
    eligible.sort(key=lambda item: item[0])
    groups: list[list[tuple[datetime, dict[str, Any]]]] = []
    for item in eligible:
        if not groups or item[0] - groups[-1][-1][0] > timedelta(
            minutes=config.maximum_internal_gap_minutes
        ):
            groups.append([item])
        else:
            groups[-1].append(item)
    candidates = []
    for group in groups:
        candidate = _candidate(group, config)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _candidate(
    group: list[tuple[datetime, dict[str, Any]]],
    config: HistoricalEVCandidateConfig,
) -> HistoricalEVCandidate | None:
    start = group[0][0]
    end = group[-1][0] + timedelta(minutes=5)
    duration = (end - start).total_seconds() / 60
    values = [float(row["baseline_house_consumption_w"]) for _, row in group]
    energy = sum(values) * 5 / 60 / 1000
    centre = median(values)
    mad = median(abs(value - centre) for value in values)
    variability = mad / max(centre, 1)
    if (
        duration < config.minimum_duration_minutes
        or energy < config.minimum_session_energy_kwh
    ):
        return None
    stable = variability <= config.plateau_variability_threshold
    supporting = [
        f"Sustained load exceeded {config.minimum_house_load_w:g} W for "
        f"{duration:g} minutes.",
        f"Observed interval energy was approximately {energy:.2f} kWh.",
    ]
    if stable:
        supporting.append("Load formed a comparatively stable high-power plateau.")
    contradictory = []
    if not stable:
        contradictory.append(
            "Load variability is not characteristic of a stable plateau."
        )
    pv_values = _values(group, "pv_power_w")
    if pv_values and median(pv_values) > 1000:
        contradictory.append("Substantial PV coincided with the interval.")
    battery_values = _values(group, "battery_power_w")
    if battery_values and max(abs(value) for value in battery_values) > 5000:
        contradictory.append(
            "Large battery power may explain part of the household pattern."
        )
    score = 35
    score += min(round(duration / 10), 25)
    score += 25 if stable else max(0, round(20 * (1 - variability)))
    score += min(round(energy), 15)
    score -= min(len(contradictory) * 10, 20)
    identifier = sha256(f"{start.isoformat()}|{end.isoformat()}".encode()).hexdigest()[
        :12
    ]
    return HistoricalEVCandidate(
        candidate_id=f"hev-{identifier}",
        start_utc=start,
        end_utc=end,
        duration_minutes=duration,
        observed_slot_count=len(group),
        estimated_energy_kwh=round(energy, 3),
        median_house_power_w=round(centre, 1),
        max_house_power_w=round(max(values), 1),
        variability=round(variability, 4),
        median_grid_power_w=_median_or_none(group, "grid_power_w"),
        median_battery_power_w=_median_or_none(group, "battery_power_w"),
        median_pv_power_w=_median_or_none(group, "pv_power_w"),
        supporting_evidence=supporting,
        contradictory_evidence=contradictory,
        false_positive_risks=[
            "oven or cooktop",
            "hot water",
            "air conditioning",
            "pool equipment",
            "battery or grid behaviour",
            "another large household load",
        ],
        candidate_score=max(0, min(score, 100)),
    )


def _values(group: list[tuple[datetime, dict[str, Any]]], name: str) -> list[float]:
    return [float(row[name]) for _, row in group if row.get(name) is not None]


def _median_or_none(
    group: list[tuple[datetime, dict[str, Any]]], name: str
) -> float | None:
    values = _values(group, name)
    return round(median(values), 1) if values else None
