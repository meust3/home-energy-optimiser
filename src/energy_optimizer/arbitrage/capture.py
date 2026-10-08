"""Bounded capture of already fetched inputs; never polls or controls a device."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from energy_optimizer import entity_ids as ids
from energy_optimizer.arbitrage.decision_types import canonical, digest, primitive
from energy_optimizer.db.models import ArbitrageCapture, ArbitrageCommitWitness

LOGGER = logging.getLogger(__name__)
VERSION = "arbitrage-capture-v1"
MAX_BYTES = 2097152
MAX_POINTS = 4096
SOURCES = {
    "soc": ids.GOODWE_BATTERY_SOC,
    "battery_power": ids.GOODWE_BATTERY_POWER,
    "house_power": ids.GOODWE_HOUSE_CONSUMPTION,
    "grid_power": ids.GOODWE_GRID_POWER,
    "pv_power": ids.GOODWE_PV_POWER,
    "battery_mode": ids.GOODWE_BATTERY_MODE,
    "work_mode": ids.GOODWE_WORK_MODE,
    "import_forecast": ids.AMBER_IMPORT_FORECAST,
    "export_forecast": ids.AMBER_EXPORT_FORECAST,
    "pv_today": ids.SOLCAST_TODAY,
    "pv_tomorrow": ids.SOLCAST_TOMORROW,
}
ATTRS = {
    "unit_of_measurement",
    "last_updated",
    "last_updated_utc",
    "last_successful_update",
}
PRICE_KEYS = {
    "start_time",
    "end_time",
    "duration",
    "per_kwh",
    "spot_per_kwh",
    "advanced_price",
    "advancedPrice",
    "descriptor",
    "spike_status",
}
PV_KEYS = {
    "period_start",
    "period_end",
    "pv_estimate",
    "pv_estimate10",
    "pv_estimate90",
}


def _small(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (str, datetime)):
        text = value.isoformat() if isinstance(value, datetime) else value
        if len(text) <= 128:
            return text
    return None


def _price_value(key, value):
    if key in {"advanced_price", "advancedPrice"} and isinstance(value, dict):
        # Preserve the exposed domain as-is. Never substitute it for per_kwh.
        return {
            k: _small(v)
            for k, v in value.items()
            if k in {"low", "high", "predicted", "unit", "unit_of_measurement"}
        }
    return _small(value)


def snapshot_states(states, *, slot, received_at):
    """Whitelist fields, never retain all HA attributes or tracker/credential data."""
    sources = {}
    for alias, entity in SOURCES.items():
        state = states.get(entity)
        if state is None:
            sources[alias] = None
            continue
        body = {
            "state": _small(state.state),
            "reported_at": state.last_updated,
            "attributes": {
                k: _small(v) for k, v in state.attributes.items() if k in ATTRS
            },
        }
        field, keys = (
            ("forecasts", PRICE_KEYS)
            if "forecast" in alias
            else ("detailedForecast", PV_KEYS)
        )
        if field in state.attributes:
            raw = state.attributes[field]
            if not isinstance(raw, list) or len(raw) > MAX_POINTS:
                raise ValueError("source_interval_bound")
            body[field] = [
                {k: _price_value(k, v) for k, v in row.items() if k in keys}
                for row in raw
                if isinstance(row, dict)
            ]
        sources[alias] = body
    result = primitive(
        {
            "version": VERSION,
            "kind": "source",
            "slot": slot,
            "received_at": received_at,
            "sources": sources,
            "provider_issue_time": "unknown unless explicitly exposed",
            "measurement_time": "HA reporting timestamps are not measurement times",
        }
    )
    if len(canonical(result).encode()) > MAX_BYTES:
        raise ValueError("capture_byte_bound")
    return result


class CaptureRepository:
    def __init__(self, repository):
        self.repository = repository

    def save(self, *, origin, kind, at, body, clock=lambda: datetime.now(UTC)):
        encoded = canonical(body)
        if len(encoded.encode()) > MAX_BYTES:
            raise ValueError("capture_byte_bound")
        key = digest({"origin": origin, "kind": kind, "version": VERSION})
        content = digest(body)
        insert = pg_insert if self.repository.backend == "postgresql" else sqlite_insert
        with self.repository.transaction() as session:
            session.execute(
                insert(ArbitrageCapture)
                .values(
                    id=key,
                    origin=origin,
                    kind=kind,
                    captured_at_utc=at,
                    body_sha256=content,
                    body=body,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            row = session.get(ArbitrageCapture, key)
            if row.body_sha256 != content:
                raise ValueError("immutable_capture_conflict")
        # This is an upper bound witnessed AFTER the first transaction committed.
        # A crash between commits leaves a visible unconfirmed capture.
        with self.repository.transaction() as session:
            session.execute(
                insert(ArbitrageCommitWitness)
                .values(capture_id=key, confirmed_at_utc=clock())
                .on_conflict_do_nothing(index_elements=["capture_id"])
            )
        return key

    def latest(self, kind, *, before=None):
        statement = (
            select(ArbitrageCapture, ArbitrageCommitWitness.confirmed_at_utc)
            .outerjoin(
                ArbitrageCommitWitness,
                ArbitrageCommitWitness.capture_id == ArbitrageCapture.id,
            )
            .where(ArbitrageCapture.kind == kind)
            .order_by(ArbitrageCapture.captured_at_utc.desc())
            .limit(1)
        )
        if before is not None:
            statement = statement.where(
                ArbitrageCapture.captured_at_utc <= before,
                ArbitrageCommitWitness.confirmed_at_utc <= before,
            )
        with self.repository.transaction() as session:
            result = session.execute(statement).first()
            if result is None:
                return None
            row, witness = result
            return {
                "id": row.id,
                "body_sha256": row.body_sha256,
                "body": row.body,
                "captured_at": row.captured_at_utc,
                "confirmed_at": witness,
            }


def capture_source(states, *, slot, receipt, repository_factory):
    repository = None
    try:
        body = snapshot_states(states, slot=slot, received_at=receipt)
        repository = repository_factory()
        return CaptureRepository(repository).save(
            origin=slot.isoformat(), kind="source", at=receipt, body=body
        )
    except Exception as exc:
        LOGGER.warning(
            "Optional arbitrage capture failed (%s); core already saved",
            type(exc).__name__,
        )
        return None
    finally:
        if repository is not None:
            repository.close()


def capture_forecast(
    repository, *, forecast, forecast_id, reserve_id, operation_id, ready_at
):
    """Append exact predictions and linked audit refs after existing operation commit."""  # noqa: E501
    source = CaptureRepository(repository).latest("source", before=ready_at)
    points = [
        {
            "start": p.period_start_utc,
            "end": p.period_end_utc,
            "value": p.expected_value,
            "lower": p.lower_value,
            "upper": p.upper_value,
            "unit": p.unit,
        }
        for p in forecast.points
    ]
    if len(points) > MAX_POINTS:
        raise ValueError("forecast_point_bound")
    body = primitive(
        {
            "version": VERSION,
            "kind": "decision_inputs",
            "ready_at": ready_at,
            "source_capture_id": source["id"] if source else None,
            "forecast_id": forecast_id,
            "reserve_id": reserve_id,
            "operation_id": operation_id,
            "model": forecast.model_version,
            "created_at": forecast.created_at_utc,
            "forecast_type": forecast.forecast_type,
            "metadata": forecast.metadata,
            "demand_points": points,
            "reserve": (
                repository.reserve_audit_read_only(reserve_id) if reserve_id else None
            ),
            "load_basis": "EV-excluded operational baseline; total load needs explicit uncontrolled-load scenario",  # noqa: E501
            "no_command_issued": True,
        }
    )
    return CaptureRepository(repository).save(
        origin=str(operation_id), kind="decision_inputs", at=ready_at, body=body
    )
