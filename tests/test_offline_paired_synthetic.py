"""Independent synthetic arithmetic and invariants; no operational data/DB."""

import copy
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction as F
from pathlib import Path

import pytest

from energy_optimizer.offline_paired_fixtures import (
    FIXTURE_SHA256,
    PUBLIC_FIXTURES,
    evaluate_fixture,
    load_case,
    load_fixture,
)
from energy_optimizer.offline_paired_synthetic import (
    AdmissionError,
    Ledger,
    Parameters,
    Sensitivities,
    Step,
    _evaluate,
    case_from_dict,
    compare_ledgers,
    evaluate,
)

ROOT = Path(__file__).resolve().parents[1]
T = datetime(2026, 1, 1, tzinfo=UTC)


def changed(name="day_charge_A_extension", **changes):
    raw = load_fixture(name)
    raw.update(changes)
    return raw


def run_raw(raw):
    return evaluate(case_from_dict(raw))


def independent_ledger_check(report):
    """Reconcile returned primitive flows with separate rational equations."""
    p = report["parameters"]
    ec, ed = F(str(p["charge_efficiency"])), F(str(p["discharge_efficiency"]))
    for arm in ("reference", "action"):
        cash = F(0)
        losses = F(0)
        for row in report["trace"][arm]:
            v = {
                k: F(str(row[k]))
                for k in (
                    "available_pv_kwh",
                    "curtailed_pv_kwh",
                    "load_kwh",
                    "import_kwh",
                    "export_kwh",
                    "charge_ac_kwh",
                    "discharge_ac_kwh",
                    "unserved_load_kwh",
                    "energy_start_kwh",
                    "energy_end_kwh",
                    "import_price",
                    "export_price",
                )
            }
            left = (
                v["available_pv_kwh"]
                - v["curtailed_pv_kwh"]
                + v["import_kwh"]
                + v["discharge_ac_kwh"]
            )
            right = (
                v["load_kwh"]
                - v["unserved_load_kwh"]
                + v["export_kwh"]
                + v["charge_ac_kwh"]
            )
            assert abs(left - right) < F(1, 10**8)
            assert abs(
                v["energy_end_kwh"]
                - v["energy_start_kwh"]
                - ec * v["charge_ac_kwh"]
                + v["discharge_ac_kwh"] / ed
            ) < F(1, 10**8)
            cash += (
                v["export_kwh"] * v["export_price"]
                - v["import_kwh"] * v["import_price"]
            )
            losses += (1 - ec) * v["charge_ac_kwh"] + (1 / ed - 1) * v[
                "discharge_ac_kwh"
            ]
            assert not (row["import_kwh"] > 1e-9 and row["export_kwh"] > 1e-9)
            assert not (row["charge_ac_kwh"] > 1e-9 and row["discharge_ac_kwh"] > 1e-9)
        assert float(cash) == pytest.approx(report[arm]["cash_aud"])
        assert float(losses) == pytest.approx(report[arm]["loss_kwh"])


def test_native_A_independent_two_hour_arithmetic():
    report = _evaluate(load_case("native_A_two_hours"), full_day=False)
    stored = F(2) * F(9, 10)
    served = stored * F(9, 10)
    ref_bill, action_bill = served * F(1, 2), F(2) * F(1, 5)
    assert report["reference"]["cash_aud"] == pytest.approx(-float(ref_bill))
    assert report["action"]["cash_aud"] == pytest.approx(-float(action_bill))
    assert report["primary_comparative_gross_value_aud"] == pytest.approx(
        float(ref_bill - action_bill)
    )
    assert report["action"]["terminal_energy_kwh"] == pytest.approx(10)
    assert report["reference"]["terminal_energy_kwh"] == pytest.approx(10)
    assert report["action"]["loss_kwh"] == pytest.approx(float(F(2) - served))
    assert report["sensitivities"]["wear_difference_aud"] == pytest.approx(
        float(stored * F(2, 25))
    )
    assert report["sensitivities"]["cash_less_wear_aud"] == pytest.approx(
        float(F(133, 500))
    )
    independent_ledger_check(report)


def supplied_B():
    raw = load_fixture("native_B_supplied_export_ledger")

    def step(key):
        value = dict(raw[key])
        for name in ("start_utc", "end_utc"):
            value[name] = datetime.fromisoformat(value[name])
        value["limiting_reasons"] = tuple(value["limiting_reasons"])
        return Step(**value)

    return (
        Ledger("reference", T, T + timedelta(hours=1), 10, (step("reference_step"),)),
        Ledger(
            "supplied_synthetic_export",
            T,
            T + timedelta(hours=1),
            10,
            (step("alternative_step"),),
        ),
        Parameters(**raw["parameters"]),
        Sensitivities(**raw["sensitivities"]),
    )


def test_native_B_supplied_ledger_only():
    ref, alt, p, sensitivity = supplied_B()
    report = compare_ledgers(ref, alt, p, sensitivity)
    ac = F(2) * F(9, 10)
    assert report["diagnostic_incremental_cash_aud"] == pytest.approx(
        float(ac * F(3, 5))
    )
    assert report["diagnostic_terminal_energy_difference_kwh"] == -2
    assert report["primary_comparative_gross_value_aud"] is None
    assert report["primary_unavailable_reasons"] == ["terminal_energy_unmatched"]
    assert report["sensitivities"]["cash_plus_terminal_aud"] == pytest.approx(0)
    assert report["sensitivities"]["cash_plus_terminal_less_wear_aud"] == pytest.approx(
        -float(F(4, 25))
    )
    other = compare_ledgers(
        ref, alt, p, replace(sensitivity, terminal_lambda_aud_per_dc_kwh=0.3)
    )
    assert other["sensitivities"]["cash_plus_terminal_aud"] == pytest.approx(
        float(F(12, 25))
    )
    assert other["primary_comparative_gross_value_aud"] is None
    bad = replace(alt, steps=(replace(alt.steps[0], energy_end_kwh=9),))
    assert any(
        "energy_balance_failed" in reason
        for reason in compare_ledgers(ref, bad, p, sensitivity)[
            "primary_unavailable_reasons"
        ]
    )


def test_native_C_total_load_not_EV_excluded_baseline():
    report = _evaluate(load_case("native_C_one_hour"), full_day=False)
    total_load = F(1) + F(1)
    assert report["action"]["import_kwh"] == float(total_load)
    assert report["action"]["cash_aud"] == -float(total_load * F(1, 2))
    assert report["reference"]["terminal_energy_kwh"] == 0
    assert report["action"]["terminal_energy_kwh"] == 2
    assert report["diagnostic_incremental_cash_aud"] == -1
    assert report["primary_comparative_gross_value_aud"] is None
    assert report["sensitivities"]["cash_plus_terminal_aud"] == 0
    assert F(1) * F(1, 2) == F(1, 2)  # Deliberately incorrect baseline-only bill.
    independent_ledger_check(report)


@pytest.mark.parametrize("name", PUBLIC_FIXTURES)
def test_public_fixtures_are_complete_24h_and_independently_reconcile(name):
    report = evaluate_fixture(name)
    assert report["admitted"]
    timing = report["timing"]
    assert datetime.fromisoformat(
        timing["comparison_end_utc"]
    ) - datetime.fromisoformat(timing["comparison_start_utc"]) == timedelta(hours=24)
    assert report["fixture_file_sha256"] == FIXTURE_SHA256[name]
    assert report["observed_accounting"] == "not_evaluated"
    assert report["expected_candidate_value"] == "not_rewritten"
    assert report["overlapping_comparisons_are_non_additive"]
    independent_ledger_check(report)


def test_native_short_examples_are_not_public_evaluations():
    for name in ("native_A_two_hours", "native_C_one_hour"):
        report = evaluate(load_case(name))
        assert not report["admitted"]
        assert "invalid_comparison_horizon" in report["primary_unavailable_reasons"]
        assert report["primary_comparative_gross_value_aud"] is None
    with pytest.raises(AdmissionError):
        evaluate_fixture("native_B_supplied_export_ledger")


def test_24h_extensions_have_their_own_supplied_continuation():
    a = evaluate_fixture("day_charge_A_extension")
    c = evaluate_fixture("day_preserve_C_extension")
    assert a["primary_comparative_gross_value_aud"] == pytest.approx(float(F(41, 100)))
    assert c["diagnostic_incremental_cash_aud"] == -1
    assert (
        a["input_sha256"]
        != _evaluate(load_case("native_A_two_hours"), full_day=False)["input_sha256"]
    )
    assert "NOT supplied in native A" in a["assumption_note"]


def test_HOLD_and_sufficient_self_consumption_are_identical_reference():
    assert (
        evaluate_fixture("day_hold_identity")["primary_comparative_gross_value_aud"]
        == 0
    )
    raw = changed("day_hold_identity")
    raw["parameters"].update(policy_floor_kwh=0, terminal_reserve_kwh=0)
    raw["schedule"].update(
        action="DISCHARGE_FOR_SELF_CONSUMPTION", power_limit_kw=2, energy_limit_ac_kwh=2
    )
    report = run_raw(raw)
    assert report["primary_comparative_gross_value_aud"] == 0
    assert report["action"]["delivered_action_ac_kwh"] == 0.5


def test_equal_terminal_below_reserve_remains_unavailable():
    report = evaluate_fixture("day_initial_policy_shortfall")
    assert report["diagnostic_incremental_cash_aud"] == 0
    assert report["diagnostic_terminal_energy_difference_kwh"] == 0
    assert report["primary_comparative_gross_value_aud"] is None
    assert report["primary_unavailable_reasons"] == [
        "reference:terminal_reserve_not_met",
        "action:terminal_reserve_not_met",
    ]
    for arm in ("reference", "action"):
        assert report[arm]["initial_policy_shortfall_kwh"] == 2
        assert report[arm]["additional_policy_shortfall_kwh"] == 0
        assert report[arm]["terminal_energy_kwh"] == 8


@pytest.mark.parametrize("energy", [-1, 21])
def test_physically_invalid_initial_state_rejected(energy):
    assert (
        "initial_energy_outside_physical_bounds"
        in run_raw(changed(initial_energy_kwh=energy))["primary_unavailable_reasons"]
    )


def test_capacity_limit_delivers_less_without_raising_state_afterwards():
    raw = changed(initial_energy_kwh=19.5)
    report = run_raw(raw)
    assert report["action"]["delivered_action_ac_kwh"] == pytest.approx(
        float(F(1, 2) / F(9, 10))
    )
    assert report["trace"]["action"][0]["energy_end_kwh"] == pytest.approx(20)
    assert any(
        "capacity_headroom" in row["limiting_reasons"]
        for row in report["trace"]["action"]
    )
    assert report["schedule_delivery_status"] == "constrained_no_catch_up"
    independent_ledger_check(report)


def test_grid_charge_respects_household_import_headroom():
    report = evaluate_fixture("day_charge_import_headroom")
    assert report["action"]["requested_action_ac_kwh"] == 2
    assert report["action"]["delivered_action_ac_kwh"] == 0.25
    assert report["action"]["import_kwh"] == 1
    assert report["diagnostic_incremental_cash_aud"] == pytest.approx(-float(F(1, 20)))
    assert report["diagnostic_terminal_energy_difference_kwh"] == pytest.approx(
        float(F(9, 40))
    )


def test_PV_priority_export_curtailed_and_lossless_energy():
    report = evaluate_fixture("day_solar_curtailment")
    assert report["reference"]["export_kwh"] == 1
    assert report["reference"]["curtailed_pv_kwh"] == 3
    assert report["reference"]["terminal_energy_kwh"] == 2
    assert report["reference"]["loss_kwh"] == 0
    assert report["reference"]["cash_aud"] == pytest.approx(float(F(1, 10)))
    assert report["primary_comparative_gross_value_aud"] == 0
    raw = changed("day_solar_curtailment")
    raw["parameters"]["curtailment_permitted"] = False
    assert any(
        "curtailment_not_permitted" in reason
        for reason in run_raw(raw)["primary_unavailable_reasons"]
    )


def test_unserved_load_is_not_an_economic_victory():
    report = evaluate_fixture("day_unserved_load")
    assert report["reference"]["unserved_load_kwh"] == 1
    assert report["diagnostic_incremental_cash_aud"] == 0
    assert report["primary_comparative_gross_value_aud"] is None
    assert any(
        "unserved_load" in reason for reason in report["primary_unavailable_reasons"]
    )


def timed_raw(seconds):
    raw = changed("day_hold_identity")
    ready = T + timedelta(seconds=seconds)
    minute = ((seconds + 299) // 300) * 5
    start = T + timedelta(minutes=minute)
    end = start + timedelta(hours=24)
    raw.update(
        decision_ready_at_utc=ready.isoformat(),
        comparison_start_utc=start.isoformat(),
        comparison_end_utc=end.isoformat(),
        initial_state_at_utc=start.isoformat(),
    )
    for name in (
        "household_load_kw",
        "available_pv_kw",
        "import_price_aud_per_kwh",
        "export_price_aud_per_kwh",
    ):
        raw[name][0].update(start_utc=start.isoformat(), end_utc=end.isoformat())
    raw["household_load_kw"][0]["value"] = 0
    raw["schedule"].update(
        action="CHARGE_BATTERY_FROM_GRID", power_limit_kw=2, energy_limit_ac_kwh=2
    )
    return raw


@pytest.mark.parametrize(
    "seconds,expected", [(0, F(2)), (20, F(11, 6)), (300, F(11, 6)), (3620, F(0))]
)
def test_exact_delayed_clipped_and_expired_schedule(seconds, expected):
    report = run_raw(timed_raw(seconds))
    assert report["action"]["delivered_action_ac_kwh"] == pytest.approx(float(expected))
    assert (
        report["timing"]["supplied_schedule"]["end_utc"]
        == (T + timedelta(hours=1)).isoformat()
    )
    if seconds > 3600:
        assert report["schedule_delivery_status"] == "expired_or_outside_horizon"


def test_energy_budget_is_not_retried_after_blocked_delivery_or_late_readiness():
    raw = timed_raw(1800)
    raw["schedule"]["energy_limit_ac_kwh"] = 0.5
    report = run_raw(raw)
    assert report["action"]["delivered_action_ac_kwh"] == 0
    assert report["requested_energy_lost_before_branch_point_ac_kwh"] == 0.5
    raw = changed("day_hold_identity")
    raw["parameters"].update(import_limit_kw=1)
    raw["household_load_kw"] = [
        dict(
            start_utc=T.isoformat(),
            end_utc=(T + timedelta(minutes=30)).isoformat(),
            value=1,
        ),
        dict(
            start_utc=(T + timedelta(minutes=30)).isoformat(),
            end_utc=(T + timedelta(hours=24)).isoformat(),
            value=0,
        ),
    ]
    raw["schedule"].update(
        action="CHARGE_BATTERY_FROM_GRID", power_limit_kw=1, energy_limit_ac_kwh=1
    )
    report = run_raw(raw)
    assert report["action"]["requested_action_ac_kwh"] == 1
    assert (
        report["action"]["delivered_action_ac_kwh"] == 0.5
    )  # First blocked half-hour is lost.


@pytest.mark.parametrize(
    "field",
    [
        "household_load_kw",
        "available_pv_kw",
        "import_price_aud_per_kwh",
        "export_price_aud_per_kwh",
    ],
)
@pytest.mark.parametrize("gap", [1, 2])
def test_cash_inputs_never_get_F3_gap_allowance(field, gap):
    raw = changed("day_hold_identity")
    row = raw[field][0]
    raw[field] = [
        dict(row, end_utc=(T + timedelta(hours=1)).isoformat()),
        dict(row, start_utc=(T + timedelta(hours=1, seconds=gap)).isoformat()),
    ]
    report = run_raw(raw)
    assert not report["admitted"]
    assert any(
        "coverage_gap" in reason for reason in report["primary_unavailable_reasons"]
    )
    assert report["diagnostic_incremental_cash_aud"] is None


@pytest.mark.parametrize(
    "mode",
    ["leading", "trailing", "duplicate", "conflicting", "nan", "inf", "negative_load"],
)
def test_bad_common_inputs_withhold_comparison(mode):
    raw = changed("day_hold_identity")
    row = raw["household_load_kw"][0]
    if mode == "leading":
        row["start_utc"] = (T + timedelta(seconds=1)).isoformat()
    elif mode == "trailing":
        row["end_utc"] = (T + timedelta(hours=24, seconds=-1)).isoformat()
    elif mode in {"duplicate", "conflicting"}:
        raw["household_load_kw"].append(
            dict(row, value=0.6 if mode == "conflicting" else 0.5)
        )
    else:
        row["value"] = {"nan": float("nan"), "inf": float("inf"), "negative_load": -1}[
            mode
        ]
    report = run_raw(raw)
    assert (
        not report["admitted"] and report["primary_comparative_gross_value_aud"] is None
    )
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf"), True])
def test_no_unknown_nonfinite_or_implicit_limits(value):
    raw = changed()
    raw["parameters"]["charge_limit_kw"] = value
    assert not run_raw(raw)["admitted"]


def test_finite_zero_limits_are_explicit_not_unlimited():
    raw = changed()
    raw["parameters"].update(
        charge_limit_kw=0, discharge_limit_kw=0, import_limit_kw=0, export_limit_kw=0
    )
    report = run_raw(raw)
    assert report["admitted"]
    assert report["action"]["delivered_action_ac_kwh"] == 0
    assert any(
        "unserved_load" in reason for reason in report["primary_unavailable_reasons"]
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("topology", "shared_hybrid_inverter"),
        ("flow_domain", "DC"),
        ("stored_energy_domain", "AC"),
        ("pv_abstraction", "observed_delivered_PV"),
        ("charge_efficiency", 0),
        ("discharge_efficiency", 1.1),
        ("terminal_reserve_kwh", 9),
    ],
)
def test_unsupported_or_inconsistent_assumptions(key, value):
    raw = changed()
    raw["parameters"][key] = value
    assert not run_raw(raw)["admitted"]


@pytest.mark.parametrize("action", ["EXPORT_BATTERY", "DEFER_EXPORT", "CHARGE_EV_NOW"])
def test_unsupported_actions_rejected_before_dispatch(action):
    raw = changed()
    raw["schedule"]["action"] = action
    report = run_raw(raw)
    assert "unsupported_action" in report["primary_unavailable_reasons"]
    assert "trace" not in report


def test_no_EV_double_count_or_vehicle_domain_substitution():
    raw = changed("day_preserve_C_extension")
    raw["load_kind"] = "total_including_fixed_ev"
    assert "ev_would_be_double_counted" in run_raw(raw)["primary_unavailable_reasons"]
    raw["load_kind"] = "vehicle_battery_power"
    assert "unsupported_load_semantics" in run_raw(raw)["primary_unavailable_reasons"]


def test_negative_prices_are_signed_and_do_not_select_action():
    raw = changed("day_hold_identity")
    raw["import_price_aud_per_kwh"][0]["value"] = -0.2
    report = run_raw(raw)
    assert report["reference"]["cash_aud"] == pytest.approx(float(F(12) * F(1, 5)))
    assert report["primary_comparative_gross_value_aud"] == 0
    solar = changed("day_solar_curtailment")
    solar["export_price_aud_per_kwh"][0]["value"] = -0.1
    assert run_raw(solar)["reference"]["cash_aud"] == pytest.approx(-0.1)
    before = evaluate_fixture("day_charge_A_extension")
    modified = changed()
    modified["import_price_aud_per_kwh"][1]["value"] = 99
    after = run_raw(modified)
    assert before["frozen_schedule_sha256"] == after["frozen_schedule_sha256"]
    assert (
        before["action"]["delivered_action_ac_kwh"]
        == after["action"]["delivered_action_ac_kwh"]
    )


@pytest.mark.parametrize(
    "delta,eligible", [(5e-7, True), (1e-6, True), (1.1e-6, False)]
)
def test_terminal_tolerance_retains_residual_without_valuation(delta, eligible):
    ref, _, p, _ = supplied_B()
    p = replace(
        p,
        policy_floor_kwh=0,
        terminal_reserve_kwh=0,
        charge_efficiency=1,
        discharge_efficiency=1,
    )
    zero = replace(ref.steps[0], energy_start_kwh=0, energy_end_kwh=0)
    ref = replace(ref, initial_energy_kwh=0, steps=(zero,))
    alt = replace(
        ref,
        label="action",
        steps=(
            replace(zero, energy_end_kwh=delta, import_kwh=delta, charge_ac_kwh=delta),
        ),
    )
    report = compare_ledgers(ref, alt, p, Sensitivities(None, None))
    assert (report["primary_comparative_gross_value_aud"] is not None) is eligible
    assert report["terminal_residual_retained_kwh"] == delta
    assert report["wear_status"] == "not_modelled"


def test_independent_ledger_mismatch_and_opposing_flows_rejected():
    ref, alt, p, sensitivity = supplied_B()
    unmatched = replace(alt, end_utc=alt.end_utc + timedelta(hours=1))
    reasons = compare_ledgers(ref, unmatched, p, sensitivity)[
        "primary_unavailable_reasons"
    ]
    assert "starting_conditions_or_horizons_differ" in reasons
    opposing = replace(
        ref, steps=(replace(ref.steps[0], import_kwh=0.1, export_kwh=0.1),)
    )
    assert any(
        "opposing_flows" in reason
        for reason in compare_ledgers(ref, opposing, p, sensitivity)[
            "primary_unavailable_reasons"
        ]
    )


def test_no_default_fields_bounded_intervals_and_causal_state():
    raw = changed()
    del raw["parameters"]["discharge_efficiency"]
    with pytest.raises(AdmissionError):
        case_from_dict(raw)
    raw = changed()
    raw["initial_state_at_utc"] = (T + timedelta(seconds=1)).isoformat()
    assert (
        "initial_state_not_at_branch_point"
        in run_raw(raw)["primary_unavailable_reasons"]
    )
    raw = changed()
    raw["schedule"]["supplied_at_utc"] = (T + timedelta(seconds=1)).isoformat()
    assert (
        "action_not_supplied_by_readiness"
        in run_raw(raw)["primary_unavailable_reasons"]
    )
    raw = changed()
    raw["household_load_kw"] *= 4097
    assert not run_raw(raw)["admitted"]


def test_immutable_inputs_deterministic_json_and_hashes():
    raw = changed()
    original = copy.deepcopy(raw)
    first = run_raw(raw)
    assert raw == original
    assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(
        run_raw(raw), sort_keys=True, allow_nan=False
    )
    assert "wear_aud_per_discharged_dc_kwh" not in first["parameters"]


def offline_env():
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(
        PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"
    )
    return env


def test_CLI_allowlist_and_deterministic_execution_without_runtime_clients():
    script = ROOT / "tools/evaluate_paired_synthetic.py"
    result = subprocess.run(
        [sys.executable, str(script), "--fixture", "day_charge_A_extension"],
        env=offline_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)[
        "primary_comparative_gross_value_aud"
    ] == pytest.approx(0.41)
    for args in (
        ["--fixture", "native_A_two_hours"],
        ["--fixture", "../../private"],
        ["--input", "some-household-export.json"],
    ):
        rejected = subprocess.run(
            [sys.executable, str(script), *args],
            env=offline_env(),
            capture_output=True,
            text=True,
        )
        assert rejected.returncode == 2
    guard = """
import sys, runpy
def audit(event,args):
    if event in {"socket.connect","socket.bind"}:
        raise AssertionError("Network forbidden")
    if event == "open" and str(args[0]).endswith(".env"):
        raise AssertionError("Environment file forbidden")
sys.addaudithook(audit)
sys.argv=["evaluate_paired_synthetic.py","--fixture","day_hold_identity"]
runpy.run_path(sys.argv[0],run_name="guarded_cli")
from energy_optimizer.offline_paired_fixtures import evaluate_fixture
evaluate_fixture("day_hold_identity")
for name in {
    "requests","sqlalchemy","psycopg","dotenv",
    "energy_optimizer.config","energy_optimizer.persistence"
}:
    assert name not in sys.modules,name
"""
    # runpy imports the script without main; evaluate_fixture exercises the same core.
    subprocess.run(
        [sys.executable, "-c", guard],
        cwd=ROOT / "tools",
        env=offline_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def test_fixture_authorship_not_a_real_data_flag_and_hash_pin(monkeypatch):
    with pytest.raises(AdmissionError):
        load_fixture("real-record-with-synthetic-flag")
    raw = changed(source_kind="anonymised_production")
    assert (
        "synthetic_authorship_required" in run_raw(raw)["primary_unavailable_reasons"]
    )
    monkeypatch.setitem(FIXTURE_SHA256, "day_hold_identity", "0" * 64)
    with pytest.raises(AdmissionError, match="fixture_byte_hash_mismatch"):
        load_case("day_hold_identity")


def test_charge_limit_and_discharge_limit_are_separate():
    raw = changed()
    raw["parameters"]["charge_limit_kw"] = 0.5
    report = run_raw(raw)
    assert report["action"]["delivered_action_ac_kwh"] == 0.5
    assert "charge_limit" in report["trace"]["action"][0]["limiting_reasons"]
    raw = changed("day_hold_identity")
    raw["parameters"].update(
        policy_floor_kwh=0, terminal_reserve_kwh=0, discharge_limit_kw=0.25
    )
    raw["schedule"].update(
        action="DISCHARGE_FOR_SELF_CONSUMPTION", power_limit_kw=2, energy_limit_ac_kwh=2
    )
    report = run_raw(raw)
    assert report["action"]["delivered_action_ac_kwh"] == 0.25
    assert report["primary_comparative_gross_value_aud"] == 0


def test_solar_charge_priority_never_imports_while_exporting():
    raw = changed("day_solar_curtailment")
    raw["schedule"].update(
        action="CHARGE_BATTERY_FROM_GRID", power_limit_kw=2, energy_limit_ac_kwh=2
    )
    report = run_raw(raw)
    row = report["trace"]["action"][0]
    assert row["charge_ac_kwh"] == 1 and row["export_kwh"] == 0.5
    assert row["delivered_action_ac_kwh"] == 0 and row["import_kwh"] == 0
    assert "opposing_export" in row["limiting_reasons"]
    independent_ledger_check(report)


def test_common_passive_charge_can_restore_initial_shortfall():
    raw = changed("day_initial_policy_shortfall")
    raw["parameters"].update(charge_efficiency=1)
    raw["available_pv_kw"] = [
        dict(
            start_utc=T.isoformat(),
            end_utc=(T + timedelta(hours=1)).isoformat(),
            value=2,
        ),
        dict(
            start_utc=(T + timedelta(hours=1)).isoformat(),
            end_utc=(T + timedelta(hours=24)).isoformat(),
            value=0,
        ),
    ]
    report = run_raw(raw)
    assert report["primary_comparative_gross_value_aud"] == 0
    assert report["reference"]["initial_policy_shortfall_kwh"] == 2
    assert report["reference"]["terminal_energy_kwh"] == 10
    assert report["reference"]["additional_policy_shortfall_kwh"] == 0


def test_opposite_flows_across_different_intervals_are_legitimate():
    raw = changed("day_solar_curtailment")
    raw["household_load_kw"] = [
        dict(
            start_utc=T.isoformat(),
            end_utc=(T + timedelta(hours=2)).isoformat(),
            value=0,
        ),
        dict(
            start_utc=(T + timedelta(hours=2)).isoformat(),
            end_utc=(T + timedelta(hours=24)).isoformat(),
            value=0.1,
        ),
    ]
    report = run_raw(raw)
    assert (
        report["reference"]["export_kwh"] > 0 and report["reference"]["import_kwh"] > 0
    )
    assert report["reference"]["trajectory_feasible"]
    assert report["primary_comparative_gross_value_aud"] == 0
    independent_ledger_check(report)


def test_partial_action_boundary_and_price_boundary_are_split():
    raw = changed("day_hold_identity")
    raw["household_load_kw"][0]["value"] = 0
    raw["schedule"].update(
        action="CHARGE_BATTERY_FROM_GRID",
        power_limit_kw=2,
        energy_limit_ac_kwh=2,
        start_utc=(T + timedelta(minutes=15)).isoformat(),
        end_utc=(T + timedelta(minutes=45)).isoformat(),
    )
    raw["import_price_aud_per_kwh"] = [
        dict(
            start_utc=T.isoformat(),
            end_utc=(T + timedelta(minutes=30)).isoformat(),
            value=0.2,
        ),
        dict(
            start_utc=(T + timedelta(minutes=30)).isoformat(),
            end_utc=(T + timedelta(hours=24)).isoformat(),
            value=0.4,
        ),
    ]
    report = run_raw(raw)
    assert report["action"]["delivered_action_ac_kwh"] == 1
    assert report["action"]["cash_aud"] == pytest.approx(
        -float(F(1, 2) * F(1, 5) + F(1, 2) * F(2, 5))
    )
    assert len(report["trace"]["action"]) == 4
    independent_ledger_check(report)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
def test_nonfinite_supplied_ledger_has_no_primary_value(bad):
    ref, alt, p, sensitivity = supplied_B()
    alt = replace(alt, steps=(replace(alt.steps[0], import_kwh=bad),))
    report = compare_ledgers(ref, alt, p, sensitivity)
    assert report["primary_comparative_gross_value_aud"] is None
    assert not report["ledger_comparison_admitted"]
    assert report["diagnostic_incremental_cash_aud"] is None


def test_cash_sign_reversal_and_bad_sensitivity():
    ref, alt, p, sensitivity = supplied_B()
    forward = compare_ledgers(ref, alt, p, sensitivity)
    reverse = compare_ledgers(alt, ref, p, sensitivity)
    assert (
        reverse["diagnostic_incremental_cash_aud"]
        == -forward["diagnostic_incremental_cash_aud"]
    )
    assert (
        reverse["diagnostic_terminal_energy_difference_kwh"]
        == -forward["diagnostic_terminal_energy_difference_kwh"]
    )
    bad = compare_ledgers(
        ref, alt, p, replace(sensitivity, wear_aud_per_discharged_dc_kwh=-1)
    )
    assert bad["primary_comparative_gross_value_aud"] is None


def test_unsupported_energy_interval_and_naive_timestamps():
    raw = changed()
    raw["parameters"]["interval_interpretation"] = "interval_energy_kwh"
    assert (
        "unsupported_interval_interpretation"
        in run_raw(raw)["primary_unavailable_reasons"]
    )
    raw = changed()
    raw["decision_ready_at_utc"] = "2026-01-01T00:00:00"
    with pytest.raises(AdmissionError, match="timestamp_timezone_missing"):
        case_from_dict(raw)


def test_request_exhaustion_is_fixed_even_if_delivery_was_constrained():
    raw = changed()
    raw["schedule"]["energy_limit_ac_kwh"] = 0.5
    raw["parameters"]["charge_limit_kw"] = 1
    report = run_raw(raw)
    assert report["action"]["requested_action_ac_kwh"] == 0.5
    assert report["action"]["delivered_action_ac_kwh"] == 0.25
    assert (
        report["trace"]["action"][0]["end_utc"]
        == (T + timedelta(minutes=15)).isoformat()
    )
    assert all(
        row["delivered_action_ac_kwh"] == 0 for row in report["trace"]["action"][1:]
    )


def test_large_energy_cap_does_not_overflow_schedule_boundary():
    raw = changed()
    raw["schedule"]["energy_limit_ac_kwh"] = 1e100
    report = run_raw(raw)
    assert report["admitted"]
    assert report["action"]["delivered_action_ac_kwh"] == 2


def test_identical_price_partition_does_not_change_capacity_limited_routing():
    raw = changed("day_hold_identity")
    raw["initial_energy_kwh"] = 9
    raw["parameters"].update(
        capacity_kwh=10,
        policy_floor_kwh=1,
        terminal_reserve_kwh=1,
        charge_efficiency=1,
        discharge_efficiency=1,
    )
    raw["household_load_kw"][0]["value"] = 0
    raw["available_pv_kw"] = [
        dict(
            start_utc=T.isoformat(),
            end_utc=(T + timedelta(hours=1)).isoformat(),
            value=1,
        ),
        dict(
            start_utc=(T + timedelta(hours=1)).isoformat(),
            end_utc=(T + timedelta(hours=24)).isoformat(),
            value=0,
        ),
    ]
    raw["schedule"].update(
        action="CHARGE_BATTERY_FROM_GRID", power_limit_kw=1, energy_limit_ac_kwh=1
    )
    before = run_raw(raw)
    row = raw["import_price_aud_per_kwh"][0]
    raw["import_price_aud_per_kwh"] = [
        dict(row, end_utc=(T + timedelta(minutes=30)).isoformat()),
        dict(row, start_utc=(T + timedelta(minutes=30)).isoformat()),
    ]
    after = run_raw(raw)
    # PV and grid charge at 1 kW each until capacity at half-hour; then PV exports.
    expected = F(1, 2) * F(1, 10) - F(1, 2) * F(1, 5)
    for report in (before, after):
        assert report["primary_comparative_gross_value_aud"] == pytest.approx(
            float(expected)
        )
        assert report["action"]["delivered_action_ac_kwh"] == 0.5
        independent_ledger_check(report)
