"""Durable weather cycles, request reservations and immutable content versions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from energy_optimizer.db.models import WEATHER_TABLES
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.weather.config import WeatherCollectionConfig
from energy_optimizer.weather.domain import Capture, utc
from energy_optimizer.weather.receipt import PayloadReceipt

CYCLES = WEATHER_TABLES["cycles"]
ATTEMPTS = WEATHER_TABLES["attempts"]
PAYLOADS = WEATHER_TABLES["payloads"]
VERSIONS = WEATHER_TABLES["versions"]
TARGETS = WEATHER_TABLES["targets"]
STATE = WEATHER_TABLES["state"]


def grouped_targets(capture: Capture) -> dict[datetime, dict[str, Any]]:
    result: dict[datetime, dict[str, Any]] = defaultdict(dict)
    for point in capture.points:
        value = point.as_dict()
        value.pop("valid_at")
        value.pop("series")
        value.pop("variable")
        value["source_path"] = re.sub(r"data\[\d+\]", "data[]", value["source_path"])
        result[point.valid_at][point.variable] = value
    return dict(result)


class WeatherRepository:
    def __init__(self, repository: DatabaseRepository) -> None:
        self.repository = repository

    @contextmanager
    def _write(self):
        with self.repository.transaction() as session:
            if self.repository.backend == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            elif self.repository.backend == "postgresql":
                if not session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(726205005030)")
                ):
                    raise RuntimeError("WEATHER_BUDGET_BUSY")
            else:
                raise ValueError("unsupported weather database backend")
            yield session

    def _once(self, session, table, values: dict[str, Any]) -> None:
        builder = (
            pg_insert if self.repository.backend == "postgresql" else sqlite_insert
        )
        session.execute(builder(table).values(**values).on_conflict_do_nothing())

    def claim_page(
        self, config: WeatherCollectionConfig, now: datetime
    ) -> dict[str, Any]:
        """Atomic cadence/lease/budget check and committed reservation BEFORE GET."""
        if not config.ready:
            return {"status": "NOT_CONFIGURED" if config.enabled else "DISABLED"}
        now = utc(now)
        with self._write() as db:
            state = (
                db.execute(
                    select(STATE).where(STATE.c.account_ref == config.account_ref)
                )
                .mappings()
                .first()
            )
            if state and state["blocked_until"] and state["blocked_until"] > now:
                return {
                    "status": "PROVIDER_BLOCKED",
                    "retry_after_utc": state["blocked_until"],
                }
            latest = (
                db.execute(
                    select(CYCLES)
                    .where(CYCLES.c.account_ref == config.account_ref)
                    .order_by(CYCLES.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if latest and latest["created_at"] > now:
                return {"status": "CLOCK_MOVED_BACKWARDS"}
            active = latest and latest["status"] == "COLLECTING"
            if active:
                in_flight = (
                    db.execute(
                        select(ATTEMPTS)
                        .where(
                            ATTEMPTS.c.cycle_id == latest["id"],
                            ATTEMPTS.c.status == "RESERVED",
                        )
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if in_flight:
                    if now - in_flight["requested_at"] <= timedelta(seconds=120):
                        return {"status": "PAGE_IN_FLIGHT"}
                    db.execute(
                        update(ATTEMPTS)
                        .where(ATTEMPTS.c.id == in_flight["id"])
                        .values(status="UNKNOWN", error_code="INTERRUPTED_REQUEST")
                    )
                    db.execute(
                        update(CYCLES)
                        .where(CYCLES.c.id == latest["id"])
                        .values(
                            status="PARTIAL",
                            completed_at=now,
                            error_code="INTERRUPTED_REQUEST",
                        )
                    )
                    return {"status": "PARTIAL", "error_code": "INTERRUPTED_REQUEST"}
                if (
                    now - latest["created_at"] > timedelta(minutes=5)
                    or latest["configuration_scope"] != config.scope
                ):
                    db.execute(
                        update(CYCLES)
                        .where(CYCLES.c.id == latest["id"])
                        .values(
                            status="PARTIAL",
                            completed_at=now,
                            error_code="STALE_OR_CHANGED_CONFIGURATION",
                        )
                    )
                    return {
                        "status": "PARTIAL",
                        "error_code": "STALE_OR_CHANGED_CONFIGURATION",
                    }
            used, newest = db.execute(
                select(func.count(), func.max(ATTEMPTS.c.requested_at)).where(
                    ATTEMPTS.c.account_ref == config.account_ref,
                    ATTEMPTS.c.requested_at > now - timedelta(hours=24),
                )
            ).one()
            if newest is not None and newest > now:
                return {"status": "CLOCK_MOVED_BACKWARDS"}
            remaining = config.local_attempt_cap - used
            if remaining < (1 if active else config.max_pages):
                if active:
                    db.execute(
                        update(CYCLES)
                        .where(CYCLES.c.id == latest["id"])
                        .values(
                            status="PARTIAL", completed_at=now, error_code="QUOTA_STOP"
                        )
                    )
                return {"status": "QUOTA_STOP", "remaining_attempts": max(remaining, 0)}
            if not active:
                slot = now.replace(
                    second=0, microsecond=0, minute=now.minute // 10 * 10
                )
                if latest and latest["scheduled_for"] >= slot:
                    return {"status": "NOT_DUE"}
                start_epoch = int(now.timestamp()) // 900 * 900
                latest = dict(
                    id=str(uuid.uuid4()),
                    account_ref=config.account_ref,
                    configuration_scope=config.scope,
                    provider="openweather",
                    product="onecall4_15min",
                    requested_units="metric",
                    scheduled_for=slot,
                    created_at=now,
                    window_start=datetime.fromtimestamp(start_epoch, UTC),
                    window_end=datetime.fromtimestamp(start_epoch + 172800, UTC),
                    next_start_epoch=start_epoch,
                    page_count=0,
                    status="COLLECTING",
                )
                db.execute(insert(CYCLES).values(**latest))
            if latest["page_count"] >= config.max_pages:
                db.execute(
                    update(CYCLES)
                    .where(CYCLES.c.id == latest["id"])
                    .values(status="PARTIAL", completed_at=now, error_code="PAGE_LIMIT")
                )
                return {"status": "PARTIAL", "error_code": "PAGE_LIMIT"}
            attempt = dict(
                id=str(uuid.uuid4()),
                account_ref=config.account_ref,
                cycle_id=latest["id"],
                page_number=latest["page_count"] + 1,
                request_start_epoch=latest["next_start_epoch"],
                requested_at=now,
                status="RESERVED",
                model_identity="UNKNOWN",
                native_resolution="UNKNOWN",
                parser_version="weather-v1",
            )
            db.execute(insert(ATTEMPTS).values(**attempt))
            return {
                **attempt,
                "status": "RESERVED",
                "configuration_scope": config.scope,
                "window_start": latest["window_start"],
                "window_end": latest["window_end"],
            }

    def finish_page(
        self,
        claim: dict[str, Any],
        *,
        now: datetime,
        config: WeatherCollectionConfig,
        raw: bytes | None = None,
        http_status: int | None = None,
        capture: Capture | None = None,
        navigation: dict[str, Any] | None = None,
        error_code: str | None = None,
        receipt: PayloadReceipt | None = None,
    ) -> dict[str, Any]:
        now = utc(now)
        with self._write() as db:
            cycle = (
                db.execute(select(CYCLES).where(CYCLES.c.id == claim["cycle_id"]))
                .mappings()
                .one()
            )
            attempt = (
                db.execute(select(ATTEMPTS).where(ATTEMPTS.c.id == claim["id"]))
                .mappings()
                .one()
            )
            if attempt["status"] not in {"RESERVED", "UNKNOWN"}:
                return {
                    "status": cycle["status"],
                    "cycle_id": cycle["id"],
                    "page_count": cycle["page_count"],
                }
            payload_hash = None
            if raw is not None:
                receipt = receipt or PayloadReceipt.from_wire(raw, config.api_key)
                stored = receipt.body
                payload_hash = receipt.original_sha256
                self._once(
                    db,
                    PAYLOADS,
                    dict(
                        original_sha256=payload_hash,
                        stored_sha256=hashlib.sha256(stored).hexdigest(),
                        original_byte_count=receipt.original_byte_count,
                        credential_redacted=receipt.credential_redacted,
                        body=stored,
                    ),
                )
            if capture is not None:
                for source_index, (target, body) in enumerate(
                    grouped_targets(capture).items()
                ):
                    canonical = json.dumps(
                        {
                            "scope": claim["configuration_scope"],
                            "target": target.isoformat(),
                            "values": body,
                            "parser": capture.parser_version,
                        },
                        sort_keys=True,
                        allow_nan=False,
                    )
                    version_hash = hashlib.sha256(canonical.encode()).hexdigest()
                    self._once(
                        db,
                        VERSIONS,
                        dict(sha256=version_hash, target_at=target, body=body),
                    )
                    db.execute(
                        insert(TARGETS).values(
                            attempt_id=claim["id"],
                            target_at=target,
                            version_sha256=version_hash,
                            source_index=source_index,
                        )
                    )
            late = cycle["status"] != "COLLECTING" or attempt["status"] != "RESERVED"
            db.execute(
                update(ATTEMPTS)
                .where(ATTEMPTS.c.id == claim["id"])
                .values(
                    status=(
                        "LATE_RESPONSE"
                        if late
                        else "RECEIVED" if raw is not None else "UNKNOWN"
                    ),
                    received_at=now if raw is not None else None,
                    http_status=http_status,
                    error_code=error_code,
                    payload_sha256=payload_hash,
                )
            )
            if http_status in {401, 403, 429}:
                blocked = (
                    now.replace(hour=0, minute=5, second=0, microsecond=0)
                    + timedelta(days=1)
                    if http_status == 429
                    else now + timedelta(hours=1)
                )
                self._once(db, STATE, dict(account_ref=config.account_ref))
                previous = db.scalar(
                    select(STATE.c.blocked_until).where(
                        STATE.c.account_ref == config.account_ref
                    )
                )
                if previous is not None:
                    blocked = max(blocked, previous)
                db.execute(
                    update(STATE)
                    .where(STATE.c.account_ref == config.account_ref)
                    .values(blocked_until=blocked, reason=error_code)
                )
            if late:
                return {"status": "PARTIAL", "error_code": "LATE_RESPONSE"}
            if error_code:
                db.execute(
                    update(CYCLES)
                    .where(CYCLES.c.id == cycle["id"])
                    .values(
                        status="PARTIAL",
                        completed_at=now,
                        page_count=claim["page_number"],
                        error_code=error_code,
                    )
                )
                return {"status": "PARTIAL", "error_code": error_code}
            rows = (
                db.execute(
                    select(TARGETS.c.target_at)
                    .join(ATTEMPTS)
                    .where(
                        ATTEMPTS.c.cycle_id == cycle["id"],
                        TARGETS.c.target_at >= cycle["window_start"],
                        TARGETS.c.target_at < cycle["window_end"],
                    )
                )
                .scalars()
                .all()
            )
            unique = set(rows)
            expected = {
                cycle["window_start"] + timedelta(minutes=15 * n) for n in range(192)
            }
            overlap = len(rows) != len(unique)
            complete = unique == expected and not overlap
            next_start = navigation.get("next_start_epoch") if navigation else None
            terminal = (
                complete
                or overlap
                or next_start is None
                or claim["page_number"] >= config.max_pages
            )
            status = "COMPLETE" if complete else "PARTIAL" if terminal else "COLLECTING"
            reason = (
                "OVERLAPPING_TARGETS"
                if overlap
                else "INCOMPLETE_COVERAGE" if terminal and not complete else None
            )
            db.execute(
                update(CYCLES)
                .where(CYCLES.c.id == cycle["id"])
                .values(
                    status=status,
                    page_count=claim["page_number"],
                    next_start_epoch=next_start or cycle["next_start_epoch"],
                    completed_at=now if terminal else None,
                    error_code=reason,
                )
            )
            return {
                "status": status,
                "cycle_id": cycle["id"],
                "page_count": claim["page_number"],
                "target_timestamps": len(unique),
                "expected_target_timestamps": 192,
                "error_code": reason,
                "received_at_utc": now,
            }

    def history(self, *, as_of: datetime, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValueError("weather history bound exceeded")
        as_of = utc(as_of)
        with self.repository.transaction() as db:
            rows = (
                db.execute(
                    select(
                        CYCLES.c.id,
                        CYCLES.c.created_at,
                        CYCLES.c.completed_at,
                        CYCLES.c.window_start,
                        CYCLES.c.window_end,
                        CYCLES.c.status,
                        CYCLES.c.error_code,
                        CYCLES.c.page_count,
                        CYCLES.c.provider,
                        CYCLES.c.product,
                        CYCLES.c.requested_units,
                    )
                    .where(CYCLES.c.created_at <= as_of)
                    .order_by(CYCLES.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            result = []
            for row in rows:
                item = dict(row)
                if item["completed_at"] is None or item["completed_at"] > as_of:
                    item.update(
                        status="INCOMPLETE_AS_OF",
                        completed_at=None,
                        error_code=None,
                        page_count=None,
                    )
                result.append(item)
            return result

    def cycle(
        self, *, cycle_id: str, as_of: datetime, limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200 or not 0 <= offset <= 1000:
            raise ValueError("weather target page bound exceeded")
        as_of = utc(as_of)
        with self.repository.transaction() as db:
            cycle = (
                db.execute(
                    select(CYCLES).where(
                        CYCLES.c.id == cycle_id, CYCLES.c.created_at <= as_of
                    )
                )
                .mappings()
                .first()
            )
            if not cycle:
                return {"status": "NO_CAPTURE", "targets": []}
            rows = (
                db.execute(
                    select(
                        TARGETS.c.target_at,
                        VERSIONS.c.body,
                        TARGETS.c.version_sha256,
                        ATTEMPTS.c.id.label("receipt_id"),
                        ATTEMPTS.c.requested_at,
                        ATTEMPTS.c.received_at,
                        ATTEMPTS.c.payload_sha256,
                        ATTEMPTS.c.page_number,
                        TARGETS.c.source_index,
                    )
                    .select_from(TARGETS.join(ATTEMPTS).join(VERSIONS))
                    .where(
                        ATTEMPTS.c.cycle_id == cycle_id,
                        ATTEMPTS.c.received_at <= as_of,
                        TARGETS.c.target_at >= cycle["window_start"],
                        TARGETS.c.target_at < cycle["window_end"],
                    )
                    .order_by(TARGETS.c.target_at, ATTEMPTS.c.page_number)
                    .offset(offset)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
            known = cycle["completed_at"] is not None and cycle["completed_at"] <= as_of
            return {
                "cycle_id": cycle_id,
                "status": cycle["status"] if known else "INCOMPLETE_AS_OF",
                "window_start": cycle["window_start"],
                "window_end": cycle["window_end"],
                "provider": cycle["provider"],
                "product": cycle["product"],
                "requested_units": cycle["requested_units"],
                "provider_issue_time": None,
                "model_identity": "UNKNOWN",
                "native_resolution": "UNKNOWN",
                "has_more": len(rows) > limit,
                "offset": offset,
                "targets": [dict(r) for r in rows[:limit]],
            }
