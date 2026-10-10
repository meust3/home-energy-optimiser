"""Opt-in decision-input derivations; never transform outcomes or raw captures."""

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta

from energy_optimizer import entity_ids
from energy_optimizer.arbitrage.decision_types import (
    Assumptions,
    DecisionContext,
    Evidence,
    canonical,
    digest,
    timestamp,
)

PROFILE_VERSION = "conditional-research-profile-v2"
PRICE_RAW = "strict_raw_v1"
PRICE_BOUNDARY = "conditional_amber_boundary_start_plus_one_v1"
PRICE_SOURCE = "recorded_amber_forecasts_v1"
FIXED_RESERVE = "fixed_research_floor_v1"
LINKED_RESERVE = "linked_capacity_capped_reserve_v1"
RESERVE_FIELD = "capacity_capped_reserve_kwh"
LEGACY_FIELDS = {
    "assumptions",
    "evidence",
    "floor_kwh",
    "state_bridge",
    "soc_report_age_seconds",
    "forecast_report_age_seconds",
    "uncontrolled_load_kw",
    "uncontrolled_load_basis",
}
V2_FIELDS = (LEGACY_FIELDS - {"floor_kwh"}) | {
    "schema_version",
    "price_interpretation",
    "reserve_binding",
}


class AdvisoryInputError(ValueError):
    """Only fixed public reason codes, never user payloads or credentials."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AdvisoryInputError(reason)


def finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def profile_modes(profile: dict) -> tuple[dict | None, dict | None]:
    """Legacy eight-key profiles retain exact original construction semantics."""
    require(isinstance(profile, dict), "research_profile_object_required")
    if set(profile) == LEGACY_FIELDS:
        return None, None
    require(
        set(profile) == V2_FIELDS and profile["schema_version"] == PROFILE_VERSION,
        "research_profile_version_or_fields_invalid",
    )
    ages = profile["forecast_report_age_seconds"]
    require(
        isinstance(ages, dict)
        and set(ages) == {"demand", "pv", "import_price", "export_price"}
        and all(finite(v) and v > 0 for v in ages.values())
        and finite(profile["soc_report_age_seconds"])
        and profile["soc_report_age_seconds"] > 0,
        "research_profile_report_ages_invalid",
    )
    price, reserve = profile["price_interpretation"], profile["reserve_binding"]
    require(
        isinstance(price, dict) and isinstance(reserve, dict),
        "input_modes_object_required",
    )
    if price.get("mode") == PRICE_RAW:
        require(set(price) == {"mode"}, "price_mode_fields_invalid")
    else:
        require(
            set(price) == {"mode", "source"}
            and price.get("mode") == PRICE_BOUNDARY
            and price.get("source") == PRICE_SOURCE,
            "price_interpretation_mode_unsupported",
        )
    if reserve.get("mode") == FIXED_RESERVE:
        require(
            set(reserve) == {"mode", "floor_kwh"} and finite(reserve["floor_kwh"]),
            "fixed_reserve_binding_invalid",
        )
    else:
        require(
            set(reserve) == {"mode", "quantity", "unit"}
            and reserve.get("mode") == LINKED_RESERVE
            and reserve.get("quantity") == RESERVE_FIELD
            and reserve.get("unit") == "stored_kWh",
            "reserve_binding_mode_unsupported",
        )
    return price, reserve


def linked_reserve(
    inputs: dict, assumptions: Assumptions, cutoff: datetime, branch_at: datetime
) -> tuple[float, str, Evidence]:
    """Bind once to embedded, witnessed snapshot; no repository/latest lookup."""
    body = inputs["body"]
    require(digest(body) == inputs["body_sha256"], "linked_reserve_input_hash_invalid")
    require(
        body.get("version") == "arbitrage-capture-v1"
        and body.get("kind") == "decision_inputs"
        and body.get("no_command_issued") is True,
        "linked_reserve_input_kind_invalid",
    )
    r = body.get("reserve")
    require(isinstance(r, dict), "linked_reserve_missing")
    required = {
        "id",
        "forecast_run_id",
        "model_version",
        RESERVE_FIELD,
        "recommended_reserve_kwh",
        "usable_battery_capacity_kwh",
        "evaluation_timestamp_utc",
        "observation_timestamp_utc",
        "observation_is_stale",
        "observation_age_seconds",
        "command_issued",
        "forecast_start_utc",
        "forecast_end_utc",
        "estimate_json",
        "health_json",
    }
    require(required <= set(r), "linked_reserve_structure_invalid")
    require(
        all(
            isinstance(body.get(k), int)
            and not isinstance(body[k], bool)
            and body[k] > 0
            for k in ("reserve_id", "forecast_id", "operation_id")
        )
        and all(
            isinstance(r[k], int) and not isinstance(r[k], bool)
            for k in ("id", "forecast_run_id")
        )
        and r["id"] == body["reserve_id"]
        and r["forecast_run_id"] == body["forecast_id"],
        "linked_reserve_ids_mismatch",
    )
    require(
        r["model_version"] == "reserve-estimator-v1"
        and body.get("forecast_type") == "baseline_household_load"
        and body.get("model") == "household-demand-hierarchy-v1-cohort-v1",
        "linked_reserve_model_or_target_incompatible",
    )
    require(
        r.get("unit", "stored_kWh") == "stored_kWh"
        and r.get("capacity_capped_reserve_unit", "stored_kWh") == "stored_kWh"
        and finite(r["usable_battery_capacity_kwh"])
        and r["usable_battery_capacity_kwh"] == assumptions.capacity_kwh,
        "linked_reserve_capacity_or_units_incompatible",
    )
    floor = r[RESERVE_FIELD]
    estimate = r["estimate_json"]
    require(
        finite(floor)
        and assumptions.physical_min_kwh <= floor <= assumptions.capacity_kwh
        and finite(r["recommended_reserve_kwh"])
        and r["recommended_reserve_kwh"] == floor
        and isinstance(estimate, dict)
        and all(
            finite(estimate.get(k))
            for k in (
                RESERVE_FIELD,
                "recommended_reserve_kwh",
                "usable_battery_capacity_kwh",
            )
        )
        and estimate.get(RESERVE_FIELD) == floor
        and estimate.get("recommended_reserve_kwh") == floor
        # save_reserve_run binds the typed row after computing the estimate;
        # its embedded estimate may retain the documented pre-persistence null.
        and "forecast_run_id" in estimate
        and estimate["forecast_run_id"] in (None, body["forecast_id"])
        and (
            estimate["forecast_run_id"] is None
            or (
                isinstance(estimate["forecast_run_id"], int)
                and not isinstance(estimate["forecast_run_id"], bool)
            )
        )
        and estimate.get("usable_battery_capacity_kwh") == assumptions.capacity_kwh,
        "linked_reserve_quantity_invalid_or_inconsistent",
    )
    require(
        r["command_issued"] is False
        and estimate.get("command_issued") is False
        and estimate.get("horizon_is_valid") is True
        and isinstance(r["health_json"], dict)
        and isinstance(r["health_json"].get("telemetry"), dict)
        and r["health_json"].get("telemetry", {}).get("is_healthy") is True,
        "linked_reserve_health_or_horizon_invalid",
    )
    try:
        observed = timestamp(r["observation_timestamp_utc"])
        evaluated = timestamp(r["evaluation_timestamp_utc"])
        ready, created = timestamp(body["ready_at"]), timestamp(body["created_at"])
        start, end = timestamp(r["forecast_start_utc"]), timestamp(
            r["forecast_end_utc"]
        )
    except (ValueError, TypeError):
        raise AdvisoryInputError("linked_reserve_time_invalid") from None
    require(
        observed <= evaluated <= ready <= cutoff
        and created <= ready
        and inputs["captured_at"] == ready
        and inputs["confirmed_at"] == cutoff
        and evaluated == created
        and start == evaluated
        and end > start
        and end >= branch_at + timedelta(minutes=30),
        "linked_reserve_asof_or_horizon_invalid",
    )
    require(
        r["observation_is_stale"] is False
        and finite(r["observation_age_seconds"])
        and 0 <= r["observation_age_seconds"] <= 600
        and 0 <= (cutoff - observed).total_seconds() <= 600,
        "linked_reserve_stale",
    )
    info = {
        "mode": LINKED_RESERVE,
        "source_field": RESERVE_FIELD,
        "unit": "stored_kWh",
        "reserve_id": r["id"],
        "forecast_id": body["forecast_id"],
        "operation_id": body["operation_id"],
        "input_id": inputs["id"],
        "input_sha256": inputs["body_sha256"],
        "snapshot_sha256": digest(r),
        "resolved_floor_kwh": floor,
        "evaluated_at": evaluated.isoformat(),
        "input_commit_witness": cutoff.isoformat(),
        "scope": (
            "exact decision-time capacity-capped reserve; frozen for R/P/G and "
            "terminal rule; analytical stored-energy domain"
        ),
    }
    evidence = Evidence(
        "linked_reserve:" + str(r["id"]),
        LINKED_RESERVE,
        digest(r),
        evaluated,
        cutoff,
        "documented_upper_bound",
        "exact embedded snapshot in post-commit witnessed decision input",
        observed + timedelta(seconds=600),
        "reserve observation-age rule; not measured physical stored energy",
        True,
        (),
    )
    return floor, canonical(info), evidence


def validate_price_times(source: dict, mode: dict | None) -> None:
    """Name malformed raw price times before the unchanged archive hydrator."""
    if mode is None or mode["mode"] != PRICE_BOUNDARY:
        return
    raw = source["body"].get("sources")
    require(isinstance(raw, dict), "amber_recorded_source_mismatch")
    for alias in ("import_forecast", "export_forecast"):
        series = raw.get(alias)
        require(
            isinstance(series, dict) and isinstance(series.get("forecasts"), list),
            "amber_original_series_mismatch",
        )
        require(0 < len(series["forecasts"]) <= 4096, "amber_original_series_mismatch")
        for row in series["forecasts"]:
            try:
                start, end = timestamp(row["start_time"]), timestamp(row["end_time"])
            except (ValueError, TypeError, KeyError):
                raise AdvisoryInputError("amber_time_invalid") from None
            require(end > start, "amber_period_reversed_or_empty")


def interpret_prices(
    context: DecisionContext, source: dict, mode: dict | None
) -> DecisionContext:
    """Derive decision prices only. Raw captured arrays and evidence stay intact."""
    if mode is None or mode["mode"] == PRICE_RAW:
        if mode is None:
            return context
        return replace(
            context,
            **{
                field: replace(
                    getattr(context, field),
                    basis=canonical(
                        {
                            "mode": PRICE_RAW,
                            "raw_series_sha256": getattr(
                                context, field
                            ).evidence.source_sha256,
                            "basis": (
                                "original recorded periods unchanged; "
                                "strict coverage required"
                            ),
                        }
                    ),
                )
                for field in ("import_price", "export_price")
            },
        )
    envelope = source["body"]
    require(
        envelope.get("version") == "arbitrage-capture-v1"
        and envelope.get("kind") == "source"
        and digest(envelope) == source["body_sha256"],
        "amber_recorded_source_mismatch",
    )
    fields = {}
    for alias, field, entity, channel in (
        (
            "import_forecast",
            "import_price",
            entity_ids.AMBER_IMPORT_FORECAST,
            "general",
        ),
        ("export_forecast", "export_price", entity_ids.AMBER_EXPORT_FORECAST, "feedIn"),
    ):
        raw = envelope["sources"].get(alias)
        require(
            isinstance(raw, dict)
            and isinstance(raw.get("attributes"), dict)
            and raw["attributes"].get("unit_of_measurement") in ("$/kWh", "AUD/kWh")
            and raw.get("entity_id", entity) == entity
            and raw.get("channel_type", channel) == channel
            and raw["attributes"].get("entity_id", entity) == entity
            and raw["attributes"].get("channel_type", channel) == channel,
            "amber_channel_or_unit_mismatch",
        )
        rows = raw.get("forecasts")
        series = getattr(context, field)
        require(
            isinstance(rows, list)
            and 0 < len(rows) <= 4096
            and len(rows) == len(series.points)
            and series.evidence.source_sha256 == digest(raw),
            "amber_original_series_mismatch",
        )
        points, segments = [], []
        for i, (row, p) in enumerate(zip(rows, series.points, strict=True)):
            require(
                isinstance(row, dict) and finite(row.get("per_kwh")),
                "amber_price_missing_or_nonfinite",
            )
            require(p.value == row["per_kwh"], "amber_original_quote_mismatch")
            boundary = p.start.replace(
                minute=p.start.minute // 5 * 5, second=0, microsecond=0
            )
            offset = (p.start - boundary).total_seconds()
            require(offset in (0, 1), "amber_unsupported_boundary_offset")
            duration = row.get("duration")
            require(
                finite(duration)
                and duration in (5, 30)
                and (duration != 30 or boundary.minute % 30 == 0)
                and p.end == boundary + timedelta(minutes=duration),
                "amber_period_metadata_inconsistent",
            )
            require(
                not points or points[-1].end == boundary,
                "amber_missing_period_overlap_or_duplicate",
            )
            points.append(replace(p, start=boundary))
            segments.append(
                [
                    i,
                    p.start.isoformat(),
                    boundary.isoformat(),
                    p.end.isoformat(),
                    (p.end - p.start).total_seconds(),
                    duration * 60,
                ]
            )
        info = {
            "mode": PRICE_BOUNDARY,
            "source": PRICE_SOURCE,
            "channel": channel,
            "entity": entity,
            "capture_id": source["id"],
            "capture_sha256": source["body_sha256"],
            "raw_series_sha256": digest(raw),
            "unit": "AUD/kWh",
            "periods": len(points),
            "segments": segments,
            "segment_fields": [
                "index",
                "raw_start",
                "interpreted_start",
                "end",
                "raw_seconds",
                "interpreted_seconds",
            ],
            "segments_sha256": digest(segments),
            "raw_duration_seconds": sum(x[4] for x in segments),
            "interpreted_duration_seconds": sum(x[5] for x in segments),
            "interpreted_start_count": sum(x[1] != x[2] for x in segments),
            "unresolved_gaps": 0,
            "basis": (
                "conditional source representation, not observed extra seconds "
                "or certified provider/settlement semantics; "
                "receipt and witness times unchanged"
            ),
        }
        fields[field] = replace(series, points=tuple(points), basis=canonical(info))
    return replace(context, **fields)


def input_semantics(context: DecisionContext, profile: dict) -> dict | None:
    """Small public projection; full bounded segment evidence is hashed privately."""
    price, reserve = profile_modes(profile)
    if price is None:
        return None
    prices = {}
    if price["mode"] == PRICE_BOUNDARY:
        for field in ("import_price", "export_price"):
            info = json.loads(getattr(context, field).basis)
            prices[field] = {
                k: v for k, v in info.items() if k not in {"segments", "segment_fields"}
            }
    binding = {"mode": reserve["mode"], "resolved_floor_kwh": context.reserve.floor_kwh}
    if reserve["mode"] == LINKED_RESERVE:
        binding = json.loads(context.reserve.basis)
    return {
        "profile_schema": PROFILE_VERSION,
        "profile_sha256": digest(profile),
        "price_mode": price["mode"],
        "prices": prices,
        "reserve_binding": binding,
        "uncontrolled_load_kw": profile["uncontrolled_load_kw"],
        "uncontrolled_load_basis": profile["uncontrolled_load_basis"],
        "full_capacity_floor": context.reserve.floor_kwh
        == context.assumptions.capacity_kwh,
    }
