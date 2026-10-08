"""Explicit archived-input admission, distinct from synthetic fixtures and outcomes."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from energy_optimizer.arbitrage.decision_types import (
    Point,
    SelectionReceipt,
    canonical,
    decision_from_dict,
    digest,
    timestamp,
)
from energy_optimizer.arbitrage.outcomes import evaluate_outcome, outcome_from_dict
from energy_optimizer.arbitrage.research_io import (
    append_receipt,
    integration_source_sha,
    load_core,
)
from energy_optimizer.arbitrage.selector import POLICY_SHA, select

INTEGRATION = "arbitrage-integration-v1"


def context_from_capture(inputs, source, declared_context):
    """Require a complete declared timing/physics/load context; copy data, no defaults.

    This does not certify the declarations. Original bytes plus the declared
    evidence must be reviewed at real-record admission. Target times never
    substitute for availability, nor do these receipts prove installed physics.
    """
    c = decision_from_dict(declared_context)
    if c.data_origin != "archived_decision_inputs":
        raise ValueError("archive_origin_required")
    for record in (inputs, source):
        if record["confirmed_at"] is None:
            raise ValueError("unconfirmed_capture")
        witness = record["confirmed_at"]
        witness = timestamp(witness) if isinstance(witness, str) else witness
        if witness > c.cutoff or digest(record["body"]) != record["body_sha256"]:
            raise ValueError("capture_unavailable_or_corrupt")
    body, raw = inputs["body"], source["body"]["sources"]
    if body["source_capture_id"] != source["id"]:
        raise ValueError("source_link_mismatch")

    def attach(series, data, points):
        if series is None or series.evidence.source_sha256 != digest(data):
            raise ValueError("missing_or_unpinned_source_contract")
        return replace(series, points=tuple(points))

    demand = []
    for p in body["demand_points"]:
        if p["unit"] != "W":
            raise ValueError("unsupported_demand_unit")
        demand.append(
            Point(timestamp(p["start"]), timestamp(p["end"]), p["value"] / 1000)
        )
    # Operational demand is baseline: a named complete uncontrolled-load series is
    # required even if its explicitly supplied conditional scenario is zero.
    if c.uncontrolled_load is None or c.demand.target != "baseline_household_load":
        raise ValueError("total_load_scenario_required")
    result = replace(c, demand=attach(c.demand, body["demand_points"], demand))
    for alias, field in (
        ("import_forecast", "import_price"),
        ("export_forecast", "export_price"),
    ):
        data = raw[alias]
        if data is None or data["attributes"].get("unit_of_measurement") not in {
            "$/kWh",
            "AUD/kWh",
        }:
            raise ValueError("price_unit_or_source_missing")
        points = [
            Point(
                timestamp(p["start_time"]), timestamp(p["end_time"]), p.get("per_kwh")
            )
            for p in data.get("forecasts", [])
        ]
        result = replace(result, **{field: attach(getattr(c, field), data, points)})
    pv_data = [raw.get("pv_today"), raw.get("pv_tomorrow")]
    # Half-hour average kW is the existing BJReplay detailedForecast contract.
    pv = {}
    for data in pv_data:
        if data:
            for p in data.get("detailedForecast", []):
                start = timestamp(p["period_start"])
                point = Point(
                    start, start + timedelta(minutes=30), p.get("pv_estimate")
                )
                if start in pv and pv[start] != point:
                    raise ValueError("conflicting_pv_overlap")
                pv[start] = point
    return replace(result, pv=attach(c.pv, pv_data, [pv[t] for t in sorted(pv)]))


def freeze_context(context, output):
    receipt = select(load_core(), context, integration_source_sha())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "decision.json").write_text(canonical(context) + "\n", encoding="utf-8")
    append_receipt(output / "receipts", receipt)
    return receipt


def evaluate_files(decision_path, receipt_path, outcome_path):
    c = decision_from_dict(json.loads(Path(decision_path).read_text()))
    raw = json.loads(Path(receipt_path).read_text())
    raw["cutoff"] = timestamp(raw["cutoff"])
    raw["horizon_end"] = timestamp(raw["horizon_end"]) if raw["horizon_end"] else None
    raw["reasons"] = tuple(raw["reasons"])
    receipt = SelectionReceipt(**raw)
    if receipt.input_sha256 != digest(c) or receipt.policy_sha256 != POLICY_SHA:
        raise ValueError("frozen_receipt_input_mismatch")
    if receipt.source_sha256 != integration_source_sha():
        raise ValueError("frozen_source_identity_mismatch")
    # Recompute only from immutable decision inputs, before opening later data.
    if select(load_core(), c, receipt.source_sha256) != receipt:
        raise ValueError("frozen_selection_mismatch")
    outcome = outcome_from_dict(json.loads(Path(outcome_path).read_text()))
    return evaluate_outcome(load_core(), c, receipt, outcome)
