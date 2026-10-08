"""Versioned, private conditional research wrapper around the pinned pure core.

No SyntheticCase, fixture registration, public evaluate(), config or client imports.
The paired kernel computes both states separately; no dispatch equations live here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

from energy_optimizer.arbitrage.independent_reconciler import (
    aggregate_intervals,
    reconcile_pair,
)

VERSION = "conditional-dispatch-adapter-v1.2"
EXPORT_SHA = "80d4c418fe7cdfe1ec912fd3431e8a2a603fc5c5a5baa7aa5c26350d50323ce4"
PROFILE_SHA = "4821698021670339156c630d94c9a00971789449761d9e58dc7ad0f083536261"
BUNDLE_SHA = "8ad2de156628ed62ad2a8439420986ca31c8928126ad9522bc7131471fa73cd4"
INPUT_SHA = "25941f3dc6aab3a34a87f97d742685457c09205ed2ed14567126f4db0c0e2e65"
START = datetime(2026, 10, 4, 1, 5, tzinfo=UTC)
EXPIRY = datetime(2026, 10, 4, 1, 30, tzinfo=UTC)
END = START + timedelta(hours=24)
BAD_SLOT = datetime(2026, 10, 4, 10, 35, tzinfo=UTC)
STEP = timedelta(minutes=5)
QUOTE_POLICY = "retained_current_quotes_with_disclosed_health_exception_v1"


class StudyError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StudyError("timezone_missing")
    return parsed.astimezone(UTC)


def finite_number(value: Any, *, nonnegative: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise StudyError("missing_or_invalid_number")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise StudyError("nonfinite_or_negative_power")
    return result


def normalize_export(raw: dict[str, Any]) -> dict[str, Any]:
    """Pure validation; preserves missing quotes for energy-only diagnosis."""
    confirmations = raw["fixed_decision_confirmation"]
    if len(confirmations) != 1:
        raise StudyError("decision_confirmation_count")
    d = confirmations[0]
    if (
        d["id"],
        d["forecast_run_id"],
        d["reserve_run_id"],
        d["input_hash"],
        d["selected_action"],
    ) != (1375, 2540, 2530, INPUT_SHA, "HOLD"):
        raise StudyError("fixed_identity_mismatch")
    if utc(d["decision_boundary_utc"]) != START - STEP:
        raise StudyError("decision_boundary_mismatch")
    rows = raw["observations"]
    expected = [START - STEP + i * STEP for i in range(290)]
    if len(rows) != 290 or [utc(r["slot_utc"]) for r in rows] != expected:
        raise StudyError("290_row_grid_duplicate_gap_range_or_order_mismatch")
    if (
        not raw["fixed_identity_checks_passed"]
        or not raw["transaction_ended_with_rollback"]
    ):
        raise StudyError("retained_export_identity_not_confirmed")
    intervals, price_issues, health_exceptions = [], [], []
    for row in rows:
        slot = utc(row["slot_utc"])
        utc(row["observed_at_utc"])
        load_kw = finite_number(row["house_consumption_w"], nonnegative=True) / 1000
        pv_kw = finite_number(row["pv_power_w"], nonnegative=True) / 1000
        if row["price_is_healthy"] is not True:
            health_exceptions.append(
                {
                    "slot_utc": slot.isoformat(),
                    "original_price_is_healthy": row["price_is_healthy"],
                    "import_quote_aud_per_kwh": row["amber_import_price_per_kwh"],
                    "export_quote_aud_per_kwh": row["amber_export_price_per_kwh"],
                    "cause": "unknown",
                }
            )
        quotes = {}
        for name, field in [
            ("import_price", "amber_import_price_per_kwh"),
            ("export_price", "amber_export_price_per_kwh"),
        ]:
            try:
                quotes[name] = finite_number(row[field])
            except (ValueError, TypeError):
                quotes[name] = (
                    None  # Unknown stays unknown; never a zero-priced interval.
                )
                if START <= slot < END:
                    price_issues.append(
                        {
                            "slot_utc": slot.isoformat(),
                            "field": field,
                            "reason": "missing_or_nonfinite_quote",
                        }
                    )
        if START <= slot < END:
            intervals.append(
                {
                    "start_utc": slot,
                    "end_utc": slot + STEP,
                    "load_kw": load_kw,
                    "pv_proxy_kw": pv_kw,
                    **quotes,
                }
            )
    approved_exception = (
        len(health_exceptions) == 1
        and utc(health_exceptions[0]["slot_utc"]) == BAD_SLOT
        and health_exceptions[0]["original_price_is_healthy"] is False
    )
    if approved_exception:
        approved_exception = (
            health_exceptions[0]["import_quote_aud_per_kwh"],
            health_exceptions[0]["export_quote_aud_per_kwh"],
        ) == (0.3603565, 0.1065998)
    if not approved_exception:
        price_issues.append({"reason": "known_health_exception_policy_mismatch"})
    branch = rows[1]
    return {
        "intervals": intervals,
        "price_issues": price_issues,
        "quote_scenario_available": not price_issues,
        "price_health_exceptions": health_exceptions,
        "aggregate_price_health_complete": False,
        "provider_settlement_verified": False,
        "observed_branch_context": {
            k: branch[k]
            for k in (
                "slot_utc",
                "observed_at_utc",
                "battery_soc_percent",
                "battery_energy_estimate_kwh",
            )
        },
        "source_kind": "real_retained_export",
        "raw_row_count": 290,
    }


def load_core(root: Path, manifest_path: Path) -> tuple[Any, dict[str, Any]]:
    sys.dont_write_bytecode = True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = {name: sha(root / name) for name in manifest["new_files"]}
    if actual != manifest["new_files"] or content_hash(actual) != BUNDLE_SHA:
        raise StudyError("reviewed_source_bundle_mismatch")
    path = root / "src/energy_optimizer/offline_paired_synthetic.py"
    name = "reviewed_conditional_arithmetic_core"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if (
        Path(module.__file__).resolve() != path.resolve()
        or sha(Path(module.__file__))
        != actual["src/energy_optimizer/offline_paired_synthetic.py"]
    ):
        raise StudyError("loaded_core_identity_mismatch")
    return module, {
        "bundle_sha256": BUNDLE_SHA,
        "prototype_file_hashes": actual,
        "loaded_module": str(path),
        "loaded_module_sha256": sha(path),
        "pure_apis_used": ["_simulate_pair", "compare_ledgers"],
        "fixture_admission_apis_called": [],
    }


def load_profiles(path: Path) -> dict[str, Any]:
    if sha(path) != PROFILE_SHA:
        raise StudyError("approved_profile_file_hash_mismatch")
    data = json.loads(path.read_text(encoding="utf-8"))
    if [p["profile_id"] for p in data["profiles"]] != ["A-plus", "B-plus", "C-plus"]:
        raise StudyError("unapproved_profile_id")
    return data


def numerical_parameters(core: Any, profile: dict, common: dict) -> Any:
    expression = profile["charge_ac_ceiling_expression"]
    ac = {
        "9.999": Fraction("9.999"),
        "8.0": Fraction(8),
        "13.5 / 0.95": Fraction("13.5") / Fraction("0.95"),
    }[expression]
    if ac * Fraction(str(profile["charge_efficiency"])) != Fraction(
        str(profile["net_stored_charge_ceiling_kw"])
    ):
        raise StudyError("stored_to_AC_charge_mapping_mismatch")
    p = core.Parameters(
        capacity_kwh=profile["capacity_kwh"],
        physical_min_kwh=common["physical_minimum_kwh"],
        policy_floor_kwh=common["policy_floor_kwh"],
        terminal_reserve_kwh=common["terminal_reserve_kwh"],
        charge_efficiency=profile["charge_efficiency"],
        discharge_efficiency=profile["discharge_efficiency"],
        charge_limit_kw=float(ac),
        discharge_limit_kw=common["discharge_ac_ceiling_kw"],
        import_limit_kw=common["grid_import_ceiling_kw"],
        export_limit_kw=common["grid_export_ceiling_kw"],
        topology=core.TOPOLOGY,
        flow_domain="AC_bus_kWh",
        stored_energy_domain="DC_stored_kWh",
        pv_abstraction="available_exogenous_synthetic",
        curtailment_permitted=True,
        interval_interpretation="piecewise_constant_interval_average_kw",
    )
    if not (
        0 <= p.physical_min_kwh <= p.policy_floor_kwh <= p.capacity_kwh
        and p.physical_min_kwh <= profile["initial_energy_kwh"] <= p.capacity_kwh
        and 0 < p.charge_efficiency <= 1
        and 0 < p.discharge_efficiency <= 1
    ):
        raise StudyError("inconsistent_approved_parameters")
    return p


@dataclass(frozen=True)
class ConditionalInputs:
    """Structural pure-kernel inputs; deliberately not a SyntheticCase."""

    data_origin: str
    study_class: str
    comparison_start_utc: datetime
    comparison_end_utc: datetime
    initial_energy_kwh: float
    parameters: Any
    schedule: Any
    load_kind: str
    household_load_kw: tuple
    fixed_ev_load_kw: tuple
    # Core variable: reported-PV proxy ceiling, not measured available solar.
    available_pv_kw: tuple
    import_price_aud_per_kwh: tuple
    export_price_aud_per_kwh: tuple


def assemble_inputs(
    core: Any,
    normalized: dict,
    profile: dict,
    common: dict,
    action: str,
    ready_upper: datetime,
) -> ConditionalInputs:
    p = numerical_parameters(core, profile, common)
    rows = normalized["intervals"]

    def series(key):
        return tuple(core.Interval(r["start_utc"], r["end_utc"], r[key]) for r in rows)

    return ConditionalInputs(
        "real_retained_export",
        "conditional_proxy_research",
        START,
        END,
        profile["initial_energy_kwh"],
        p,
        core.Schedule(action, ready_upper, START, EXPIRY, 0.0, 0.0),
        "total_household_including_EV_once",
        series("load_kw"),
        (),
        series("pv_proxy_kw"),
        series("import_price"),
        series("export_price"),
    )


def calculate_pair(
    core: Any, inputs: ConditionalInputs, *, cash_available: bool
) -> tuple[Any, Any, dict | None]:
    reference, alternative = core._simulate_pair(inputs)
    comparison = None
    if cash_available:
        comparison = core.compare_ledgers(
            reference, alternative, inputs.parameters, core.Sensitivities(None, None)
        )
        if not comparison["ledger_comparison_admitted"]:
            raise StudyError("pure_comparator_rejected_generated_ledgers")
    return reference, alternative, comparison


def serialise_ledger(ledger: Any) -> dict:
    rows = []
    for step in ledger.steps:
        row = asdict(step)
        row["proxy_pv_ceiling_kwh"] = row.pop("available_pv_kwh")
        row["proxy_spillage_kwh"] = row.pop("curtailed_pv_kwh")
        for key in ("start_utc", "end_utc"):
            row[key] = row[key].astimezone(UTC).isoformat()
        rows.append(row)
    return {
        "label": ledger.label,
        "start_utc": ledger.start_utc.isoformat(),
        "end_utc": ledger.end_utc.isoformat(),
        "initial_energy_kwh": ledger.initial_energy_kwh,
        "steps": rows,
    }


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )


def evaluate_study(
    core: Any, normalized: dict, profiles: dict, selection: dict
) -> tuple[dict, dict, list[dict]]:
    comparisons, reconciliations, interval_rows = [], [], []
    for profile in profiles["profiles"]:
        for action, candidate in [("PRESERVE_BATTERY", 12369), ("HOLD", 12367)]:
            inputs = assemble_inputs(
                core,
                normalized,
                profile,
                profiles["common"],
                action,
                utc(selection["ready_upper_bound_utc"]),
            )
            reference, alternative, comparison = calculate_pair(
                core, inputs, cash_available=normalized["quote_scenario_available"]
            )
            ledgers = {
                "reference": serialise_ledger(reference),
                "alternative": serialise_ledger(alternative),
            }
            key = profile["profile_id"] + "/" + action
            reconciled = reconcile_pair(
                ledgers,
                asdict(inputs.parameters),
                comparison,
                normalized,
                expiry=EXPIRY,
                bad_slot=BAD_SLOT,
            )
            # Comparator's primary is retained ONLY as abstract numerical comparability.
            numeric_value = (
                None
                if comparison is None
                else comparison["primary_comparative_gross_value_aud"]
            )
            item = {
                "comparison_id": key,
                "profile_id": profile["profile_id"],
                "candidate_id": candidate,
                "action": action,
                "profile": profile,
                "core_numeric_parameters": asdict(inputs.parameters),
                "price_policy": QUOTE_POLICY,
                "price_health_exception": normalized["price_health_exceptions"],
                "aggregate_price_health_complete": False,
                "provider_settlement_verified": False,
                "strict_price_validated_cost_aud": {
                    "reference": None,
                    "alternative": None,
                },
                "installed_clean_price_primary_value_aud": None,
                "strict_primary_unavailable_reasons": [
                    "installed_system_admission_not_passed",
                    "known_price_health_failure_cause_unknown",
                    "point_sample_AC_equivalent_load_and_reported_PV_proxy",
                    "interventions_unknown",
                ],
                "abstract_numerical_comparability": comparison is not None
                and numeric_value is not None,
                "abstract_numerical_value_aud": numeric_value,
                "abstract_numerical_unavailable_reasons": (
                    normalized["price_issues"]
                    if comparison is None
                    else comparison["primary_unavailable_reasons"]
                ),
                "conditional_incremental_cash_aud": (
                    None
                    if comparison is None
                    else comparison["diagnostic_incremental_cash_aud"]
                ),
                "terminal_energy_difference_kwh": alternative.steps[-1].energy_end_kwh
                - reference.steps[-1].energy_end_kwh,
                "reference": reconciled["path_summaries"]["reference"],
                "alternative": reconciled["path_summaries"]["alternative"],
                "ledgers": ledgers,
            }
            comparisons.append(item)
            reconciliations.append({"comparison_id": key, **reconciled})
            for arm, ledger in ledgers.items():
                interval_rows.extend(
                    {"comparison_id": key, "path": arm, **row}
                    for row in aggregate_intervals(ledger, normalized["intervals"])
                )
    payload = {
        "adapter_version": VERSION,
        "data_origin": "real_retained_export",
        "study_class": "conditional_proxy_research",
        "installed_system_admission": "not_passed",
        "model_profile_origin": "explicitly_authorised_research_assumption",
        "export_sha256": EXPORT_SHA,
        "profile_set_id": profiles["profile_set_id"],
        "observed_branch_context": normalized["observed_branch_context"],
        "assumed_initial_states_not_overridden": True,
        "decision_id": 1375,
        "original_preserve_id": 12369,
        "selected_hold_control_id": 12367,
        "comparison_start_utc": START.isoformat(),
        "action_expiry_utc": EXPIRY.isoformat(),
        "comparison_end_utc": END.isoformat(),
        "ready_timestamp_class": "retained_cycle_finish_upper_bound_only",
        "intervention_status": "unknown",
        "comparisons": comparisons,
        "overlapping_comparisons_non_additive": True,
    }
    return (
        payload,
        {
            "comparisons": reconciliations,
            "all_checks_passed": all(r["passed"] for r in reconciliations),
        },
        interval_rows,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "export",
        "profiles",
        "kernel-root",
        "source-manifest",
        "selection",
        "output-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if sha(args.export) != EXPORT_SHA:
        raise StudyError("private_export_hash_mismatch")
    raw = json.loads(args.export.read_text(encoding="utf-8"))
    normalized = normalize_export(raw)
    profiles = load_profiles(args.profiles)
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    expected = (1375, 12369, 12367, 2540, 2530, 2536, INPUT_SHA)
    if (
        tuple(
            selection[k]
            for k in (
                "decision_id",
                "preserve_candidate_id",
                "hold_identity_candidate_id",
                "forecast_id",
                "reserve_id",
                "operation_id",
                "original_input_hash",
            )
        )
        != expected
    ):
        raise StudyError("frozen_selection_mismatch")
    if (
        utc(selection["comparison_start_utc"]),
        utc(selection["original_expiry_utc"]),
        utc(selection["comparison_end_utc"]),
        selection["frozen_policy_floor_kwh"],
    ) != (START, EXPIRY, END, 26.32):
        raise StudyError("frozen_selection_timing_or_floor_mismatch")
    core, source = load_core(args.kernel_root, args.source_manifest)
    manifest = {
        "adapter_version": VERSION,
        "source": source,
        "export_sha256": sha(args.export),
        "profiles_file_sha256": sha(args.profiles),
        "adapter_source_sha256": sha(Path(__file__)),
        "reconciler_source_sha256": sha(
            Path(__file__).with_name("independent_reconciler.py")
        ),
        "profile_set": profiles,
        "profile_hashes": {
            p["profile_id"]: content_hash({"profile": p, "common": profiles["common"]})
            for p in profiles["profiles"]
        },
        "selection": selection,
        "selection_sha256": sha(args.selection),
        "data_origin": "real_retained_export",
        "study_class": "conditional_proxy_research",
        "installed_system_admission": "not_passed",
        "model_profile_origin": "explicitly_authorised_research_assumption",
        "sampling": (
            "288 left-endpoint point samples held constant five minutes; "
            "bracket and final endpoint excluded"
        ),
        "PV": (
            "fixed reported delivered-PV AC-equivalent proxy ceiling; "
            "additional model spillage is hypothetical"
        ),
        "load": "total household including EV once",
        "price_policy": QUOTE_POLICY,
        "price_health_exception": normalized["price_health_exceptions"],
        "intervention_status": "unknown",
        "actions": [
            "PRESERVE_BATTERY first 25 minutes",
            "selected HOLD separate control for each profile",
        ],
        "continuation": (
            "passive PV first, no extra grid action, top-up, "
            "observed SOC reset, wear or terminal tariff"
        ),
        "C_charge_AC_exact_expression": "13.5 / 0.95 = 270/19 kW",
        "core_compatibility_tokens": {
            "explanation": (
                "Legacy parameter enum spellings select only the hypothetical "
                "independent-port arithmetic contract; no SyntheticCase or "
                "synthetic-authorship flag is constructed. Source provenance "
                "stays real_retained_export."
            ),
            "topology": core.TOPOLOGY,
            "pv_abstraction": "available_exogenous_synthetic",
            "interval_interpretation": "piecewise_constant_interval_average_kw",
            "meaning_here": (
                "AC independent ports; exogenous reported-PV ceiling; "
                "constant powers derived from held point samples, "
                "not measured averages"
            ),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    write_json(
        args.output_dir / "run-manifest.json", manifest
    )  # Frozen BEFORE dispatch/cash.
    started = datetime.now(UTC).isoformat()
    try:
        payload, reconciliation, interval_rows = evaluate_study(
            core, normalized, profiles, selection
        )
        payload["run_manifest_sha256"] = sha(args.output_dir / "run-manifest.json")
        write_json(args.output_dir / "conditional-ledgers.json", payload)
        write_json(args.output_dir / "independent-reconciliation.json", reconciliation)
        with (args.output_dir / "conditional-interval-summary.csv").open(
            "x", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(interval_rows[0]))
            writer.writeheader()
            writer.writerows(interval_rows)
        write_json(
            args.output_dir / "execution-receipt.json",
            {
                "started_utc": started,
                "finished_utc": datetime.now(UTC).isoformat(),
                "deterministic_payload_sha256": sha(
                    args.output_dir / "conditional-ledgers.json"
                ),
                "canonical_payload_sha256": content_hash(payload),
                "run_manifest_sha256": sha(args.output_dir / "run-manifest.json"),
                "all_reconciliation_checks_passed": reconciliation["all_checks_passed"],
                "new_network_or_database_connections": 0,
                "profile_count": 3,
                "paired_evaluations": 6,
            },
        )
        print(
            canonical(
                {
                    "completed_pairs": 6,
                    "reconciliation_passed": reconciliation["all_checks_passed"],
                    "result_sha256": sha(args.output_dir / "conditional-ledgers.json"),
                }
            )
        )
        return 0 if reconciliation["all_checks_passed"] else 2
    except Exception as error:
        write_json(
            args.output_dir / "failed-execution-receipt.json",
            {
                "started_utc": started,
                "failed_utc": datetime.now(UTC).isoformat(),
                "error_type": type(error).__name__,
                "error": str(error),
                "adapter_source_sha256": sha(Path(__file__)),
            },
        )
        raise


if __name__ == "__main__":
    sys.exit(main())
