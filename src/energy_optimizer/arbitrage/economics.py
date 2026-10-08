"""Versioned diagnostic policy, terminal bounds and continuous-state replay."""

import json
import math
from dataclasses import dataclass, replace
from datetime import timedelta

from energy_optimizer.arbitrage.core_bridge import make_inputs, parameters
from energy_optimizer.arbitrage.decision_types import digest
from energy_optimizer.arbitrage.selector import select

OPERATIONAL_VERSION = "arbitrage-operational-diagnostic-v1"
TERMINAL_VERSION = "stored-inventory-bound-diagnostic-v1"
SEQUENTIAL_VERSION = "continuous-state-rpg-replay-candidate-v1"


@dataclass(frozen=True)
class BusinessScenario:
    """All business thresholds explicitly supplied; no physical authority."""

    scenario_id: str
    material_benefit_aud: float
    uncertainty_budget_aud: float
    wear_aud_per_discharged_dc_kwh: float
    minimum_dwell_minutes: int
    expiry_minutes: int

    def __post_init__(self):
        if (
            not self.scenario_id
            or any(
                not math.isfinite(v) or v < 0
                for v in (
                    self.material_benefit_aud,
                    self.uncertainty_budget_aud,
                    self.wear_aud_per_discharged_dc_kwh,
                    self.minimum_dwell_minutes,
                    self.expiry_minutes,
                )
            )
            or self.expiry_minutes > 30
        ):
            raise ValueError("invalid_business_scenario")


def operational_choice(
    receipt, scenario, *, now, discharge_efficiency, last_change=None
):
    if not math.isfinite(discharge_efficiency) or not 0 < discharge_efficiency <= 1:
        raise ValueError("explicit_discharge_efficiency_required")
    estimates = json.loads(receipt.estimates_json)
    reasons = []
    if now < receipt.cutoff or now >= receipt.cutoff + timedelta(
        minutes=scenario.expiry_minutes
    ):
        reasons.append("proposal_expired_or_clock_reversed")
    if last_change is not None and now < last_change + timedelta(
        minutes=scenario.minimum_dwell_minutes
    ):
        reasons.append("minimum_dwell")
    candidates = {"HOLD": 0.0}
    margins = {}
    if estimates is not None:
        for action, pairs in (
            ("P", (("preservation", "R", "P"),)),
            ("G", (("combined", "R", "G"), ("charging_increment", "P", "G"))),
        ):
            values = []
            for name, a, b in pairs:
                gross = estimates["comparisons"][name][
                    "primary_comparative_gross_value_aud"
                ]
                ledgers = estimates["original_ledgers"]

                def dc(path, ledgers=ledgers):
                    return sum(s["discharge_ac_kwh"] for s in ledgers[path]["steps"])

                wear_delta = (
                    (dc(b) - dc(a))
                    / discharge_efficiency
                    * scenario.wear_aud_per_discharged_dc_kwh
                )
                values.append(
                    None
                    if gross is None
                    else gross - wear_delta - scenario.uncertainty_budget_aud
                )
            margins[action] = values
            if action in estimates["qualifying_actions"] and all(
                v is not None and v > scenario.material_benefit_aud for v in values
            ):
                candidates[action] = values[0]
    else:
        reasons.append("incomplete_research_comparison")
    chosen = max(candidates, key=candidates.get) if not reasons else "HOLD"
    return {
        "version": OPERATIONAL_VERSION,
        "scenario": scenario.scenario_id,
        "selected": chosen,
        "margins_aud": margins,
        "reasons": sorted(set(reasons)),
        "action_request": {
            "power_ac_kw": 2,
            "energy_ac_kwh": 1,
            "duration_minutes": 30,
        },
        "status": "research_only",
        "no_command_issued": True,
    }


def terminal_bounds(
    *,
    cash_benefit_aud,
    stored_delta_kwh,
    lower_aud_per_dc_kwh,
    upper_aud_per_dc_kwh,
    assumptions_id,
    feasible,
):
    values = (
        cash_benefit_aud,
        stored_delta_kwh,
        lower_aud_per_dc_kwh,
        upper_aud_per_dc_kwh,
    )
    if (
        not assumptions_id
        or any(not math.isfinite(v) for v in values)
        or lower_aud_per_dc_kwh > upper_aud_per_dc_kwh
    ):
        raise ValueError("explicit_finite_inventory_bounds_required")
    bounds = sorted(
        cash_benefit_aud + stored_delta_kwh * price
        for price in (lower_aud_per_dc_kwh, upper_aud_per_dc_kwh)
    )
    return {
        "version": TERMINAL_VERSION,
        "assumptions_id": assumptions_id,
        "cash_benefit_aud": cash_benefit_aud,
        "stored_delta_kwh": stored_delta_kwh,
        "conditional_value_bounds_aud": bounds if feasible else None,
        "reason": None if feasible else "infeasible_path",
        "primary_v1_value": None,
    }


def replay(
    core,
    contexts,
    *,
    initial_energy_kwh,
    scenario,
    realised_case_factory,
    reserve_equation,
):
    """Own state continuously; only next half-hour is simulated, never overlap-sum.

    Factory supplies explicitly qualified common exogenous realised trajectories.
    Reserve equation receives each path's OWN state, never operated-battery reserves.
    Missing evidence aborts replay rather than silently bridging a state gap.
    """
    if not 1 <= len(contexts) <= 350:
        raise ValueError("sequential_origin_bound")
    energies = {"R": initial_energy_kwh, "candidate": initial_energy_kwh}
    paths = {"R": [], "candidate": []}
    cursor = contexts[0].action_start
    last_change = None
    prior_action = "HOLD"
    decisions = []
    for c in contexts:
        if c.action_start != cursor or cursor - contexts[0].action_start >= timedelta(
            days=7
        ):
            raise ValueError("noncontiguous_or_out_of_tranche")
        if c.assumptions != contexts[0].assumptions:
            raise ValueError("sequential_physical_profile_changed")
        own = replace(
            c,
            branch=replace(c.branch, energy_kwh=energies["candidate"]),
            reserve=reserve_equation(c, energies["candidate"]),
        )
        receipt = select(core, own, digest(SEQUENTIAL_VERSION))
        choice = operational_choice(
            receipt,
            scenario,
            now=c.cutoff,
            discharge_efficiency=c.assumptions.discharge_efficiency,
            last_change=last_change,
        )
        selected = choice["selected"]
        if selected != prior_action:
            last_change, prior_action = c.cutoff, selected
        decisions.append(choice)
        common_exogenous = None
        for label in paths:
            action = (
                "HOLD"
                if label == "R"
                else {
                    "HOLD": "HOLD",
                    "P": "PRESERVE_BATTERY",
                    "G": "CHARGE_BATTERY_FROM_GRID",
                }[selected]
            )
            path_context = replace(
                c,
                branch=replace(c.branch, energy_kwh=energies[label]),
                reserve=reserve_equation(c, energies[label]),
            )
            inputs = make_inputs(core, path_context, c.action_end, action)
            actual_inputs = realised_case_factory(inputs, c, label)
            if (
                actual_inputs.initial_energy_kwh != energies[label]
                or actual_inputs.comparison_start_utc != cursor
                or actual_inputs.comparison_end_utc != c.action_end
                or actual_inputs.parameters != parameters(core, path_context)
                or actual_inputs.schedule != inputs.schedule
            ):
                raise ValueError("replay_state_horizon_or_reserve_reset")
            exogenous = tuple(
                getattr(actual_inputs, name)
                for name in (
                    "household_load_kw",
                    "fixed_ev_load_kw",
                    "available_pv_kw",
                    "import_price_aud_per_kwh",
                    "export_price_aud_per_kwh",
                )
            )
            if common_exogenous is not None and exogenous != common_exogenous:
                raise ValueError("replay_exogenous_paths_differ")
            common_exogenous = exogenous
            reasons = core._parameter_reasons(actual_inputs.parameters)
            for index, rows in enumerate(exogenous):
                if index == 1 and actual_inputs.load_kind != "baseline_plus_fixed_ev":
                    if rows:
                        reasons.append("ev_double_count")
                    continue
                reasons += core._coverage_reasons(
                    str(index),
                    rows,
                    cursor,
                    c.action_end,
                    price=index >= 3,
                )
            if reasons or not (
                actual_inputs.parameters.physical_min_kwh
                <= energies[label]
                <= actual_inputs.parameters.capacity_kwh
            ):
                raise ValueError("invalid_realised_replay_inputs")
            ledger = core._simulate_pair(actual_inputs)[1]
            if core._ledger_reasons(ledger, actual_inputs.parameters):
                raise ValueError("infeasible_replay_interval")
            energies[label] = ledger.steps[-1].energy_end_kwh
            paths[label].extend(ledger.steps)
        cursor = c.action_end
    return {
        "version": SEQUENTIAL_VERSION,
        "origins": len(contexts),
        "tranche_start": contexts[0].action_start,
        "tranche_end": cursor,
        "decisions": decisions,
        "terminal_energy_kwh": energies,
        "net_variable_cost_aud": {
            k: -sum(r.cash_aud for r in v) for k, v in paths.items()
        },
        "ledgers": paths,
        "energy_metrics": {
            k: {
                "import_ac_kwh": sum(r.import_kwh for r in v),
                "export_ac_kwh": sum(r.export_kwh for r in v),
                "charged_ac_kwh": sum(r.charge_ac_kwh for r in v),
                "discharged_ac_kwh": sum(r.discharge_ac_kwh for r in v),
                "conversion_loss_kwh": sum(
                    r.charge_ac_kwh * (1 - contexts[0].assumptions.charge_efficiency)
                    + r.discharge_ac_kwh
                    * (1 / contexts[0].assumptions.discharge_efficiency - 1)
                    for r in v
                ),
                "unserved_load_kwh": sum(r.unserved_load_kwh for r in v),
            }
            for k, v in paths.items()
        },
        "primary_comparative_claim": None,
        "qualification": "continuous conditional proxy; inventory differences visible; no annualised or overlapping savings",  # noqa: E501
    }
