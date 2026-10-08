"""Authored witnesses. No household records or historical winner labels."""

from datetime import UTC, datetime, timedelta

from energy_optimizer.arbitrage.decision_types import (
    Assumptions,
    BranchState,
    DecisionContext,
    Evidence,
    Forecast,
    Point,
    Reserve,
    digest,
)


def authored_case(kind="charging_without_preservation_benefit"):
    t = datetime(2030, 1, 1, tzinfo=UTC)
    evidence = Evidence(
        "authored-fixture",
        "v1",
        digest("authored-fixture"),
        t,
        t,
        "exact",
        "authored before hypothetical cutoff",
        t + timedelta(hours=24),
        "explicit fixture freshness",
        True,
        (),
    )

    def series(target, unit, interpretation, values, basis):
        return Forecast(
            target,
            unit,
            interpretation,
            basis,
            evidence,
            tuple(
                Point(
                    t + timedelta(minutes=30 * i),
                    t + timedelta(minutes=30 * (i + 1)),
                    v,
                )
                for i, v in enumerate(values)
            ),
        )

    load, pv, prices = [1, 1, 2], [0, 0, 0], [0.3, 0.1, 1]
    if kind == "preservation":
        load, pv, prices = [1, 1, 0], [0, 0, 4], [0.2, 1, 0.1]
    elif kind in ("charging", "zero_delivery_preservation"):
        prices = [0.1, 0.4, 1]
    elif kind == "hold":
        load, pv, prices = [0, 0, 0], [0, 0, 0], [0.2, 0.2, 0.2]
    elif kind == "negative_price":
        prices = [-0.2, 0.4, 1]
    assumptions = Assumptions(
        "authored-profile",
        2.0,
        0.0,
        1.0,
        1.0,
        0.0 if kind == "zero_delivery_preservation" else 4.0,
        4.0,
        8.0,
        8.0,
        "synthetic_ac_bus_independent_ports",
        "AC_bus_kWh",
        "DC_stored_kWh",
        "available_exogenous_synthetic",
        True,
        "piecewise_constant_interval_average_kw",
        (
            "standby",
            "self_discharge",
            "wear",
            "terminal_value",
            "shared_inverter_coupling",
        ),
        ("Authored idealised model; no equipment applicability claimed",),
        evidence,
    )
    return DecisionContext(
        kind,
        "authored_synthetic",
        t,
        t,
        t,
        t,
        "authored instantaneous readiness at branch",
        BranchState(
            t,
            0.5,
            "authored_assumption",
            "explicit authored stored DC energy",
            evidence,
        ),
        Reserve(t, 0.0, "explicit authored floor", evidence),
        assumptions,
        t,
        t + timedelta(minutes=30),
        series(
            "total_household_including_uncontrolled_ev",
            "kW",
            "interval_average_power",
            load,
            "authored total includes uncontrolled EV once; no separate EV addition",
        ),
        series(
            "available_pv_scenario",
            "kW",
            "fixed_exogenous_ac_ceiling",
            pv,
            "authored fixed available PV",
        ),
        series(
            "import_price",
            "AUD/kWh",
            "interval_price",
            prices,
            "authored import quotes",
        ),
        series(
            "export_price",
            "AUD/kWh",
            "interval_price",
            [0] * 3,
            "authored export quotes",
        ),
        None,
    )


CASES = (
    "hold",
    "preservation",
    "charging",
    "charging_without_preservation_benefit",
    "zero_delivery_preservation",
    "negative_price",
)
