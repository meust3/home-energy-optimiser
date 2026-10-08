"""Persist conditional advice at capture time; dashboard reads it without computing."""

import json
from datetime import timedelta

from energy_optimizer import offline_paired_synthetic as core
from energy_optimizer.arbitrage.archive import INTEGRATION, context_from_capture
from energy_optimizer.arbitrage.capture import CaptureRepository
from energy_optimizer.arbitrage.decision_types import (
    Assumptions,
    BranchState,
    DecisionContext,
    Evidence,
    Forecast,
    Point,
    Reserve,
    digest,
    evidence_from_dict,
    primitive,
    timestamp,
)
from energy_optimizer.arbitrage.selector import select


def declared_context(inputs, source, profile):
    """Explicit conditional profile; installed parameters are never defaulted.

    Capture-version issue time is archive construction, not provider forecast
    issuance. Provider issuance and physical measurement timing remain unknown.
    Profile report-age limits are declared conditional research freshness rules.
    """
    required = {
        "assumptions",
        "evidence",
        "floor_kwh",
        "state_bridge",
        "soc_report_age_seconds",
        "forecast_report_age_seconds",
        "uncontrolled_load_kw",
        "uncontrolled_load_basis",
    }
    if (
        set(profile) != required
        or profile["state_bridge"] != "constant_soc_capacity_proxy_until_branch"
    ):
        raise ValueError("complete_explicit_research_profile_required")
    ready = inputs["confirmed_at"]
    if ready is None:
        raise ValueError("unconfirmed_capture")
    ready = timestamp(ready) if isinstance(ready, str) else ready
    start = core.ceil_five_minutes(ready)
    evidence = evidence_from_dict(profile["evidence"])
    raw_a = dict(profile["assumptions"])
    raw_a["evidence"] = evidence
    raw_a["omitted_effects"] = tuple(raw_a["omitted_effects"])
    raw_a["uncertainty"] = tuple(raw_a["uncertainty"])
    assumptions = Assumptions(**raw_a)
    raw = source["body"]["sources"]
    soc = raw["soc"]
    if soc is None or soc["attributes"].get("unit_of_measurement") != "%":
        raise ValueError("soc_domain_missing")
    reported = timestamp(soc["reported_at"])
    if not 0 <= (ready - reported).total_seconds() <= profile["soc_report_age_seconds"]:
        raise ValueError("soc_report_stale_or_future")
    energy = float(soc["state"]) / 100 * assumptions.capacity_kwh

    def forecast(name, target, unit, interpretation, data, reports):
        issued = (
            timestamp(source["body"]["received_at"])
            if name != "demand"
            else timestamp(inputs["body"]["ready_at"])
        )
        available = (
            source["confirmed_at"] if name != "demand" else inputs["confirmed_at"]
        )
        available = timestamp(available) if isinstance(available, str) else available
        age_limit = profile["forecast_report_age_seconds"][name]
        if age_limit <= 0:
            raise ValueError("explicit_positive_report_age_required")
        issues = tuple(
            "missing_stale_or_future_report"
            for r in reports
            if r is None or not 0 <= (ready - timestamp(r)).total_seconds() <= age_limit
        )
        e = Evidence(
            "captured_" + name,
            "immutable-capture-envelope-v1",
            digest(data),
            issued,
            available,
            "documented_upper_bound",
            "post-commit witness of this exact archive version; provider issue unknown",
            min((timestamp(r) for r in reports if r is not None), default=issued)
            + timedelta(seconds=age_limit),
            "declared report-age scenario; not verified physical measurement freshness",
            not issues,
            issues,
        )
        return Forecast(
            target,
            unit,
            interpretation,
            "captured exact inputs; explicit conditional profile",
            e,
            (),
        )

    demand = forecast(
        "demand",
        "baseline_household_load",
        "kW",
        "interval_average_power",
        inputs["body"]["demand_points"],
        [inputs["body"]["created_at"]],
    )
    prices = []
    for alias, target in (
        ("import_forecast", "import_price"),
        ("export_forecast", "export_price"),
    ):
        data = raw[alias]
        prices.append(
            forecast(
                target,
                target,
                "AUD/kWh",
                "interval_price",
                data,
                [data["reported_at"] if data else None],
            )
        )
    pv_data = [raw.get("pv_today"), raw.get("pv_tomorrow")]
    pv = forecast(
        "pv",
        "available_pv_scenario",
        "kW",
        "fixed_exogenous_ac_ceiling",
        pv_data,
        [v["reported_at"] if v else None for v in pv_data],
    )
    load = profile["uncontrolled_load_kw"]
    if load is None or not profile["uncontrolled_load_basis"]:
        raise ValueError("explicit_total_load_scenario_required")
    uncontrolled = Forecast(
        "named_uncontrolled_load_scenario",
        "kW",
        "interval_average_power",
        profile["uncontrolled_load_basis"],
        evidence,
        (Point(start, start + timedelta(hours=24), load),),
    )
    return DecisionContext(
        inputs["id"],
        "archived_decision_inputs",
        ready,
        ready,
        ready,
        ready,
        "exact linked capture versions committed before this cutoff; conditional profile",  # noqa: E501
        BranchState(
            start,
            energy,
            "dated_analytical_hypothesis",
            profile["state_bridge"],
            evidence,
        ),
        Reserve(
            start,
            profile["floor_kwh"],
            "explicit conditional floor, distinct from installed/backup settings",
            evidence,
        ),
        assumptions,
        start,
        start + timedelta(minutes=30),
        demand,
        pv,
        prices[0],
        prices[1],
        uncontrolled,
    )


def save_opportunity(repository, *, profile_json=""):
    capture = CaptureRepository(repository)
    inputs = capture.latest("decision_inputs")
    if inputs is None:
        return None
    source = capture.latest("source", before=inputs["captured_at"])
    result = {
        "version": "arbitrage-opportunity-v1",
        "status": "blocked",
        "selected": "HOLD",
        "no_command_issued": True,
        "execution": "disabled",
        "research_only": True,
        "input_capture_id": inputs["id"],
        "created_at": inputs["confirmed_at"],
        "observed_accounting": None,
        "simulated_comparative_value": None,
        "expected_candidate_value": None,
        "reasons": [],
        "profile_id": None,
    }
    try:
        if inputs["confirmed_at"] is None:
            raise ValueError("unconfirmed_capture")
        if not profile_json:
            raise ValueError("explicit_physical_and_total_load_profile_missing")
        if source is None:
            raise ValueError("source_capture_missing")
        c = declared_context(inputs, source, json.loads(profile_json))
        c = context_from_capture(inputs, source, primitive(c))
        receipt = select(core, c, digest(INTEGRATION))
        estimates = json.loads(receipt.estimates_json)
        # The immutable receipt retains complete ledgers. The public projection
        # must not duplicate those same bytes inside the bounded capture body.
        summary = (
            {
                k: v
                for k, v in estimates.items()
                if k not in {"original_ledgers", "common_partition_ledgers"}
            }
            if estimates
            else None
        )
        result.update(
            status="research_only" if estimates else "blocked",
            selected=receipt.selected,
            reasons=list(receipt.reasons),
            profile_id=c.assumptions.profile_id,
            context=primitive(c),
            receipt=primitive(receipt),
            receipt_sha256=receipt.sha256,
            expires_at=c.action_start,
            expected_candidate_value=summary,
            action_clipping_reasons={
                path: sorted(
                    {
                        reason
                        for step in ledger["steps"]
                        if c.action_start <= timestamp(step["start_utc"]) < c.action_end
                        for reason in step["limiting_reasons"]
                    }
                )
                for path, ledger in (estimates or {})
                .get("original_ledgers", {})
                .items()
                if path != "R_control"
            },
            reserve_summary={
                "floor_stored_kwh": c.reserve.floor_kwh,
                "branch_stored_kwh": c.branch.energy_kwh,
                "capacity_stored_kwh": c.assumptions.capacity_kwh,
                "scope": (
                    "explicit conditional profile; installed applicability unverified"
                ),
            },
        )
    except (ValueError, TypeError, KeyError) as exc:
        # Never echo arbitrary profile/input contents in public error messages.
        result["reasons"] = [
            (
                str(exc)
                if type(exc) is ValueError
                and str(exc)
                in {
                    "unconfirmed_capture",
                    "explicit_physical_and_total_load_profile_missing",
                    "source_capture_missing",
                    "complete_explicit_research_profile_required",
                    "soc_domain_missing",
                    "soc_report_stale_or_future",
                    "explicit_positive_report_age_required",
                    "explicit_total_load_scenario_required",
                    "price_unit_or_source_missing",
                    "capture_unavailable_or_corrupt",
                    "source_link_mismatch",
                    "total_load_scenario_required",
                    "missing_or_unpinned_source_contract",
                    "unsupported_demand_unit",
                    "conflicting_pv_overlap",
                }
                else "invalid_declared_research_profile"
            )
        ]
    if source:
        result["source_ages_seconds"] = {
            k: (
                (inputs["captured_at"] - timestamp(v["reported_at"])).total_seconds()
                if v
                else None
            )
            for k, v in source["body"]["sources"].items()
        }
        result["sources"] = source["body"]["sources"]
    result["provenance"] = {
        "forecast_id": inputs["body"]["forecast_id"],
        "reserve_id": inputs["body"]["reserve_id"],
        "model": inputs["body"]["model"],
        "capture_hash": inputs["body_sha256"],
        "commit_witness": inputs["confirmed_at"],
        "provider_issue": "unknown",
        "physical_applicability": "unverified",
    }
    result["load_basis"] = inputs["body"]["load_basis"]
    result["baseline_demand_points"] = inputs["body"]["demand_points"]
    return capture.save(
        origin=inputs["id"],
        kind="opportunity",
        at=inputs["captured_at"],
        body=primitive(result),
    )


def board(repository, *, now):
    """Presentation only; no capture, selector, simulation or persistence on GET."""
    row = CaptureRepository(repository).latest("opportunity")
    if row is None:
        return {
            "status": "awaiting_capture",
            "execution": "disabled",
            "no_command_issued": True,
            "reasons": ["no_arbitrage_capture_deployed"],
            "items": [],
        }
    body = row["body"]
    # Do not expose large immutable simulation ledgers or declared private evidence.
    public = {k: v for k, v in body.items() if k not in {"context", "receipt"}}
    estimates = public.get("expected_candidate_value")
    if estimates:
        public["expected_candidate_value"] = {
            k: v
            for k, v in estimates.items()
            if k not in {"original_ledgers", "common_partition_ledgers"}
        }
    if row["confirmed_at"] is None:
        public["status"] = "unconfirmed"
    elif body.get("expires_at") and timestamp(body["expires_at"]) <= now:
        public["status"] = "expired"
    return {
        "status": public["status"],
        "execution": "disabled",
        "no_command_issued": True,
        "items": [public],
    }
