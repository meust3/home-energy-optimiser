"""Later evaluation only. No outcome object is accepted by select()."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime

from energy_optimizer.arbitrage.core_bridge import estimate
from energy_optimizer.arbitrage.decision_types import (
    DecisionContext,
    Point,
    SelectionReceipt,
    _exact,
    digest,
    primitive,
    timestamp,
)


@dataclass(frozen=True)
class QuoteHealth:
    start: datetime
    end: datetime
    healthy: bool
    reason: str


@dataclass(frozen=True)
class OutcomeContext:
    outcome_id: str
    receipt_sha256: str
    data_origin: str
    source_sha256: str
    measurement_basis: str
    start: datetime
    end: datetime
    total_household_kw: tuple[Point, ...]
    pv_proxy_kw: tuple[Point, ...]
    import_quotes: tuple[Point, ...]
    export_quotes: tuple[Point, ...]
    quote_health: tuple[QuoteHealth, ...]
    verified_settlement_quotes: bool
    model_applicability_verified: bool


def outcome_from_dict(raw):
    v = _exact(OutcomeContext, raw)
    for k in ("start", "end"):
        v[k] = timestamp(v[k])
    for name in ("total_household_kw", "pv_proxy_kw", "import_quotes", "export_quotes"):
        rows = []
        for raw_point in v[name]:
            p = _exact(Point, raw_point)
            rows.append(Point(timestamp(p["start"]), timestamp(p["end"]), p["value"]))
        v[name] = tuple(rows)
    rows = []
    for raw_health in v["quote_health"]:
        h = _exact(QuoteHealth, raw_health)
        rows.append(
            QuoteHealth(
                timestamp(h["start"]), timestamp(h["end"]), h["healthy"], h["reason"]
            )
        )
    v["quote_health"] = tuple(rows)
    return OutcomeContext(**v)


def _shape(points, start, end, nonnegative):
    cursor = start
    if not points or len(points) > 4096:
        return False
    for p in points:
        if any(
            not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
            for t in (p.start, p.end, start, end)
        ):
            return False
        if p.start != cursor or p.end <= p.start or p.end > end:
            return False
        if (
            not isinstance(p.value, (int, float))
            or isinstance(p.value, bool)
            or not math.isfinite(p.value)
            or (nonnegative and p.value < 0)
        ):
            return False
        cursor = p.end
    return cursor == end


def quote_components(estimates, health):
    """Whole-horizon attribution, including all later flows, never just action cost."""
    paths = estimates["common_partition_ledgers"]
    output = {}
    unhealthy = [h for h in health if not h.healthy]
    for key, a, b in (
        ("preservation", "R", "P"),
        ("charging_increment", "P", "G"),
        ("combined", "R", "G"),
    ):
        bad, good, downstream = 0.0, 0.0, 0.0
        for x, y in zip(paths[a]["steps"], paths[b]["steps"], strict=True):
            duration = (x["end_utc"] - x["start_utc"]).total_seconds()
            delta = (x["import_kwh"] - y["import_kwh"]) * x["import_price"] - (
                x["export_kwh"] - y["export_kwh"]
            ) * x["export_price"]
            for h in health:
                left, right = max(h.start, x["start_utc"]), min(h.end, x["end_utc"])
                if right <= left:
                    continue
                part = delta * (right - left).total_seconds() / duration
                if h.healthy:
                    good += part
                    if unhealthy and left >= min(v.end for v in unhealthy):
                        downstream += part
                else:
                    bad += part
        total = estimates["comparisons"][key]["diagnostic_incremental_cash_aud"]
        if abs(bad + good - total) > 1e-9:
            raise ValueError("quote_attribution_reconciliation_failed")
        output[key] = {
            "unhealthy_quote_contribution_aud": bad,
            "other_quote_contribution_aud": good,
            "later_healthy_interval_contribution_aud": downstream,
            "full_horizon_diagnostic_aud": total,
            "unhealthy_quote_exposure": bool(unhealthy),
            "interpretation": "cash by quote-health interval; later flows retained; not causal removal of a bad price",
        }
    return output


def evaluate_outcome(
    core, decision: DecisionContext, receipt: SelectionReceipt, outcome: OutcomeContext
):
    """Freeze first; later inputs can only produce a separate retained evaluation."""
    base = {
        "outcome_sha256": digest(outcome),
        "raw_outcome": primitive(outcome),
        "selection_receipt_sha256": receipt.sha256,
        "selected": receipt.selected,
        "hold_reasons": receipt.reasons,
        "prediction": json.loads(receipt.estimates_json),
        "realised_proxy": None,
        "unavailable_reasons": [],
        "eligibility_counts": {"numerical": 0, "quote_qualified": 0, "strict": 0},
        "false_positive": None,
        "charging_increment_false_positive": None,
        "missed_opportunity": None,
        "hindsight_diagnostic": None,
        "selected_vs_R_aud": None,
        "selected_G_vs_P_aud": None,
    }
    reasons = base["unavailable_reasons"]
    if (
        digest(decision) != receipt.input_sha256
        or outcome.receipt_sha256 != receipt.sha256
    ):
        reasons.append("receipt_or_input_identity_mismatch")
    if receipt.horizon_end is None or (outcome.start, outcome.end) != (
        decision.action_start,
        receipt.horizon_end,
    ):
        reasons.append("outcome_must_use_frozen_horizon")
    if (
        outcome.data_origin not in ("authored_synthetic", "realised_input_proxy")
        or not outcome.measurement_basis
    ):
        reasons.append("missing_outcome_origin_or_measurement_basis")
    if len(outcome.source_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in outcome.source_sha256
    ):
        reasons.append("invalid_outcome_source_hash")
    for name in ("total_household_kw", "pv_proxy_kw", "import_quotes", "export_quotes"):
        if not _shape(
            getattr(outcome, name),
            outcome.start,
            outcome.end,
            name in ("total_household_kw", "pv_proxy_kw"),
        ):
            reasons.append(name + ":missing_invalid_or_incomplete")
    cursor = outcome.start
    for h in outcome.quote_health:
        if (
            h.start != cursor
            or h.end <= h.start
            or h.end > outcome.end
            or type(h.healthy) is not bool
            or not h.reason
        ):
            reasons.append("invalid_quote_health_coverage")
            break
        cursor = h.end
    if cursor != outcome.end:
        reasons.append("incomplete_quote_health")
    if base["prediction"] is None:
        reasons.append("decision_inputs_not_admitted_no_evaluable_frozen_experiment")
    if reasons:
        return base
    # Replace scenario only; branch, reserve, limits, original action and horizon remain frozen.
    c = replace(
        decision,
        data_origin=outcome.data_origin,
        uncontrolled_load=None,
        demand=replace(
            decision.demand,
            target="total_household_including_uncontrolled_ev",
            points=outcome.total_household_kw,
        ),
        pv=replace(decision.pv, points=outcome.pv_proxy_kw),
        import_price=replace(decision.import_price, points=outcome.import_quotes),
        export_price=replace(decision.export_price, points=outcome.export_quotes),
    )
    try:
        result = estimate(core, c, receipt.horizon_end)
    except core.AdmissionError as exc:
        reasons.extend(exc.reasons)
        return base
    base["realised_proxy"] = result
    base["quote_dependence"] = quote_components(result, outcome.quote_health)
    comps = result["comparisons"]
    for name, v in comps.items():
        reasons.extend(
            name + ":" + reason for reason in v["primary_unavailable_reasons"]
        )
    quote_ok = all(h.healthy for h in outcome.quote_health)
    component_counts = {}
    for name, v in comps.items():
        numeric = v["primary_comparative_gross_value_aud"] is not None
        component_counts[name] = {
            "numerical": int(numeric),
            "quote_qualified": int(numeric and quote_ok),
            "strict": int(
                numeric
                and quote_ok
                and outcome.verified_settlement_quotes is True
                and outcome.model_applicability_verified is True
            ),
        }
    base["component_eligibility"] = component_counts
    base["prediction_errors_aud"] = {
        name: {
            "diagnostic_realised_minus_predicted": value[
                "diagnostic_incremental_cash_aud"
            ]
            - base["prediction"]["comparisons"][name][
                "diagnostic_incremental_cash_aud"
            ],
            "both_primary_available": value["primary_comparative_gross_value_aud"]
            is not None
            and base["prediction"]["comparisons"][name][
                "primary_comparative_gross_value_aud"
            ]
            is not None,
        }
        for name, value in comps.items()
    }
    key = {"P": "preservation", "G": "combined"}.get(receipt.selected)
    # HOLD is not credited as success, especially when forced by absent evidence.
    if key:
        base["selected_vs_R_aud"] = comps[key]["primary_comparative_gross_value_aud"]
        base["eligibility_counts"] = component_counts[key]
        if base["selected_vs_R_aud"] is not None and quote_ok:
            base["false_positive"] = base["selected_vs_R_aud"] <= 1e-8
    if receipt.selected == "G":
        base["selected_G_vs_P_aud"] = comps["charging_increment"][
            "primary_comparative_gross_value_aud"
        ]
        if base["selected_G_vs_P_aud"] is not None and quote_ok:
            base["charging_increment_false_positive"] = (
                base["selected_G_vs_P_aud"] <= 1e-8
            )
    if receipt.selected == "HOLD":
        reference = comps["preservation"]["reference"]
        if (
            reference["trajectory_feasible"]
            and reference["terminal_margin_kwh"] >= -1e-9
        ):
            base["selected_vs_R_aud"] = 0.0
    # Diagnostic hindsight is a separate output, not input to the frozen selector.
    p = comps["preservation"]["primary_comparative_gross_value_aud"]
    g = comps["combined"]["primary_comparative_gross_value_aud"]
    inc = comps["charging_increment"]["primary_comparative_gross_value_aud"]
    alternatives = [("HOLD", result["costs_aud"]["R"])]
    if p is not None and p > 1e-8:
        alternatives.append(("P", result["costs_aud"]["P"]))
    if g is not None and inc is not None and g > 1e-8 and inc > 1e-8:
        alternatives.append(("G", result["costs_aud"]["G"]))
    best = alternatives[0]
    for alt in alternatives[1:]:
        if alt[1] < best[1] - 1e-8:
            best = alt
    base["hindsight_diagnostic"] = {
        "best_eligible_action": best[0],
        "not_selector_input": True,
    }
    # No false success/missed-opportunity classification when counterfactual comparisons unavailable.
    if all(component_counts[k]["quote_qualified"] for k in component_counts):
        chosen_cost = result["costs_aud"][
            "R" if receipt.selected == "HOLD" else receipt.selected
        ]
        base["missed_opportunity"] = chosen_cost - best[1] > 1e-8
    return base


def summarize(evaluations):
    """Counts only; never sum overlapping cash estimates or annualise."""
    counts = {
        "selections": {},
        "hold_reasons": {},
        "eligibility": {"numerical": 0, "quote_qualified": 0, "strict": 0},
        "false_positive": 0,
        "false_positive_evaluable": 0,
        "charging_increment_false_positive": 0,
        "charging_increment_evaluable": 0,
        "missed_opportunity": 0,
        "missed_opportunity_evaluable": 0,
        "unavailable_outcomes": 0,
        "unmatched_components": 0,
        "unmet_reserve_components": 0,
        "infeasible_components": 0,
        "clipped_G_paths": 0,
        "zero_delivery_G_paths": 0,
        "unhealthy_quote_episodes": 0,
    }
    for row in evaluations:
        action = row["selected"]
        counts["selections"][action] = counts["selections"].get(action, 0) + 1
        if action == "HOLD":
            for reason in row["hold_reasons"]:
                counts["hold_reasons"][reason] = (
                    counts["hold_reasons"].get(reason, 0) + 1
                )
        for k in counts["eligibility"]:
            counts["eligibility"][k] += row["eligibility_counts"][k]
        counts["false_positive"] += row["false_positive"] is True
        counts["false_positive_evaluable"] += row["false_positive"] is not None
        counts["charging_increment_false_positive"] += (
            row["charging_increment_false_positive"] is True
        )
        counts["charging_increment_evaluable"] += (
            row["charging_increment_false_positive"] is not None
        )
        counts["missed_opportunity"] += row["missed_opportunity"] is True
        counts["missed_opportunity_evaluable"] += row["missed_opportunity"] is not None
        counts["unavailable_outcomes"] += row["realised_proxy"] is None
        if row["realised_proxy"] is not None:
            result = row["realised_proxy"]
            g = result["paths"]["G"]
            counts["clipped_G_paths"] += (
                g["delivered_action_ac_kwh"] < g["requested_action_ac_kwh"] - 1e-9
            )
            counts["zero_delivery_G_paths"] += g["delivered_action_ac_kwh"] <= 1e-9
            counts["unhealthy_quote_episodes"] += any(
                v["unhealthy_quote_exposure"] for v in row["quote_dependence"].values()
            )
            for v in result["comparisons"].values():
                counts["unmatched_components"] += (
                    "terminal_energy_unmatched" in v["primary_unavailable_reasons"]
                )
                counts["unmet_reserve_components"] += any(
                    "terminal_reserve_not_met" in r
                    for r in v["primary_unavailable_reasons"]
                )
                counts["infeasible_components"] += not (
                    v["reference"]["trajectory_feasible"]
                    and v["action"]["trajectory_feasible"]
                )
    return counts
