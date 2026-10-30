"""Atomic SEMS backfill/reversal using the existing shared annotation tables.

No schema change, network client or automatic invocation. The caller supplies an
explicit repository and reviewed plan. Only two baseline metadata fields change.
"""

import json
from datetime import UTC, datetime

from sqlalchemy import insert, select, text, update

from energy_optimizer.db.models import (
    EVSessionAnnotation,
    EVSessionAnnotationRow,
    Observation,
)
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.sems_backfill import CHANGED_COLUMNS, guard, stamp, verify_plan


def apply_context_plan(
    repository: DatabaseRepository, plan: dict, *, now: datetime, reverse: bool = False
) -> str:
    """Apply once or reverse once; any changed guard/annotation aborts all rows.

    Reversal is not a blind restore: later annotation audit entries or changed
    guarded values block it. Reapplication after reversal requires a fresh plan.
    Historical replay must use the original snapshot, not rewritten eligibility.
    """
    verify_plan(plan)
    current_time = stamp(now)
    if current_time < stamp(plan["snapshot_at_utc"]):
        raise ValueError("Application time precedes snapshot")
    key = "sems-context-" + plan["plan_id"]
    changed = [
        e for e in plan["entries"] if e["disposition"] == "exclude_session_window"
    ]
    if not changed:
        return "no_changes"
    with repository.transaction() as session:
        # Serialize this bounded maintenance operation, never the collector.
        if repository.backend == "postgresql" and not session.scalar(
            text("SELECT pg_try_advisory_xact_lock(73451026)")
        ):
            raise ValueError("Another SEMS maintenance operation is active")
        audits = (
            session.execute(
                select(EVSessionAnnotation)
                .where(EVSessionAnnotation.session_id == key)
                .order_by(EVSessionAnnotation.id)
            )
            .scalars()
            .all()
        )
        if audits and audits[-1].action == "remove":
            if reverse:
                return "already_reversed"
            raise ValueError("Reversed plan requires a fresh snapshot")
        if reverse and not audits:
            raise ValueError("Plan has not been applied")
        if audits and json.loads(audits[0].note)["plan_id"] != plan["plan_id"]:
            raise ValueError("Audit identity mismatch")
        original_id = audits[0].id if audits else None
        for entry in changed:
            before = entry["before"]
            slot = stamp(before["slot_utc"])
            statement = select(Observation.__table__).where(
                Observation.slot_utc == slot
            )
            if repository.backend == "postgresql":
                statement = statement.with_for_update(nowait=True)
            row = session.execute(statement).mappings().one_or_none()
            expected = {**before, **entry["after"]} if audits else before
            if row is None or guard(dict(row)) != expected:
                raise ValueError(
                    "Observation changed since review; aborting entire plan"
                )
            later = select(EVSessionAnnotationRow.annotation_id).where(
                EVSessionAnnotationRow.slot_utc == slot
            )
            if original_id is not None:
                later = later.where(EVSessionAnnotationRow.annotation_id > original_id)
            if session.execute(later).first() is not None:
                raise ValueError("Conflicting annotation history; aborting entire plan")
        if audits and not reverse:
            return "already_applied"
        note = json.dumps(
            {
                "plan_id": plan["plan_id"],
                "snapshot_sha256": plan["snapshot_sha256"],
                "evidence_sha256": plan["evidence_sha256"],
                "boundary_policy": plan["boundary_policy"],
                "session_evidence": plan["session_evidence"],
                "row_context": [
                    {
                        "slot_utc": e["before"]["slot_utc"],
                        "session_ids": e["session_ids"],
                    }
                    for e in changed
                ],
            }
        )
        audit_id = session.execute(
            insert(EVSessionAnnotation)
            .values(
                annotation_timestamp_utc=current_time.astimezone(UTC),
                range_start_utc=stamp(changed[0]["before"]["slot_utc"]),
                range_end_utc=stamp(changed[-1]["before"]["slot_utc"]),
                affected_row_count=len(changed),
                session_id=key,
                note=note,
                previous_eligibility_json={"eligible": 0 if reverse else len(changed)},
                new_eligibility_json={"eligible": len(changed) if reverse else 0},
                annotation_source="sems_session_context",
                action="remove" if reverse else "apply",
            )
            .returning(EVSessionAnnotation.id)
        ).scalar_one()
        for entry in changed:
            before = entry["before"]
            expected = {**before, **entry["after"]} if reverse else before
            target = (
                {k: before[k] for k in CHANGED_COLUMNS} if reverse else entry["after"]
            )
            session.execute(
                insert(EVSessionAnnotationRow).values(
                    annotation_id=audit_id,
                    slot_utc=stamp(before["slot_utc"]),
                    previous_state_json={k: expected[k] for k in CHANGED_COLUMNS},
                )
            )
            predicates = []
            for column, value in expected.items():
                if column in ("slot_utc", "observed_at_utc"):
                    value = stamp(value)
                predicates.append(
                    Observation.__table__.c[column].is_(None)
                    if value is None
                    else Observation.__table__.c[column] == value
                )
            result = session.execute(
                update(Observation.__table__).where(*predicates).values(**target)
            )
            if result.rowcount != 1:
                raise ValueError("Concurrent observation change; rollback required")
    return "reversed" if reverse else "applied"
