"""Deterministic, advisory-only battery shadow decisioning.

This module deliberately has no Home Assistant, Modbus, vehicle-cloud, or device
client dependency.  It turns immutable repository snapshots into auditable data;
it cannot execute the action names it evaluates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from energy_optimizer.timestamps import aware_datetime, native_json

POLICY_VERSION = "battery-shadow-policy-v1"
ASSUMPTION_SET_VERSION = "battery-shadow-assumptions-v1"
OUTCOME_SCORING_VERSION = "battery-shadow-outcome-v2"
PRICE_GAP_TOLERANCE_SECONDS = 1.0


class BatteryAction(StrEnum):
    HOLD = "HOLD"
    CHARGE_BATTERY_FROM_GRID = "CHARGE_BATTERY_FROM_GRID"
    PRESERVE_BATTERY = "PRESERVE_BATTERY"
    DISCHARGE_FOR_SELF_CONSUMPTION = "DISCHARGE_FOR_SELF_CONSUMPTION"
    EXPORT_BATTERY = "EXPORT_BATTERY"
    DEFER_EXPORT = "DEFER_EXPORT"


BLOCKED_EV_ACTIONS = (
    ("CHARGE_EV_NOW", "direct_charger_power_unavailable"),
    ("DEFER_EV", "ev_target_soc_unavailable"),
    ("PRESERVE_EV_ENERGY_REQUIREMENT", "ev_ready_by_unavailable"),
)


@dataclass(frozen=True)
class ShadowDecisionConfig:
    """Safe, versioned policy inputs; zero power limits mean unverified."""

    enabled: bool = False
    allow_non_hold_recommendations: bool = False
    decision_interval_minutes: int = 30
    max_runtime_seconds: int = 60
    minimum_expected_value_aud: float = 0.25
    outcome_scoring_delay_minutes: int = 10
    maximum_analysis_horizon_hours: int = 24
    maximum_export_power_w: float = 0.0
    maximum_discharge_power_w: float = 0.0
    import_limit_w: float = 0.0
    discharge_efficiency: float = 0.95

    def __post_init__(self) -> None:
        if not 5 <= self.decision_interval_minutes <= 1440:
            raise ValueError("shadow decision interval must be 5-1440 minutes")
        if not 5 <= self.max_runtime_seconds <= 900:
            raise ValueError("shadow decision runtime must be 5-900 seconds")
        if self.minimum_expected_value_aud < 0:
            raise ValueError("minimum expected value must not be negative")
        if not 0 <= self.outcome_scoring_delay_minutes <= 1440:
            raise ValueError("outcome scoring delay must be 0-1440 minutes")
        if not 1 <= self.maximum_analysis_horizon_hours <= 168:
            raise ValueError("shadow analysis horizon must be 1-168 hours")
        if (
            min(
                self.maximum_export_power_w,
                self.maximum_discharge_power_w,
                self.import_limit_w,
            )
            < 0
        ):
            raise ValueError("shadow power limits must not be negative")
        if not 0 < self.discharge_efficiency <= 1:
            raise ValueError("discharge efficiency must be in (0, 1]")


@dataclass(frozen=True)
class CalibrationGate:
    identity: dict[str, str]
    identity_matches: bool
    status: str
    independent_evidence_sufficient: bool
    required_horizons_present: bool
    quality_blocks: tuple[str, ...] = ()
    rollup_backfill_complete: bool = False

    @property
    def permits_non_hold(self) -> bool:
        return (
            self.identity_matches
            and self.status in {"acceptable", "good"}
            and self.independent_evidence_sufficient
            and self.required_horizons_present
            and not self.quality_blocks
            and self.rollup_backfill_complete
        )


@dataclass(frozen=True)
class PriceCoverage:
    coverage_percent: float
    weighted_average_aud_per_kwh: float | None
    horizon_end_utc: datetime | None
    covered_seconds: float
    required_seconds: float

    @property
    def complete(self) -> bool:
        return self.required_seconds > 0 and self.coverage_percent >= 99.999


@dataclass
class ShadowCandidate:
    action: str
    feasible: bool
    feasibility_reason: str
    blocking_constraints: list[str] = field(default_factory=list)
    warning_constraints: list[str] = field(default_factory=list)
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    power_w: float | None = None
    battery_energy_delta_kwh: float | None = None
    grid_energy_delta_kwh: float | None = None
    gross_import_cost_aud: float | None = None
    gross_export_revenue_aud: float | None = None
    gross_avoided_import_value_aud: float | None = None
    opportunity_cost_aud: float | None = None
    gross_incremental_value_aud: float | None = None
    reserve_before_kwh: float | None = None
    reserve_margin_after_kwh: float | None = None
    battery_energy_after_kwh: float | None = None
    price_coverage_percent: float | None = None
    price_horizon_end_utc: datetime | None = None
    average_import_price_aud_per_kwh: float | None = None
    average_export_price_aud_per_kwh: float | None = None
    confidence_rating: str = "low"
    confidence_components: dict[str, Any] = field(default_factory=dict)
    assumptions: dict[str, Any] = field(default_factory=dict)
    candidate_rank: int | None = None
    ranking_score: float | None = None
    ranking_components: dict[str, Any] = field(default_factory=dict)
    tie_break_reason: str | None = None

    def block(self, reason: str) -> None:
        if reason not in self.blocking_constraints:
            self.blocking_constraints.append(reason)
        self.feasible = False
        self.feasibility_reason = reason

    def as_record(self) -> dict[str, Any]:
        value = asdict(self)
        value["start_utc"] = _iso(self.start_utc)
        value["end_utc"] = _iso(self.end_utc)
        value["price_horizon_end_utc"] = _iso(self.price_horizon_end_utc)
        return value


@dataclass(frozen=True)
class ShadowDecisionResult:
    decision_boundary_utc: datetime
    created_at_utc: datetime
    status: str
    selected_action: str | None
    selected_candidate: ShadowCandidate | None
    reason_codes: tuple[str, ...]
    explanation: dict[str, Any]
    candidates: tuple[ShadowCandidate, ...]
    input_snapshot: dict[str, Any]
    constraint_snapshot: dict[str, Any]
    assumption_snapshot: dict[str, Any]
    input_hash: str
    price_horizon_end_utc: datetime | None
    solar_horizon_end_utc: datetime | None
    tradable_calibrated: bool
    no_command_issued: bool = True
    policy_version: str = POLICY_VERSION
    assumption_set_version: str = ASSUMPTION_SET_VERSION


def evaluate_shadow_decision(
    *,
    decision_boundary_utc: datetime,
    created_at_utc: datetime,
    observation: dict[str, Any] | None,
    forecast_run: dict[str, Any] | None,
    reserve_run: dict[str, Any] | None,
    calibration: CalibrationGate,
    collector_config: Any,
    config: ShadowDecisionConfig,
    synthetic_replay: bool = False,
) -> ShadowDecisionResult:
    """Evaluate one battery-only interval without producing an executable plan."""
    boundary = _utc(decision_boundary_utc)
    created = _utc(created_at_utc)
    action_start = created
    action_end = boundary + timedelta(minutes=config.decision_interval_minutes)
    if action_end <= action_start:
        action_end = action_start

    assumptions = build_assumption_snapshot(
        collector_config=collector_config,
        config=config,
        reserve_run=reserve_run,
    )
    common_blockers = _current_state_blockers(
        observation,
        created_at=created,
        freshness_minutes=int(
            getattr(collector_config, "battery_soc_freshness_minutes", 10)
        ),
    )
    forecast_identity = _forecast_identity(forecast_run)
    if forecast_run is None:
        common_blockers.append("forecast_missing")
    if reserve_run is None:
        common_blockers.append("reserve_missing")
    elif forecast_run is not None and int(
        reserve_run.get("forecast_run_id", -1)
    ) != int(forecast_run.get("id", -2)):
        common_blockers.append("reserve_forecast_identity_mismatch")

    import_intervals = _price_intervals(
        (observation or {}).get("amber_import_forecast_json")
    )
    export_intervals = _price_intervals(
        (observation or {}).get("amber_export_forecast_json")
    )
    import_coverage = integrate_price_intervals(
        import_intervals, start=action_start, end=action_end
    )
    export_coverage = integrate_price_intervals(
        export_intervals, start=action_start, end=action_end
    )
    price_horizon = _common_horizon(
        import_coverage.horizon_end_utc, export_coverage.horizon_end_utc
    )
    solar = _solar_context(
        observation,
        created,
        timezone_name=str(getattr(collector_config, "timezone", "Australia/Brisbane")),
    )
    solar_horizon = solar["horizon_end_utc"]
    forecast_horizon = (
        _optional_utc(forecast_run.get("horizon_end_utc"))
        if forecast_run is not None
        else None
    )
    maximum_horizon = created + timedelta(hours=config.maximum_analysis_horizon_hours)
    analysis_horizon = _minimum_horizon(
        forecast_horizon,
        _interval_horizon(import_intervals),
        _interval_horizon(export_intervals),
        solar_horizon,
        maximum_horizon,
    )

    battery_energy = _number((observation or {}).get("battery_energy_estimate_kwh"))
    if battery_energy is None:
        soc = _number((observation or {}).get("battery_soc_percent"))
        capacity = float(getattr(collector_config, "usable_battery_capacity_kwh", 0))
        battery_energy = (
            capacity * soc / 100 if soc is not None and capacity > 0 else None
        )
    reserve = _number((reserve_run or {}).get("recommended_reserve_kwh"))
    capacity = float(getattr(collector_config, "usable_battery_capacity_kwh", 0))
    energy_above_reserve = (
        max(battery_energy - reserve, 0.0)
        if battery_energy is not None and reserve is not None
        else None
    )
    duration_hours = max((action_end - action_start).total_seconds() / 3600, 0)
    demand_energy = _forecast_energy(forecast_run, start=action_start, end=action_end)
    conservative_solar = _solar_energy_for_window(solar.get("p10_kwh"), duration_hours)
    household_deficit = (
        max(demand_energy - (conservative_solar or 0.0), 0.0)
        if demand_energy is not None
        else None
    )
    future_import = _maximum_interval_price(
        import_intervals, start=action_end, end=analysis_horizon
    )
    future_export = _maximum_interval_price(
        export_intervals, start=action_end, end=analysis_horizon
    )
    future_use_value = max(
        [value for value in (future_import, future_export) if value is not None],
        default=None,
    )

    hold = ShadowCandidate(
        action=BatteryAction.HOLD,
        feasible=True,
        feasibility_reason="baseline_no_intentional_action",
        start_utc=action_start,
        end_utc=action_end,
        battery_energy_delta_kwh=0.0,
        grid_energy_delta_kwh=0.0,
        gross_incremental_value_aud=0.0,
        reserve_before_kwh=reserve,
        reserve_margin_after_kwh=energy_above_reserve,
        battery_energy_after_kwh=battery_energy,
        price_coverage_percent=min(
            import_coverage.coverage_percent, export_coverage.coverage_percent
        ),
        confidence_rating="high" if not common_blockers else "low",
        assumptions=assumptions,
    )
    candidates: list[ShadowCandidate] = [hold]
    candidates.append(
        _charge_candidate(
            action_start=action_start,
            action_end=action_end,
            duration_hours=duration_hours,
            battery_energy=battery_energy,
            reserve=reserve,
            capacity=capacity,
            import_coverage=import_coverage,
            future_use_value=future_use_value,
            collector_config=collector_config,
            config=config,
            assumptions=assumptions,
        )
    )
    candidates.append(
        _preserve_candidate(
            action_start=action_start,
            action_end=action_end,
            battery_energy=battery_energy,
            reserve=reserve,
            household_deficit=household_deficit,
            assumptions=assumptions,
        )
    )
    candidates.append(
        _discharge_candidate(
            action_start=action_start,
            action_end=action_end,
            duration_hours=duration_hours,
            battery_energy=battery_energy,
            reserve=reserve,
            available=energy_above_reserve,
            household_deficit=household_deficit,
            import_coverage=import_coverage,
            future_use_value=future_use_value,
            config=config,
            assumptions=assumptions,
        )
    )
    candidates.append(
        _export_candidate(
            action_start=action_start,
            action_end=action_end,
            duration_hours=duration_hours,
            battery_energy=battery_energy,
            reserve=reserve,
            available=energy_above_reserve,
            export_coverage=export_coverage,
            future_use_value=future_use_value,
            config=config,
            assumptions=assumptions,
        )
    )
    candidates.append(
        _defer_candidate(
            action_start=action_start,
            action_end=action_end,
            duration_hours=duration_hours,
            battery_energy=battery_energy,
            reserve=reserve,
            available=energy_above_reserve,
            current_export=export_coverage,
            future_export=future_export,
            config=config,
            assumptions=assumptions,
        )
    )
    for action, reason in BLOCKED_EV_ACTIONS:
        candidates.append(
            ShadowCandidate(
                action=action,
                feasible=False,
                feasibility_reason=reason,
                blocking_constraints=[reason, "ev_required_energy_unavailable"],
                warning_constraints=["ev_load_not_quantified"],
                start_utc=action_start,
                end_utc=action_end,
                assumptions=assumptions,
            )
        )
    for candidate in candidates:
        candidate.price_horizon_end_utc = price_horizon
        candidate.average_import_price_aud_per_kwh = (
            import_coverage.weighted_average_aud_per_kwh
        )
        candidate.average_export_price_aud_per_kwh = (
            export_coverage.weighted_average_aud_per_kwh
        )
        if (
            candidate.price_coverage_percent is None
            and not candidate.action.startswith(
                ("CHARGE_EV", "DEFER_EV", "PRESERVE_EV")
            )
        ):
            candidate.price_coverage_percent = min(
                import_coverage.coverage_percent,
                export_coverage.coverage_percent,
            )

    if common_blockers:
        for candidate in candidates:
            if (
                candidate.action != BatteryAction.HOLD
                and not candidate.action.startswith(
                    ("CHARGE_EV", "DEFER_EV", "PRESERVE_EV")
                )
            ):
                for blocker in common_blockers:
                    candidate.block(blocker)
    _rank_candidates(candidates)

    selection_reasons: list[str] = []
    selected: ShadowCandidate | None = None
    status = "completed"
    current_state_blocks = {
        "latest_observation_missing",
        "latest_observation_stale",
        "battery_soc_missing",
        "battery_soc_stale",
        "current_state_unavailable",
    }
    if current_state_blocks.intersection(common_blockers):
        status = "blocked"
        selection_reasons.extend(
            reason for reason in common_blockers if reason in current_state_blocks
        )
    elif forecast_run is None:
        selected = hold
        selection_reasons.append("forecast_missing")
    elif reserve_run is None:
        selected = hold
        selection_reasons.append("reserve_missing")
    elif not import_coverage.complete or not export_coverage.complete:
        selected = hold
        selection_reasons.append("price_window_incomplete")
    elif not calibration.permits_non_hold:
        selected = hold
        selection_reasons.append(
            "calibration_rollup_incomplete"
            if not calibration.rollup_backfill_complete
            else "calibration_evidence_insufficient"
        )
    elif solar.get("p50_kwh") is None:
        selected = hold
        selection_reasons.append("solar_constraint_context_uncertain")
    elif not config.allow_non_hold_recommendations:
        selected = hold
        selection_reasons.append("non_hold_selection_disabled")
    else:
        eligible = [
            item
            for item in candidates
            if item.feasible
            and item.action != BatteryAction.HOLD
            and not item.action.startswith(("CHARGE_EV", "DEFER_EV", "PRESERVE_EV"))
            and item.gross_incremental_value_aud is not None
            and item.gross_incremental_value_aud >= config.minimum_expected_value_aud
        ]
        selected = eligible[0] if eligible else hold
        selection_reasons.append(
            "highest_ranked_feasible_candidate"
            if eligible
            else "minimum_expected_value_not_met"
        )

    snapshot = {
        "synthetic_replay": synthetic_replay,
        "observation_slot_utc": _iso(
            _optional_utc((observation or {}).get("slot_utc"))
        ),
        "observation_collected_at_utc": _iso(
            _optional_utc((observation or {}).get("observed_at_utc"))
        ),
        "battery_soc_percent": _number((observation or {}).get("battery_soc_percent")),
        "battery_energy_kwh": battery_energy,
        "forecast_run_id": (forecast_run or {}).get("id"),
        "reserve_run_id": (reserve_run or {}).get("id"),
        "forecast_identity": forecast_identity,
        "calibration": {
            **asdict(calibration),
            "tradable_calibrated": calibration.permits_non_hold,
        },
        "demand_energy_action_window_kwh": demand_energy,
        "household_deficit_action_window_kwh": household_deficit,
        "import_price_coverage": _coverage_snapshot(import_coverage),
        "export_price_coverage": _coverage_snapshot(export_coverage),
        "solar": {**solar, "horizon_end_utc": _iso(solar_horizon)},
        "analysis_horizon_end_utc": _iso(analysis_horizon),
    }
    constraint_snapshot = {
        "current_battery_energy_kwh": battery_energy,
        "recommended_reserve_kwh": reserve,
        "energy_above_reserve_kwh": energy_above_reserve,
        "maximum_export_power_w": _positive_or_none(config.maximum_export_power_w),
        "maximum_discharge_power_w": _positive_or_none(
            config.maximum_discharge_power_w
        ),
        "maximum_grid_charge_power_w": _number(
            getattr(collector_config, "reserve_max_charge_power_w", None)
        ),
        "import_limit_w": _positive_or_none(config.import_limit_w),
        "common_blockers": common_blockers,
    }
    input_hash = _hash_snapshot(
        {
            "policy_version": POLICY_VERSION,
            "decision_boundary_utc": boundary.isoformat(),
            "input": snapshot,
            "constraints": constraint_snapshot,
            "assumptions": assumptions,
        }
    )
    explanation = {
        "summary": (
            "No recommendation selected because current state is unavailable."
            if selected is None
            else f"{selected.action} selected by deterministic shadow policy."
        ),
        "selection_reasons": selection_reasons,
        "alternatives": [
            {
                "action": item.action,
                "feasible": item.feasible,
                "gross_incremental_value_aud": item.gross_incremental_value_aud,
                "blocking_constraints": item.blocking_constraints,
            }
            for item in candidates
            if selected is None or item.action != selected.action
        ],
        "economics_scope": "expected_gross_variable_energy_value",
        "excluded_costs": [
            "battery_degradation",
            "fixed_supply_charges",
            "uncertain_tax_and_tariff_composition",
            "unvalidated_physical_losses",
            "demand_charges",
            "ev_costs",
        ],
        "optimality_claimed": False,
        "no_command_issued": True,
    }
    return ShadowDecisionResult(
        decision_boundary_utc=boundary,
        created_at_utc=created,
        status=status,
        selected_action=selected.action if selected else None,
        selected_candidate=selected,
        reason_codes=tuple(dict.fromkeys(selection_reasons or common_blockers)),
        explanation=explanation,
        candidates=tuple(candidates),
        input_snapshot=snapshot,
        constraint_snapshot=constraint_snapshot,
        assumption_snapshot=assumptions,
        input_hash=input_hash,
        price_horizon_end_utc=price_horizon,
        solar_horizon_end_utc=solar_horizon,
        tradable_calibrated=calibration.permits_non_hold,
    )


def integrate_price_intervals(
    intervals: list[dict[str, Any]], *, start: datetime, end: datetime
) -> PriceCoverage:
    """Duration-weight prices and expose gaps; absent prices are never zero-filled."""
    start_utc = _utc(start)
    end_utc = _utc(end)
    required = max((end_utc - start_utc).total_seconds(), 0.0)
    pieces: list[tuple[datetime, datetime, float]] = []
    horizon: datetime | None = None
    for item in intervals:
        price = _number(item.get("per_kwh"))
        interval_start = _optional_utc(item.get("start_time"))
        interval_end = _optional_utc(item.get("end_time"))
        if interval_start is not None and interval_end is None:
            duration = _number(item.get("duration"))
            if duration is not None and duration > 0:
                interval_end = interval_start + timedelta(minutes=duration)
        if price is None or interval_start is None or interval_end is None:
            continue
        if interval_end <= interval_start:
            continue
        horizon = max(horizon, interval_end) if horizon is not None else interval_end
        overlap_start = max(start_utc, interval_start)
        overlap_end = min(end_utc, interval_end)
        if overlap_end > overlap_start:
            pieces.append((overlap_start, overlap_end, price))
    if required <= 0:
        return PriceCoverage(0.0, None, horizon, 0.0, required)
    pieces.sort(key=lambda value: (value[0], value[1]))
    cursor = start_utc
    covered = 0.0
    weighted = 0.0
    for piece_start, piece_end, price in pieces:
        if piece_start > cursor + timedelta(seconds=PRICE_GAP_TOLERANCE_SECONDS):
            cursor = piece_start
        effective_start = max(piece_start, cursor)
        if effective_start > piece_end:
            continue
        seconds = (piece_end - effective_start).total_seconds()
        if seconds <= 0:
            continue
        covered += seconds
        weighted += seconds * price
        cursor = max(cursor, piece_end)
    # Amber can expose adjacent intervals one second apart.  Treat only that
    # documented boundary offset as covered, without interpolating larger gaps.
    missing = max(required - covered, 0.0)
    weighted_seconds = covered
    if 0 < missing <= PRICE_GAP_TOLERANCE_SECONDS * max(len(pieces) + 1, 1):
        covered = required
    coverage = min(covered / required * 100, 100.0)
    average = weighted / max(weighted_seconds, 1)
    return PriceCoverage(
        coverage_percent=coverage,
        weighted_average_aud_per_kwh=average if covered > 0 else None,
        horizon_end_utc=horizon,
        covered_seconds=covered,
        required_seconds=required,
    )


def build_assumption_snapshot(
    *,
    collector_config: Any,
    config: ShadowDecisionConfig,
    reserve_run: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return unit-explicit assumptions; classifications are not physical claims."""
    reserve = _number((reserve_run or {}).get("recommended_reserve_kwh"))
    return {
        "version": ASSUMPTION_SET_VERSION,
        "items": [
            _assumption(
                "usable_battery_capacity",
                _number(getattr(collector_config, "usable_battery_capacity_kwh", None)),
                "kWh",
                "App configuration",
                "configured",
            ),
            _assumption(
                "charge_efficiency",
                _number(getattr(collector_config, "battery_charge_efficiency", None)),
                "ratio",
                "reserve model configuration",
                "modelled",
            ),
            _assumption(
                "discharge_efficiency",
                config.discharge_efficiency,
                "ratio",
                "shadow policy configuration",
                "modelled",
            ),
            _assumption(
                "maximum_grid_charge_power",
                _number(getattr(collector_config, "reserve_max_charge_power_w", None)),
                "W",
                "reserve model configuration",
                "modelled",
            ),
            _assumption(
                "maximum_export_power",
                _positive_or_none(config.maximum_export_power_w),
                "W",
                "shadow App option" if config.maximum_export_power_w > 0 else "unknown",
                "configured" if config.maximum_export_power_w > 0 else "unknown",
            ),
            _assumption(
                "maximum_discharge_power",
                _positive_or_none(config.maximum_discharge_power_w),
                "W",
                (
                    "shadow App option"
                    if config.maximum_discharge_power_w > 0
                    else "not independently validated"
                ),
                "configured" if config.maximum_discharge_power_w > 0 else "unknown",
            ),
            _assumption(
                "import_limit",
                _positive_or_none(config.import_limit_w),
                "W",
                "shadow App option" if config.import_limit_w > 0 else "unknown",
                "configured" if config.import_limit_w > 0 else "unknown",
            ),
            _assumption(
                "policy_reserve",
                reserve,
                "kWh",
                "linked immutable reserve run",
                "observed" if reserve is not None else "unknown",
            ),
            _assumption(
                "emergency_reserve",
                _number((reserve_run or {}).get("emergency_reserve_kwh")),
                "kWh",
                "linked immutable reserve run",
                (
                    "observed"
                    if _number((reserve_run or {}).get("emergency_reserve_kwh"))
                    is not None
                    else "unknown"
                ),
            ),
            _assumption(
                "minimum_expected_gross_value",
                config.minimum_expected_value_aud,
                "AUD",
                "shadow selection policy",
                "policy",
            ),
        ],
    }


def score_shadow_outcome(
    *,
    decision_run: dict[str, Any],
    candidates: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    scored_at_utc: datetime,
    scoring_version: str = OUTCOME_SCORING_VERSION,
) -> dict[str, Any]:
    """Integrate observed evidence; no validated counterfactual model exists yet.

    Five-minute samples approximate constant power/price until the next slot.
    Original candidates remain immutable, but are not treated as extra flows on
    top of the observed (potentially operator-controlled) battery trajectory.
    """
    window_start = _utc(decision_run["selected_start_utc"])
    window_end = _utc(decision_run["selected_end_utc"])
    if window_end <= window_start or _utc(scored_at_utc) < window_end:
        raise ValueError("outcome requires a positive, completed action window")
    duration = (window_end - window_start).total_seconds()
    samples: list[tuple[dict[str, Any], float]] = []
    seen: set[datetime] = set()
    for row in observations:
        slot = _utc(row["slot_utc"])
        seconds = (
            min(slot + timedelta(minutes=5), window_end) - max(slot, window_start)
        ).total_seconds()
        if seconds <= 0:
            continue
        if slot.second or slot.microsecond or slot.minute % 5 or slot in seen:
            raise ValueError("outcome observations must have unique five-minute slots")
        seen.add(slot)
        samples.append((row, seconds))
    samples.sort(key=lambda item: _utc(item[0]["slot_utc"]))
    coverage = sum(seconds for _, seconds in samples) / duration
    price_fields = ("amber_import_price_per_kwh", "amber_export_price_per_kwh")
    flow_fields = ("grid_import_power_w", "grid_export_power_w")
    price_seconds = sum(
        seconds
        for row, seconds in samples
        if all(_outcome_number(row.get(key)) is not None for key in price_fields)
    )
    energy_seconds = sum(
        seconds
        for row, seconds in samples
        if all(
            _outcome_number(row.get(key), power=True) is not None for key in flow_fields
        )
    )
    observed_value = 0.0 if coverage >= 1.0 - 1e-9 else None
    for row, seconds in samples:
        import_power, export_power = (
            _outcome_number(row.get(key), power=True) for key in flow_fields
        )
        import_price, export_price = (
            _outcome_number(row.get(key)) for key in price_fields
        )
        if None in (import_power, export_power, import_price, export_price):
            observed_value = None
            break
        if observed_value is not None:
            observed_value += (
                (export_power * export_price - import_power * import_price)
                * seconds
                / 3_600_000
            )
    intervention = _operator_intervention([row for row, _ in samples])
    return {
        "decision_run_id": int(decision_run["id"]),
        "scoring_version": scoring_version,
        "scored_at_utc": _utc(scored_at_utc),
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "actual_coverage_percent": min(coverage, 1.0) * 100,
        "actual_price_coverage_percent": min(price_seconds / duration, 1.0) * 100,
        "actual_energy_coverage_percent": min(energy_seconds / duration, 1.0) * 100,
        "observed_import_kwh": _integrate_outcome_power(
            samples, "grid_import_power_w", coverage
        ),
        "observed_export_kwh": _integrate_outcome_power(
            samples, "grid_export_power_w", coverage
        ),
        "observed_battery_charge_kwh": _integrate_outcome_power(
            samples, "battery_charge_power_w", coverage
        ),
        "observed_battery_discharge_kwh": _integrate_outcome_power(
            samples, "battery_discharge_power_w", coverage
        ),
        "observed_household_kwh": _integrate_outcome_power(
            samples, "house_consumption_w", coverage
        ),
        "observed_pv_kwh": _integrate_outcome_power(samples, "pv_power_w", coverage),
        "observed_variable_energy_value_aud": observed_value,
        "simulated_selected_value_aud": None,
        "simulated_hold_value_aud": None,
        "selected_vs_hold_value_aud": None,
        "hindsight_best_action": None,
        "hindsight_best_value_aud": None,
        "regret_aud": None,
        "simulated_min_battery_energy_kwh": None,
        "simulated_reserve_breach": None,
        "operator_intervention_possible": intervention["possible"],
        "operator_intervention_confidence": intervention["confidence"],
        "operator_intervention_evidence_json": intervention["evidence"],
        "counterfactual_confidence": "unavailable",
        "counterfactual_limitations_json": [
            "counterfactual_model_not_validated",
            "observed_operation_is_not_a_hold_baseline",
            "candidate_battery_trajectory_not_simulated",
            "incomplete_window_totals_are_null",
            "five_minute_constant_sample_approximation",
            "observed_value_is_gross_variable_energy_only",
            "operator_intent_not_proven",
        ],
    }


def _charge_candidate(**values: Any) -> ShadowCandidate:
    coverage: PriceCoverage = values["import_coverage"]
    config: ShadowDecisionConfig = values["config"]
    collector = values["collector_config"]
    battery = values["battery_energy"]
    capacity = values["capacity"]
    reserve = values["reserve"]
    efficiency = float(getattr(collector, "battery_charge_efficiency", 0))
    power = _number(getattr(collector, "reserve_max_charge_power_w", None))
    candidate = ShadowCandidate(
        action=BatteryAction.CHARGE_BATTERY_FROM_GRID,
        feasible=True,
        feasibility_reason="feasible",
        start_utc=values["action_start"],
        end_utc=values["action_end"],
        reserve_before_kwh=reserve,
        price_coverage_percent=coverage.coverage_percent,
        confidence_rating="medium",
        assumptions=values["assumptions"],
    )
    if battery is None or capacity <= 0:
        candidate.block("battery_soc_missing")
        return candidate
    headroom = max(capacity - battery, 0.0)
    if headroom <= 0.001:
        candidate.block("battery_headroom_insufficient")
    if not coverage.complete:
        candidate.block("price_window_incomplete")
    if power is None or power <= 0 or efficiency <= 0:
        candidate.block("constraint_missing")
    if config.import_limit_w <= 0:
        candidate.block("constraint_missing")
    if values["future_use_value"] is None:
        candidate.block("forecast_missing")
    if not candidate.feasible:
        return candidate
    constrained_power = min(power, config.import_limit_w)
    battery_delta = min(
        headroom,
        constrained_power / 1000 * values["duration_hours"] * efficiency,
    )
    grid_delta = battery_delta / efficiency
    import_cost = grid_delta * float(coverage.weighted_average_aud_per_kwh)
    future_value = battery_delta * float(values["future_use_value"])
    candidate.power_w = min(
        constrained_power,
        battery_delta / efficiency / values["duration_hours"] * 1000,
    )
    candidate.battery_energy_delta_kwh = battery_delta
    candidate.grid_energy_delta_kwh = grid_delta
    candidate.gross_import_cost_aud = import_cost
    candidate.opportunity_cost_aud = 0.0
    candidate.gross_incremental_value_aud = future_value - import_cost
    candidate.battery_energy_after_kwh = battery + battery_delta
    candidate.reserve_margin_after_kwh = (
        battery + battery_delta - reserve if reserve is not None else None
    )
    candidate.warning_constraints.append("operator_intervention_possible")
    return candidate


def _preserve_candidate(**values: Any) -> ShadowCandidate:
    battery = values["battery_energy"]
    reserve = values["reserve"]
    deficit = values["household_deficit"]
    feasible = battery is not None and reserve is not None
    return ShadowCandidate(
        action=BatteryAction.PRESERVE_BATTERY,
        feasible=feasible,
        feasibility_reason=(
            "reserve_or_future_demand_material" if feasible else "reserve_missing"
        ),
        blocking_constraints=[] if feasible else ["reserve_missing"],
        warning_constraints=["operator_intervention_possible"],
        start_utc=values["action_start"],
        end_utc=values["action_end"],
        battery_energy_delta_kwh=0.0,
        grid_energy_delta_kwh=0.0,
        gross_incremental_value_aud=0.0,
        reserve_before_kwh=reserve,
        reserve_margin_after_kwh=(battery - reserve if feasible else None),
        battery_energy_after_kwh=battery,
        confidence_rating="medium" if deficit is not None else "low",
        confidence_components={"household_deficit_kwh": deficit},
        assumptions=values["assumptions"],
    )


def _discharge_candidate(**values: Any) -> ShadowCandidate:
    coverage: PriceCoverage = values["import_coverage"]
    config: ShadowDecisionConfig = values["config"]
    battery = values["battery_energy"]
    reserve = values["reserve"]
    available = values["available"]
    deficit = values["household_deficit"]
    candidate = ShadowCandidate(
        action=BatteryAction.DISCHARGE_FOR_SELF_CONSUMPTION,
        feasible=True,
        feasibility_reason="feasible",
        start_utc=values["action_start"],
        end_utc=values["action_end"],
        reserve_before_kwh=reserve,
        price_coverage_percent=coverage.coverage_percent,
        confidence_rating="medium",
        assumptions=values["assumptions"],
    )
    if available is None or battery is None or reserve is None:
        candidate.block("reserve_missing")
    elif available <= 0.001:
        candidate.block("battery_energy_above_reserve_insufficient")
    if deficit is None:
        candidate.block("forecast_missing")
    elif deficit <= 0.001:
        candidate.block("candidate_energy_zero")
    if not coverage.complete:
        candidate.block("price_window_incomplete")
    if config.maximum_discharge_power_w <= 0:
        candidate.block("constraint_missing")
    if not candidate.feasible:
        return candidate
    grid_energy = min(
        deficit,
        config.maximum_discharge_power_w / 1000 * values["duration_hours"],
        available * config.discharge_efficiency,
    )
    battery_delta = -grid_energy / config.discharge_efficiency
    avoided = grid_energy * float(coverage.weighted_average_aud_per_kwh)
    opportunity = max(float(values["future_use_value"] or 0), 0) * -battery_delta
    after = battery + battery_delta
    candidate.power_w = grid_energy / values["duration_hours"] * 1000
    candidate.battery_energy_delta_kwh = battery_delta
    candidate.grid_energy_delta_kwh = -grid_energy
    candidate.gross_avoided_import_value_aud = avoided
    candidate.opportunity_cost_aud = opportunity
    candidate.gross_incremental_value_aud = avoided - opportunity
    candidate.battery_energy_after_kwh = after
    candidate.reserve_margin_after_kwh = after - reserve
    candidate.warning_constraints.extend(
        [
            "discharge_limit_assumed",
            "efficiency_assumed",
            "operator_intervention_possible",
        ]
    )
    if candidate.reserve_margin_after_kwh < -1e-9:
        candidate.block("battery_energy_above_reserve_insufficient")
    return candidate


def _export_candidate(**values: Any) -> ShadowCandidate:
    coverage: PriceCoverage = values["export_coverage"]
    config: ShadowDecisionConfig = values["config"]
    battery = values["battery_energy"]
    reserve = values["reserve"]
    available = values["available"]
    candidate = ShadowCandidate(
        action=BatteryAction.EXPORT_BATTERY,
        feasible=True,
        feasibility_reason="feasible",
        start_utc=values["action_start"],
        end_utc=values["action_end"],
        reserve_before_kwh=reserve,
        price_coverage_percent=coverage.coverage_percent,
        confidence_rating="medium",
        assumptions=values["assumptions"],
    )
    if available is None or battery is None or reserve is None:
        candidate.block("reserve_missing")
    elif available <= 0.001:
        candidate.block("battery_energy_above_reserve_insufficient")
    if not coverage.complete:
        candidate.block("price_window_incomplete")
    if config.maximum_export_power_w <= 0:
        candidate.block("constraint_missing")
    if config.maximum_discharge_power_w <= 0:
        candidate.block("constraint_missing")
    if not candidate.feasible:
        return candidate
    power = min(config.maximum_export_power_w, config.maximum_discharge_power_w)
    grid_energy = min(
        power / 1000 * values["duration_hours"],
        available * config.discharge_efficiency,
    )
    battery_delta = -grid_energy / config.discharge_efficiency
    revenue = grid_energy * float(coverage.weighted_average_aud_per_kwh)
    opportunity = max(float(values["future_use_value"] or 0), 0) * -battery_delta
    after = battery + battery_delta
    candidate.power_w = power
    candidate.battery_energy_delta_kwh = battery_delta
    candidate.grid_energy_delta_kwh = -grid_energy
    candidate.gross_export_revenue_aud = revenue
    candidate.opportunity_cost_aud = opportunity
    candidate.gross_incremental_value_aud = revenue - opportunity
    candidate.battery_energy_after_kwh = after
    candidate.reserve_margin_after_kwh = after - reserve
    candidate.warning_constraints.extend(
        [
            "efficiency_assumed",
            "solar_constraint_context_uncertain",
            "operator_intervention_possible",
        ]
    )
    if grid_energy <= 0:
        candidate.block("candidate_energy_zero")
    if candidate.reserve_margin_after_kwh < -1e-9:
        candidate.block("battery_energy_above_reserve_insufficient")
    return candidate


def _defer_candidate(**values: Any) -> ShadowCandidate:
    coverage: PriceCoverage = values["current_export"]
    config: ShadowDecisionConfig = values["config"]
    battery = values["battery_energy"]
    reserve = values["reserve"]
    available = values["available"]
    later = values["future_export"]
    candidate = ShadowCandidate(
        action=BatteryAction.DEFER_EXPORT,
        feasible=True,
        feasibility_reason="later_export_value_is_higher",
        warning_constraints=[
            "operator_intervention_possible",
            "solar_constraint_context_uncertain",
        ],
        start_utc=values["action_start"],
        end_utc=values["action_end"],
        battery_energy_delta_kwh=0.0,
        grid_energy_delta_kwh=0.0,
        reserve_before_kwh=reserve,
        battery_energy_after_kwh=battery,
        reserve_margin_after_kwh=available,
        price_coverage_percent=coverage.coverage_percent,
        confidence_rating="medium",
        assumptions=values["assumptions"],
    )
    if available is None or available <= 0.001:
        candidate.block("battery_energy_above_reserve_insufficient")
    if not coverage.complete:
        candidate.block("price_window_incomplete")
    if later is None:
        candidate.block("price_window_missing")
    if config.maximum_export_power_w <= 0 or config.maximum_discharge_power_w <= 0:
        candidate.block("constraint_missing")
    current = coverage.weighted_average_aud_per_kwh
    if later is not None and current is not None and later <= current:
        candidate.block("candidate_energy_zero")
    if not candidate.feasible:
        return candidate
    comparable = min(
        available * config.discharge_efficiency,
        min(config.maximum_export_power_w, config.maximum_discharge_power_w)
        / 1000
        * values["duration_hours"],
    )
    candidate.gross_incremental_value_aud = comparable * (later - current)
    candidate.confidence_components = {
        "current_export_price_aud_per_kwh": current,
        "later_export_price_aud_per_kwh": later,
        "comparable_grid_energy_kwh": comparable,
    }
    return candidate


def _rank_candidates(candidates: list[ShadowCandidate]) -> None:
    tie_order = {
        BatteryAction.DEFER_EXPORT: 0,
        BatteryAction.EXPORT_BATTERY: 1,
        BatteryAction.CHARGE_BATTERY_FROM_GRID: 2,
        BatteryAction.DISCHARGE_FOR_SELF_CONSUMPTION: 3,
        BatteryAction.PRESERVE_BATTERY: 4,
        BatteryAction.HOLD: 5,
    }
    ranked = sorted(
        [item for item in candidates if item.feasible and item.action in tie_order],
        key=lambda item: (
            -float(item.gross_incremental_value_aud or 0.0),
            tie_order[item.action],
        ),
    )
    for rank, item in enumerate(ranked, start=1):
        item.candidate_rank = rank
        item.ranking_score = item.gross_incremental_value_aud
        item.ranking_components = {
            "gross_incremental_value_aud": item.gross_incremental_value_aud,
            "reserve_gate_passed": (
                item.reserve_margin_after_kwh is None
                or item.reserve_margin_after_kwh >= -1e-9
            ),
        }
        item.tie_break_reason = "stable_action_precedence" if rank > 1 else None


def _current_state_blockers(
    observation: dict[str, Any] | None, *, created_at: datetime, freshness_minutes: int
) -> list[str]:
    if observation is None:
        return ["latest_observation_missing", "current_state_unavailable"]
    blockers: list[str] = []
    observed = _optional_utc(observation.get("observed_at_utc"))
    if observed is None:
        blockers.extend(["latest_observation_missing", "current_state_unavailable"])
    elif created_at - observed > timedelta(minutes=freshness_minutes):
        blockers.append("latest_observation_stale")
    if _number(observation.get("battery_soc_percent")) is None:
        blockers.append("battery_soc_missing")
    health = observation.get("health_domains_json") or {}
    telemetry = health.get("telemetry", {}) if isinstance(health, dict) else {}
    freshness = (
        telemetry.get("entity_freshness", {}) if isinstance(telemetry, dict) else {}
    )
    if any(
        value == "source_update_stale"
        for key, value in freshness.items()
        if "state_of_charge" in key
    ):
        blockers.append("battery_soc_stale")
    if observation.get("telemetry_is_healthy") is False:
        blockers.append("current_state_unavailable")
    if observation.get("sign_convention_status") != "confirmed":
        blockers.append("directional_flow_signs_unconfirmed")
    return list(dict.fromkeys(blockers))


def _price_intervals(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    try:
        parsed = native_json(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return (
        [dict(item) for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, list)
        else []
    )


def _forecast_energy(
    run: dict[str, Any] | None, *, start: datetime, end: datetime
) -> float | None:
    if run is None:
        return None
    total = 0.0
    covered = 0.0
    for point in run.get("points", []):
        point_start = _optional_utc(point.get("period_start_utc"))
        point_end = _optional_utc(point.get("period_end_utc"))
        expected = _number(point.get("expected_value"))
        if point_start is None or point_end is None or expected is None:
            continue
        overlap_start = max(start, point_start)
        overlap_end = min(end, point_end)
        seconds = max((overlap_end - overlap_start).total_seconds(), 0.0)
        if seconds:
            total += expected / 1000 * seconds / 3600
            covered += seconds
    required = max((end - start).total_seconds(), 0.0)
    return total if required > 0 and covered >= required - 1 else None


def _solar_context(
    observation: dict[str, Any] | None,
    created: datetime,
    *,
    timezone_name: str,
) -> dict[str, Any]:
    observation = observation or {}
    summary = _json_dict(observation.get("solcast_next_hour_kwh_json"))
    source = "solcast_next_hour"
    horizon = created + timedelta(hours=1) if summary else None
    if not summary:
        summary = _json_dict(observation.get("solcast_remaining_today_kwh_json"))
        source = "solcast_remaining_today"
        local_created = created.astimezone(ZoneInfo(timezone_name))
        horizon = (
            local_created.replace(
                hour=23, minute=59, second=59, microsecond=0
            ).astimezone(UTC)
            if summary
            else None
        )
    return {
        "source": source if summary else None,
        "p10_kwh": _number(summary.get("estimate10_kwh")),
        "p50_kwh": _number(summary.get("estimate_kwh")),
        "p90_kwh": _number(summary.get("estimate90_kwh")),
        "constraint_context": (
            "diagnostic_context_only_no_automatic_derating"
            if summary
            else "unavailable"
        ),
        "confidence_limit": "medium" if summary else "low",
        "horizon_end_utc": horizon,
    }


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    try:
        parsed = native_json(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _solar_energy_for_window(next_hour_p10: Any, duration_hours: float) -> float | None:
    value = _number(next_hour_p10)
    return value * min(max(duration_hours, 0), 1.0) if value is not None else None


def _interval_horizon(intervals: list[dict[str, Any]]) -> datetime | None:
    values = [_optional_utc(item.get("end_time")) for item in intervals]
    available = [value for value in values if value is not None]
    return max(available) if available else None


def _maximum_interval_price(
    intervals: list[dict[str, Any]], *, start: datetime, end: datetime | None
) -> float | None:
    if end is None or end <= start:
        return None
    values = []
    for item in intervals:
        interval_start = _optional_utc(item.get("start_time"))
        interval_end = _optional_utc(item.get("end_time"))
        price = _number(item.get("per_kwh"))
        if (
            interval_start is not None
            and interval_end is not None
            and price is not None
            and interval_end > start
            and interval_start < end
        ):
            values.append(price)
    return max(values) if values else None


def _forecast_identity(run: dict[str, Any] | None) -> dict[str, Any]:
    if run is None:
        return {}
    metadata = run.get("metadata_json") or {}
    return {
        "forecast_type": run.get("forecast_type"),
        "model_version": run.get("model_version"),
        "alignment_version": metadata.get("alignment_version"),
        "training_policy": metadata.get("training_policy"),
    }


def _minimum_horizon(*values: datetime | None) -> datetime | None:
    available = [value for value in values if value is not None]
    return min(available) if len(available) == len(values) else None


def _common_horizon(first: datetime | None, second: datetime | None) -> datetime | None:
    return min(first, second) if first is not None and second is not None else None


def _coverage_snapshot(value: PriceCoverage) -> dict[str, Any]:
    return {
        "coverage_percent": value.coverage_percent,
        "average_aud_per_kwh": value.weighted_average_aud_per_kwh,
        "horizon_end_utc": _iso(value.horizon_end_utc),
    }


def _assumption(
    name: str, value: Any, unit: str, source: str, classification: str
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "source": source,
        "classification": classification,
    }


def _hash_snapshot(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _outcome_number(value: Any, *, power: bool = False) -> float | None:
    number = _number(value)
    if number is None or not isfinite(number) or (power and number < 0):
        return None
    return number


def _integrate_outcome_power(
    samples: list[tuple[dict[str, Any], float]], field_name: str, coverage: float
) -> float | None:
    if coverage < 1.0 - 1e-9:
        return None
    total = 0.0
    for row, seconds in samples:
        power = _outcome_number(row.get(field_name), power=True)
        if power is None:
            return None
        total += power * seconds / 3_600_000
    return total


def _operator_intervention(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = []
    for row in rows:
        import_power = _number(row.get("grid_import_power_w")) or 0.0
        export_power = _number(row.get("grid_export_power_w")) or 0.0
        charge_power = _number(row.get("battery_charge_power_w")) or 0.0
        discharge_power = _number(row.get("battery_discharge_power_w")) or 0.0
        import_price = _number(row.get("amber_import_price_per_kwh"))
        export_price = _number(row.get("amber_export_price_per_kwh"))
        if (
            import_power >= 1500
            and charge_power >= 1000
            and import_price is not None
            and import_price <= 0.15
        ):
            evidence.append("grid_import_and_battery_charge_during_low_price")
        if (
            export_power >= 1500
            and discharge_power >= 1000
            and export_price is not None
            and export_price >= 0.30
        ):
            evidence.append("grid_export_and_battery_discharge_during_elevated_price")
    unique = sorted(set(evidence))
    return {
        "possible": bool(unique),
        "confidence": (
            "medium" if len(unique) >= 2 else ("low" if unique else "unavailable")
        ),
        "evidence": {
            "patterns": unique,
            "interpretation": (
                "Probable intervention evidence; operator intent is not proven."
            ),
        },
    }


def _positive_or_none(value: float) -> float | None:
    return value if value > 0 else None


def _number(value: Any) -> float | None:
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is None or result == result else None


def _optional_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return _utc(value)
    except (TypeError, ValueError):
        return None


def _utc(value: Any) -> datetime:
    return aware_datetime(value).astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None
