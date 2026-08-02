"""Explainable hierarchical household-demand forecasting."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field

FallbackMode = Literal["banded", "flat"]
ForecastTier = Literal[
    "tier1_exact",
    "tier2_day_type_30m",
    "tier3_all_days_30m",
    "tier4_recent_band",
    "tier5_fallback",
]
FALLBACK_BANDS = ("overnight", "morning", "daytime", "evening", "late_evening")
TIERS: tuple[ForecastTier, ...] = (
    "tier1_exact",
    "tier2_day_type_30m",
    "tier3_all_days_30m",
    "tier4_recent_band",
    "tier5_fallback",
)


class FallbackContribution(BaseModel):
    configured_power_kw: float = Field(ge=0)
    slot_count: int = Field(ge=0)
    energy_kwh: float = Field(ge=0)


class TierContribution(BaseModel):
    slot_count: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    energy_kwh: float = Field(ge=0)
    average_variability: float | None = Field(default=None, ge=0)
    average_sample_age_days: float | None = Field(default=None, ge=0)
    description: str


class ForecastSlotDecision(BaseModel):
    period_start_local: datetime
    tier: ForecastTier
    estimated_power_kw: float = Field(ge=0)
    sample_count: int = Field(ge=0)
    variability: float | None = Field(default=None, ge=0)
    explanation: str


class DemandDiagnostics(BaseModel):
    total_observations_examined: int = Field(ge=0)
    eligible_baseline_observations: int = Field(ge=0)
    ineligible_observations_by_reason: dict[str, int]
    minimum_samples_per_weekday_slot: int = Field(gt=0)
    historical_slots_qualified: int = Field(ge=0)
    slots_with_insufficient_matching_history: int = Field(ge=0)
    slots_with_no_matching_history: int = Field(ge=0)
    matching_rule: str
    legacy_row_policy: str
    samples_available_by_tier: dict[str, int]
    tier_contributions: dict[str, TierContribution]
    fallback_share: float = Field(ge=0, le=1)


class DemandForecast(BaseModel):
    start_local: datetime
    end_local: datetime
    expected_energy_kwh: float = Field(ge=0)
    history_sample_count: int = Field(ge=0)
    historical_slot_count: int = Field(ge=0)
    fallback_slot_count: int = Field(ge=0)
    fallback_mode: FallbackMode
    fallback_contributions: dict[str, FallbackContribution]
    slot_decisions: list[ForecastSlotDecision]
    diagnostics: DemandDiagnostics
    recent_adjustment: float = Field(gt=0)
    confidence: Literal["low", "medium", "high"]
    explanation: str


def forecast_household_demand(
    rows: list[Any],
    *,
    start_local: datetime,
    end_local: datetime,
    minimum_samples: int,
    fallback_kw: float,
    fallback_mode: FallbackMode = "flat",
    fallback_band_powers_kw: dict[str, float] | None = None,
    recent_days: int = 7,
    tier2_minimum_samples: int = 3,
    tier3_minimum_samples: int = 3,
    tier4_minimum_samples: int = 6,
    tier4_lookback_days: int = 7,
    weekend_days: set[int] | None = None,
) -> DemandForecast:
    """Forecast each five-minute slot using the strongest available tier."""
    if start_local.tzinfo is None or end_local.tzinfo is None:
        raise ValueError("demand forecast datetimes must be timezone-aware")
    if end_local < start_local:
        raise ValueError("demand forecast end must not precede start")
    weekends = weekend_days or {5, 6}
    band_powers = _fallback_powers(
        mode=fallback_mode, flat_kw=fallback_kw, configured=fallback_band_powers_kw
    )
    samples, ineligible = _eligible_samples(rows)
    exact: dict[tuple[int, int], list[_Sample]] = defaultdict(list)
    day_type: dict[tuple[bool, int], list[_Sample]] = defaultdict(list)
    all_days: dict[int, list[_Sample]] = defaultdict(list)
    recent_band: dict[str, list[_Sample]] = defaultdict(list)
    recent_cutoff = start_local - timedelta(days=tier4_lookback_days)
    for sample in samples:
        slot = sample.local.hour * 12 + sample.local.minute // 5
        bucket = sample.local.hour * 2 + sample.local.minute // 30
        exact[(sample.local.weekday(), slot)].append(sample)
        day_type[(sample.local.weekday() in weekends, bucket)].append(sample)
        all_days[bucket].append(sample)
        if sample.local >= recent_cutoff:
            recent_band[_band_for_time(sample.local.time())].append(sample)

    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)
    current_utc = _floor_five_minutes(start_local).astimezone(UTC)
    decisions: list[ForecastSlotDecision] = []
    tier_energy: Counter[str] = Counter()
    tier_slots: Counter[str] = Counter()
    tier_samples: Counter[str] = Counter()
    tier_variability: dict[str, list[float]] = defaultdict(list)
    tier_sample_age: dict[str, list[float]] = defaultdict(list)
    fallback_energy: Counter[str] = Counter()
    fallback_slots: Counter[str] = Counter()
    insufficient_exact = 0
    no_exact = 0
    total_energy = 0.0
    while current_utc < end_utc:
        local = current_utc.astimezone(start_local.tzinfo)
        slot = local.hour * 12 + local.minute // 5
        bucket = local.hour * 2 + local.minute // 30
        band = _band_for_time(local.time())
        exact_values = exact[(local.weekday(), slot)]
        if exact_values and len(exact_values) < minimum_samples:
            insufficient_exact += 1
        elif not exact_values:
            no_exact += 1
        tier, selected, description = _select_tier(
            exact_values=exact_values,
            day_type_values=day_type[(local.weekday() in weekends, bucket)],
            all_day_values=all_days[bucket],
            recent_band_values=recent_band[band],
            tier1_minimum=minimum_samples,
            tier2_minimum=tier2_minimum_samples,
            tier3_minimum=tier3_minimum_samples,
            tier4_minimum=tier4_minimum_samples,
        )
        if tier == "tier5_fallback":
            power = band_powers[band]
            variability = None
            sample_count = 0
            fallback_slots[band] += 1
        else:
            values = [item.power_kw for item in selected]
            power = (
                median(values)
                if tier == "tier4_recent_band"
                else sum(values) / len(values)
            )
            variability = _variability(values)
            sample_count = len(values)
            if variability is not None:
                tier_variability[tier].append(variability)
            tier_sample_age[tier].extend(
                max((local - item.local).total_seconds() / 86400, 0.0)
                for item in selected
            )
        segment_start = max(current_utc, start_utc)
        segment_end = min(current_utc + timedelta(minutes=5), end_utc)
        hours = max((segment_end - segment_start).total_seconds() / 3600, 0.0)
        energy = power * hours
        total_energy += energy
        tier_energy[tier] += energy
        tier_slots[tier] += 1
        tier_samples[tier] += sample_count
        if tier == "tier5_fallback":
            fallback_energy[band] += energy
        decisions.append(
            ForecastSlotDecision(
                period_start_local=local,
                tier=tier,
                estimated_power_kw=round(power, 3),
                sample_count=sample_count,
                variability=None if variability is None else round(variability, 3),
                explanation=description,
            )
        )
        current_utc += timedelta(minutes=5)

    total_slots = len(decisions)
    fallback_count = tier_slots["tier5_fallback"]
    fallback_share = fallback_count / total_slots if total_slots else 0.0
    contributions = {
        tier: TierContribution(
            slot_count=tier_slots[tier],
            sample_count=tier_samples[tier],
            energy_kwh=round(tier_energy[tier], 3),
            average_variability=(
                round(sum(tier_variability[tier]) / len(tier_variability[tier]), 3)
                if tier_variability[tier]
                else None
            ),
            average_sample_age_days=(
                round(sum(tier_sample_age[tier]) / len(tier_sample_age[tier]), 2)
                if tier_sample_age[tier]
                else None
            ),
            description=_tier_description(tier),
        )
        for tier in TIERS
    }
    diagnostics = DemandDiagnostics(
        total_observations_examined=len(rows),
        eligible_baseline_observations=len(samples),
        ineligible_observations_by_reason=dict(sorted(ineligible.items())),
        minimum_samples_per_weekday_slot=minimum_samples,
        historical_slots_qualified=tier_slots["tier1_exact"],
        slots_with_insufficient_matching_history=insufficient_exact,
        slots_with_no_matching_history=no_exact,
        matching_rule="Tier 1 requires exact local weekday and five-minute slot.",
        legacy_row_policy=(
            "Rows without an eligible baseline are excluded as "
            "legacy_or_unclassified; values are never reconstructed."
        ),
        samples_available_by_tier={
            "tier1_exact": sum(len(value) for value in exact.values()),
            "tier2_day_type_30m": sum(len(value) for value in day_type.values()),
            "tier3_all_days_30m": sum(len(value) for value in all_days.values()),
            "tier4_recent_band": sum(len(value) for value in recent_band.values()),
            "tier5_fallback": 0,
        },
        tier_contributions=contributions,
        fallback_share=round(fallback_share, 3),
    )
    confidence = _forecast_confidence(contributions, fallback_share)
    fallback_contributions = {
        band: FallbackContribution(
            configured_power_kw=band_powers[band],
            slot_count=fallback_slots[band],
            energy_kwh=round(fallback_energy[band], 3),
        )
        for band in FALLBACK_BANDS
        if fallback_slots[band] or fallback_mode == "banded"
    }
    tier_summary = ", ".join(
        f"{tier}={tier_slots[tier]}" for tier in TIERS if tier_slots[tier]
    )
    return DemandForecast(
        start_local=start_local,
        end_local=end_local,
        expected_energy_kwh=round(max(total_energy, 0.0), 3),
        history_sample_count=len(samples),
        historical_slot_count=total_slots - fallback_count,
        fallback_slot_count=fallback_count,
        fallback_mode=fallback_mode,
        fallback_contributions=fallback_contributions,
        slot_decisions=decisions,
        diagnostics=diagnostics,
        recent_adjustment=1.0,
        confidence=confidence,
        explanation=(
            f"Five-minute forecast tiers: {tier_summary or 'no slots'}. "
            f"Tier 2-4 values are broader contextual estimates, not exact household "
            f"patterns. Configured fallback share was {fallback_share:.1%}."
        ),
    )


class _Sample:
    def __init__(self, local: datetime, power_kw: float) -> None:
        self.local = local
        self.power_kw = power_kw


def _eligible_samples(rows: list[Any]) -> tuple[list[_Sample], Counter[str]]:
    samples: list[_Sample] = []
    ineligible: Counter[str] = Counter()
    for original in rows:
        row = dict(original)
        reason = _ineligibility_reason(row)
        if reason:
            ineligible[reason] += 1
            continue
        value = row.get("baseline_house_consumption_w", row.get("house_consumption_w"))
        local_value = row.get("observed_at_local")
        if value is None or not isinstance(local_value, str):
            ineligible["missing_baseline_or_timestamp"] += 1
            continue
        samples.append(
            _Sample(datetime.fromisoformat(local_value), max(float(value), 0) / 1000)
        )
    return samples, ineligible


def _select_tier(
    *,
    exact_values: list[_Sample],
    day_type_values: list[_Sample],
    all_day_values: list[_Sample],
    recent_band_values: list[_Sample],
    tier1_minimum: int,
    tier2_minimum: int,
    tier3_minimum: int,
    tier4_minimum: int,
) -> tuple[ForecastTier, list[_Sample], str]:
    choices = (
        ("tier1_exact", exact_values, tier1_minimum),
        ("tier2_day_type_30m", day_type_values, tier2_minimum),
        ("tier3_all_days_30m", all_day_values, tier3_minimum),
        ("tier4_recent_band", recent_band_values, tier4_minimum),
    )
    for tier, values, required in choices:
        if len(values) >= required:
            return tier, values, _tier_description(tier)
    return "tier5_fallback", [], _tier_description("tier5_fallback")


def _tier_description(tier: str) -> str:
    return {
        "tier1_exact": "Exact local weekday and five-minute slot mean.",
        "tier2_day_type_30m": "Weekday/weekend 30-minute bucket mean; broader context.",
        "tier3_all_days_30m": "All-days 30-minute bucket mean; broader context.",
        "tier4_recent_band": "Recent same-band median; not an exact time pattern.",
        "tier5_fallback": "Configured fallback assumption; not learned from history.",
    }[tier]


def _ineligibility_reason(row: dict[str, Any]) -> str | None:
    if "telemetry_is_healthy" not in row and "baseline_training_eligible" not in row:
        return None
    if not bool(row.get("telemetry_is_healthy")):
        return "telemetry_unhealthy"
    if not bool(row.get("baseline_training_eligible")):
        return row.get("baseline_exclusion_reason") or "legacy_or_unclassified"
    if row.get("baseline_house_consumption_w") is None:
        return "baseline_value_missing"
    return None


def _fallback_powers(
    *, mode: FallbackMode, flat_kw: float, configured: dict[str, float] | None
) -> dict[str, float]:
    if mode == "flat":
        return {band: flat_kw for band in FALLBACK_BANDS}
    if configured is None or set(configured) != set(FALLBACK_BANDS):
        raise ValueError("banded fallback requires every configured time band")
    if any(value < 0 for value in configured.values()):
        raise ValueError("fallback power values must be non-negative")
    return configured


def _band_for_time(value: time) -> str:
    if value < time(6):
        return "overnight"
    if value < time(9):
        return "morning"
    if value < time(17):
        return "daytime"
    if value < time(22):
        return "evening"
    return "late_evening"


def _variability(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    centre = median(values)
    mad = median([abs(value - centre) for value in values])
    return mad / max(centre, 0.05)


def _forecast_confidence(
    contributions: dict[str, TierContribution], fallback_share: float
) -> Literal["low", "medium", "high"]:
    total = sum(item.slot_count for item in contributions.values())
    if total == 0:
        return "low"
    weights = {
        "tier1_exact": 1.0,
        "tier2_day_type_30m": 0.8,
        "tier3_all_days_30m": 0.65,
        "tier4_recent_band": 0.5,
        "tier5_fallback": 0.2,
    }
    quality = (
        sum(contributions[tier].slot_count * weights[tier] for tier in TIERS) / total
    )
    variability = [
        item.average_variability
        for item in contributions.values()
        if item.average_variability is not None
    ]
    if variability and sum(variability) / len(variability) > 0.35:
        quality -= 0.15
    ages = [
        item.average_sample_age_days
        for item in contributions.values()
        if item.average_sample_age_days is not None
    ]
    if ages and sum(ages) / len(ages) > 30:
        quality -= 0.1
    if fallback_share > 0.5:
        quality -= 0.1
    if quality >= 0.85 and fallback_share <= 0.1:
        return "high"
    if quality >= 0.55 and fallback_share <= 0.5:
        return "medium"
    return "low"


def _floor_five_minutes(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 5) * 5, second=0, microsecond=0)
