"""Offline SEMS session evidence; never changes observations or training flags."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo


def prepare_sessions(evidence: dict[str, Any]) -> dict[str, Any]:
    """Deduplicate one charger's portal records, retaining unqualified source time.

    Session energy is deliberately not distributed across five-minute samples.
    A repeated interval with different energy requires review, not replacement.
    """
    sessions: dict[str, dict[str, Any]] = {}
    for row in evidence["session_records"]:
        interval = row["display_interval"]
        start_text, end_text = interval.split(" - ")
        start = datetime.strptime(start_text, "%d-%m-%Y %H:%M:%S")
        end = datetime.strptime(end_text, "%d-%m-%Y %H:%M:%S")
        if end <= start:
            raise ValueError("Session end must follow start")
        raw_energy = row.get("charged_energy_display_kwh")
        try:
            energy = Decimal(raw_energy) if raw_energy is not None else None
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError("Invalid session energy") from error
        if energy is not None and (not energy.is_finite() or energy < 0):
            raise ValueError("Invalid session energy")
        record = {
            "session_evidence_id": "sems-" + sha256(interval.encode()).hexdigest()[:24],
            "display_interval": interval,
            "start_source_local": start.isoformat(),
            "end_source_local": end.isoformat(),
            "charged_energy_display_kwh": raw_energy,
            "start_utc": None,
            "end_utc": None,
            "source_timezone": None,
            "measurement_domain": "unverified_session_energy",
            "ev_power_w": None,
            "training_eligible": False,
            "qualification": "timezone_and_interval_semantics_unverified",
        }
        previous = sessions.get(interval)
        if previous is not None and previous != record:
            raise ValueError("Conflicting duplicate session; review source evidence")
        sessions[interval] = record
    ordered = sorted(sessions.values(), key=lambda row: row["start_source_local"])
    return {
        "schema": "sems-session-evidence-v1",
        "source": "SEMS+ portal charging records, single charger",
        "observed_at_utc": evidence["observed_at_utc"],
        "coverage_complete": False,
        "production_consumption_enabled": False,
        "sessions": ordered,
    }


def qualify_session_times(
    ledger: dict[str, Any],
    *,
    timezone_name: str,
    evidence_references: list[str],
    validated_at: datetime,
) -> dict[str, Any]:
    """Apply an evidence-reviewed timezone, without qualifying power or training.

    The caller must independently validate station time and session linkage.
    The references record that review; this function cannot establish it itself.
    Ambiguous/nonexistent local timestamps require separate source evidence.
    """
    if not evidence_references or any(not ref.strip() for ref in evidence_references):
        raise ValueError("Timezone qualification requires evidence references")
    if validated_at.tzinfo is None or validated_at.utcoffset() is None:
        raise ValueError("Validation time must be timezone-aware")
    acquired = datetime.fromisoformat(ledger["observed_at_utc"].replace("Z", "+00:00"))
    if acquired.tzinfo is None or acquired.utcoffset() is None:
        raise ValueError("Acquisition time must be timezone-aware")
    if validated_at < acquired:
        raise ValueError("Validation cannot precede evidence acquisition")
    zone = ZoneInfo(timezone_name)
    result = deepcopy(ledger)
    for row in result["sessions"]:
        for source, target in (
            ("start_source_local", "start_utc"),
            ("end_source_local", "end_utc"),
        ):
            local = datetime.fromisoformat(row[source])
            if local.tzinfo is not None:
                raise ValueError("Expected unqualified local source time")
            candidates = {
                candidate.astimezone(UTC)
                for fold in (0, 1)
                if (candidate := local.replace(tzinfo=zone, fold=fold))
                .astimezone(UTC)
                .astimezone(zone)
                .replace(tzinfo=None)
                == local
            }
            if len(candidates) != 1:
                raise ValueError("Ambiguous or nonexistent source local time")
            row[target] = candidates.pop().isoformat()
        if row["end_utc"] <= row["start_utc"]:
            raise ValueError("Qualified session end must follow start")
        if datetime.fromisoformat(row["end_utc"]) > acquired:
            raise ValueError("Completed session ends after evidence acquisition")
        row["source_timezone"] = timezone_name
        row["qualification"] = "session_window_context_only"
        row["timezone_evidence_references"] = list(evidence_references)
        row["context_known_at_utc"] = validated_at.astimezone(UTC).isoformat()
        row["continuous_charging_verified"] = False
    # One charger cannot have overlapping completed session records without review.
    ordered = sorted(result["sessions"], key=lambda row: row["start_utc"])
    if any(
        a["end_utc"] > b["start_utc"]
        for a, b in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("Overlapping session records require source review")
    return result


def preview_join(
    observations: list[dict[str, Any]],
    ledger: dict[str, Any],
    *,
    confirmed_utc_offset_hours: int,
) -> list[dict[str, Any]]:
    """Return separate context at observation instants under a confirmed offset.

    This is not an interval-energy join or permission to exclude training rows.
    No match means no evidence, never 'not charging'. Raw rows stay unchanged.
    """
    from datetime import timedelta, timezone

    zone = timezone(timedelta(hours=confirmed_utc_offset_hours))
    ranges = [
        (
            datetime.fromisoformat(s["start_source_local"]).replace(tzinfo=zone),
            datetime.fromisoformat(s["end_source_local"]).replace(tzinfo=zone),
            s["session_evidence_id"],
        )
        for s in ledger["sessions"]
    ]
    result = []
    for row in observations:
        stamp = datetime.fromisoformat(row["slot_utc"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Observation timestamps must have UTC offsets")
        matches = [sid for start, end, sid in ranges if start <= stamp < end]
        result.append(
            {
                "slot_utc": stamp.astimezone(UTC).isoformat(),
                "session_evidence_ids": matches,
                "context": "within_recorded_session" if matches else "unknown",
                "confirmed_source_utc_offset_hours": confirmed_utc_offset_hours,
                "training_change_authorized": False,
            }
        )
    return result
