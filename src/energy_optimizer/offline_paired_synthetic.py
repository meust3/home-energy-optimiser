"""Pure, synthetic-only one-deviation experiments; no runtime/client imports.

All physical numbers are supplied assumptions. This module neither chooses an
action nor represents installed inverter firmware or historical operation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

IDENTITY = "offline-paired-synthetic-v1"
RELEASE_SHA = "a93532b9ad5d604ee69a8215bb8ee9b5482e7af4"
DESIGN_SHA = "68cc021a9bd55fed8f21a555687475bfbcf62b3dc3a35d9ef2630e2bbb5b041c"
ERRATUM_SHA = "6e6c6d81fc446f51e2528626a605a3e94212c92e1d43f874b68c24bc58c14060"
TERMINAL_TOLERANCE_KWH = 1e-6
NUMERICAL_EPSILON = 1e-9
MAX_INTERVALS = 4096
ACTIONS = frozenset(
    {
        "HOLD",
        "PRESERVE_BATTERY",
        "CHARGE_BATTERY_FROM_GRID",
        "DISCHARGE_FOR_SELF_CONSUMPTION",
    }
)
TOPOLOGY = "synthetic_ac_bus_independent_ports"


class AdmissionError(ValueError):
    """Specific input failures, suitable for a diagnostic-only result."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(", ".join(self.reasons))


@dataclass(frozen=True)
class Interval:
    start_utc: datetime
    end_utc: datetime
    value: float


@dataclass(frozen=True)
class Parameters:
    capacity_kwh: float
    physical_min_kwh: float
    policy_floor_kwh: float
    terminal_reserve_kwh: float
    charge_efficiency: float
    discharge_efficiency: float
    charge_limit_kw: float
    discharge_limit_kw: float
    import_limit_kw: float
    export_limit_kw: float
    topology: str
    flow_domain: str
    stored_energy_domain: str
    pv_abstraction: str
    curtailment_permitted: bool
    interval_interpretation: str


@dataclass(frozen=True)
class Schedule:
    action: str
    supplied_at_utc: datetime
    start_utc: datetime
    end_utc: datetime
    power_limit_kw: float
    energy_limit_ac_kwh: float


@dataclass(frozen=True)
class Sensitivities:
    terminal_lambda_aud_per_dc_kwh: float | None
    wear_aud_per_discharged_dc_kwh: float | None


@dataclass(frozen=True)
class SyntheticCase:
    case_id: str
    source_kind: str
    profile: str
    assumption_note: str
    source_design_sha256: str
    source_erratum_sha256: str
    decision_ready_at_utc: datetime
    comparison_start_utc: datetime
    comparison_end_utc: datetime
    initial_state_at_utc: datetime
    initial_energy_kwh: float
    parameters: Parameters
    schedule: Schedule
    load_kind: str
    household_load_kw: tuple[Interval, ...]
    fixed_ev_load_kw: tuple[Interval, ...]
    available_pv_kw: tuple[Interval, ...]
    import_price_aud_per_kwh: tuple[Interval, ...]
    export_price_aud_per_kwh: tuple[Interval, ...]
    sensitivities: Sensitivities


@dataclass(frozen=True)
class Step:
    start_utc: datetime
    end_utc: datetime
    action: str
    energy_start_kwh: float
    energy_end_kwh: float
    available_pv_kwh: float
    curtailed_pv_kwh: float
    load_kwh: float
    import_kwh: float
    export_kwh: float
    charge_ac_kwh: float
    discharge_ac_kwh: float
    unserved_load_kwh: float
    import_price: float
    export_price: float
    requested_action_ac_kwh: float
    delivered_action_ac_kwh: float
    limiting_reasons: tuple[str, ...]

    @property
    def cash_aud(self) -> float:
        return self.export_kwh * self.export_price - self.import_kwh * self.import_price


@dataclass(frozen=True)
class Ledger:
    label: str
    start_utc: datetime
    end_utc: datetime
    initial_energy_kwh: float
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Flows:
    """Common-domain flows: kWh for steps, kW for saturation-rate checks."""

    imports: float
    export: float
    charge: float
    discharge: float
    curtail: float
    unserved: float
    delivered: float
    limits: tuple[str, ...]


def json_value(value: Any) -> Any:
    """Canonical, finite JSON representation; invalid diagnostics stay missing."""
    if isinstance(value, datetime):
        return (
            value.isoformat()
            if value.tzinfo is None or value.utcoffset() is None
            else value.astimezone(UTC).isoformat()
        )
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def content_hash(value: Any) -> str:
    text = json.dumps(
        json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise AdmissionError(["invalid_timestamp_type"])
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionError(["invalid_timestamp"]) from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise AdmissionError(["timestamp_timezone_missing"])
    return result.astimezone(UTC)


def case_from_dict(raw: dict[str, Any]) -> SyntheticCase:
    """Strict schema: no defaults, production record readers or parameter repair."""
    try:
        values = dict(raw)
        for key in (
            "decision_ready_at_utc",
            "comparison_start_utc",
            "comparison_end_utc",
            "initial_state_at_utc",
        ):
            values[key] = _utc(values[key])
        values["parameters"] = Parameters(**values["parameters"])
        schedule = dict(values["schedule"])
        for key in ("supplied_at_utc", "start_utc", "end_utc"):
            schedule[key] = _utc(schedule[key])
        values["schedule"] = Schedule(**schedule)
        values["sensitivities"] = Sensitivities(**values["sensitivities"])
        for key in (
            "household_load_kw",
            "fixed_ev_load_kw",
            "available_pv_kw",
            "import_price_aud_per_kwh",
            "export_price_aud_per_kwh",
        ):
            values[key] = tuple(
                Interval(_utc(item["start_utc"]), _utc(item["end_utc"]), item["value"])
                for item in values[key]
                if _interval_keys(item)
            )
        return SyntheticCase(**values)
    except KeyError as exc:
        raise AdmissionError([f"missing_field:{exc.args[0]}"]) from exc
    except TypeError as exc:
        raise AdmissionError(["schema_fields_missing_or_unexpected"]) from exc


def _interval_keys(item: dict[str, Any]) -> bool:
    if set(item) != {"start_utc", "end_utc", "value"}:
        raise AdmissionError(["interval_fields_missing_or_unexpected"])
    return True


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def ceil_five_minutes(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AdmissionError(["timestamp_timezone_missing"])
    current = value.astimezone(UTC)
    boundary = current.replace(minute=current.minute // 5 * 5, second=0, microsecond=0)
    return boundary if current == boundary else boundary + timedelta(minutes=5)


def _parameter_reasons(p: Parameters) -> list[str]:
    reasons = []
    for name, value in asdict(p).items():
        if name in {
            "topology",
            "flow_domain",
            "stored_energy_domain",
            "pv_abstraction",
            "curtailment_permitted",
            "interval_interpretation",
        }:
            continue
        if not _finite(value) or value < 0:
            reasons.append(f"invalid_or_unknown_parameter:{name}")
    if reasons:
        return reasons
    if (
        not 0 <= p.physical_min_kwh <= p.policy_floor_kwh <= p.capacity_kwh
        or p.capacity_kwh <= 0
    ):
        reasons.append("inconsistent_physical_policy_bounds")
    if p.terminal_reserve_kwh != p.policy_floor_kwh:
        reasons.append("terminal_reserve_must_equal_frozen_floor")
    if not 0 < p.charge_efficiency <= 1 or not 0 < p.discharge_efficiency <= 1:
        reasons.append("efficiency_out_of_range")
    if p.topology != TOPOLOGY:
        reasons.append("unsupported_topology")
    if p.flow_domain != "AC_bus_kWh" or p.stored_energy_domain != "DC_stored_kWh":
        reasons.append("unsupported_energy_domain")
    if p.pv_abstraction != "available_exogenous_synthetic":
        reasons.append("unsupported_pv_abstraction")
    if p.interval_interpretation != "piecewise_constant_interval_average_kw":
        reasons.append("unsupported_interval_interpretation")
    if not isinstance(p.curtailment_permitted, bool):
        reasons.append("curtailment_permission_must_be_explicit_boolean")
    return reasons


def _coverage_reasons(
    name: str,
    series: tuple[Interval, ...],
    start: datetime,
    end: datetime,
    *,
    price: bool,
) -> list[str]:
    reasons = []
    if not series or len(series) > MAX_INTERVALS:
        return [f"missing_or_unbounded_series:{name}"]
    cursor = start
    previous_end = None
    for row in sorted(series, key=lambda item: item.start_utc):
        if not _finite(row.value) or (not price and row.value < 0):
            reasons.append(f"invalid_value:{name}")
        if row.end_utc <= row.start_utc:
            reasons.append(f"invalid_interval:{name}")
        if previous_end is not None and row.start_utc < previous_end:
            reasons.append(f"overlap_or_duplicate:{name}")
        previous_end = row.end_utc
        left, right = max(start, row.start_utc), min(end, row.end_utc)
        if right <= left:
            continue
        if left != cursor:
            reasons.append(f"coverage_gap:{name}")
        cursor = right
    if cursor != end:
        reasons.append(f"coverage_gap:{name}")
    return reasons


def validate_case(case: SyntheticCase, *, full_day: bool = True) -> None:
    reasons = _parameter_reasons(case.parameters)
    if case.source_kind != "deliberately_authored_synthetic":
        reasons.append("synthetic_authorship_required")
    if (
        case.source_design_sha256 != DESIGN_SHA
        or case.source_erratum_sha256 != ERRATUM_SHA
    ):
        reasons.append("source_artifact_identity_mismatch")
    if not case.case_id or not case.assumption_note:
        reasons.append("fixture_identity_and_assumption_note_required")
    if full_day and case.profile != "public_24h":
        reasons.append("public_evaluation_requires_24h_profile")
    start, end = case.comparison_start_utc, case.comparison_end_utc
    times = [
        start,
        end,
        case.initial_state_at_utc,
        case.decision_ready_at_utc,
        case.schedule.supplied_at_utc,
        case.schedule.start_utc,
        case.schedule.end_utc,
    ]
    series = [
        case.household_load_kw,
        case.fixed_ev_load_kw,
        case.available_pv_kw,
        case.import_price_aud_per_kwh,
        case.export_price_aud_per_kwh,
    ]
    times.extend(
        t for rows in series for row in rows for t in (row.start_utc, row.end_utc)
    )
    if any(
        not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
        for t in times
    ):
        raise AdmissionError(reasons + ["timestamp_timezone_missing"])
    if start != ceil_five_minutes(case.decision_ready_at_utc):
        reasons.append("comparison_start_not_ready_boundary")
    if case.initial_state_at_utc != start:
        reasons.append("initial_state_not_at_branch_point")
    if end <= start or (full_day and end - start != timedelta(hours=24)):
        reasons.append("invalid_comparison_horizon")
    if not _finite(case.initial_energy_kwh):
        reasons.append("invalid_initial_energy")
    elif (
        not reasons
        and not case.parameters.physical_min_kwh
        <= case.initial_energy_kwh
        <= case.parameters.capacity_kwh
    ):
        reasons.append("initial_energy_outside_physical_bounds")
    s = case.schedule
    if s.action not in ACTIONS:
        reasons.append("unsupported_action")
    if s.supplied_at_utc > case.decision_ready_at_utc:
        reasons.append("action_not_supplied_by_readiness")
    if s.end_utc <= s.start_utc:
        reasons.append("invalid_action_window")
    if any(not _finite(v) or v < 0 for v in (s.power_limit_kw, s.energy_limit_ac_kwh)):
        reasons.append("invalid_or_unknown_action_request")
    elif s.action in {"HOLD", "PRESERVE_BATTERY"} and (
        s.power_limit_kw != 0 or s.energy_limit_ac_kwh != 0
    ):
        reasons.append("non_energy_action_requires_zero_request")
    for name, value in asdict(case.sensitivities).items():
        if value is not None and (not _finite(value) or value < 0):
            reasons.append(f"invalid_sensitivity:{name}")
    if case.load_kind not in {"total_including_fixed_ev", "baseline_plus_fixed_ev"}:
        reasons.append("unsupported_load_semantics")
    if case.load_kind == "total_including_fixed_ev" and case.fixed_ev_load_kw:
        reasons.append("ev_would_be_double_counted")
    pairs = [
        ("household_load_kw", case.household_load_kw, False),
        ("available_pv_kw", case.available_pv_kw, False),
        ("import_price", case.import_price_aud_per_kwh, True),
        ("export_price", case.export_price_aud_per_kwh, True),
    ]
    if case.load_kind == "baseline_plus_fixed_ev":
        pairs.append(("fixed_ev_load_kw", case.fixed_ev_load_kw, False))
    for name, rows, price in pairs:
        reasons.extend(_coverage_reasons(name, rows, start, end, price=price))
    if sum(len(rows) for _, rows, _ in pairs) > MAX_INTERVALS:
        reasons.append("input_interval_bound_exceeded")
    if reasons:
        raise AdmissionError(reasons)


def _value_at(series: tuple[Interval, ...], at: datetime) -> float:
    return next(row.value for row in series if row.start_utc <= at < row.end_utc)


def _boundaries(case: SyntheticCase) -> list[datetime]:
    start, end = case.comparison_start_utc, case.comparison_end_utc
    points = {start, end}
    for rows in (
        case.household_load_kw,
        case.fixed_ev_load_kw,
        case.available_pv_kw,
        case.import_price_aud_per_kwh,
        case.export_price_aud_per_kwh,
    ):
        points.update(
            t for row in rows for t in (row.start_utc, row.end_utc) if start < t < end
        )
    points.update(
        t for t in (case.schedule.start_utc, case.schedule.end_utc) if start < t < end
    )
    # Exhaustion is a fixed schedule boundary, not rescheduled by delivery.
    if case.schedule.power_limit_kw > 0:
        hours = case.schedule.energy_limit_ac_kwh / case.schedule.power_limit_kw
        if (
            hours
            < (
                min(end, case.schedule.end_utc) - case.schedule.start_utc
            ).total_seconds()
            / 3600
        ):
            exhaustion = case.schedule.start_utc + timedelta(hours=hours)
            if start < exhaustion < min(end, case.schedule.end_utc):
                points.add(exhaustion)
    return sorted(points)


def _requested(case: SyntheticCase, left: datetime, right: datetime) -> float:
    s = case.schedule
    if s.action not in {"CHARGE_BATTERY_FROM_GRID", "DISCHARGE_FOR_SELF_CONSUMPTION"}:
        return 0.0
    elapsed = max((left - s.start_utc).total_seconds() / 3600, 0)
    remaining = max(s.energy_limit_ac_kwh - elapsed * s.power_limit_kw, 0)
    return min(s.power_limit_kw * (right - left).total_seconds() / 3600, remaining)


def _step(
    case: SyntheticCase,
    energy: float,
    left: datetime,
    right: datetime,
    *,
    alternative: bool,
) -> Step:
    p, s = case.parameters, case.schedule
    hours = (right - left).total_seconds() / 3600
    active = alternative and s.start_utc <= left < s.end_utc
    action = s.action if active else "HOLD"
    request = _requested(case, left, right) if active else 0.0
    pv = _value_at(case.available_pv_kw, left) * hours
    load = _value_at(case.household_load_kw, left) * hours
    if case.load_kind == "baseline_plus_fixed_ev":
        load += _value_at(case.fixed_ev_load_kw, left) * hours
    flows = _route(
        p,
        load,
        pv,
        action,
        request,
        hours,
        headroom_budget=max(p.capacity_kwh - energy, 0) / p.charge_efficiency,
        available_budget=max(energy - p.policy_floor_kwh, 0) * p.discharge_efficiency,
    )
    after = (
        energy
        + p.charge_efficiency * flows.charge
        - flows.discharge / p.discharge_efficiency
    )
    return Step(
        left,
        right,
        action,
        energy,
        after,
        pv,
        flows.curtail,
        load,
        flows.imports,
        flows.export,
        flows.charge,
        flows.discharge,
        flows.unserved,
        _value_at(case.import_price_aud_per_kwh, left),
        _value_at(case.export_price_aud_per_kwh, left),
        request,
        flows.delivered,
        flows.limits,
    )


def _route(
    p: Parameters,
    load: float,
    pv: float,
    action: str,
    request: float,
    hours: float,
    *,
    headroom_budget: float,
    available_budget: float,
) -> Flows:
    solar_to_house = min(pv, load)
    surplus, deficit = pv - solar_to_house, load - solar_to_house
    charge = min(surplus, p.charge_limit_kw * hours, headroom_budget)
    export = min(surplus - charge, p.export_limit_kw * hours)
    curtail = surplus - charge - export
    discharge = 0.0
    if action not in {"PRESERVE_BATTERY", "CHARGE_BATTERY_FROM_GRID"}:
        discharge = min(deficit, p.discharge_limit_kw * hours, available_budget)
        if action == "DISCHARGE_FOR_SELF_CONSUMPTION":
            discharge = min(discharge, request)
    imports = min(deficit - discharge, p.import_limit_kw * hours)
    unserved = deficit - discharge - imports
    delivered = 0.0
    limits = []
    if action == "CHARGE_BATTERY_FROM_GRID":
        budgets = {
            "site_import_limit": p.import_limit_kw * hours - imports,
            "charge_limit": p.charge_limit_kw * hours - charge,
            "capacity_headroom": headroom_budget - charge,
            "opposing_export": 0.0 if export > NUMERICAL_EPSILON else request,
        }
        delivered = max(min(request, *budgets.values()), 0)
        limits = [
            key
            for key, budget in budgets.items()
            if budget + NUMERICAL_EPSILON < request
        ]
        imports += delivered
        charge += delivered
    elif action == "DISCHARGE_FOR_SELF_CONSUMPTION":
        delivered = discharge
        budgets = {
            "net_household_deficit": deficit,
            "discharge_limit": p.discharge_limit_kw * hours,
            "policy_floor": available_budget,
        }
        limits = [
            key
            for key, budget in budgets.items()
            if budget + NUMERICAL_EPSILON < request
        ]
    return Flows(
        imports, export, charge, discharge, curtail, unserved, delivered, tuple(limits)
    )


def _saturation_end(
    case: SyntheticCase,
    energy: float,
    left: datetime,
    right: datetime,
    *,
    alternative: bool,
) -> datetime:
    """End a constant-power phase when its modelled capacity/floor is reached."""
    p, s = case.parameters, case.schedule
    active = alternative and s.start_utc <= left < s.end_utc
    action = s.action if active else "HOLD"
    request_kw = (
        _requested(case, left, right) / ((right - left).total_seconds() / 3600)
        if active
        else 0
    )
    load = _value_at(case.household_load_kw, left)
    if case.load_kind == "baseline_plus_fixed_ev":
        load += _value_at(case.fixed_ev_load_kw, left)
    # Instantaneous headroom permission; finite declared port power bounds it.
    rate = _route(
        p,
        load,
        _value_at(case.available_pv_kw, left),
        action,
        request_kw,
        1,
        headroom_budget=(
            p.charge_limit_kw if energy < p.capacity_kwh - NUMERICAL_EPSILON else 0
        ),
        available_budget=(
            p.discharge_limit_kw
            if energy > p.policy_floor_kwh + NUMERICAL_EPSILON
            else 0
        ),
    )
    dc_kw = p.charge_efficiency * rate.charge - rate.discharge / p.discharge_efficiency
    if dc_kw > 0:
        hours = max(p.capacity_kwh - energy, 0) / dc_kw
    elif dc_kw < 0:
        hours = max(energy - p.policy_floor_kwh, 0) / -dc_kw
    else:
        return right
    if hours >= (right - left).total_seconds() / 3600:
        return right
    hit = left + timedelta(hours=hours)
    return min(right, max(hit, left + timedelta(microseconds=1)))


def _simulate_pair(case: SyntheticCase) -> tuple[Ledger, Ledger]:
    energies = [case.initial_energy_kwh, case.initial_energy_kwh]
    traces: list[list[Step]] = [[], []]
    boundaries = _boundaries(case)
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        cursor = left
        while cursor < right:
            end = min(
                _saturation_end(case, energies[i], cursor, right, alternative=bool(i))
                for i in (0, 1)
            )
            for i in (0, 1):
                row = _step(case, energies[i], cursor, end, alternative=bool(i))
                traces[i].append(row)
                energies[i] = row.energy_end_kwh
            if len(traces[0]) > MAX_INTERVALS:
                raise AdmissionError(["elementary_interval_bound_exceeded"])
            cursor = end
    return (
        Ledger(
            "reference",
            case.comparison_start_utc,
            case.comparison_end_utc,
            case.initial_energy_kwh,
            tuple(traces[0]),
        ),
        Ledger(
            "action",
            case.comparison_start_utc,
            case.comparison_end_utc,
            case.initial_energy_kwh,
            tuple(traces[1]),
        ),
    )


def _ledger_reasons(ledger: Ledger, p: Parameters) -> list[str]:
    reasons = []
    cursor, energy = ledger.start_utc, ledger.initial_energy_kwh
    if not ledger.steps or len(ledger.steps) > MAX_INTERVALS:
        return ["missing_or_unbounded_ledger"]
    times = [ledger.start_utc, ledger.end_utc] + [
        t for row in ledger.steps for t in (row.start_utc, row.end_utc)
    ]
    if any(
        not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
        for t in times
    ):
        return [f"{ledger.label}:invalid_ledger_timestamp"]
    if (
        not _finite(ledger.initial_energy_kwh)
        or not p.physical_min_kwh <= ledger.initial_energy_kwh <= p.capacity_kwh
    ):
        return [f"{ledger.label}:invalid_initial_energy"]
    for index, row in enumerate(ledger.steps):
        prefix = f"{ledger.label}:interval_{index}:"
        if row.start_utc != cursor or row.end_utc <= row.start_utc:
            reasons.append(prefix + "ledger_coverage_gap_or_overlap")
        cursor = row.end_utc
        numbers = [
            v
            for key, v in asdict(row).items()
            if key not in {"start_utc", "end_utc", "action", "limiting_reasons"}
        ]
        if any(not _finite(v) for v in numbers):
            reasons.append(prefix + "nonfinite_ledger")
            continue
        if not _finite(row.cash_aud):
            reasons.append(prefix + "nonfinite_ledger")
            continue
        if abs(row.energy_start_kwh - energy) > NUMERICAL_EPSILON:
            reasons.append(prefix + "state_discontinuity")
        energy = row.energy_end_kwh
        flows = [
            row.available_pv_kwh,
            row.curtailed_pv_kwh,
            row.load_kwh,
            row.import_kwh,
            row.export_kwh,
            row.charge_ac_kwh,
            row.discharge_ac_kwh,
            row.unserved_load_kwh,
            row.requested_action_ac_kwh,
            row.delivered_action_ac_kwh,
        ]
        if min(flows) < -NUMERICAL_EPSILON:
            reasons.append(prefix + "negative_energy")
        if row.unserved_load_kwh > row.load_kwh + NUMERICAL_EPSILON:
            reasons.append(prefix + "unserved_exceeds_demand")
        if (
            row.delivered_action_ac_kwh
            > row.requested_action_ac_kwh + NUMERICAL_EPSILON
        ):
            reasons.append(prefix + "delivery_exceeds_request")
        ac = (
            row.available_pv_kwh
            - row.curtailed_pv_kwh
            + row.import_kwh
            + row.discharge_ac_kwh
            - (
                row.load_kwh
                - row.unserved_load_kwh
                + row.export_kwh
                + row.charge_ac_kwh
            )
        )
        dc = (
            row.energy_end_kwh
            - row.energy_start_kwh
            - p.charge_efficiency * row.charge_ac_kwh
            + row.discharge_ac_kwh / p.discharge_efficiency
        )
        if abs(ac) > NUMERICAL_EPSILON or abs(dc) > NUMERICAL_EPSILON:
            reasons.append(prefix + "energy_balance_failed")
        if row.curtailed_pv_kwh > row.available_pv_kwh + NUMERICAL_EPSILON:
            reasons.append(prefix + "curtailment_exceeds_available_pv")
        if row.unserved_load_kwh > NUMERICAL_EPSILON:
            reasons.append(prefix + "unserved_load")
        if row.curtailed_pv_kwh > NUMERICAL_EPSILON and not p.curtailment_permitted:
            reasons.append(prefix + "curtailment_not_permitted")
        if (
            min(row.energy_start_kwh, row.energy_end_kwh)
            < p.physical_min_kwh - NUMERICAL_EPSILON
            or max(row.energy_start_kwh, row.energy_end_kwh)
            > p.capacity_kwh + NUMERICAL_EPSILON
        ):
            reasons.append(prefix + "physical_state_bound_failed")
        if (
            row.discharge_ac_kwh > NUMERICAL_EPSILON
            and row.energy_end_kwh < p.policy_floor_kwh - NUMERICAL_EPSILON
        ):
            reasons.append(prefix + "additional_policy_shortfall")
        if (
            row.import_kwh > NUMERICAL_EPSILON
            and row.export_kwh > NUMERICAL_EPSILON
            or row.charge_ac_kwh > NUMERICAL_EPSILON
            and row.discharge_ac_kwh > NUMERICAL_EPSILON
        ):
            reasons.append(prefix + "opposing_flows")
        hours = (row.end_utc - row.start_utc).total_seconds() / 3600
        for name, value, limit in (
            ("import", row.import_kwh, p.import_limit_kw),
            ("export", row.export_kwh, p.export_limit_kw),
            ("charge", row.charge_ac_kwh, p.charge_limit_kw),
            ("discharge", row.discharge_ac_kwh, p.discharge_limit_kw),
        ):
            if value > limit * hours + NUMERICAL_EPSILON:
                reasons.append(prefix + name + "_limit_failed")
    if cursor != ledger.end_utc:
        reasons.append(f"{ledger.label}:ledger_coverage_incomplete")
    return reasons


def _summary(ledger: Ledger, p: Parameters) -> dict[str, Any]:
    rows = ledger.steps
    state = rows[-1].energy_end_kwh if rows else ledger.initial_energy_kwh
    discharge_dc = sum(r.discharge_ac_kwh / p.discharge_efficiency for r in rows)
    ac_residuals = [
        r.available_pv_kwh
        - r.curtailed_pv_kwh
        + r.import_kwh
        + r.discharge_ac_kwh
        - (r.load_kwh - r.unserved_load_kwh + r.export_kwh + r.charge_ac_kwh)
        for r in rows
    ]
    dc_residuals = [
        r.energy_end_kwh
        - r.energy_start_kwh
        - p.charge_efficiency * r.charge_ac_kwh
        + r.discharge_ac_kwh / p.discharge_efficiency
        for r in rows
    ]
    energies = [ledger.initial_energy_kwh] + [r.energy_end_kwh for r in rows]
    return {
        "cash_aud": sum(r.cash_aud for r in rows),
        "terminal_energy_kwh": state,
        "terminal_margin_kwh": state - p.terminal_reserve_kwh,
        "initial_policy_shortfall_kwh": max(
            p.policy_floor_kwh - ledger.initial_energy_kwh, 0
        ),
        "minimum_policy_margin_kwh": min(energies) - p.policy_floor_kwh,
        "additional_policy_shortfall_kwh": max(
            min(ledger.initial_energy_kwh, p.policy_floor_kwh) - min(energies), 0
        ),
        "discharged_dc_kwh": discharge_dc,
        "loss_kwh": sum(
            (1 - p.charge_efficiency) * r.charge_ac_kwh
            + (1 / p.discharge_efficiency - 1) * r.discharge_ac_kwh
            for r in rows
        ),
        "import_kwh": sum(r.import_kwh for r in rows),
        "export_kwh": sum(r.export_kwh for r in rows),
        "curtailed_pv_kwh": sum(r.curtailed_pv_kwh for r in rows),
        "unserved_load_kwh": sum(r.unserved_load_kwh for r in rows),
        "requested_action_ac_kwh": sum(r.requested_action_ac_kwh for r in rows),
        "delivered_action_ac_kwh": sum(r.delivered_action_ac_kwh for r in rows),
        "maximum_served_ac_balance_residual_kwh": max(
            map(abs, ac_residuals), default=0
        ),
        "maximum_dc_balance_residual_kwh": max(map(abs, dc_residuals), default=0),
    }


def compare_ledgers(
    reference: Ledger, alternative: Ledger, p: Parameters, sensitivities: Sensitivities
) -> dict[str, Any]:
    """Also accepts an explicitly supplied synthetic ledger (native witness B).

    This checks ledgers; it contains no export or deferred-export dispatcher.
    """
    parameter_errors = _parameter_reasons(p)
    if parameter_errors:
        return _unavailable_comparison(parameter_errors)
    for name, value in asdict(sensitivities).items():
        if value is not None and (not _finite(value) or value < 0):
            return _unavailable_comparison([f"invalid_sensitivity:{name}"])
    reference_errors = _ledger_reasons(reference, p)
    alternative_errors = _ledger_reasons(alternative, p)
    reasons = reference_errors + alternative_errors
    if any(
        "nonfinite_ledger" in r
        or "invalid_initial_energy" in r
        or "invalid_ledger_timestamp" in r
        for r in reasons
    ):
        return _unavailable_comparison(reasons)
    if (reference.start_utc, reference.end_utc, reference.initial_energy_kwh) != (
        alternative.start_utc,
        alternative.end_utc,
        alternative.initial_energy_kwh,
    ):
        reasons.append("starting_conditions_or_horizons_differ")
    external_reference = [
        (
            r.start_utc,
            r.end_utc,
            r.load_kwh,
            r.available_pv_kwh,
            r.import_price,
            r.export_price,
        )
        for r in reference.steps
    ]
    external_alternative = [
        (
            r.start_utc,
            r.end_utc,
            r.load_kwh,
            r.available_pv_kwh,
            r.import_price,
            r.export_price,
        )
        for r in alternative.steps
    ]
    if external_reference != external_alternative:
        reasons.append("external_inputs_or_interval_partition_differ")
    ref, alt = _summary(reference, p), _summary(alternative, p)
    ref.update(
        trajectory_feasible=not reference_errors,
        trajectory_infeasibility_reasons=reference_errors,
    )
    alt.update(
        trajectory_feasible=not alternative_errors,
        trajectory_infeasibility_reasons=alternative_errors,
    )
    delta_cash = alt["cash_aud"] - ref["cash_aud"]
    delta_energy = alt["terminal_energy_kwh"] - ref["terminal_energy_kwh"]
    if abs(delta_energy) > TERMINAL_TOLERANCE_KWH:
        reasons.append("terminal_energy_unmatched")
    for label, summary in (("reference", ref), ("action", alt)):
        if summary["terminal_margin_kwh"] < -NUMERICAL_EPSILON:
            reasons.append(label + ":terminal_reserve_not_met")
    lam = sensitivities.terminal_lambda_aud_per_dc_kwh
    wear = sensitivities.wear_aud_per_discharged_dc_kwh
    wear_delta = (
        None
        if wear is None
        else wear * (alt["discharged_dc_kwh"] - ref["discharged_dc_kwh"])
    )
    terminal_adjustment = None if lam is None else lam * delta_energy
    return json_value(
        {
            "ledger_comparison_admitted": True,
            "reference": ref,
            "action": alt,
            "diagnostic_incremental_cash_aud": delta_cash,
            "diagnostic_terminal_energy_difference_kwh": delta_energy,
            "primary_comparative_gross_value_aud": None if reasons else delta_cash,
            "primary_unavailable_reasons": list(dict.fromkeys(reasons)),
            "terminal_equality_tolerance_kwh": TERMINAL_TOLERANCE_KWH,
            "terminal_residual_retained_kwh": delta_energy,
            "wear_status": (
                "not_modelled" if wear is None else "explicit_synthetic_sensitivity"
            ),
            "sensitivities": {
                "terminal_lambda_aud_per_dc_kwh": lam,
                "wear_aud_per_discharged_dc_kwh": wear,
                "terminal_adjustment_aud": terminal_adjustment,
                "wear_difference_aud": wear_delta,
                "cash_plus_terminal_aud": (
                    None if lam is None else delta_cash + terminal_adjustment
                ),
                "cash_less_wear_aud": None if wear is None else delta_cash - wear_delta,
                "cash_plus_terminal_less_wear_aud": (
                    None
                    if lam is None or wear is None
                    else delta_cash + terminal_adjustment - wear_delta
                ),
                "does_not_restore_primary_eligibility": True,
            },
            "trace": {
                "reference": [_trace(r, p) for r in reference.steps],
                "action": [_trace(r, p) for r in alternative.steps],
            },
        }
    )


def _unavailable_comparison(reasons: list[str]) -> dict[str, Any]:
    return {
        "ledger_comparison_admitted": False,
        "primary_comparative_gross_value_aud": None,
        "diagnostic_incremental_cash_aud": None,
        "diagnostic_terminal_energy_difference_kwh": None,
        "primary_unavailable_reasons": list(dict.fromkeys(reasons)),
    }


def _trace(row: Step, p: Parameters) -> dict[str, Any]:
    used_pv = row.available_pv_kwh - row.curtailed_pv_kwh
    full_ac_residual = (
        used_pv
        + row.import_kwh
        + row.discharge_ac_kwh
        - row.load_kwh
        - row.export_kwh
        - row.charge_ac_kwh
    )
    return asdict(row) | {
        "cash_aud": row.cash_aud,
        "used_pv_kwh": used_pv,
        "served_load_kwh": row.load_kwh - row.unserved_load_kwh,
        "discharged_dc_kwh": row.discharge_ac_kwh / p.discharge_efficiency,
        "loss_kwh": (1 - p.charge_efficiency) * row.charge_ac_kwh
        + (1 / p.discharge_efficiency - 1) * row.discharge_ac_kwh,
        "full_demand_ac_balance_residual_kwh": full_ac_residual,
        "served_demand_ac_balance_residual_kwh": full_ac_residual
        + row.unserved_load_kwh,
        "dc_balance_residual_kwh": row.energy_end_kwh
        - row.energy_start_kwh
        - p.charge_efficiency * row.charge_ac_kwh
        + row.discharge_ac_kwh / p.discharge_efficiency,
    }


def _evaluate(case: SyntheticCase, *, full_day: bool) -> dict[str, Any]:
    base = {
        "comparison_identity": IDENTITY,
        "release_reference_sha": RELEASE_SHA,
        "source_design_sha256": case.source_design_sha256,
        "source_erratum_sha256": case.source_erratum_sha256,
        "case_id": case.case_id,
        "profile": case.profile,
        "input_sha256": content_hash(asdict(case)),
        "assumptions_sha256": content_hash(asdict(case.parameters)),
        "frozen_schedule_sha256": content_hash(asdict(case.schedule)),
        "information_classes": {
            "decision_inputs": "supplied_frozen_schedule",
            "evaluation_scenario": "supplied_synthetic_exogenous",
            "initial_state": "explicit_at_common_branch_point",
        },
        "observed_accounting": "not_evaluated",
        "expected_candidate_value": "not_rewritten",
        "historical_selected_policy_performance": "not_established",
        "overlapping_comparisons_are_non_additive": True,
        "limitations": [
            "synthetic_independent_ac_ports_not_goodwe_firmware",
            "variable_energy_only_fixed_charges_taxes_other_tariff_components_excluded",
            "no_realised_savings_or_optimality_claim",
        ],
    }
    try:
        validate_case(case, full_day=full_day)
    except AdmissionError as exc:
        return json_value(
            base
            | {
                "admitted": False,
                "primary_comparative_gross_value_aud": None,
                "primary_unavailable_reasons": list(exc.reasons),
                "diagnostic_incremental_cash_aud": None,
                "diagnostic_terminal_energy_difference_kwh": None,
            }
        )
    try:
        reference, alternative = _simulate_pair(case)
    except AdmissionError as exc:
        return base | _unavailable_comparison(list(exc.reasons)) | {"admitted": False}
    comparison = compare_ledgers(
        reference, alternative, case.parameters, case.sensitivities
    )
    if not comparison["ledger_comparison_admitted"]:
        return base | comparison | {"admitted": False}
    start, end = case.comparison_start_utc, case.comparison_end_utc
    effective_start = max(start, case.schedule.start_utc)
    effective_end = min(end, case.schedule.end_utc)
    return json_value(
        base
        | comparison
        | {
            "admitted": True,
            "assumption_note": case.assumption_note,
            "parameters": asdict(case.parameters),
            "coverage": "complete_valid_common_inputs",
            "timing": {
                "decision_ready_at_utc": case.decision_ready_at_utc,
                "comparison_start_utc": start,
                "comparison_end_utc": end,
                "initial_state_at_utc": case.initial_state_at_utc,
                "supplied_schedule": asdict(case.schedule),
                "effective_action_start_utc": (
                    effective_start if effective_end > effective_start else None
                ),
                "effective_action_end_utc": (
                    effective_end if effective_end > effective_start else None
                ),
            },
            "schedule_delivery_status": (
                "expired_or_outside_horizon"
                if effective_end <= effective_start
                else (
                    "constrained_no_catch_up"
                    if comparison["action"]["delivered_action_ac_kwh"]
                    + NUMERICAL_EPSILON
                    < comparison["action"]["requested_action_ac_kwh"]
                    else "delivered_or_non_energy_action"
                )
            ),
            "requested_energy_lost_before_branch_point_ac_kwh": min(
                case.schedule.energy_limit_ac_kwh,
                max((start - case.schedule.start_utc).total_seconds() / 3600, 0)
                * case.schedule.power_limit_kw,
            ),
        }
    )


def evaluate(case: SyntheticCase) -> dict[str, Any]:
    """Public synthetic evaluation: aligned readiness and exactly 24 hours."""
    return _evaluate(case, full_day=True)
