"""Independent rational reconciliation of supplied ledgers, never a dispatcher."""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction as F
from typing import Any

ENERGY_TOL = F(1, 10**8)
CASH_TOL = F(1, 10**8)
FLOW_FIELDS = (
    "proxy_pv_ceiling_kwh",
    "proxy_spillage_kwh",
    "load_kwh",
    "import_kwh",
    "export_kwh",
    "charge_ac_kwh",
    "discharge_ac_kwh",
    "unserved_load_kwh",
    "requested_action_ac_kwh",
    "delivered_action_ac_kwh",
)


def number(value: Any) -> F:
    return F(str(value))


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def hours(start: datetime, end: datetime) -> F:
    delta = end - start
    return F(
        delta.days * 86400 * 1000000 + delta.seconds * 1000000 + delta.microseconds,
        3600 * 1000000,
    )


def aggregate_intervals(ledger: dict, intervals: list[dict]) -> list[dict]:
    """Aggregate elementary steps by exact overlap; no energy beyond the horizon."""
    output = []
    for interval in intervals:
        left, right = interval["start_utc"], interval["end_utc"]
        totals = {key: F(0) for key in FLOW_FIELDS}
        cash_total, import_cost, export_credit = F(0), F(0), F(0)
        valid_cash = True
        duration = F(0)
        initial = ending = None
        for step in ledger["steps"]:
            begin, finish = timestamp(step["start_utc"]), timestamp(step["end_utc"])
            start, end = max(begin, left), min(finish, right)
            if end <= start:
                continue
            overlap = hours(start, end)
            ratio = overlap / hours(begin, finish)
            duration += overlap
            if begin < left or finish > right:
                raise ValueError("kernel_step_crosses_input_boundary")
            if initial is None:
                initial = step["energy_start_kwh"]
            ending = step["energy_end_kwh"]
            for key in FLOW_FIELDS:
                totals[key] += number(step[key]) * ratio
            if step["import_price"] is None or step["export_price"] is None:
                valid_cash = False
            else:
                debit = (
                    number(step["import_kwh"]) * number(step["import_price"]) * ratio
                )
                credit = (
                    number(step["export_kwh"]) * number(step["export_price"]) * ratio
                )
                import_cost += debit
                export_credit += credit
                cash_total += debit - credit
        if duration != hours(left, right):
            raise ValueError("elementary_overlap_duration_mismatch")
        output.append(
            {
                "start_utc": left.isoformat(),
                "end_utc": right.isoformat(),
                "duration_hours": float(duration),
                "energy_start_kwh": initial,
                "energy_end_kwh": ending,
                **{key: float(value) for key, value in totals.items()},
                "import_cost_aud": float(import_cost) if valid_cash else None,
                "export_credit_aud": float(export_credit) if valid_cash else None,
                "net_quote_cost_aud": float(cash_total) if valid_cash else None,
            }
        )
    return output


def reconcile_path(
    ledger: dict, p: dict, normalized: dict, *, expiry: datetime, bad_slot: datetime
) -> dict:
    ec, ed = number(p["charge_efficiency"]), number(p["discharge_efficiency"])
    floor, capacity, minimum = (
        number(p["policy_floor_kwh"]),
        number(p["capacity_kwh"]),
        number(p["physical_min_kwh"]),
    )
    totals = {key: F(0) for key in FLOW_FIELDS}
    cost = import_cost = export_credit = charge_loss = discharge_loss = F(0)
    residuals = {
        key: F(0)
        for key in (
            "AC_balance_kwh",
            "stored_balance_kwh",
            "state_continuity_kwh",
            "cash_aud",
            "loss_kwh",
        )
    }
    errors, states = [], [number(ledger["initial_energy_kwh"])]
    cursor = timestamp(ledger["start_utc"])
    prior = states[0]
    expiry_energy = None
    first_window_discharge = F(0)
    for index, row in enumerate(ledger["steps"]):
        start, end = timestamp(row["start_utc"]), timestamp(row["end_utc"])
        v = {key: number(row[key]) for key in FLOW_FIELDS}
        before, after = number(row["energy_start_kwh"]), number(row["energy_end_kwh"])
        h = hours(start, end)
        source = next(
            (
                item
                for item in normalized["intervals"]
                if item["start_utc"] <= start < item["end_utc"]
            ),
            None,
        )
        if source is None or end > source["end_utc"]:
            errors.append(f"input_interval_mapping:{index}")
        else:
            if abs(v["load_kwh"] - number(source["load_kw"]) * h) > ENERGY_TOL:
                errors.append(f"source_load_mismatch:{index}")
            if (
                abs(v["proxy_pv_ceiling_kwh"] - number(source["pv_proxy_kw"]) * h)
                > ENERGY_TOL
            ):
                errors.append(f"source_PV_mismatch:{index}")
            if (row["import_price"], row["export_price"]) != (
                source["import_price"],
                source["export_price"],
            ):
                errors.append(f"source_quote_mismatch:{index}")
        if start != cursor or h <= 0:
            errors.append(f"coverage:{index}")
        cursor = end
        continuity = abs(before - prior)
        residuals["state_continuity_kwh"] = max(
            residuals["state_continuity_kwh"], continuity
        )
        ac = (
            v["proxy_pv_ceiling_kwh"]
            + v["import_kwh"]
            + v["discharge_ac_kwh"]
            - (
                v["load_kwh"]
                - v["unserved_load_kwh"]
                + v["export_kwh"]
                + v["charge_ac_kwh"]
                + v["proxy_spillage_kwh"]
            )
        )
        stored = after - before - ec * v["charge_ac_kwh"] + v["discharge_ac_kwh"] / ed
        residuals["AC_balance_kwh"] = max(residuals["AC_balance_kwh"], abs(ac))
        residuals["stored_balance_kwh"] = max(
            residuals["stored_balance_kwh"], abs(stored)
        )
        loss_charge = (1 - ec) * v["charge_ac_kwh"]
        loss_discharge = (1 / ed - 1) * v["discharge_ac_kwh"]
        loss_identity = v["charge_ac_kwh"] - v["discharge_ac_kwh"] - (after - before)
        residuals["loss_kwh"] = max(
            residuals["loss_kwh"], abs(loss_identity - loss_charge - loss_discharge)
        )
        charge_loss += loss_charge
        discharge_loss += loss_discharge
        for field in FLOW_FIELDS:
            totals[field] += v[field]
        if row["import_price"] is not None and row["export_price"] is not None:
            debit, credit = v["import_kwh"] * number(row["import_price"]), v[
                "export_kwh"
            ] * number(row["export_price"])
            float_cost = (
                row["import_kwh"] * row["import_price"]
                - row["export_kwh"] * row["export_price"]
            )
            residuals["cash_aud"] = max(
                residuals["cash_aud"], abs(number(float_cost) - (debit - credit))
            )
            cost += debit - credit
            import_cost += debit
            export_credit += credit
        if (
            min(v.values()) < -ENERGY_TOL
            or min(before, after) < minimum - ENERGY_TOL
            or max(before, after) > capacity + ENERGY_TOL
        ):
            errors.append(f"physical_bounds:{index}")
        if v["discharge_ac_kwh"] > ENERGY_TOL and after < floor - ENERGY_TOL:
            errors.append(f"discharge_below_floor:{index}")
        if v["unserved_load_kwh"] > v["load_kwh"] + ENERGY_TOL:
            errors.append(f"unserved_exceeds_requested_load:{index}")
        if (v["charge_ac_kwh"] > ENERGY_TOL and v["discharge_ac_kwh"] > ENERGY_TOL) or (
            v["import_kwh"] > ENERGY_TOL and v["export_kwh"] > ENERGY_TOL
        ):
            errors.append(f"opposing_flows:{index}")
        for field, cap in [
            ("charge_ac_kwh", "charge_limit_kw"),
            ("discharge_ac_kwh", "discharge_limit_kw"),
            ("import_kwh", "import_limit_kw"),
            ("export_kwh", "export_limit_kw"),
        ]:
            if v[field] > number(p[cap]) * h + ENERGY_TOL:
                errors.append(f"power_cap:{index}:{field}")
        if start < expiry:
            first_window_discharge += v["discharge_ac_kwh"]
        if end == expiry:
            expiry_energy = after
        prior = after
        states.append(after)
    if cursor != timestamp(ledger["end_utc"]):
        errors.append("horizon_end_mismatch")
    for key, value in residuals.items():
        if value > (CASH_TOL if key == "cash_aud" else ENERGY_TOL):
            errors.append("residual_exceeds_tolerance:" + key)
    interval_rows = aggregate_intervals(ledger, normalized["intervals"])
    for key in FLOW_FIELDS:
        difference = abs(sum(number(row[key]) for row in interval_rows) - totals[key])
        if difference > ENERGY_TOL:
            errors.append("aggregation:" + key)
    flagged = next(
        row for row in interval_rows if timestamp(row["start_utc"]) == bad_slot
    )
    flagged_input = next(
        row for row in normalized["intervals"] if row["start_utc"] == bad_slot
    )
    other_cost = (
        None
        if not normalized["quote_scenario_available"]
        else cost - number(flagged["net_quote_cost_aud"])
    )
    initial, end_energy = states[0], states[-1]
    lowest = min(states)
    summary = {
        "quote_scenario_net_cost_aud": (
            float(cost) if normalized["quote_scenario_available"] else None
        ),
        "import_cost_aud": (
            float(import_cost) if normalized["quote_scenario_available"] else None
        ),
        "export_credit_aud": (
            float(export_credit) if normalized["quote_scenario_available"] else None
        ),
        "strict_price_validated_cost_aud": None,
        "aggregate_price_health_complete": False,
        "provider_settlement_verified": False,
        **{key: float(value) for key, value in totals.items()},
        "charge_conversion_loss_kwh": float(charge_loss),
        "discharge_conversion_loss_kwh": float(discharge_loss),
        "total_conversion_loss_kwh": float(charge_loss + discharge_loss),
        "charged_stored_energy_kwh": float(ec * totals["charge_ac_kwh"]),
        "discharged_stored_energy_kwh": float(totals["discharge_ac_kwh"] / ed),
        "initial_energy_kwh": float(initial),
        "minimum_energy_kwh": float(lowest),
        "action_expiry_energy_kwh": (
            None if expiry_energy is None else float(expiry_energy)
        ),
        "terminal_energy_kwh": float(end_energy),
        "initial_reserve_shortfall_kwh": float(max(F(0), floor - initial)),
        "minimum_signed_reserve_margin_kwh": float(lowest - floor),
        "terminal_signed_reserve_margin_kwh": float(end_energy - floor),
        "maximum_reserve_shortfall_kwh": float(max(F(0), floor - lowest)),
        "additional_reserve_shortfall_kwh": float(
            max(F(0), min(initial, floor) - lowest)
        ),
        "terminal_reserve_shortfall_kwh": float(max(F(0), floor - end_energy)),
        "battery_discharge_first_25_minutes_ac_kwh": float(first_window_discharge),
        "trajectory_feasible": not errors and totals["unserved_load_kwh"] <= ENERGY_TOL,
        "elementary_interval_count": len(ledger["steps"]),
        "price_health_exception_contribution": {
            "slot_utc": bad_slot.isoformat(),
            "original_price_is_healthy": False,
            "import_quote_aud_per_kwh": flagged_input["import_price"],
            "export_quote_aud_per_kwh": flagged_input["export_price"],
            "import_kwh": flagged["import_kwh"],
            "export_kwh": flagged["export_kwh"],
            "net_quote_cost_aud": flagged["net_quote_cost_aud"],
            "other_interval_subtotal_aud": (
                None if other_cost is None else float(other_cost)
            ),
            "cause": "unknown",
            "quote_validity_and_settlement_not_verified": True,
        },
    }
    whole_ac = (
        totals["proxy_pv_ceiling_kwh"]
        + totals["import_kwh"]
        + totals["discharge_ac_kwh"]
        - (
            totals["load_kwh"]
            - totals["unserved_load_kwh"]
            + totals["export_kwh"]
            + totals["charge_ac_kwh"]
            + totals["proxy_spillage_kwh"]
        )
    )
    whole_stored = (
        end_energy
        - initial
        - ec * totals["charge_ac_kwh"]
        + totals["discharge_ac_kwh"] / ed
    )
    if abs(whole_ac) > ENERGY_TOL or abs(whole_stored) > ENERGY_TOL:
        errors.append("whole_path_energy_balance")
    return {
        "summary": summary,
        "errors": errors,
        "passed": not errors,
        "maximum_elementary_residuals": {
            key: float(value) for key, value in residuals.items()
        },
        "whole_path_AC_residual_kwh": float(whole_ac),
        "whole_path_stored_residual_kwh": float(whole_stored),
    }


def reconcile_pair(
    ledgers: dict,
    parameters: dict,
    comparison: dict | None,
    normalized: dict,
    *,
    expiry: datetime,
    bad_slot: datetime,
) -> dict:
    checked = {
        arm: reconcile_path(
            ledger, parameters, normalized, expiry=expiry, bad_slot=bad_slot
        )
        for arm, ledger in ledgers.items()
    }
    comparator_residuals = []
    if comparison is not None:
        for arm, label in [("reference", "reference"), ("alternative", "action")]:
            expected, actual = checked[arm]["summary"], comparison[label]
            for own, theirs in [
                ("quote_scenario_net_cost_aud", "cash_aud"),
                ("terminal_energy_kwh", "terminal_energy_kwh"),
                ("import_kwh", "import_kwh"),
                ("export_kwh", "export_kwh"),
                ("total_conversion_loss_kwh", "loss_kwh"),
            ]:
                difference = abs(
                    number(expected[own])
                    - (
                        -number(actual[theirs])
                        if theirs == "cash_aud"
                        else number(actual[theirs])
                    )
                )
                comparator_residuals.append(float(difference))
        ref, alt = checked["reference"]["summary"], checked["alternative"]["summary"]
        delta = number(ref["quote_scenario_net_cost_aud"]) - number(
            alt["quote_scenario_net_cost_aud"]
        )
        comparator_residuals.append(
            float(abs(delta - number(comparison["diagnostic_incremental_cash_aud"])))
        )
        comparator_residuals.append(
            float(
                abs(
                    number(alt["terminal_energy_kwh"])
                    - number(ref["terminal_energy_kwh"])
                    - number(comparison["diagnostic_terminal_energy_difference_kwh"])
                )
            )
        )
    maximum = max(comparator_residuals, default=0)
    return {
        "path_summaries": {arm: checked[arm]["summary"] for arm in checked},
        "path_checks": checked,
        "comparator_maximum_residual": maximum,
        "energy_tolerance_kwh": float(ENERGY_TOL),
        "cash_tolerance_aud": float(CASH_TOL),
        "passed": all(r["passed"] for r in checked.values())
        and maximum <= float(CASH_TOL),
    }
