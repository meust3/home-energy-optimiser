"""Deterministic, reviewable SEMS context plans; no network or scheduled work."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

GUARD_COLUMNS = (
    "slot_utc",
    "observed_at_utc",
    "house_consumption_w",
    "ev_charging_active",
    "ev_power_w",
    "ev_session_id",
    "ev_source",
    "ev_detection_confidence",
    "baseline_house_consumption_w",
    "baseline_training_eligible",
    "baseline_exclusion_reason",
    "telemetry_is_healthy",
)
CHANGED_COLUMNS = ("baseline_training_eligible", "baseline_exclusion_reason")
REASON = "sems_recorded_session_window_ac_power_unknown"


def stamp(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps required")
    return parsed.astimezone(UTC)


def digest(value: Any) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def guard(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: row[key] for key in GUARD_COLUMNS}
    for key in ("slot_utc", "observed_at_utc"):
        result[key] = stamp(result[key]).isoformat()
    return result


def prepare_backfill(
    snapshot: dict[str, Any], ledger: dict[str, Any]
) -> dict[str, Any]:
    """Use observation instants, not rounded slots, for conservative exclusions.

    Session windows are half open [start,end). Partial-slot overlaps remain
    contextual evidence only when the actual observation is outside the window.
    Existing exclusions, measured power and annotation history take precedence.
    """
    captured = stamp(snapshot["snapshot_at_utc"])
    sessions = ledger["sessions"]
    windows = []
    for session in sessions:
        if session["qualification"] != "session_window_context_only":
            raise ValueError("Qualified session windows required")
        known = stamp(session["context_known_at_utc"])
        start, end = stamp(session["start_utc"]), stamp(session["end_utc"])
        if not start < end <= stamp(ledger["observed_at_utc"]) or known > captured:
            raise ValueError("Invalid session or evidence newer than snapshot")
        windows.append((start, end, session["session_evidence_id"]))
    windows.sort()
    if any(a[1] > b[0] for a, b in zip(windows, windows[1:], strict=False)):
        raise ValueError("Overlapping single-charger windows")
    annotated = {stamp(s) for s in snapshot["previously_annotated_slots"]}
    entries = []
    seen = set()
    for source in snapshot["observations"]:
        row = guard(source)
        slot, observed = stamp(row["slot_utc"]), stamp(row["observed_at_utc"])
        if slot in seen:
            raise ValueError("Duplicate observation slot")
        seen.add(slot)
        overlaps = [
            sid
            for start, end, sid in windows
            if slot < end and slot + timedelta(minutes=5) > start
        ]
        if not overlaps:
            continue
        matches = [sid for start, end, sid in windows if start <= observed < end]
        if not slot <= observed < slot + timedelta(minutes=5):
            disposition = "invalid_observation_time"
        elif not matches:
            disposition = "boundary_context_only"
        elif slot in annotated or row["ev_session_id"]:
            disposition = "preserve_existing_annotation"
        elif row["ev_power_w"] is not None:
            disposition = "preserve_direct_power"
        elif row["baseline_training_eligible"] is not True:
            disposition = "preserve_existing_exclusion"
        elif (
            row["telemetry_is_healthy"] is not True
            or row["baseline_house_consumption_w"] is None
        ):
            disposition = "not_effective_training_row"
        else:
            disposition = "exclude_session_window"
        after = {key: row[key] for key in CHANGED_COLUMNS}
        if disposition == "exclude_session_window":
            after = dict(
                baseline_training_eligible=False, baseline_exclusion_reason=REASON
            )
        entries.append(
            {
                "before": row,
                "after": after,
                "session_ids": matches,
                "overlapping_session_ids": overlaps,
                "disposition": disposition,
            }
        )
    payload = {
        "schema": "sems-context-backfill-v1",
        "boundary_policy": "observation_in_half_open_session_v1",
        "snapshot_at_utc": captured.isoformat(),
        "snapshot_sha256": digest(snapshot),
        "evidence_sha256": digest(ledger),
        "session_evidence": sessions,
        "entries": sorted(entries, key=lambda e: e["before"]["slot_utc"]),
    }
    return {**payload, "plan_id": digest(payload)}


def verify_plan(plan: dict[str, Any]) -> None:
    if plan["schema"] != "sems-context-backfill-v1":
        raise ValueError("Unsupported backfill plan")
    if digest({k: v for k, v in plan.items() if k != "plan_id"}) != plan["plan_id"]:
        raise ValueError("Backfill plan digest mismatch")
    for entry in plan["entries"]:
        expected = {key: entry["before"][key] for key in CHANGED_COLUMNS}
        if entry["disposition"] == "exclude_session_window":
            expected = dict(
                baseline_training_eligible=False, baseline_exclusion_reason=REASON
            )
        if entry["after"] != expected:
            raise ValueError("Plan attempts unsupported changes")
