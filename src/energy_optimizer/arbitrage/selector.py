"""Pure decision-time selector. This module cannot consume OutcomeContext."""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime, timedelta

from energy_optimizer.arbitrage.core_bridge import CORE_SHA, estimate, parameters
from energy_optimizer.arbitrage.decision_types import (
    DecisionContext,
    SelectionReceipt,
    canonical,
    digest,
)

POLICY_VERSION = "conditional-forecast-rpg-selector-v1"
TOLERANCE = 1e-8
POLICY = {
    "version": POLICY_VERSION,
    "cash_tolerance_aud": TOLERANCE,
    "terminal_tolerance_kwh": 1e-6,
    "energy_tolerance_kwh": 1e-9,
    "horizon": "ceil5(readiness) to floor5(contiguous required coverage), capped24h; complete30m action required",
    "P": "RP eligible and CR-CP>tolerance",
    "G": "RG and PG eligible and CR-CG>tolerance and CP-CG>tolerance; P need not beat R",
    "choice": "lowest cost qualifying alternative; ties within tolerance HOLD,P,G",
    "zero_delivery": "if PG physically equivalent and extra G charge<=1e-9, exclude G",
    "availability": "issued<=available<=cutoff<=readiness; cutoff=readiness; explicit freshness and provenance",
    "health": "all required decision evidence healthy; no retained-quote exception for decisions",
    "terminal": "unchanged core gates; no balancing trades, terminal price or wear",
    "load": "explicit total including uncontrolled EV once, or named baseline plus uncontrolled scenario",
    "profiles": "independent, no cross-profile winner",
    "data_origin": "authored_synthetic or archived_decision_inputs; never inferred from real outcomes",
    "core_sha256": CORE_SHA,
}
POLICY_SHA = digest(POLICY)


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def aware(x):
    return (
        isinstance(x, datetime) and x.tzinfo is not None and x.utcoffset() is not None
    )


def evidence_reasons(e, cutoff):
    reasons = []
    if not all(aware(t) for t in (e.issued_at, e.available_at, e.fresh_until)):
        return ["invalid_evidence_time"]
    if not e.issued_at <= e.available_at <= cutoff:
        reasons.append("future_issued_or_unavailable_at_cutoff")
    if e.fresh_until < cutoff or e.fresh_until < e.available_at:
        reasons.append("stale_at_cutoff")
    if e.availability_kind not in ("exact", "documented_upper_bound"):
        reasons.append("unsupported_availability_evidence")
    if not all(
        isinstance(v, str) and v.strip()
        for v in (e.source_id, e.version, e.availability_basis, e.freshness_basis)
    ):
        reasons.append("missing_source_or_timing_basis")
    if (
        not isinstance(e.source_sha256, str)
        or len(e.source_sha256) != 64
        or any(x not in "0123456789abcdef" for x in e.source_sha256)
    ):
        reasons.append("invalid_source_hash")
    if e.healthy is not True or e.issues:
        reasons.append("unhealthy_evidence")
    return reasons


def series_reasons(series, name):
    if series is None:
        return [name + ":missing"]
    reasons = []
    if not series.basis:
        reasons.append(name + ":missing_basis")
    if not series.points or len(series.points) > 4096:
        reasons.append(name + ":empty_or_excessive_intervals")
    previous_end = None
    for p in series.points:
        if not aware(p.start) or not aware(p.end) or p.end <= p.start:
            return reasons + [name + ":invalid_interval_time"]
        if previous_end is not None and p.start < previous_end:
            reasons.append(name + ":overlap_or_unordered")
        previous_end = p.end
        if not finite(p.value) or (
            name not in ("import_price", "export_price") and p.value < 0
        ):
            reasons.append(name + ":missing_or_invalid_value")
    return list(dict.fromkeys(reasons))


def prefix_end(series, start, cap):
    end = start
    for p in series.points:
        if p.end <= end:
            continue
        if p.start > end:
            break
        end = min(p.end, cap)
        if end == cap:
            break
    return end


def admission(core, c):
    reasons, coverage = [], {}
    times = (
        c.decision_at,
        c.evaluated_at,
        c.ready_at,
        c.cutoff,
        c.action_start,
        c.action_end,
        c.branch.at,
        c.reserve.at,
    )
    if not all(aware(t) for t in times):
        return ["invalid_context_time"], None, coverage
    if not c.decision_at <= c.evaluated_at <= c.ready_at == c.cutoff:
        reasons.append("decision_evaluation_readiness_cutoff_order")
    if not c.context_id or not c.readiness_basis:
        reasons.append("missing_identity_or_readiness_basis")
    if c.data_origin not in ("authored_synthetic", "archived_decision_inputs"):
        reasons.append("unsupported_decision_origin")
    if c.action_start != core.ceil_five_minutes(
        c.ready_at
    ) or c.action_end != c.action_start + timedelta(minutes=30):
        reasons.append("action_must_be_first_ready_boundary_and_exactly_30m")
    if c.branch.at != c.action_start or c.reserve.at != c.action_start:
        reasons.append("state_and_reserve_must_be_dated_at_branch")
    if (
        c.branch.kind
        not in (
            "authored_assumption",
            "dated_analytical_hypothesis",
            "observed_soc_capacity_proxy",
        )
        or not c.branch.basis
        or not c.reserve.basis
    ):
        reasons.append("unsupported_state_or_reserve_basis")
    if c.branch.kind == "observed_soc_capacity_proxy" and c.branch.at > c.cutoff:
        reasons.append("future_observed_state_not_available")
    for name, obj in (
        ("branch", c.branch),
        ("reserve", c.reserve),
        ("assumptions", c.assumptions),
    ):
        reasons += [name + ":" + r for r in evidence_reasons(obj.evidence, c.cutoff)]
    a = c.assumptions
    if (
        not a.profile_id
        or not a.uncertainty
        or set(a.omitted_effects)
        != {
            "standby",
            "self_discharge",
            "wear",
            "terminal_value",
            "shared_inverter_coupling",
        }
    ):
        reasons.append("incomplete_assumption_declaration")
    p = parameters(core, c)
    reasons += core._parameter_reasons(p)
    if (
        not finite(c.branch.energy_kwh)
        or not finite(a.capacity_kwh)
        or not finite(a.physical_min_kwh)
    ):
        reasons.append("invalid_initial_energy")
    elif not a.physical_min_kwh <= c.branch.energy_kwh <= a.capacity_kwh:
        reasons.append("initial_energy_outside_physical_bounds")
    required = {
        k: getattr(c, k) for k in ("demand", "pv", "import_price", "export_price")
    }
    if c.uncontrolled_load is not None:
        required["uncontrolled_load"] = c.uncontrolled_load
    expected = {
        "demand": (
            (
                "baseline_household_load"
                if c.uncontrolled_load
                else "total_household_including_uncontrolled_ev"
            ),
            "kW",
            "interval_average_power",
        ),
        "uncontrolled_load": (
            "named_uncontrolled_load_scenario",
            "kW",
            "interval_average_power",
        ),
        "pv": ("available_pv_scenario", "kW", "fixed_exogenous_ac_ceiling"),
        "import_price": ("import_price", "AUD/kWh", "interval_price"),
        "export_price": ("export_price", "AUD/kWh", "interval_price"),
    }
    shapes_valid = True
    for name, series in required.items():
        bad = series_reasons(series, name)
        reasons += bad
        shapes_valid &= not bad
        if series is not None:
            if (series.target, series.unit, series.interpretation) != expected[name]:
                reasons.append(name + ":unsupported_target_unit_or_interpretation")
            reasons += [
                name + ":" + r for r in evidence_reasons(series.evidence, c.cutoff)
            ]
    end = None
    if shapes_valid:
        cap = c.action_start + timedelta(hours=24)
        ends = {k: prefix_end(v, c.action_start, cap) for k, v in required.items()}
        end = min(ends.values())
        end = end.replace(minute=end.minute - end.minute % 5, second=0, microsecond=0)
        coverage = {
            "contiguous_ends": ends,
            "cap": cap,
            "supported_hours": max(0, (end - c.action_start).total_seconds() / 3600),
            "short_of_24h": {k: v < cap for k, v in ends.items()},
        }
        if end < c.action_end:
            reasons.append("coverage_does_not_include_complete_action")
    return list(dict.fromkeys(reasons)), end, coverage


def choose(estimates):
    costs = estimates["costs_aud"]
    comparisons = estimates["comparisons"]

    def benefit(k):
        return comparisons[k]["primary_comparative_gross_value_aud"]

    p, g, inc = (
        benefit("preservation"),
        benefit("combined"),
        benefit("charging_increment"),
    )
    eligible = ["HOLD"]
    if p is not None and p > TOLERANCE:
        eligible.append("P")
    equivalent = (
        estimates["pg_physically_equivalent"]
        and estimates["paths"]["G"]["delivered_action_ac_kwh"] <= 1e-9
    )
    if (
        not equivalent
        and g is not None
        and inc is not None
        and g > TOLERANCE
        and inc > TOLERANCE
    ):
        eligible.append("G")
    chosen = "HOLD"
    for action in eligible[1:]:
        if costs[action] < costs["R" if chosen == "HOLD" else chosen] - TOLERANCE:
            chosen = action
    return chosen, eligible


def select(core, c: DecisionContext, source_sha256: str) -> SelectionReceipt:
    if type(c) is not DecisionContext:
        raise TypeError("decision_context_only")
    reasons, end, coverage = admission(core, c)
    estimates, chosen = None, "HOLD"
    if not reasons:
        try:
            estimates = estimate(core, c, end)
        except core.AdmissionError as exc:
            reasons = ["kernel:" + r for r in exc.reasons]
        else:
            chosen, eligible = choose(estimates)
            estimates["qualifying_actions"] = eligible
            if chosen == "HOLD":
                reasons = ["no_eligible_positive_alternative"]
                for component, comparison in estimates["comparisons"].items():
                    reasons += [
                        component + ":" + r
                        for r in comparison["primary_unavailable_reasons"]
                    ]
    return SelectionReceipt(
        POLICY_VERSION,
        POLICY_SHA,
        source_sha256,
        digest(c),
        digest(
            {
                "assumptions": asdict(c.assumptions),
                "reserve": asdict(c.reserve),
                "branch": asdict(c.branch),
            }
        ),
        chosen,
        c.cutoff,
        end,
        tuple(reasons),
        canonical(estimates),
        canonical(coverage),
    )
