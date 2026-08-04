"""Strictly local, reversible historical EV-session annotations."""

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from energy_optimizer.historian import Historian

STATE_COLUMNS = (
    "ev_charging_active",
    "ev_source",
    "ev_session_id",
    "ev_detection_confidence",
    "ev_power_w",
    "baseline_house_consumption_w",
    "baseline_training_eligible",
    "baseline_exclusion_reason",
)


class EVAnnotationReport(BaseModel):
    action: str
    dry_run: bool
    session_id: str
    matching_observation_count: int = Field(ge=0)
    first_matching_slot: str | None
    last_matching_slot: str | None
    current_baseline_eligibility_counts: dict[str, int]
    rows_that_would_become_excluded: int = Field(ge=0)
    rows_with_existing_ev_data: int = Field(ge=0)
    direct_ev_power_rows_retained: int = Field(ge=0)
    audit_record_created: bool = False


def parse_aware_timestamp(value: str) -> datetime:
    """Parse ISO 8601 and reject timestamps without an explicit offset."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone offset")
    return parsed


def annotate_ev_session(
    historian: Historian,
    *,
    start: datetime,
    end: datetime,
    session_id: str | None = None,
    note: str | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> EVAnnotationReport:
    _validate_range(start, end)
    if apply:
        historian.migrate()
    assigned_id = session_id or f"manual-{uuid4()}"
    with historian.connect() if apply else historian.connect_read_only() as connection:
        rows = _range_rows(connection, start, end)
        report = _report(rows, assigned_id, apply, "annotate")
        if apply and rows:
            annotation_id = _insert_audit(
                connection, rows, start, end, assigned_id, note, now, "apply"
            )
            for row in rows:
                _store_previous(connection, annotation_id, row)
                direct_power = row["ev_power_w"]
                eligible = bool(
                    direct_power is not None
                    and row["telemetry_is_healthy"]
                    and row["house_consumption_w"] is not None
                )
                baseline = (
                    max(float(row["house_consumption_w"]) - float(direct_power), 0.0)
                    if eligible
                    else row["baseline_house_consumption_w"]
                )
                connection.execute(
                    """UPDATE observations SET ev_charging_active=1,
                    ev_source='manual_annotation', ev_session_id=?,
                    ev_detection_confidence='confirmed_manual',
                    baseline_house_consumption_w=?, baseline_training_eligible=?,
                    baseline_exclusion_reason=? WHERE slot_utc=?""",
                    (
                        assigned_id,
                        baseline,
                        int(eligible),
                        None if eligible else "known_ev_session_without_ev_power",
                        row["slot_utc"],
                    ),
                )
            report.audit_record_created = True
        return report


def remove_ev_session(
    historian: Historian,
    *,
    session_id: str,
    apply: bool = False,
    note: str | None = None,
    now: datetime | None = None,
) -> EVAnnotationReport:
    if apply:
        historian.migrate()
    with historian.connect() if apply else historian.connect_read_only() as connection:
        if not apply and not _table_exists(connection, "ev_session_annotations"):
            return _report([], session_id, apply, "remove")
        audit = connection.execute(
            """SELECT * FROM ev_session_annotations
            WHERE session_id=? AND action='apply'
            ORDER BY id DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        if audit is None:
            return _report([], session_id, apply, "remove")
        rows = connection.execute(
            """SELECT o.*, r.previous_state_json FROM ev_session_annotation_rows r
            JOIN observations o ON o.slot_utc=r.slot_utc
            WHERE r.annotation_id=? AND o.ev_session_id=? ORDER BY o.slot_utc""",
            (audit["id"], session_id),
        ).fetchall()
        report = _report(rows, session_id, apply, "remove")
        if apply and rows:
            removal_id = _insert_audit(
                connection,
                rows,
                parse_aware_timestamp(audit["range_start_utc"]),
                parse_aware_timestamp(audit["range_end_utc"]),
                session_id,
                note,
                now,
                "remove",
            )
            for row in rows:
                _store_previous(connection, removal_id, row)
                previous = json.loads(row["previous_state_json"])
                assignments = ",".join(f"{name}=?" for name in STATE_COLUMNS)
                connection.execute(
                    f"UPDATE observations SET {assignments} WHERE slot_utc=?",
                    (*[previous[name] for name in STATE_COLUMNS], row["slot_utc"]),
                )
            report.audit_record_created = True
        return report


def _range_rows(connection: sqlite3.Connection, start: datetime, end: datetime):
    start = _floor_slot(start)
    end = _floor_slot(end)
    return connection.execute(
        """SELECT * FROM observations
        WHERE slot_utc>=? AND slot_utc<=? ORDER BY slot_utc""",
        (start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()),
    ).fetchall()


def _floor_slot(value: datetime) -> datetime:
    return value.replace(
        minute=value.minute - value.minute % 5, second=0, microsecond=0
    )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _report(rows, session_id: str, apply: bool, action: str) -> EVAnnotationReport:
    eligibility = Counter(
        "eligible" if row["baseline_training_eligible"] else "ineligible"
        for row in rows
    )
    existing = sum(
        row["ev_power_w"] is not None
        or row["ev_session_id"] is not None
        or row["ev_source"] not in (None, "none")
        for row in rows
    )
    return EVAnnotationReport(
        action=action,
        dry_run=not apply,
        session_id=session_id,
        matching_observation_count=len(rows),
        first_matching_slot=rows[0]["slot_utc"] if rows else None,
        last_matching_slot=rows[-1]["slot_utc"] if rows else None,
        current_baseline_eligibility_counts=dict(eligibility),
        rows_that_would_become_excluded=sum(
            bool(row["baseline_training_eligible"]) and row["ev_power_w"] is None
            for row in rows
        ),
        rows_with_existing_ev_data=existing,
        direct_ev_power_rows_retained=sum(
            row["ev_power_w"] is not None
            and bool(row["telemetry_is_healthy"])
            and row["house_consumption_w"] is not None
            for row in rows
        ),
    )


def _insert_audit(connection, rows, start, end, session_id, note, now, action):
    previous = Counter(
        "eligible" if row["baseline_training_eligible"] else "ineligible"
        for row in rows
    )
    if action == "apply":
        new = Counter(
            (
                "eligible"
                if row["ev_power_w"] is not None
                and row["telemetry_is_healthy"]
                and row["house_consumption_w"] is not None
                else "ineligible"
            )
            for row in rows
        )
    else:
        new = Counter(
            (
                "eligible"
                if json.loads(row["previous_state_json"])["baseline_training_eligible"]
                else "ineligible"
            )
            for row in rows
        )
    cursor = connection.execute(
        """INSERT INTO ev_session_annotations
        (annotation_timestamp_utc,range_start_utc,range_end_utc,affected_row_count,
        session_id,note,previous_eligibility_json,new_eligibility_json,
        annotation_source,action) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
            start.astimezone(UTC).isoformat(),
            end.astimezone(UTC).isoformat(),
            len(rows),
            session_id,
            note,
            json.dumps(previous),
            json.dumps(new),
            "manual_annotation",
            action,
        ),
    )
    return cursor.lastrowid


def _store_previous(connection, annotation_id, row):
    state = {name: row[name] for name in STATE_COLUMNS}
    connection.execute(
        "INSERT INTO ev_session_annotation_rows VALUES (?,?,?)",
        (annotation_id, row["slot_utc"], json.dumps(state)),
    )


def _validate_range(start: datetime, end: datetime) -> None:
    for value in (start, end):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
    if end < start:
        raise ValueError("end must not precede start")
