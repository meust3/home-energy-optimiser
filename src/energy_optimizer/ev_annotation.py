"""Strictly local, reversible historical EV-session annotations."""

from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from energy_optimizer.db.repository import DatabaseRepository

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
    historian: DatabaseRepository,
    *,
    start: datetime,
    end: datetime,
    session_id: str | None = None,
    note: str | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> EVAnnotationReport:
    _validate_range(start, end)
    assigned_id = session_id or f"manual-{uuid4()}"
    rows = historian.observation_rows(start=_floor_slot(start), end=_floor_slot(end))
    report = _report(rows, assigned_id, apply, "annotate")
    if apply and rows:
        historian.apply_ev_annotation(
            rows=rows,
            start=start,
            end=end,
            session_id=assigned_id,
            note=note,
            now=now or datetime.now(UTC),
            state_columns=STATE_COLUMNS,
        )
        report.audit_record_created = True
    return report


def remove_ev_session(
    historian: DatabaseRepository,
    *,
    session_id: str,
    apply: bool = False,
    note: str | None = None,
    now: datetime | None = None,
) -> EVAnnotationReport:
    rows = historian.removable_ev_session_rows(session_id)
    report = _report(rows, session_id, apply, "remove")
    if apply and rows:
        historian.remove_ev_annotation(
            rows=rows,
            session_id=session_id,
            note=note,
            now=now or datetime.now(UTC),
            state_columns=STATE_COLUMNS,
        )
        report.audit_record_created = True
    return report


def _floor_slot(value: datetime) -> datetime:
    return value.replace(
        minute=value.minute - value.minute % 5, second=0, microsecond=0
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
        first_matching_slot=_slot_text(rows[0]["slot_utc"]) if rows else None,
        last_matching_slot=_slot_text(rows[-1]["slot_utc"]) if rows else None,
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


def _validate_range(start: datetime, end: datetime) -> None:
    for value in (start, end):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
    if end < start:
        raise ValueError("end must not precede start")


def _slot_text(value: datetime | str) -> str:
    return value.isoformat() if isinstance(value, datetime) else value
