"""Accounting adapter around the byte-pinned dispatch/comparator, not a model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from fractions import Fraction
from types import ModuleType

CORE_SHA = "e0c3236868079a04f4358cc0441304fc3db06bfeb4090a7326ebc920a967fe2f"
BUNDLE_SHA = "8ad2de156628ed62ad2a8439420986ca31c8928126ad9522bc7131471fa73cd4"


@dataclass(frozen=True)
class KernelInputs:
    """Research context, deliberately not the core's SyntheticCase."""

    data_origin: str
    comparison_start_utc: datetime
    comparison_end_utc: datetime
    initial_energy_kwh: float
    parameters: object
    schedule: object
    load_kind: str
    household_load_kw: tuple
    fixed_ev_load_kw: tuple
    available_pv_kw: tuple
    import_price_aud_per_kwh: tuple
    export_price_aud_per_kwh: tuple


def parameters(core, c):
    a = asdict(c.assumptions)
    for k in ("profile_id", "omitted_effects", "uncertainty", "evidence"):
        del a[k]
    return core.Parameters(
        **a,
        policy_floor_kwh=c.reserve.floor_kwh,
        terminal_reserve_kwh=c.reserve.floor_kwh,
    )


def make_inputs(core, c, end, action):
    def points(series):
        return (
            ()
            if series is None
            else tuple(core.Interval(p.start, p.end, p.value) for p in series.points)
        )

    return KernelInputs(
        c.data_origin,
        c.action_start,
        end,
        c.branch.energy_kwh,
        parameters(core, c),
        core.Schedule(
            action,
            c.ready_at,
            c.action_start,
            c.action_end,
            2.0 if action == "CHARGE_BATTERY_FROM_GRID" else 0.0,
            1.0 if action == "CHARGE_BATTERY_FROM_GRID" else 0.0,
        ),
        "baseline_plus_fixed_ev" if c.uncontrolled_load else "total_including_fixed_ev",
        points(c.demand),
        points(c.uncontrolled_load),
        points(c.pv),
        points(c.import_price),
        points(c.export_price),
    )


FLOW_FIELDS = (
    "available_pv_kwh",
    "curtailed_pv_kwh",
    "load_kwh",
    "import_kwh",
    "export_kwh",
    "charge_ac_kwh",
    "discharge_ac_kwh",
    "unserved_load_kwh",
    "requested_action_ac_kwh",
    "delivered_action_ac_kwh",
)


def value_at(series, at):
    return next(p.value for p in series if p.start_utc <= at < p.end_utc)


def align(core, ledger, boundaries, case):
    """Split constant-flow phases only; verify source before canonicalizing inputs."""
    rows = []
    for left, right in zip(boundaries[:-1], boundaries[1:], strict=True):
        row = next(s for s in ledger.steps if s.start_utc <= left < s.end_utc)
        if right > row.end_utc:
            raise ValueError("partition_crosses_phase")
        duration = (row.end_utc - row.start_utc).total_seconds()
        ratio = (right - left).total_seconds() / duration
        offset = (left - row.start_utc).total_seconds() / duration
        flows = {k: getattr(row, k) * ratio for k in FLOW_FIELDS}
        hours = (right - left).total_seconds() / 3600
        load = value_at(case.household_load_kw, left)
        if case.fixed_ev_load_kw:
            load += value_at(case.fixed_ev_load_kw, left)
        exact = dict(
            load_kwh=load * hours,
            available_pv_kwh=value_at(case.available_pv_kw, left) * hours,
        )
        if any(abs(flows[k] - v) > 1e-9 for k, v in exact.items()):
            raise ValueError("source_energy_mismatch")
        if row.import_price != value_at(
            case.import_price_aud_per_kwh, left
        ) or row.export_price != value_at(case.export_price_aud_per_kwh, left):
            raise ValueError("source_quote_mismatch")
        flows.update(exact)
        delta = row.energy_end_kwh - row.energy_start_kwh
        rows.append(
            replace(
                row,
                start_utc=left,
                end_utc=right,
                energy_start_kwh=row.energy_start_kwh + delta * offset,
                energy_end_kwh=row.energy_start_kwh + delta * (offset + ratio),
                **flows,
            )
        )
    split = replace(ledger, steps=tuple(rows))
    for key in FLOW_FIELDS:
        if (
            abs(
                sum(getattr(r, key) for r in ledger.steps)
                - sum(getattr(r, key) for r in split.steps)
            )
            > 1e-9
        ):
            raise ValueError("split_aggregate_mismatch:" + key)
    return split


def reconcile(ledger, p):
    """Independent rational AC/DC/cash accounting; no routing equations."""

    def f(v):
        return Fraction(str(v))

    cost = Fraction(0)
    import_debit = Fraction(0)
    export_credit = Fraction(0)
    residual = Fraction(0)
    for s in ledger.steps:
        import_debit += f(s.import_kwh) * f(s.import_price)
        export_credit += f(s.export_kwh) * f(s.export_price)
        cost += f(s.import_kwh) * f(s.import_price) - f(s.export_kwh) * f(
            s.export_price
        )
        ac = (
            f(s.available_pv_kwh)
            - f(s.curtailed_pv_kwh)
            + f(s.import_kwh)
            + f(s.discharge_ac_kwh)
            - f(s.load_kwh)
            + f(s.unserved_load_kwh)
            - f(s.export_kwh)
            - f(s.charge_ac_kwh)
        )
        dc = (
            f(s.energy_end_kwh)
            - f(s.energy_start_kwh)
            - f(s.charge_ac_kwh) * f(p.charge_efficiency)
            + f(s.discharge_ac_kwh) / f(p.discharge_efficiency)
        )
        residual = max(residual, abs(ac), abs(dc))
    if residual > f(1e-9):
        raise ValueError("independent_energy_reconciliation_failed")
    return {
        "cost_aud": float(cost),
        "import_debit_aud": float(import_debit),
        "export_credit_aud": float(export_credit),
        "maximum_balance_residual_kwh": float(residual),
    }


def estimate(core: ModuleType, c, end):
    p_case = make_inputs(core, c, end, "PRESERVE_BATTERY")
    g_case = make_inputs(core, c, end, "CHARGE_BATTERY_FROM_GRID")
    r1, p = core._simulate_pair(p_case)
    r2, g = core._simulate_pair(g_case)
    originals = {"R": r1, "P": p, "G": g, "R_control": r2}
    bounds = sorted(
        {
            t
            for path in originals.values()
            for row in path.steps
            for t in (row.start_utc, row.end_utc)
        }
    )
    paths = {k: align(core, v, bounds, p_case) for k, v in originals.items()}
    reference_residual = max(
        abs(getattr(a, k) - getattr(b, k))
        for a, b in zip(paths["R"].steps, paths["R_control"].steps, strict=True)
        for k in ("energy_start_kwh", "energy_end_kwh") + FLOW_FIELDS
    )
    # Pair-specific saturation splits differ by floating point/microsecond rounding.
    # Retain both originals; equality uses the core's unchanged numerical tolerance.
    if reference_residual > core.NUMERICAL_EPSILON:
        raise ValueError("independent_reference_mismatch")
    audits = {k: reconcile(v, p_case.parameters) for k, v in originals.items()}
    for k, v in paths.items():
        split_audit = reconcile(v, p_case.parameters)
        if abs(split_audit["cost_aud"] - audits[k]["cost_aud"]) > 1e-9:
            raise ValueError("split_cash_mismatch")
    comparisons = {}
    for name, a, b in (
        ("preservation", "R", "P"),
        ("charging_increment", "P", "G"),
        ("combined", "R", "G"),
    ):
        result = core.compare_ledgers(
            paths[a], paths[b], p_case.parameters, core.Sensitivities(None, None)
        )
        result.pop("trace", None)
        original_errors = core._ledger_reasons(
            originals[a], p_case.parameters
        ) + core._ledger_reasons(originals[b], p_case.parameters)
        if original_errors:
            result["primary_comparative_gross_value_aud"] = None
            result["primary_unavailable_reasons"] = list(
                dict.fromkeys(result["primary_unavailable_reasons"] + original_errors)
            )
        independent = audits[a]["cost_aud"] - audits[b]["cost_aud"]
        if abs(result["diagnostic_incremental_cash_aud"] - independent) > 1e-9:
            raise ValueError("cash_comparison_reconciliation_failed")
        comparisons[name] = result
    costs = {k: v["cost_aud"] for k, v in audits.items() if k != "R_control"}
    residual = (
        (costs["R"] - costs["P"])
        + (costs["P"] - costs["G"])
        - (costs["R"] - costs["G"])
    )
    energies = {
        k: v.steps[-1].energy_end_kwh for k, v in originals.items() if k != "R_control"
    }
    energy_residual = (
        (energies["P"] - energies["R"])
        + (energies["G"] - energies["P"])
        - (energies["G"] - energies["R"])
    )
    if abs(residual) > 1e-9 or abs(energy_residual) > 1e-9:
        raise ValueError("decomposition_reconciliation_failed")
    physical_fields = ("energy_start_kwh", "energy_end_kwh") + FLOW_FIELDS[:-2]
    identical = all(
        abs(getattr(a, k) - getattr(b, k)) <= 1e-9
        for a, b in zip(paths["P"].steps, paths["G"].steps, strict=True)
        for k in physical_fields
    )
    return {
        "costs_aud": costs,
        "terminal_energy_kwh": energies,
        "comparisons": comparisons,
        "paths": {
            k: core._summary(v, p_case.parameters)
            for k, v in originals.items()
            if k != "R_control"
        },
        "independent_reconciliation": audits,
        "reference_control_maximum_residual_kwh": reference_residual,
        "cash_decomposition_residual_aud": residual,
        "energy_decomposition_residual_kwh": energy_residual,
        "pg_physically_equivalent": identical,
        "original_ledgers": {k: asdict(v) for k, v in originals.items()},
        "common_partition_ledgers": {k: asdict(v) for k, v in paths.items()},
    }
