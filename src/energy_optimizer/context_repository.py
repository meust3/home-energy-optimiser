"""Append-only optional context persistence over the shared SQLAlchemy backend."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from energy_optimizer.db.models import ContextObservation, WeatherContextSnapshot
from energy_optimizer.db.repository import DatabaseRepository
from energy_optimizer.forecast_context import ContextBatch, content_hash
from energy_optimizer.timestamps import aware_datetime


class ContextRepository:
    def __init__(self, repository: DatabaseRepository) -> None:
        self.repository = repository

    def save(
        self, batch: ContextBatch, *, recorded_at: datetime | None = None
    ) -> dict[str, Any]:
        """Commit separately after core observation; retries never rewrite evidence."""
        recorded = aware_datetime(recorded_at or datetime.now(UTC)).astimezone(UTC)
        if recorded < batch.received_at_utc:
            raise ValueError("recording cannot precede receipt")
        batch_id = content_hash({"slot": batch.slot_utc, "mapping": batch.mapping_hash})
        insert = pg_insert if self.repository.backend == "postgresql" else sqlite_insert
        with self.repository.transaction() as session:
            existing = session.get(ContextObservation, batch_id)
            if existing is not None:
                return _diagnostic(existing.body, inserted=False)
            body = batch.model_dump(mode="json", exclude={"weather"})
            weather_id = None
            if batch.weather is not None:
                weather = batch.weather
                source_key = content_hash(
                    {
                        "source": weather.source.model_dump(),
                        "mapping": batch.mapping_hash,
                    }
                )
                latest = session.scalar(
                    select(WeatherContextSnapshot)
                    .where(WeatherContextSnapshot.source_key == source_key)
                    .order_by(
                        WeatherContextSnapshot.recorded_at_utc.desc(),
                        WeatherContextSnapshot.received_at_utc.desc(),
                    )
                    .limit(1)
                )
                if latest is not None and latest.semantic_hash == weather.semantic_hash:
                    weather_id = latest.id
                else:
                    # Cache identity distinguishes a later A->B->A revision.
                    # Issue/version remains distinct even when values agree.
                    weather_id = content_hash(
                        {
                            "source": source_key,
                            "semantic": weather.semantic_hash,
                            "cache_success": weather.cache_success_utc,
                            "previous_snapshot_id": latest.id if latest else None,
                        }
                    )
                    session.execute(
                        insert(WeatherContextSnapshot)
                        .values(
                            id=weather_id,
                            source_key=source_key,
                            semantic_hash=weather.semantic_hash,
                            received_at_utc=batch.received_at_utc,
                            recorded_at_utc=recorded,
                            body=weather.model_dump(mode="json"),
                        )
                        .on_conflict_do_nothing(index_elements=["id"])
                    )
            body["weather_snapshot_id"] = weather_id
            body["weather_receipt"] = (
                {
                    "cache_success_utc": batch.weather.cache_success_utc.isoformat(),
                    "payload_hash": batch.weather.payload_hash,
                }
                if batch.weather
                else None
            )
            result = session.execute(
                insert(ContextObservation)
                .values(
                    id=batch_id,
                    slot_utc=batch.slot_utc,
                    received_at_utc=batch.received_at_utc,
                    recorded_at_utc=recorded,
                    mapping_hash=batch.mapping_hash,
                    body=body,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
        return _diagnostic(body, inserted=bool(result.rowcount))

    def context_as_of(self, origin: datetime) -> dict[str, Any] | None:
        """Future experiment support only; no production forecast consumes this."""
        origin = aware_datetime(origin)
        with self.repository.transaction() as session:
            row = session.scalar(
                select(ContextObservation)
                .where(
                    ContextObservation.received_at_utc <= origin,
                    ContextObservation.recorded_at_utc <= origin,
                )
                .order_by(ContextObservation.received_at_utc.desc())
                .limit(1)
            )
            return row.body if row else None

    def weather_as_of(self, source_key: str, origin: datetime) -> dict[str, Any] | None:
        origin = aware_datetime(origin)
        with self.repository.transaction() as session:
            row = session.scalar(
                select(WeatherContextSnapshot)
                .where(
                    WeatherContextSnapshot.source_key == source_key,
                    WeatherContextSnapshot.received_at_utc <= origin,
                    WeatherContextSnapshot.recorded_at_utc <= origin,
                )
                .order_by(
                    WeatherContextSnapshot.recorded_at_utc.desc(),
                    WeatherContextSnapshot.received_at_utc.desc(),
                )
                .limit(1)
            )
            return row.body if row else None


def _diagnostic(body: dict[str, Any], *, inserted: bool) -> dict[str, Any]:
    size = len(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())
    diagnostic = body["diagnostic"]
    return {
        "inserted": inserted,
        "diagnostic": diagnostic,
        "last_useful_receipt_utc": (
            body["received_at_utc"]
            if diagnostic.get("valid", 0) or body.get("weather_snapshot_id")
            else None
        ),
        "bytes_this_context_record": size,
        "estimated_context_rows_per_day": 288,
        "estimated_context_bytes_per_day": size * 288,
        "weather_snapshot_id": body.get("weather_snapshot_id"),
    }
