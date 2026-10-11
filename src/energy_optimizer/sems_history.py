"""Offline SEMS session evidence; never changes observations or training flags."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any


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
