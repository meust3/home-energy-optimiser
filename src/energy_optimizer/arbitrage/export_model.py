"""Battery-AC export research v1, with explicit shared-envelope hypotheses.

PV AC first, household service first, no simultaneous charge/discharge. Gross PV
AC plus battery AC discharge shares the supplied output envelope. Charging has a
separately supplied input envelope. These are model hypotheses, not GoodWe limits.
The frozen kernel owns base routing, conversions, accounting and eligibility.
"""

import math
from dataclasses import dataclass, replace
from datetime import timedelta

from energy_optimizer import offline_paired_synthetic as core

VERSION = "battery-ac-export-model-candidate-v1"


@dataclass(frozen=True)
class SharedEnvelope:
    output_ac_kw: float
    charge_ac_kw: float
    site_export_caps_kw: tuple[core.Interval, ...]
    assumption_id: str

    def __post_init__(self):
        if not self.assumption_id or any(
            not math.isfinite(v) or v < 0
            for v in (self.output_ac_kw, self.charge_ac_kw)
        ):
            raise ValueError("explicit_shared_envelope_required")


def _epoch(case, envelope, at, end, energy, action, request_kw):
    """Reuse the frozen step, then add only explicitly discretionary AC export."""
    pv_kw = core._value_at(case.available_pv_kw, at)
    clipped_pv_kw = min(pv_kw, envelope.output_ac_kw)
    cap = core._value_at(envelope.site_export_caps_kw, at)
    p = replace(
        case.parameters,
        export_limit_kw=min(case.parameters.export_limit_kw, cap),
        discharge_limit_kw=min(
            case.parameters.discharge_limit_kw,
            max(envelope.output_ac_kw - clipped_pv_kw, 0),
        ),
        charge_limit_kw=min(case.parameters.charge_limit_kw, envelope.charge_ac_kw),
    )
    virtual = replace(
        case,
        parameters=p,
        available_pv_kw=(core.Interval(at, end, clipped_pv_kw),),
        schedule=core.Schedule(
            (
                "DISCHARGE_FOR_SELF_CONSUMPTION"
                if action == "EXPORT_BATTERY_AC"
                else action
            ),
            at,
            at,
            end,
            request_kw,
            request_kw * (end - at).total_seconds() / 3600,
        ),
    )
    base = core._step(virtual, energy, at, end, alternative=True)
    extra = 0.0
    hours = (end - at).total_seconds() / 3600
    if action == "EXPORT_BATTERY_AC" and base.charge_ac_kwh <= core.NUMERICAL_EPSILON:
        extra = max(
            0,
            min(
                request_kw * hours - base.discharge_ac_kwh,
                p.discharge_limit_kw * hours - base.discharge_ac_kwh,
                max(energy - p.policy_floor_kwh, 0) * p.discharge_efficiency
                - base.discharge_ac_kwh,
                p.export_limit_kw * hours - base.export_kwh,
            ),
        )
    return replace(
        base,
        action=action,
        energy_end_kwh=base.energy_end_kwh - extra / p.discharge_efficiency,
        export_kwh=base.export_kwh + extra,
        discharge_ac_kwh=base.discharge_ac_kwh + extra,
        available_pv_kwh=pv_kw * hours,
        curtailed_pv_kwh=base.curtailed_pv_kwh + (pv_kw - clipped_pv_kw) * hours,
        delivered_action_ac_kwh=(
            base.discharge_ac_kwh + extra
            if action == "EXPORT_BATTERY_AC"
            else base.delivered_action_ac_kwh
        ),
        requested_action_ac_kwh=request_kw * hours,
    )


def simulate(case, *, envelope, action):
    """Separate model identity; original four-action fixture contract untouched."""
    if action not in core.ACTIONS | {"EXPORT_BATTERY_AC"}:
        raise ValueError("unsupported_export_model_action")
    reasons = core._parameter_reasons(case.parameters)
    for name, series, price in (
        ("load", case.household_load_kw, False),
        ("pv", case.available_pv_kw, False),
        ("import", case.import_price_aud_per_kwh, True),
        ("export", case.export_price_aud_per_kwh, True),
        ("dynamic_cap", envelope.site_export_caps_kw, False),
    ):
        reasons += core._coverage_reasons(
            name,
            series,
            case.comparison_start_utc,
            case.comparison_end_utc,
            price=price,
        )
    if case.load_kind == "baseline_plus_fixed_ev":
        reasons += core._coverage_reasons(
            "ev",
            case.fixed_ev_load_kw,
            case.comparison_start_utc,
            case.comparison_end_utc,
            price=False,
        )
    if (
        not math.isfinite(case.initial_energy_kwh)
        or not case.parameters.physical_min_kwh
        <= case.initial_energy_kwh
        <= case.parameters.capacity_kwh
    ):
        reasons.append("initial_energy_outside_bounds")
    if action == "EXPORT_BATTERY_AC" and (
        case.schedule.power_limit_kw > 2 or case.schedule.energy_limit_ac_kwh > 1
    ):
        reasons.append("diagnostic_request_scale_exceeded")
    if reasons:
        raise core.AdmissionError(reasons)
    boundaries = sorted(
        set(core._boundaries(case))
        | {
            t
            for p in envelope.site_export_caps_kw
            for t in (p.start_utc, p.end_utc)
            if case.comparison_start_utc < t < case.comparison_end_utc
        }
    )
    energy, steps = case.initial_energy_kwh, []
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        cursor = left
        while cursor < right:
            active = case.schedule.start_utc <= cursor < case.schedule.end_utc
            epoch_action = action if active else "HOLD"
            elapsed = max((cursor - case.schedule.start_utc).total_seconds() / 3600, 0)
            request_kw = (
                case.schedule.power_limit_kw
                if elapsed * case.schedule.power_limit_kw
                < case.schedule.energy_limit_ac_kwh - 1e-9
                else 0
            )
            if epoch_action in {"HOLD", "PRESERVE_BATTERY"}:
                request_kw = 0
            # Probe the constant-flow phase with enough hypothetical inventory to
            # avoid clipping its RATE; restore real inventory for the actual step.
            probe_p = replace(
                case.parameters,
                capacity_kwh=max(case.parameters.capacity_kwh, energy + 1000),
            )
            probe_case = replace(case, parameters=probe_p)
            probe_energy = (
                energy
                if energy <= case.parameters.policy_floor_kwh + 1e-9
                else energy + 100
            )
            probe = _epoch(
                probe_case,
                envelope,
                cursor,
                right,
                probe_energy,
                epoch_action,
                request_kw,
            )
            hours = (right - cursor).total_seconds() / 3600
            dc_rate = (probe.energy_end_kwh - probe.energy_start_kwh) / hours
            target = (
                case.parameters.capacity_kwh
                if dc_rate > 0
                else case.parameters.policy_floor_kwh
            )
            hit_hours = (target - energy) / dc_rate if dc_rate != 0 else hours
            end = (
                right
                if hit_hours >= hours or hit_hours <= 0
                else cursor + timedelta(hours=hit_hours)
            )
            end = min(right, max(end, cursor + timedelta(microseconds=1)))
            row = _epoch(case, envelope, cursor, end, energy, epoch_action, request_kw)
            if (
                not case.parameters.physical_min_kwh - 1e-9
                <= row.energy_end_kwh
                <= case.parameters.capacity_kwh + 1e-9
            ):
                raise ValueError("export_energy_constraint")
            if row.unserved_load_kwh > 1e-9:
                raise ValueError("export_unserved_load")
            steps.append(row)
            if len(steps) > core.MAX_INTERVALS:
                raise ValueError("export_interval_bound")
            energy, cursor = row.energy_end_kwh, end
    return core.Ledger(
        action,
        case.comparison_start_utc,
        case.comparison_end_utc,
        case.initial_energy_kwh,
        tuple(steps),
    )


def compare(case, envelope, *, action="EXPORT_BATTERY_AC"):
    reference = simulate(case, envelope=envelope, action="HOLD")
    alternative = simulate(case, envelope=envelope, action=action)
    # Base comparator intentionally rejects a new action identifier. Audit the
    # physical fields separately and retain v1 terminal/reserve gates explicitly.
    from energy_optimizer.arbitrage.core_bridge import reconcile

    audits = [reconcile(path, case.parameters) for path in (reference, alternative)]
    reasons = []
    delta = alternative.steps[-1].energy_end_kwh - reference.steps[-1].energy_end_kwh
    if abs(delta) > 1e-6:
        reasons.append("terminal_energy_unmatched")
    if (
        min(path.steps[-1].energy_end_kwh for path in (reference, alternative))
        < case.parameters.terminal_reserve_kwh - 1e-9
    ):
        reasons.append("terminal_reserve_shortfall")
    cash = audits[0]["cost_aud"] - audits[1]["cost_aud"]
    return {
        "version": VERSION,
        "setpoint_domain": "battery_delivered_AC_kw",
        "diagnostic_cash_difference_aud": cash,
        "terminal_delta_stored_kwh": delta,
        "primary_conditional_value_aud": cash if not reasons else None,
        "primary_unavailable_reasons": reasons,
        "reference": reference,
        "alternative": alternative,
        "audits": audits,
        "execution": "disabled; effective installed export permission unknown",
    }
